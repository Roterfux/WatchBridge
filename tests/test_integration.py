"""Tests for the Sailfish-facing pieces that do not need a real D-Bus."""

import json
import os
import socket
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(__file__))
import stubs  # noqa: E402,F401  - dbus/GLib stand-ins when they are not installed

from watchbridge.config import Config  # noqa: E402
from watchbridge.bluez import Bluez  # noqa: E402
from watchbridge.service import ReconnectBackoff, Service  # noqa: E402
from watchbridge.notifications import Notification, NotificationMonitor  # noqa: E402


class TestNotificationFilter(unittest.TestCase):
    def setUp(self):
        self.mon = NotificationMonitor(lambda n: None)

    def n(self, app="Messages", summary="Bob", body="Hi", **hints):
        return Notification(app, summary, body, hints, 0)

    def test_accepts_messages_and_maps_package(self):
        n = self.n(category="x-nemo.messaging.sms")
        self.assertTrue(self.mon._accept(n))
        self.assertEqual(n.package, "com.android.mms")
        self.assertEqual(n.kind, 0x02)

    def test_android_origin_package(self):
        n = self.n(app="WhatsApp", **{"x-nemo-origin-package": "com.whatsapp", "transient": True})
        self.assertTrue(self.mon._accept(n))
        self.assertEqual(n.package, "com.whatsapp")

    def test_filters(self):
        self.assertFalse(self.mon._accept(self.n(summary="", body="")))
        self.assertFalse(self.mon._accept(self.n(app="WatchBridge")))
        self.assertFalse(self.mon._accept(self.n(category="x-nemo.battery.lowbattery")))
        self.mon.blocked_apps = {"Email"}
        self.assertFalse(self.mon._accept(self.n(app="Email")))

    def test_duplicate_suppressed(self):
        self.assertTrue(self.mon._accept(self.n()))
        self.assertFalse(self.mon._accept(self.n()))
        self.assertTrue(self.mon._accept(self.n(body="Another")))

    def test_include_system(self):
        self.mon.include_system = True
        self.assertTrue(self.mon._accept(self.n(category="x-nemo.battery.lowbattery")))

    def test_selected_apps_only(self):
        self.mon.mode = "selected"
        self.assertFalse(self.mon._accept(self.n(app="Messages")))  # empty allow-list: nothing
        self.mon.allowed_apps = {"Messages", "com.whatsapp"}
        self.mon.blocked_apps = {"Messages"}  # ignored in this mode
        self.assertTrue(self.mon._accept(self.n(app="Messages")))
        self.assertTrue(self.mon._accept(self.n(app="WhatsApp", **{"x-nemo-origin-package": "com.whatsapp"})))
        self.assertFalse(self.mon._accept(self.n(app="Email")))

    def test_filtered_apps_are_still_remembered(self):
        seen, forwarded = [], []
        mon = NotificationMonitor(forwarded.append, on_app_seen=lambda a, p: seen.append((a, p)))
        mon.mode = "selected"

        mon._filter(None, Msg.notify("Email", category="x-nemo.email"))
        mon._filter(None, Msg.notify("WatchBridge", category="x-nemo.email"))
        self.assertEqual(seen, [("Email", "com.android.email")])
        self.assertEqual(forwarded, [])

    def test_dismissed_on_phone_is_reported(self):
        forwarded, closed = [], []
        mon = NotificationMonitor(forwarded.append, on_closed=closed.append)
        mon._filter(None, Msg.notify("Messages", "Bob", "Hi", sender=":1.50", serial=7))
        mon._filter(None, Msg.reply(":1.99", 7, 1))       # someone else's answer: ignored
        mon._filter(None, Msg.reply(":1.50", 7, 904))      # lipstick: notification id 904
        first = forwarded[0]
        self.assertEqual(first.phone_id, 904)
        # An update of 904 keeps its watch key, so the watch replaces it
        mon._filter(None, Msg.notify("Messages", "Bob", "Hi again", replaces=904, sender=":1.50", serial=8))
        mon._filter(None, Msg.reply(":1.50", 8, 904))
        self.assertEqual(forwarded[1].watch_key, first.watch_key)
        mon._filter(None, Msg.closed(904, 1))              # banner expired: stays on the watch
        self.assertEqual(closed, [])
        mon._filter(None, Msg.notify("Mail", "Ann", "Re:", sender=":1.60", serial=3))
        mon._filter(None, Msg.reply(":1.60", 3, 905))
        mon._filter(None, Msg.closed(905, 2))              # dismissed by the user
        mon._filter(None, Msg.closed(905, 2))              # repeated: reported once
        mon._filter(None, Msg.closed(12345, 3))            # never forwarded
        self.assertEqual([n.app_name for n in closed], ["Mail"])


