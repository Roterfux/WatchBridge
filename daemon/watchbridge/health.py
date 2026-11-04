# WatchBridge - Huawei Watch GT 5 companion for Sailfish OS
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Health data synced from the watch: an SQLite database plus CSV files.

Everything lives in one folder the user can reach from the file manager, over
USB or with a sync app (default ~/Documents/WatchBridge):

    health.sqlite          all data, the source of truth
    activity-YYYY-MM.csv   one row per minute: steps, kcal, distance, heart rate, SpO2
    sleep.csv              one row per period (light/deep sleep, other-0xNN = not sleep)
    daily.csv              one row per day: totals, heart rate range, sleep minutes

CSV files are rewritten from the database after each sync (only the months that
changed), so they can be edited or deleted freely.
"""

import csv
import datetime
import logging
import os
import sqlite3
import time

log = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS activity (
    time INTEGER PRIMARY KEY,           -- unix seconds, start of the minute
    steps INTEGER, kcal REAL, distance INTEGER,
    heart_rate INTEGER, spo2 INTEGER, resting_heart_rate INTEGER
);
CREATE TABLE IF NOT EXISTS sleep (
    start INTEGER PRIMARY KEY,          -- unix seconds
    end INTEGER NOT NULL,
    type TEXT NOT NULL                  -- light, deep, or other-0xNN (not sleep, see SLEEP_NAMES)
);
CREATE TABLE IF NOT EXISTS totals (
    day TEXT PRIMARY KEY,               -- local date, YYYY-MM-DD
    steps INTEGER, calories INTEGER, distance INTEGER,
    updated INTEGER
);
"""

# Basic sleep types (Gadgetbridge HuaweiSampleProvider). The same messages carry other
# period types too: on a Watch GT 5, 0x01 and 0x03 line up with walking, not sleep.
SLEEP_NAMES = {0x06: "light", 0x07: "deep"}
SLEEP_KINDS = tuple(SLEEP_NAMES.values())
ACTIVITY_FIELDS = ("steps", "kcal", "distance", "heart_rate", "spo2", "resting_heart_rate")

# A night belongs to the day it ends on; sleep that starts after 18:00 counts for the next day
NIGHT_SPLIT_HOUR = 18


def default_folder():
    return os.path.join(os.path.expanduser("~"), "Documents", "WatchBridge")


def _day(ts):
    return time.strftime("%Y-%m-%d", time.localtime(ts))


def _day_bounds(day):
    d = datetime.datetime.strptime(day, "%Y-%m-%d")
    start = int(time.mktime(d.timetuple()))
    end = int(time.mktime((d + datetime.timedelta(days=1)).timetuple()))
    return start, end


def _iso(ts):
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(ts))


def _valid_hr(v):
    # 0 and 255 mean "not measured"
    return v if v is not None and 0 < v < 255 else None


