"""Health sync: FitnessData packets (Gadgetbridge vectors), a full sync against the
simulated watch, and the SQLite/CSV store."""

import csv
import os
import socket
import sys
import tempfile
import threading
import time
import unittest

sys.path.insert(0, os.path.dirname(__file__))
import stubs  # noqa: E402,F401

from watchbridge.health import HealthStore  # noqa: E402
from watchbridge.huawei import device as D  # noqa: E402
from watchbridge.huawei import fitness as F  # noqa: E402
from watchbridge.huawei.packet import Params, StreamParser  # noqa: E402
from fake_watch import FakeWatch  # noqa: E402

H = bytes.fromhex


def zero_params():
    p = Params()
    p.secret_key = bytes(16)
    return p


def decode(hexstr):
    pkts = StreamParser(zero_params()).feed(H(hexstr))
    assert len(pkts) == 1
    return pkts[0]


class TestGadgetbridgeVectors(unittest.TestCase):
    """From Gadgetbridge's TestFitnessData.java (key and IV all zero)."""

    def test_message_count_requests(self):
        self.assertEqual(F.message_count_request(F.FC.SLEEP_COUNT, 0, 0x01020304).serialize(zero_params(), bytes(16)),
                         [H("5a002a00070c7c01017d10000000000000000000000000000000007e1032697b5185209b166b938a3dd59af929df07")])
        self.assertEqual(F.message_count_request(F.FC.STEP_COUNT, 0x01020304, 0x10203040)
                         .serialize(zero_params(), bytes(16)),
                         [H("5a002a00070a7c01017d10000000000000000000000000000000007e104d527957493075c6285b79d5ab890d1ea9c9")])

    def test_message_count_response(self):
        for raw in ("5a002a00070c7c01017d10000000000000000000000000000000007e10f6fbc0b64f9afa7753287d13ca49dafd9309",
                    "5a002a00070a7c01017d10000000000000000000000000000000007e10f6fbc0b64f9afa7753287d13ca49dafdd493"):
            self.assertEqual(F.parse_message_count(decode(raw).tlv), 0x1337)

    def test_message_data_requests(self):
        self.assertEqual(F.message_data_request(F.FC.SLEEP_DATA, 0x1337).serialize(zero_params(), bytes(16)),
                         [H("5a002a00070d7c01017d10000000000000000000000000000000007e10f6fbc0b64f9afa7753287d13ca49dafd7dad")])
        self.assertEqual(F.message_data_request(F.FC.STEP_DATA, 0x1337).serialize(zero_params(), bytes(16)),
                         [H("5a002a00070b7c01017d10000000000000000000000000000000007e10f6fbc0b64f9afa7753287d13ca49dafd3a37")])

    def test_sleep_response_with_short_timestamps(self):
        pkt = decode("5a003a00070d7c01017d10000000000000000000000000000000007e20a49ed8d37a0e5155c548"
                     "0799f599483e41ed16f152d29f38e8b183d6cb52b09f4805")
        number, periods = F.parse_sleep_data(pkt.tlv)
        self.assertEqual(number, 0x1337)
        self.assertEqual(periods, [])  # both containers have fewer than 6 timestamp bytes

    def test_step_response(self):
        pkt = decode("5a005a00070b7c01017d10000000000000000000000000000000007e40dcb7f6aab2f103532539e479ddbf18"
                     "7b9830b74c33d20ca5eefe5fa51220ec7938ec9e4dfcc35c5967514bef5048b7f8c7e3f7df82b41ab894780d"
                     "da53e3bebf21c2")
        number, samples, errors = F.parse_step_data(pkt.tlv)
        self.assertEqual((number, errors), (0x1337, 2))  # empty data, and data too short
        self.assertEqual(samples[0], {"time": 0xCAFEBEEF + 120, "steps": 1, "calories": 2, "distance": 3,
                                      "unknown": []})
        self.assertEqual(samples[1], {"time": 0xCAFEBEEF + 120, "unknown": [(1, 0x01, 1)]})

    def test_step_response_single_byte_fields(self):
        pkt = decode("5a003a00070b7c01017d10000000000000000000000000000000007e20cfa7763069a3836ed28470c8ca94"
                     "87d20d1ef56072a4d98ff6df09353c8662000a3b")
        number, samples, errors = F.parse_step_data(pkt.tlv)
        self.assertEqual(samples, [{"time": 2, "unknown": [(1, 0x20, 1)]},
                                   {"time": 0x3E, "heart_rate": 2, "unknown": []}])

    def test_spo2(self):
        pkt = decode("5a003a00070b7c01017d10000000000000000000000000000000007e2030df42c97991363d806b99d33fbf"
                     "1f1ec10bbfcdae38896060f793843a09d3771eb9")
        _, samples, _ = F.parse_step_data(pkt.tlv)
        self.assertEqual(samples, [{"time": 0xCAFEBEEF, "spo2": 0x42, "unknown": []}])

    def test_missing_count_is_an_error(self):
        pkt = decode("5a002a00070b7c01017d10000000000000000000000000000000007e104cdd9979f63c1ebb0a958d1205817fffeb45")
        with self.assertRaises(KeyError):
            F.parse_step_data(pkt.tlv)


