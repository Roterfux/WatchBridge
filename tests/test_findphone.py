"""Find my phone: the ring and notification, and the exchange with the watch."""

import os
import socket
import sys
import threading
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "daemon"))
sys.path.insert(0, os.path.dirname(__file__))

import stubs  # noqa: E402,F401
from watchbridge import findphone as F  # noqa: E402
from watchbridge import service as S  # noqa: E402
from watchbridge.huawei import device as D  # noqa: E402
from watchbridge.huawei.tlv import TLV  # noqa: E402
from fake_watch import FakeWatch  # noqa: E402


class FakeBus:
    def __init__(self, name="session", calls=None):
        self.name = name
        self.calls = [] if calls is None else calls     # (method, args, reply, error, bus name)

    def call_async(self, service, path, iface, method, signature, args, reply, error, timeout=-1):
        self.calls.append((method, args, reply, error, self.name))

    def methods(self):
        return [c[0] for c in self.calls]

    def answer(self, method, value):
        next(c for c in self.calls if c[0] == method)[2](value)


class TestRinger(unittest.TestCase):
    def setUp(self):
        self.bus = FakeBus()
        self.timers = {}
        self.timeouts = 0

        def add(seconds, fn):
            self.timers[len(self.timers) + 1] = (seconds, fn)
            return len(self.timers)

        def expired():
            self.timeouts += 1

        self.removed = []
        system_bus = FakeBus("system", self.bus.calls)
        self.ringer = F.PhoneRinger(self.bus, system_bus, expired, add, self.removed.append)

    def test_rings_and_notifies(self):
        self.ringer.start()
        self.assertTrue(self.ringer.active)
        self.assertEqual(self.bus.methods(), ["Play", "Notify"])
        self.assertEqual(self.bus.calls[0][1][0], "clock")  # "ringtone" follows the silent profile
        self.assertEqual(self.timers[1][0], F.RING_TIME)

    def test_sound_goes_to_the_system_bus(self):
        # ngfd is not on the session bus: the first version rang nothing on the real phone
        self.ringer.start()
        self.bus.answer("Play", 7)
        self.bus.answer("Notify", 9)
        self.ringer.stop()
        self.assertEqual({c[0]: c[4] for c in self.bus.calls},
                         {"Play": "system", "Stop": "system", "Notify": "session", "CloseNotification": "session"})

    def test_second_start_changes_nothing(self):
        self.ringer.start()
        self.ringer.start()
        self.assertEqual(self.bus.methods(), ["Play", "Notify"])
        self.assertEqual(len(self.timers), 1)

    def test_stop_ends_sound_notification_and_timer(self):
        self.ringer.start()
        self.bus.answer("Play", 7)
        self.bus.answer("Notify", 9)
        self.ringer.stop()
        self.assertFalse(self.ringer.active)
        self.assertEqual(self.bus.methods()[2:], ["Stop", "CloseNotification"])
        self.assertEqual(self.bus.calls[2][1][0], 7)
        self.assertEqual(self.bus.calls[3][1][0], 9)
        self.assertEqual(self.removed, [1])

    def test_stop_without_a_ring_does_nothing(self):
        self.ringer.stop()
        self.assertEqual(self.bus.calls, [])

    def test_reply_after_the_stop_is_stopped_too(self):
        self.ringer.start()
        self.ringer.stop()
        self.bus.answer("Play", 7)
        self.bus.answer("Notify", 9)
        self.assertEqual(self.bus.methods()[2:], ["Stop", "CloseNotification"])

    def test_late_reply_does_not_touch_the_next_ring(self):
        self.ringer.start()
        first = self.bus.calls[0]
        self.ringer.stop()
        self.ringer.start()
        first[2](7)                 # the first ring's sound: stop it
        self.assertEqual(self.bus.calls[-1][0], "Stop")
        self.assertTrue(self.ringer.active)
        self.assertIsNone(self.ringer._sound)

    def test_timeout_stops_and_reports(self):
        self.ringer.start()
        self.bus.answer("Play", 7)
        self.assertFalse(self.timers[1][1]())   # one-shot
        self.assertFalse(self.ringer.active)
        self.assertEqual(self.timeouts, 1)
        self.assertIn("Stop", self.bus.methods())
        self.assertEqual(self.removed, [])      # a timer that fired is not removed again

    def test_old_timer_cannot_end_a_newer_ring(self):
        self.ringer.start()
        self.ringer.stop()
        self.assertEqual(self.removed, [1])     # it is cancelled, not left to fire
        self.ringer.start()
        self.assertEqual(sorted(self.timers), [1, 2])

    def test_failure_of_ngf_leaves_the_notification(self):
        self.ringer.start()
        self.bus.calls[0][3]("no ngfd")
        self.assertTrue(self.ringer.active)

    def test_tapping_the_notification_calls_our_own_method(self):
        args = F.notification_args()
        hints = args[6]
        self.assertEqual(args[0], "WatchBridge")  # NotificationMonitor must skip it
        self.assertEqual(hints["x-nemo-remote-action-default"],
                         "%s %s %s StopFindPhone" % (S.BUS_NAME, S.OBJECT_PATH, S.IFACE))
        self.assertEqual(hints["x-nemo-remote-action-default"], hints["x-nemo-remote-action-stop"])
        self.assertEqual(args[5], ["default", "", "stop", "Found it"])


class Recorder(D.Listener):
    def __init__(self):
        self.connected = threading.Event()
        self.find = []

    def on_state(self, state, detail=""):
        if state == D.STATE_CONNECTED:
            self.connected.set()

    def on_find_phone(self, start):
        self.find.append(start)


def wait_for(cond, timeout=10.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False


class TestExchange(unittest.TestCase):
    def connect(self):
        phone, watch_sock = socket.socketpair()
        watch = FakeWatch(watch_sock).start()
        rec = Recorder()
        dev = D.HuaweiWatch(phone, "AA:BB:CC:DD:EE:FF", D.DeviceStore({}, lambda: None), rec)
        self.addCleanup(dev.stop)
        self.addCleanup(watch_sock.close)
        dev.start()
        self.assertTrue(rec.connected.wait(10))
        return dev, watch, rec

    def test_start_and_stop_from_the_watch(self):
        dev, watch, rec = self.connect()
        watch.push(0x0B, 0x01, TLV().put(0x01, True))
        watch.push(0x0B, 0x01, TLV().put(0x01, False))
        self.assertTrue(wait_for(lambda: rec.find == [True, False]), rec.find)

    def test_missing_tag_means_stop(self):
        dev, watch, rec = self.connect()
        watch.push(0x0B, 0x01, TLV())
        self.assertTrue(wait_for(lambda: rec.find == [False]), rec.find)

    def test_watch_is_told_when_the_phone_stops(self):
        dev, watch, rec = self.connect()
        dev.stop_find_phone()
        self.assertTrue(wait_for(lambda: any((p.service, p.command) == (0x0B, 0x02) and p.tlv.get_byte(0x01) == 2
                                             for p in watch.received)))


if __name__ == "__main__":
    unittest.main()
