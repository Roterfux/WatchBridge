"""Battery level updates (polling, P2P charging events) and the day/night watch face schedule."""

import datetime
import os
import socket
import sys
import tempfile
import threading
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "daemon"))
sys.path.insert(0, os.path.dirname(__file__))

import stubs  # noqa: E402,F401
from watchbridge import faceschedule as FS  # noqa: E402
from watchbridge import service as S  # noqa: E402
from watchbridge.config import Config  # noqa: E402
from watchbridge.huawei import device as D  # noqa: E402
from watchbridge.huawei import p2p as P2P  # noqa: E402
from fake_watch import FakeWatch  # noqa: E402


def at(h, m, day=15):
    return datetime.datetime(2026, 11, day, h, m)


SCHEDULE = {"enabled": True, "day_start": "07:00", "night_start": "21:00",
            "day": {"file": "100000001", "version": "1.0.0"}, "night": {"file": "200000002", "version": "2.1.0"}}
FACES = [{"file": "100000001", "version": "1.0.0", "current": True},
         {"file": "200000002", "version": "2.1.0", "current": False}]


class TestSchedule(unittest.TestCase):
    def test_periods(self):
        self.assertEqual(FS.current_period(SCHEDULE, at(6, 59)), ("night", at(21, 0, 14)))
        self.assertEqual(FS.current_period(SCHEDULE, at(7, 0)), ("day", at(7, 0)))
        self.assertEqual(FS.current_period(SCHEDULE, at(20, 59)), ("day", at(7, 0)))
        self.assertEqual(FS.current_period(SCHEDULE, at(23, 30)), ("night", at(21, 0)))

    def test_night_starting_after_midnight(self):
        s = dict(SCHEDULE, day_start="08:00", night_start="00:30")
        self.assertEqual(FS.current_period(s, at(0, 10)), ("day", at(8, 0, 14)))
        self.assertEqual(FS.current_period(s, at(3, 0)), ("night", at(0, 30)))
        self.assertEqual(FS.current_period(s, at(9, 0)), ("day", at(8, 0)))

    def test_applied_once_per_period(self):
        face, applied, _ = FS.face_to_apply(SCHEDULE, at(22, 0), FACES, None)
        self.assertEqual((face["file"], applied), ("200000002", at(21, 0)))
        # The user then picks another face on the watch: left alone until the next switch
        face, applied, _ = FS.face_to_apply(SCHEDULE, at(23, 0), FACES, applied)
        self.assertIsNone(face)
        face, applied, _ = FS.face_to_apply(SCHEDULE, at(7, 1, 16), FACES, applied)
        self.assertIsNone(face)                   # the day face is already shown
        self.assertEqual(applied, at(7, 0, 16))

    def test_nothing_without_a_choice_or_the_face(self):
        self.assertIsNone(FS.face_to_apply(dict(SCHEDULE, enabled=False), at(22, 0), FACES, None)[0])
        self.assertIsNone(FS.face_to_apply(dict(SCHEDULE, night=None), at(22, 0), FACES, None)[0])
        self.assertIsNone(FS.face_to_apply(SCHEDULE, at(22, 0), FACES[:1], None)[0])   # deleted from the watch
        self.assertIsNone(FS.face_to_apply(SCHEDULE, at(22, 0), None, None)[0])        # list not read yet


class FakeWatchObject:
    def __init__(self):
        self.operations = []
        self.uploading = False

    def is_ready(self):
        return True

    def watchface_operation(self, file_name, version, operation):
        self.operations.append((file_name, version, operation))


class TestScheduleInTheService(unittest.TestCase):
    def test_settings_change_applies_now(self):
        s = S.Service.__new__(S.Service)
        s.config = Config(os.path.join(tempfile.mkdtemp(), "config.json"))
        s.config.data["face_schedule"] = dict(SCHEDULE, day_start="00:00", night_start="00:00")   # always day
        s.watch, s.watchfaces, s.watchfaces_loading, s._face_applied = FakeWatchObject(), [
            {"file": "100000001", "version": "1.0.0", "current": False}], False, None
        s._emit_status = lambda: None
        s._check_face_schedule()
        s._check_face_schedule()                  # once per period
        self.assertEqual(s.watch.operations, [("100000001", "1.0.0", S.WFP.OPERATION_ACTIVATE)])


class TestBatteryEvents(unittest.TestCase):
    def test_parse(self):
        e = b'{"type":"battery","wearingStatus":"OFF","chargingStatus":"ON","powerStatus":"MIDDLE","powerValue":87}\x00'
        self.assertEqual(P2P.parse_battery_event(e), (87, True))
        self.assertEqual(P2P.parse_battery_event(b'{"type":"battery","chargingStatus":"OFF"}'), (None, False))
        self.assertIsNone(P2P.parse_battery_event(b'{"type":"other"}'))
        self.assertIsNone(P2P.parse_battery_event(b"not json"))

    def test_charging_event_from_the_watch_and_polling(self):
        phone, watch_sock = socket.socketpair()
        watch = FakeWatch(watch_sock).start()
        levels = []
        connected = threading.Event()

        class Rec(D.Listener):
            def on_state(self, state, detail=""):
                if state == D.STATE_CONNECTED:
                    connected.set()

            def on_battery(self, level, charging=None):
                levels.append((level, charging))

        dev = D.HuaweiWatch(phone, "AA:BB:CC:DD:EE:FF", D.DeviceStore({}, lambda: None), Rec())
        self.addCleanup(dev.stop)
        self.addCleanup(watch_sock.close)
        dev.start()
        self.assertTrue(connected.wait(10))
        body = b'{"type":"battery","chargingStatus":"ON","powerValue":64}'
        watch.push(0x34, 0x01, P2P.data(77, P2P.BATTERY_PACKAGE, "com.huawei.health", "SystemApp", body).tlv)
        dev.read_battery()
        end = time.time() + 5
        while time.time() < end and not ((64, True) in levels and levels[-1] == (87, None)):
            time.sleep(0.02)
        self.assertIn((64, True), levels)           # the P2P event, with the charging state
        self.assertEqual(levels[-1], (87, None))    # the polled level (the fake watch reports 87)


class TestNoWarningWhileCharging(unittest.TestCase):
    def test(self):
        s = S.Service.__new__(S.Service)
        s.config = Config(os.path.join(tempfile.mkdtemp(), "config.json"))
        shown = []
        s._notify_phone = lambda summary, body: shown.append(body)
        s._battery_warned, s.battery_charging = False, True
        s._check_low_battery(15)
        self.assertEqual(shown, [])
        s.battery_charging = False
        s._check_low_battery(15)
        self.assertEqual(len(shown), 1)


if __name__ == "__main__":
    unittest.main()
