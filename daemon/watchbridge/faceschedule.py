# WatchBridge - Huawei Watch GT 5 companion for Sailfish OS
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Which watch face to show: one by day, one at night.

The schedule switches at two local times. Each change of period is applied once: a face the user
picks on the watch in between stays until the next switch.
"""

import datetime


def minutes(text, default):
    """"HH:MM" -> minutes after midnight."""
    try:
        h, m = str(text).split(":")
        h, m = int(h), int(m)
        if 0 <= h < 24 and 0 <= m < 60:
            return h * 60 + m
    except ValueError:
        pass
    return default


def current_period(schedule, now):
    """("day" or "night", the local datetime that period began) for `now` (a naive local datetime)."""
    day = minutes(schedule.get("day_start"), 7 * 60)
    night = minutes(schedule.get("night_start"), 21 * 60)
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    at = now.hour * 60 + now.minute

    def start(offset_days, mins):
        return midnight + datetime.timedelta(days=offset_days, minutes=mins)

    if day == night:
        return "day", start(0 if at >= day else -1, day)
    if day < night:
        if day <= at < night:
            return "day", start(0, day)
        return "night", start(0 if at >= night else -1, night)
    # Day starts after night in clock terms (e.g. night 00:30, day 08:00)
    if night <= at < day:
        return "night", start(0, night)
    return "day", start(0 if at >= day else -1, day)


def next_switch(schedule, now):
    """The local datetime of the next day/night change after `now`."""
    day = minutes(schedule.get("day_start"), 7 * 60)
    night = minutes(schedule.get("night_start"), 21 * 60)
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    candidates = [midnight + datetime.timedelta(days=d, minutes=m) for d in (0, 1) for m in (day, night)]
    return min(t for t in candidates if t > now)


def quiet_now(start, end, now):
    """True if `now` lies in the daily window start..end ("HH:MM"; may span midnight, equal = never)."""
    s, e = minutes(start, 22 * 60), minutes(end, 7 * 60)
    at = now.hour * 60 + now.minute
    if s == e:
        return False
    return s <= at < e if s < e else (at >= s or at < e)


def face_to_apply(schedule, now, faces, applied):
    """The face to activate now, or None.

    schedule: {"enabled", "day": {"file", "version"}, "night": {...}, "day_start", "night_start"}
    faces: the faces on the watch (dicts with "file", "version", "current"), or None if unknown
    applied: the period start returned last time (from this function's second value), or None
    Returns (face or None, period start to remember as applied, reason for the log).
    """
    if not schedule or not schedule.get("enabled") or faces is None:
        return None, applied, "off or faces unknown"
    period, began = current_period(schedule, now)
    if applied == began:
        return None, applied, "already applied"
    wanted = schedule.get(period) or {}
    if not wanted.get("file"):
        return None, began, "no %s face chosen" % period
    match = next((f for f in faces if f.get("file") == wanted["file"]), None)
    if match is None:
        return None, began, "%s face %s is not on the watch" % (period, wanted["file"])
    if match.get("current"):
        return None, began, "%s face already shown" % period
    return match, began, "%s face" % period
