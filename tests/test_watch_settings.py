"""Alarms, profile, move reminder, blood oxygen and the watch battery warning."""

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
from watchbridge.config import Config  # noqa: E402
from watchbridge.health import HealthStore  # noqa: E402
from watchbridge.huawei import alarms as A  # noqa: E402
from watchbridge.huawei import device as D  # noqa: E402
from watchbridge.huawei import fitness as F  # noqa: E402
from watchbridge.huawei.tlv import TLV  # noqa: E402
from watchbridge import service as S  # noqa: E402
from fake_watch import FakeWatch  # noqa: E402


class TestPackets(unittest.TestCase):
    """Byte layouts as Gadgetbridge builds them (Java byte/short/int widths)."""

    def test_user_info(self):
        p = F.user_info(175, 70.5, 40, (1986, 5, 17), F.GENDER_MALE, True, True)
        expected = (TLV().put_byte(0x01, 175).put_byte(0x02, 70).put_byte(0x03, 40)
                    .put_int(0x04, (1986 << 16) + (5 << 8) + 17).put_byte(0x05, 1)
                    .put_byte(0x06, 74)     # Math.round(0.42 * 175 = 73.5) rounds the half up
                    .put_byte(0x07, 145)    # 0.83 * 175 = 145.25
                    .put_int(0x0B, 7050))   # precision weight, kg * 100
        self.assertEqual((p.service, p.command, p.tlv.serialize()), (0x07, 0x02, expected.serialize()))

    def test_user_info_unknown_gender_only_where_supported(self):
        without = F.user_info(170, 60, 30, (1996, 1, 2), F.GENDER_UNKNOWN, False, False)
        self.assertFalse(without.tlv.contains(0x05))
        self.assertFalse(without.tlv.contains(0x0B))
        self.assertEqual(F.user_info(170, 60, 30, (1996, 1, 2), F.GENDER_UNKNOWN, True, False).tlv.get_byte(0x05), 3)

    def test_move_reminder(self):
        p = F.activity_reminder(True, 60, (8, 0), (22, 30), 0x1F)
        inner = TLV().put(0x02, True).put_byte(0x03, 60).put(0x04, bytes([8, 0])).put(0x05, bytes([22, 30])) \
            .put_byte(0x06, 0x1F)
        self.assertEqual((p.command, p.tlv.serialize()), (0x07, TLV().put(0x81, inner).serialize()))

    def test_spo2(self):
        self.assertEqual(F.automatic_spo2(True).tlv.serialize(), TLV().put(0x01, True).serialize())
        self.assertEqual(F.low_spo2_alert(90).tlv.serialize(), TLV().put(0x01, True).put_byte(0x02, 90).serialize())
        self.assertEqual(F.low_spo2_alert(0).tlv.serialize(), TLV().put(0x01, False).serialize())

    def test_alarms(self):
        p = A.set_event_alarms([{"enabled": True, "hour": 6, "minute": 30, "repeat": 0x1F, "name": "Work"},
                                {"enabled": False, "hour": 9, "minute": 5, "repeat": 0, "name": ""}])
        subs = p.tlv.get_object(0x81).get_objects(0x82)
        self.assertEqual([s.get_byte(0x03) for s in subs], [1, 2])           # indexes start at 1
        self.assertEqual(subs[0].get_short(0x05), (6 << 8) | 30)
        self.assertEqual(subs[1].get_string(0x07), "Alarm")                  # never an empty name
        reply = TLV().put(0x81, TLV().put(0x82, subs[1]).put(0x82, subs[0]))
        self.assertEqual(A.parse_event_alarm_list(reply),
                         [{"index": 1, "enabled": True, "hour": 6, "minute": 30, "repeat": 0x1F, "name": "Work"},
                          {"index": 2, "enabled": False, "hour": 9, "minute": 5, "repeat": 0, "name": "Alarm"}])

    def test_no_alarms_switches_them_all_off(self):
        sub = A.set_event_alarms([]).tlv.get_object(0x81).get_objects(0x82)
        self.assertEqual([s.serialize() for s in sub], [TLV().put_byte(0x03, 1).serialize()])


class Recorder(D.Listener):
    def __init__(self):
        self.connected = threading.Event()
        self.alarms = []

    def on_state(self, state, detail=""):
        if state == D.STATE_CONNECTED:
            self.connected.set()

    def on_alarms(self, alarms, error=""):
        self.alarms.append((alarms, error))