class TestStepBytes(unittest.TestCase):
    def test_heart_rate_above_127_is_not_negative(self):
        self.assertEqual(F.parse_step_bytes(bytes([0x40, 168]))["heart_rate"], 168)

    def test_all_fields(self):
        data = bytes([0x80 | 0x40 | 0x08 | 0x04 | 0x02, 0x03, 0x00, 0x2A, 0x00, 0x05, 0x00, 0x20, 72, 97, 55])
        self.assertEqual(F.parse_step_bytes(data), {"steps": 42, "calories": 5, "distance": 32, "heart_rate": 72,
                                                    "spo2": 97, "resting_heart_rate": 55, "unknown": []})


def minute(steps=None, hr=None):
    bitmap, body = 0, b""
    if steps is not None:
        bitmap |= 0x02
        body += steps.to_bytes(2, "big")
    if hr is not None:
        bitmap |= 0x40
        body += bytes([hr])
    return bytes([bitmap]) + body


class Recorder(D.Listener):
    def __init__(self):
        self.connected = threading.Event()
        self.health = threading.Event()
        self.result = None

    def on_state(self, state, detail=""):
        if state == D.STATE_CONNECTED:
            self.connected.set()

    def on_health_data(self, result):
        self.result = result
        self.health.set()


class TestHealthSync(unittest.TestCase):
    def test_sync_against_simulated_watch(self):
        base = int(time.time()) - 3 * 3600
        health = {
            "totals": (5432, 210, 3900),
            "steps": [{"base": base, "minutes": [(0, minute(steps=30, hr=80)), (1, minute(steps=12))]},
                      {"base": base + 3600, "minutes": [(5, minute(hr=150))]}],
            "sleep": [{"periods": [(0x06, base - 8 * 3600, 90), (0x07, base - 8 * 3600 + 5400, 45)]}],
        }
        phone_sock, watch_sock = socket.socketpair()
        watch = FakeWatch(watch_sock, health=health).start()
        rec = Recorder()
        dev = D.HuaweiWatch(phone_sock, "AA:BB:CC:DD:EE:FF", D.DeviceStore({}, lambda: None), rec)
        self.addCleanup(dev.stop)
        self.addCleanup(watch_sock.close)
        dev.start()
        self.assertTrue(rec.connected.wait(10))
        dev.sync_health(base - 10 * 86400, base - 10 * 86400)
        # A notification queued during the sync still goes out (one request per job)
        dev.send_notification("Alice", "Hi", key="n1")
        self.assertTrue(rec.health.wait(10))
        r = rec.result
        self.assertEqual(r["error"], "")
        self.assertEqual(r["totals"], {"steps": 5432, "calories": 210, "distance": 3900})
        self.assertEqual([(s["time"] - base, s.get("steps"), s.get("heart_rate")) for s in r["samples"]],
                         [(0, 30, 80), (60, 12, None), (3600 + 300, None, 150)])
        self.assertEqual(r["sleep"], [(base - 8 * 3600, base - 8 * 3600 + 5400, 0x06),
                                      (base - 8 * 3600 + 5400, base - 8 * 3600 + 8100, 0x07)])
        self.assertTrue(watch.notifications)
        # Requests went out in Gadgetbridge's order: sleep, steps, totals (0x23, the resting
        # heart rate capability, is sent while connecting)
        order = [c for c, _ in watch.fitness_requests if c != 0x23]
        self.assertEqual(order, [0x0C, 0x0D, 0x0A, 0x0B, 0x0B, 0x03])


