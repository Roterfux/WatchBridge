"""Power saving, do not disturb, the face-switch timer and the heart-rate mode."""

import datetime
import os
import socket
import sys
import tempfile
import threading
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "daemon"))
sys.path.insert(0, os.path.dirname(__file__))

import stubs  # noqa: E402,F401
from watchbridge import faceschedule as FS  # noqa: E402
from watchbridge import phonestate as PS  # noqa: E402
from watchbridge import service as S  # noqa: E402
from watchbridge.config import Config  # noqa: E402
from watchbridge.huawei import device as D  # noqa: E402
from fake_watch import FakeWatch  # noqa: E402


def at(h, m, day=15):
    return datetime.datetime(2026, 11, day, h, m)


class TestTimes(unittest.TestCase):
    def test_next_switch(self):
        s = {"day_start": "07:00", "night_start": "21:00"}
        self.assertEqual(FS.next_switch(s, at(6, 59)), at(7, 0))
        self.assertEqual(FS.next_switch(s, at(7, 0)), at(21, 0))
        self.assertEqual(FS.next_switch(s, at(22, 0)), at(7, 0, 16))
        self.assertEqual(FS.next_switch({"day_start": "08:00", "night_start": "00:30"}, at(23, 0)), at(0, 30, 16))

    def test_quiet_window(self):
        self.assertTrue(FS.quiet_now("22:00", "07:00", at(23, 0)))
        self.assertTrue(FS.quiet_now("22:00", "07:00", at(6, 59)))
        self.assertFalse(FS.quiet_now("22:00", "07:00", at(7, 0)))
        self.assertTrue(FS.quiet_now("13:00", "14:00", at(13, 30)))
        self.assertFalse(FS.quiet_now("13:00", "14:00", at(14, 0)))
        self.assertFalse(FS.quiet_now("08:00", "08:00", at(8, 0)))

    def test_dconf_notify(self):
        self.assertTrue(PS.dconf_touches("/lipstick/do_not_disturb", [""], PS.DND_KEY))
        self.assertTrue(PS.dconf_touches("/lipstick/", ["do_not_disturb", "other"], PS.DND_KEY))
        self.assertTrue(PS.dconf_touches("/", [], PS.DND_KEY))        # a reset of everything
        self.assertFalse(PS.dconf_touches("/lipstick/do_not_disturb_ringtone", [""], PS.DND_KEY))
        self.assertFalse(PS.dconf_touches("/apps/", ["x"], PS.DND_KEY))


class Phone:
    def __init__(self, power_save=False, dnd=False):
        self.power_save, self.do_not_disturb = power_save, dnd


class ReadyWatch:
    uploading = False

    def __init__(self):
        self.sent, self.polls, self.calls = [], 0, []

    def is_ready(self):
        return True

    def read_battery(self):
        self.polls += 1

    def send_notification(self, *a, **k):
        self.sent.append(a)

    def send_incoming_call(self, shown, number):
        self.calls.append(number)
        return True


class Note:
    app_name, summary, body, package, kind, watch_key = "Chat", "Hi", "there", "chat", 0, 1

    def to_dict(self):
        return {}


def service(phone=None):
    s = S.Service.__new__(S.Service)
    s.config = Config(os.path.join(tempfile.mkdtemp(), "config.json"))
    s._phone = phone or Phone()
    s._emit_status = lambda: None
    s.watch = ReadyWatch()
    s.forwarded, s.last_notification = 0, None
    return s


class TestPowerSaving(unittest.TestCase):
    def test_modes(self):
        s = service(Phone(power_save=False))
        self.assertFalse(s._saving())
        s._phone.power_save = True
        self.assertTrue(s._saving())                      # default: follow the phone
        s.config.data["power_save"]["mode"] = "off"
        self.assertFalse(s._saving())
        s.config.data["power_save"]["mode"] = "always"
        s._phone.power_save = False
        self.assertTrue(s._saving())

    def test_battery_poll_hourly_while_saving(self):
        s = service(Phone(power_save=True))
        for minute in (0, 15, 30, 45, 60, 75):
            s._poll_battery(now=10000 + minute * 60)
        self.assertEqual(s.watch.polls, 2)                # at 0 and 60
        s._phone.power_save = False
        s._poll_battery(now=10000 + 90 * 60)
        self.assertEqual(s.watch.polls, 3)

    def test_reconnect_every_30_minutes_while_saving(self):
        s = service(Phone(power_save=True))
        s.config.data["device"]["address"] = "AA:BB:CC:00:11:22"
        s._backoff, s._reconnect_source = S.ReconnectBackoff(), None
        delays = []
        with mock.patch.object(S.GLib, "timeout_add_seconds", lambda d, fn: delays.append(d) or 1), \
                mock.patch.object(S.GLib, "source_remove", lambda src: None):
            for _ in range(len(S.RECONNECT_DELAYS) + 1):
                s._schedule_reconnect()
        self.assertEqual(delays[:6], S.RECONNECT_DELAYS[:6])   # the quick retries stay quick
        self.assertEqual(delays[6:], [S.SAVING_RECONNECT, S.SAVING_RECONNECT])

    def test_health_waits_longer(self):
        s = service(Phone(power_save=True))
        s.config.data["health"]["last_sync"] = 0
        synced = []
        s._sync_health = lambda: synced.append(True)
        with mock.patch.object(S.time, "time", lambda: 7 * 3600):
            s._maybe_sync_health()                        # 7 h > 6 h, but < 12 h while saving
            self.assertEqual(synced, [])
            s._phone.power_save = False
            s._maybe_sync_health()
        self.assertEqual(synced, [True])