def wait_for(cond, timeout=10.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False


class TestOnTheWatch(unittest.TestCase):
    def connect(self, settings=None):
        phone, watch_sock = socket.socketpair()
        watch = FakeWatch(watch_sock).start()
        rec = Recorder()
        dev = D.HuaweiWatch(phone, "AA:BB:CC:DD:EE:FF", D.DeviceStore({}, lambda: None), rec, settings=settings)
        self.addCleanup(dev.stop)
        self.addCleanup(watch_sock.close)
        dev.start()
        self.assertTrue(rec.connected.wait(10))
        return dev, watch, rec

    def test_alarms_are_read_when_connecting_and_replaced(self):
        dev, watch, rec = self.connect()
        self.assertTrue(dev.alarms_supported)
        self.assertEqual(rec.alarms[0][0][0]["name"], "Work")
        dev.set_alarms([{"enabled": True, "hour": 7, "minute": 0, "repeat": 0x60, "name": "Weekend"},
                        {"enabled": True, "hour": 6, "minute": 0, "repeat": 0, "name": "Once"}])
        self.assertTrue(wait_for(lambda: len(rec.alarms) == 2))
        alarms, error = rec.alarms[1]
        self.assertEqual(error, "")
        self.assertEqual([(a["name"], a["hour"], a["repeat"]) for a in alarms], [("Weekend", 7, 0x60), ("Once", 6, 0)])

    def test_settings_are_sent_only_once_set(self):
        dev, watch, rec = self.connect()
        self.assertFalse([c for c, _ in watch.fitness_requests if c in (0x02, 0x07, 0x24, 0x25)])

    def test_profile_reminder_and_spo2_when_connecting(self):
        settings = {"profile": {"height": 180, "weight": 75, "birthday": "1990-06-15", "gender": "female"},
                    "move_reminder": {"enabled": True, "interval": 45, "start": "09:00", "end": "18:00", "days": 0x1F},
                    "automatic_spo2": True, "low_spo2_alert": 85}
        dev, watch, rec = self.connect(settings)
        self.assertTrue(wait_for(lambda: 0x25 in [c for c, _ in watch.fitness_requests]))
        sent = dict(watch.fitness_requests)
        self.assertEqual((sent[0x02].get_byte(0x01), sent[0x02].get_byte(0x05)), (180, F.GENDER_FEMALE))
        self.assertEqual(sent[0x07].get_object(0x81).get_byte(0x03), 45)
        self.assertEqual((sent[0x24].get_bool(0x01), sent[0x25].get_byte(0x02)), (True, 85))


class FakeSessionBus:
    def __init__(self):
        self.calls = []

    def call_async(self, service, path, iface, method, signature, args, reply, error, timeout=-1):
        self.calls.append((method, args))
        reply(len(self.calls))


class TestBatteryWarning(unittest.TestCase):
    def test_warns_once_per_discharge(self):
        s = S.Service.__new__(S.Service)
        s.config = Config(os.path.join(tempfile.mkdtemp(), "config.json"))
        s.session_bus = FakeSessionBus()
        s._battery_warned, s._battery_notification, s.battery_charging = False, 0, None
        for level in (30, 21, 20, 19, 15, 21, 23, 40, 18):
            s._check_low_battery(level)
        shown = [c[1] for c in s.session_bus.calls]
        self.assertEqual([args[4] for args in shown], [S.BATTERY_BODY % 20, S.BATTERY_BODY % 18])
        self.assertEqual(shown[0][0], "WatchBridge")    # not forwarded back to the watch
        self.assertEqual(int(shown[1][1]), 1)          # replaces the first notification

    def test_off(self):
        s = S.Service.__new__(S.Service)
        s.config = Config(os.path.join(tempfile.mkdtemp(), "config.json"))
        s.config.data["watch"]["low_battery_warning"] = 0
        s.session_bus = FakeSessionBus()
        s._battery_warned, s._battery_notification, s.battery_charging = False, 0, None
        s._check_low_battery(5)
        self.assertEqual(s.session_bus.calls, [])


class TestBatteryHistory(unittest.TestCase):
    def test_changes_are_kept_and_repeats_thinned(self):
        store = HealthStore(tempfile.mkdtemp())
        self.addCleanup(store.close)
        t = 1_700_000_000
        self.assertTrue(store.add_battery(80, t))
        self.assertFalse(store.add_battery(80, t + 60))          # same level, too soon
        self.assertTrue(store.add_battery(79, t + 120))
        self.assertTrue(store.add_battery(79, t + 120 + HealthStore.BATTERY_REPEAT))
        self.assertFalse(store.add_battery(120, t + 9999))       # not a level
        self.assertEqual(store.battery_history(t + 100), [[t + 100, 80], [t + 120, 79],
                                                          [t + 120 + HealthStore.BATTERY_REPEAT, 79]])


if __name__ == "__main__":
    unittest.main()