class Msg:
    """Just enough of dbus.lowlevel.Message for NotificationMonitor._filter."""

    def __init__(self, mtype, member="", args=(), sender=":1.1", serial=1, destination=None, reply_serial=None,
                 signature=""):
        self.mtype, self.member, self.args = mtype, member, list(args)
        self.sender, self.serial, self.destination, self.reply_serial = sender, serial, destination, reply_serial
        self.signature = signature

    @classmethod
    def notify(cls, app, summary="Bob", body="Hi", category="", replaces=0, sender=":1.1", serial=1):
        hints = {"category": category} if category else {}
        return cls(1, "Notify", [app, replaces, "", summary, body, [], hints, -1], sender, serial,
                   signature="susssasa{sv}i")

    @classmethod
    def reply(cls, destination, reply_serial, nid):
        return cls(2, args=[nid], destination=destination, reply_serial=reply_serial)

    @classmethod
    def closed(cls, nid, reason):
        return cls(4, "NotificationClosed", [nid, reason])

    def get_type(self):
        return self.mtype

    def get_member(self):
        return self.member

    def get_interface(self):
        return "org.freedesktop.Notifications" if self.member else None

    def get_signature(self):
        return self.signature

    def get_args_list(self):
        return self.args

    def get_sender(self):
        return self.sender

    def get_serial(self):
        return self.serial

    def get_destination(self):
        return self.destination

    def get_reply_serial(self):
        return self.reply_serial


class TestConfig(unittest.TestCase):
    def test_public_hides_secrets_and_merges(self):
        path = os.path.join(tempfile.mkdtemp(), "c", "config.json")
        c = Config(path)
        c.data["device"].update({"address": "AA:BB", "auth_key": "SECRET", "android_id": "X"})
        c.save()
        pub = c.public()
        self.assertNotIn("auth_key", pub["device"])
        self.assertEqual(pub["device"]["address"], "AA:BB")
        c.update_public({"weather": {"fahrenheit": True}, "device": {"auth_key": "evil", "name": "Mine"},
                         "bogus": 1})
        again = Config(path)
        self.assertTrue(again.data["weather"]["fahrenheit"])
        self.assertEqual(again.data["weather"]["interval_minutes"], 60)
        self.assertEqual(again.data["device"]["auth_key"], "SECRET")
        self.assertEqual(again.data["device"]["name"], "Mine")
        self.assertNotIn("bogus", json.load(open(path)))

    def test_remember_app(self):
        c = Config(os.path.join(tempfile.mkdtemp(), "config.json"))
        self.assertTrue(c.remember_app("Signal", "org.thoughtcrime.securesms", 1000))
        self.assertFalse(c.remember_app("Signal", "org.thoughtcrime.securesms", 1060))  # no rewrite yet
        self.assertTrue(c.remember_app("Signal", "org.thoughtcrime.securesms", 1000 + 7 * 3600))
        for i in range(70):
            c.remember_app("App%d" % i, "pkg%d" % i, 50000 + i)
        seen = Config(c.path).data["notifications"]["seen_apps"]
        self.assertEqual(len(seen), 60)
        self.assertNotIn("Signal", seen)      # oldest entries are dropped first
        self.assertIn("App69", seen)
        c.update_public({"notifications": {"mode": "selected", "seen_apps": {}}})
        self.assertEqual(len(c.data["notifications"]["seen_apps"]), 60)  # the UI cannot wipe it
        self.assertEqual(c.data["notifications"]["mode"], "selected")