class TestDoNotDisturb(unittest.TestCase):
    def test_follows_the_phone(self):
        s = service(Phone(dnd=True))
        s._on_notification(Note())
        self.assertEqual((s.watch.sent, s.held_notifications), ([], 1))
        s._phone.do_not_disturb = False
        s._on_notification(Note())
        self.assertEqual(len(s.watch.sent), 1)

    def test_not_followed(self):
        s = service(Phone(dnd=True))
        s.config.data["do_not_disturb"]["follow_phone"] = False
        self.assertFalse(s._quiet())

    def test_schedule(self):
        s = service()
        s.config.data["do_not_disturb"].update(scheduled=True, start="22:00", end="07:00")
        self.assertTrue(s._quiet(at(23, 0)))
        self.assertFalse(s._quiet(at(12, 0)))

    def test_calls(self):
        s = service(Phone(dnd=True))
        s._call_on_watch, s._contacts_time = None, 0
        s.config.data["calls"]["caller_names"] = False
        s._on_incoming_call(1, "123")
        self.assertEqual(s.watch.calls, ["123"])          # calls still come through by default
        s.config.data["do_not_disturb"]["calls"] = False
        s._on_incoming_call(2, "456")
        self.assertEqual(s.watch.calls, ["123"])


class TestFaceTimer(unittest.TestCase):
    def test_one_wakeup_per_switch_at_most_hourly(self):
        s = service()
        s.config.data["face_schedule"].update(enabled=True, day_start="07:00", night_start="21:00")
        armed = []
        with mock.patch.object(S.GLib, "timeout_add_seconds", lambda d, fn: armed.append(d) or 9), \
                mock.patch.object(S.GLib, "source_remove", lambda src: None):
            s._arm_face_timer()
            s._arm_face_timer(90)
            s.config.data["face_schedule"]["enabled"] = False
            s._arm_face_timer()
        self.assertTrue(5 <= armed[0] <= S.FACE_SCHEDULE_MAX_WAIT)
        self.assertEqual(armed[1:], [90])                 # off: no timer at all
        self.assertIsNone(s._face_timer)


class TestHeartRateMode(unittest.TestCase):
    def sent(self, enabled, mode):
        phone, watch_sock = socket.socketpair()
        watch = FakeWatch(watch_sock).start()
        connected = threading.Event()

        class Rec(D.Listener):
            def on_state(self, state, detail=""):
                if state == D.STATE_CONNECTED:
                    connected.set()

        dev = D.HuaweiWatch(phone, "AA:BB:CC:DD:EE:FF", D.DeviceStore({}, lambda: None), Rec(),
                            settings={"continuous_heart_rate": enabled, "heart_rate_mode": mode})
        self.addCleanup(dev.stop)
        self.addCleanup(watch_sock.close)
        dev.start()
        self.assertTrue(connected.wait(10))
        return [(c, t.get_byte(0x01)) for c, t in watch.fitness_requests if c in (0x17, 0x1C)]

    def test_smart_leaves_realtime_first(self):
        self.assertEqual(self.sent(True, "smart"), [(0x1C, 0), (0x17, 1)])

    def test_realtime(self):
        self.assertEqual(self.sent(True, "realtime"), [(0x1C, 1)])

    def test_no_mode_as_before(self):
        self.assertEqual(self.sent(True, None), [(0x17, 1)])

    def test_off(self):
        self.assertEqual(self.sent(False, "smart"), [(0x1C, 0), (0x17, 0)])


if __name__ == "__main__":
    unittest.main()
