"""Tests for the Sailfish-facing pieces that do not need a real D-Bus."""

import json
import os
import sys
import tempfile
import types
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "daemon"))

# Minimal stand-in so the modules import without dbus-python installed
if "dbus" not in sys.modules:
    fake = types.ModuleType("dbus")
    fake.bus = types.ModuleType("dbus.bus")
    fake.DBusException = Exception
    sys.modules["dbus"] = fake
    sys.modules["dbus.bus"] = fake.bus

from watchbridge.config import Config  # noqa: E402
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

        class Msg:
            def __init__(self, app):
                self.args = [app, 0, "", "Bob", "Hi", [], {"category": "x-nemo.email"}, -1]

            def get_member(self):
                return "Notify"

            def get_interface(self):
                return "org.freedesktop.Notifications"

            def get_signature(self):
                return "susssasa{sv}i"

            def get_args_list(self):
                return self.args

        mon._filter(None, Msg("Email"))
        mon._filter(None, Msg("WatchBridge"))
        self.assertEqual(seen, [("Email", "com.android.email")])
        self.assertEqual(forwarded, [])


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


if __name__ == "__main__":
    unittest.main()