class TestHealthStore(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.store = HealthStore(self.folder)
        self.addCleanup(self.store.close)
        # 07:00 local time today
        lt = time.localtime()
        self.t0 = int(time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 7, 0, 0, 0, 0, -1)))
        self.day = time.strftime("%Y-%m-%d", time.localtime(self.t0))

    def result(self, samples=(), sleep=(), totals=None):
        return {"samples": list(samples), "sleep": list(sleep), "totals": totals, "error": "", "end": self.t0}

    def test_minutes_are_merged_not_overwritten(self):
        self.store.add_sync_result(self.result([{"time": self.t0, "steps": 50}, {"time": self.t0, "heart_rate": 90}]))
        self.store.add_sync_result(self.result([{"time": self.t0, "spo2": 96, "heart_rate": 255}]))
        row = self.store.db.execute("SELECT steps, heart_rate, spo2 FROM activity").fetchone()
        self.assertEqual(row, (50, 90, 96))  # 255 = not measured, keeps the earlier value

    def test_day_summary_and_csv(self):
        samples = [{"time": self.t0 + 60 * i, "steps": 10, "heart_rate": 60 + i} for i in range(30)]
        sleep = [(self.t0 - 7 * 3600, self.t0 - 4 * 3600, 0x06), (self.t0 - 4 * 3600, self.t0 - 3 * 3600, 0x07)]
        counts = self.store.add_sync_result(self.result(samples, sleep), now=self.t0)
        self.assertEqual(counts, {"minutes": 30, "sleep": 2, "sleepSessions": 0, "stress": 0})
        s = self.store.day_summary(self.day)
        self.assertEqual((s["steps"], s["hourlySteps"][7], s["heartRateMin"], s["heartRateMax"]), (300, 300, 60, 89))
        self.assertEqual(s["sleep"]["byType"], {"light": 180, "deep": 60})
        self.assertEqual(self.store.last_activity_time(), self.t0 + 29 * 60)
        month = time.strftime("%Y-%m", time.localtime(self.t0))
        with open(os.path.join(self.folder, "activity-%s.csv" % month), encoding="utf-8") as f:
            rows = list(csv.reader(f))
        self.assertEqual(rows[0][:5], ["time", "steps", "kcal", "distance_m", "heart_rate"])
        self.assertEqual(len(rows), 31)
        with open(os.path.join(self.folder, "daily.csv"), encoding="utf-8") as f:
            daily = list(csv.DictReader(f))
        self.assertEqual((daily[-1]["day"], daily[-1]["steps"], daily[-1]["sleep_minutes"]), (self.day, "300", "240"))

    def test_minute_calories_are_small_calories(self):
        # Real GT 5 data: two busy minutes of 3742 and 2981 calories, i.e. about 6.7 kcal
        self.store.add_sync_result(self.result([{"time": self.t0, "steps": 112, "calories": 3742},
                                                {"time": self.t0 + 60, "steps": 106, "calories": 2981}]))
        self.assertEqual(self.store.day_summary(self.day)["calories"], 7)

    def test_non_sleep_periods_are_not_counted_as_sleep(self):
        # On a GT 5 the "sleep" messages also carry type 0x01 periods while walking
        sleep = [(self.t0 - 3600, self.t0 - 3000, 0x06), (self.t0 + 600, self.t0 + 1200, 0x01)]
        self.store.add_sync_result(self.result(sleep=sleep))
        night = self.store.day_summary(self.day)["sleep"]
        self.assertEqual((night["minutes"], night["byType"]), (10, {"light": 10}))
        with open(os.path.join(self.folder, "sleep.csv"), encoding="utf-8") as f:
            self.assertEqual([r["type"] for r in csv.DictReader(f)], ["light", "other-0x01"])

    def test_watch_totals_win_for_their_day(self):
        self.store.add_sync_result(self.result([{"time": self.t0, "steps": 10}],
                                               totals={"steps": 8000, "calories": 300, "distance": 5000}), now=self.t0)
        self.assertEqual(self.store.day_summary(self.day)["steps"], 8000)


if __name__ == "__main__":
    unittest.main()