ADDR = "A8:6E:4E:B0:F0:F7"


class FakeDBusError(Exception):
    def __init__(self, name):
        super().__init__(name)
        self.name = name

    def get_dbus_name(self):
        return self.name

    def get_dbus_message(self):
        return "no reply"


class TestBluezConnect(unittest.TestCase):
    """ConnectProfile answering late must not start a second (direct) connection."""

    def make(self):
        from watchbridge.bluez import HUAWEI_SPP_UUID
        b = Bluez.__new__(Bluez)  # no system bus needed
        b.adapter_path = "/org/bluez/hci1"
        b.devices = {"/org/bluez/hci1/dev_A8_6E_4E_B0_F0_F7":
                     {"Address": ADDR, "UUIDs": [HUAWEI_SPP_UUID], "Trusted": True}}
        b._profile_registered = True
        b._register_profile = lambda: None
        b._last_connection = {}
        b.delivered, b.direct, b.errors, handlers = [], [], [], {}
        b.on_connection = lambda address, sock: b.delivered.append(address)
        b._connect_direct = lambda address, on_error: b.direct.append(address)

        class Device:
            def ConnectProfile(self, uuid, reply_handler, error_handler, timeout):
                handlers["error"] = error_handler

        b._device = lambda address, iface=None: Device()
        b.connect(ADDR, b.errors.append)
        return b, handlers["error"]

    def test_late_error_after_new_connection_is_ignored(self):
        b, error = self.make()
        b._connected(ADDR, object())  # Profile1.NewConnection delivered the socket
        error(FakeDBusError("org.freedesktop.DBus.Error.NoReply"))
        self.assertEqual((b.delivered, b.direct, b.errors), ([ADDR], [], []))

    def test_error_without_connection_falls_back_to_direct(self):
        b, error = self.make()
        error(FakeDBusError("org.bluez.Error.Failed"))
        self.assertEqual(b.direct, [ADDR])


class TestServiceRfcomm(unittest.TestCase):
    def test_extra_socket_does_not_replace_live_connection(self):
        s = Service.__new__(Service)  # no D-Bus needed for this path
        s.config = Config(os.path.join(tempfile.mkdtemp(), "config.json"))
        s.config.data["device"]["address"] = ADDR

        class LiveWatch:
            def is_alive(self):
                return True

            def stop(self):
                raise AssertionError("the working connection was stopped")

        live = s.watch = LiveWatch()
        extra, other = socket.socketpair()
        self.addCleanup(other.close)
        s._on_rfcomm(ADDR, extra)
        self.assertIs(s.watch, live)
        self.assertEqual(extra.fileno(), -1)  # closed


class TestReconnectBackoff(unittest.TestCase):
    def test_short_connections_keep_growing_the_delay(self):
        b = ReconnectBackoff()
        delays = []
        for i in range(4):  # the watch drops every link ~20 s after setup
            b.connected(i * 100)
            self.assertEqual(b.disconnected(i * 100 + 20), 20)
            delays.append(b.next_delay())
        self.assertEqual(delays, [5, 15, 30, 60])
        self.assertTrue(b.flapping)

    def test_stable_connection_resets(self):
        b = ReconnectBackoff()
        b.next_delay(), b.next_delay()
        b.connected(0)
        b.disconnected(600)
        self.assertEqual(b.next_delay(), 5)
        self.assertIsNone(b.disconnected(700))  # not connected in between


class TestVersionMarkers(unittest.TestCase):
    """rpm/harbour-watchbridge.spec stamps the version into these two lines."""

    def test_markers_present(self):
        root = os.path.join(os.path.dirname(__file__), "..")
        with open(os.path.join(root, "daemon", "watchbridge", "__init__.py"), encoding="utf-8") as f:
            self.assertRegex(f.read(), r'(?m)^__version__ = "[^"]*"$')
        with open(os.path.join(root, "qml", "pages", "AboutPage.qml"), encoding="utf-8") as f:
            self.assertEqual(f.read().count('appVersion: "'), 1)


if __name__ == "__main__":
    unittest.main()