class HealthStore:
    def __init__(self, folder=None):
        self.folder = folder or default_folder()
        os.makedirs(self.folder, exist_ok=True)
        self.db = sqlite3.connect(os.path.join(self.folder, "health.sqlite"))
        self.db.executescript(SCHEMA)

    def close(self):
        self.db.close()

    # ------------------------------------------------------------- writing
    def add_sync_result(self, result, now=None):
        """Store a device.HuaweiWatch health sync result. Returns counts of new rows."""
        now = int(now if now is not None else time.time())
        months = set()
        # The watch may send several records for one minute, each with some of the
        # fields; merge them (and with what is stored) instead of overwriting.
        merged = {}
        for s in result.get("samples", []):
            row = merged.setdefault(s["time"], {})
            fields = dict(s)
            # Per-minute calories are small calories: on a GT 5 the minutes of a day add
            # up to the watch's own kcal total times 1000
            if fields.get("calories") is not None:
                fields["kcal"] = fields["calories"] / 1000.0
            for key in ACTIVITY_FIELDS:
                value = fields.get(key)
                if key in ("heart_rate", "resting_heart_rate"):
                    value = _valid_hr(value)
                if value is not None:
                    row[key] = value
        with self.db:
            for t, row in merged.items():
                values = [row.get(k) for k in ACTIVITY_FIELDS]
                self.db.execute("INSERT OR IGNORE INTO activity (time) VALUES (?)", (t,))
                self.db.execute("UPDATE activity SET " + ", ".join("%s = COALESCE(?, %s)" % (k, k)
                                                                   for k in ACTIVITY_FIELDS)
                                + " WHERE time = ?", values + [t])
                months.add(time.strftime("%Y-%m", time.localtime(t)))
            for start, end, kind in result.get("sleep", []):
                name = SLEEP_NAMES.get(kind, "other-0x%02x" % kind)
                self.db.execute("INSERT OR REPLACE INTO sleep VALUES (?, ?, ?)", (start, end, name))
            totals = result.get("totals")
            if totals:
                self.db.execute("INSERT OR REPLACE INTO totals VALUES (?, ?, ?, ?, ?)",
                                (_day(now), totals["steps"], totals["calories"], totals["distance"], now))
        self.export_csv(months, sleep_changed=bool(result.get("sleep")), totals_changed=bool(totals))
        return {"minutes": len(merged), "sleep": len(result.get("sleep", []))}

    # -------------------------------------------------------------- reading
    def last_activity_time(self):
        row = self.db.execute("SELECT MAX(time) FROM activity").fetchone()
        return row[0]

    def last_sleep_end(self):
        row = self.db.execute("SELECT MAX(end) FROM sleep").fetchone()
        return row[0]

    def day_summary(self, day):
        """Everything the health page shows for one local date."""
        start, end = _day_bounds(day)
        rows = self.db.execute(
            "SELECT time, steps, kcal, distance, heart_rate, spo2, resting_heart_rate "
            "FROM activity WHERE time >= ? AND time < ? ORDER BY time", (start, end)).fetchall()
        hourly = [0] * 24
        hr_points = []
        steps = calories = distance = 0
        resting = []
        spo2 = []
        for t, st, cal, dist, hr, sp, rhr in rows:
            hour = time.localtime(t).tm_hour
            hourly[hour] += st or 0
            steps += st or 0
            calories += cal or 0
            distance += dist or 0
            if hr:
                hr_points.append([t - start, hr])
            if rhr:
                resting.append(rhr)
            if sp:
                spo2.append(sp)
        totals = self.db.execute("SELECT steps, calories, distance, updated FROM totals WHERE day = ?",
                                 (day,)).fetchone()
        heart = [p[1] for p in hr_points]
        return {
            "day": day,
            # The watch's own totals are authoritative for the day they were read
            "steps": totals[0] if totals else steps,
            "calories": totals[1] if totals else int(round(calories)),
            "distance": totals[2] if totals else distance,
            "totalsUpdated": totals[3] if totals else None,
            "minutes": len(rows),
            "hourlySteps": hourly,
            # Seconds since local midnight + bpm, thinned to at most one point per 5 minutes
            "heartRate": _thin(hr_points, 300),
            "heartRateMin": min(heart) if heart else None,
            "heartRateMax": max(heart) if heart else None,
            "heartRateAvg": round(sum(heart) / len(heart)) if heart else None,
            "restingHeartRate": min(resting) if resting else None,
            "spo2Min": min(spo2) if spo2 else None,
            "sleep": self.night(day),
        }

    def night(self, day):
        """Sleep periods of the night ending on `day` (from 18:00 the evening before)."""
        start, _ = _day_bounds(day)
        lo, hi = start - (24 - NIGHT_SPLIT_HOUR) * 3600, start + NIGHT_SPLIT_HOUR * 3600
        rows = self.db.execute("SELECT start, end, type FROM sleep WHERE start >= ? AND start < ? AND type IN (%s) "
                               "ORDER BY start" % ",".join("?" * len(SLEEP_KINDS)),
                               (lo, hi) + SLEEP_KINDS).fetchall()
        minutes = {}
        for s, e, kind in rows:
            minutes[kind] = minutes.get(kind, 0) + (e - s) // 60
        return {
            "periods": [[s, e, kind] for s, e, kind in rows],
            "start": rows[0][0] if rows else None,
            "end": max(e for _, e, _ in rows) if rows else None,
            "minutes": sum(minutes.values()),
            "byType": minutes,
        }

    # --------------------------------------------------------------- export
    def export_csv(self, months, sleep_changed=True, totals_changed=True):
        for month in sorted(months):
            self._export_month(month)
        if sleep_changed:
            self._export_sleep()
        if months or sleep_changed or totals_changed:
            self._export_daily()

    def _write(self, name, header, rows):
        path = os.path.join(self.folder, name)
        tmp = path + ".tmp"
        with open(tmp, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(header)
            w.writerows(rows)
        os.replace(tmp, path)

    def _export_month(self, month):
        first = datetime.datetime.strptime(month + "-01", "%Y-%m-%d")
        nxt = (first + datetime.timedelta(days=32)).replace(day=1)
        lo, hi = int(time.mktime(first.timetuple())), int(time.mktime(nxt.timetuple()))
        rows = self.db.execute("SELECT * FROM activity WHERE time >= ? AND time < ? ORDER BY time",
                               (lo, hi)).fetchall()
        self._write("activity-%s.csv" % month,
                    ["time", "steps", "kcal", "distance_m", "heart_rate", "spo2", "resting_heart_rate"],
                    [[_iso(r[0])] + ["" if v is None else (round(v, 3) if isinstance(v, float) else v)
                                     for v in r[1:]] for r in rows])

    def _export_sleep(self):
        rows = self.db.execute("SELECT start, end, type FROM sleep ORDER BY start").fetchall()
        self._write("sleep.csv", ["start", "end", "minutes", "type"],
                    [[_iso(s), _iso(e), (e - s) // 60, kind] for s, e, kind in rows])

    def _export_daily(self):
        days = {}
        for t, st, cal, dist, hr in self.db.execute(
                "SELECT time, steps, kcal, distance, heart_rate FROM activity ORDER BY time"):
            d = days.setdefault(_day(t), {"steps": 0, "calories": 0, "distance": 0, "hr": []})
            d["steps"] += st or 0
            d["calories"] += cal or 0
            d["distance"] += dist or 0
            if hr:
                d["hr"].append(hr)
        for day, st, cal, dist in self.db.execute("SELECT day, steps, calories, distance FROM totals"):
            d = days.setdefault(day, {"steps": 0, "calories": 0, "distance": 0, "hr": []})
            d.update(steps=st, calories=cal, distance=dist)
        rows = []
        for day in sorted(days):
            d = days[day]
            night = self.night(day)
            hr = d["hr"]
            rows.append([day, d["steps"], int(round(d["calories"])), d["distance"],
                         min(hr) if hr else "", round(sum(hr) / len(hr)) if hr else "", max(hr) if hr else "",
                         night["minutes"] or "", night["byType"].get("deep", "") or ""])
        self._write("daily.csv", ["day", "steps", "kcal", "distance_m", "heart_rate_min",
                                  "heart_rate_avg", "heart_rate_max", "sleep_minutes", "deep_sleep_minutes"], rows)


def _thin(points, step):
    """Keep the first point of every `step`-second bucket."""
    out = []
    last_bucket = None
    for t, v in points:
        bucket = t // step
        if bucket != last_bucket:
            out.append([t, v])
            last_bucket = bucket
    return out
