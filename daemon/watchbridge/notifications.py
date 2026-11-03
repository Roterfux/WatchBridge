# WatchBridge - Huawei Watch GT 5 companion for Sailfish OS
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Observe org.freedesktop.Notifications.Notify calls on the session bus.

Lipstick (the Sailfish home screen) owns the notification service, so we
watch the calls apps make to it using the D-Bus monitoring API, the same way
Amazfish does. Notifications from Android apps (App Support) carry the
originating Android package in the x-nemo-origin-package hint, which lets
the watch show the matching app icon.
"""

import logging
import time

import dbus
import dbus.bus

log = logging.getLogger(__name__)

MATCH = "type='method_call',interface='org.freedesktop.Notifications',member='Notify'"

# Categories that are device status chatter rather than messages
_SYSTEM_CATEGORY_PREFIXES = (
    "x-nemo.battery", "x-nemo.transfer", "x-nemo.connectivity", "device", "network",
    "x-nemo.general.warning", "x-nemo.system-update", "x-jolla.store", "x-nemo.usb",
)

# Map Sailfish notification categories to Android package names the watch knows
_CATEGORY_PACKAGES = {
    "x-nemo.messaging.sms": "com.android.mms",
    "x-nemo.messaging.mms": "com.android.mms",
    "x-nemo.messaging.im": "com.android.mms",
    "x-nemo.email": "com.android.email",
    "x-nemo.call.missed": "com.android.phone",
    "x-nemo.calendar.reminder": "com.android.calendar",
}


class Notification:
    def __init__(self, app_name, summary, body, hints, replaces_id):
        self.app_name = app_name
        self.summary = summary
        self.body = body
        self.hints = hints
        self.replaces_id = replaces_id

    @property
    def category(self):
        return str(self.hints.get("category", ""))

    @property
    def package(self):
        pkg = str(self.hints.get("x-nemo-origin-package", ""))
        if pkg:
            return pkg
        return _CATEGORY_PACKAGES.get(self.category, "sailfish." + (self.app_name or "app").lower().replace(" ", ""))

    @property
    def kind(self):
        """Huawei notification type: 0x02 sms, 0x0F email, 0x7F generic."""
        cat = self.category
        if cat.startswith("x-nemo.messaging.sms") or cat.startswith("x-nemo.messaging.mms"):
            return 0x02
        if cat.startswith("x-nemo.email"):
            return 0x0F
        return 0x7F

    def key(self):
        return "%s|%s|%s" % (self.app_name, self.summary, self.body)

    def to_dict(self):
        return {"app": self.app_name, "title": self.summary, "body": self.body,
                "category": self.category, "time": int(time.time())}


def _text(hints, key, fallback):
    v = hints.get(key)
    return str(v) if v else fallback


MODE_ALL = "all"            # everything except blocked_apps
MODE_SELECTED = "selected"  # only allowed_apps


class NotificationMonitor:
    def __init__(self, on_notification, own_app_name="WatchBridge", on_app_seen=None):
        self.on_notification = on_notification
        # Called with (app_name, package) for every app that sends a notification,
        # filtered or not, so the settings can offer it in the app lists
        self.on_app_seen = on_app_seen or (lambda app_name, package: None)
        self.own_app_name = own_app_name
        self.mode = MODE_ALL
        self.blocked_apps = set()
        self.allowed_apps = set()
        self.include_system = False
        self._recent = {}
        self._bus = None

    def start(self):
        bus = dbus.bus.BusConnection(dbus.bus.BUS_SESSION)
        bus.add_message_filter(self._filter)
        try:
            monitoring = dbus.Interface(bus.get_object("org.freedesktop.DBus", "/org/freedesktop/DBus"),
                                        "org.freedesktop.DBus.Monitoring")
            monitoring.BecomeMonitor([MATCH], dbus.UInt32(0))
            log.info("Monitoring notifications (BecomeMonitor)")
        except dbus.DBusException as e:
            log.warning("BecomeMonitor failed (%s), falling back to eavesdropping", e)
            bus.add_match_string(MATCH + ",eavesdrop='true'")
        self._bus = bus

    def _filter(self, bus, message):
        try:
            if message.get_member() != "Notify" or message.get_interface() != "org.freedesktop.Notifications":
                return
            args = message.get_args_list()
            if len(args) < 7:
                return
            app_name, replaces_id, _icon, summary, body, _actions, hints = args[:7]
            if message.get_signature() != "susssasa{sv}i" or not isinstance(hints, dict):
                log.debug("Ignoring Notify call with unexpected signature %s", message.get_signature())
                return
            hints = dict(hints)
            n = Notification(str(app_name), _text(hints, "x-nemo-preview-summary", str(summary)),
                             _text(hints, "x-nemo-preview-body", str(body)), hints, int(replaces_id))
            if n.app_name and n.app_name != self.own_app_name:
                self.on_app_seen(n.app_name, n.package)
            accepted = self._accept(n)
            log.debug("Notification from %r (%s): %s", n.app_name, n.category, "forward" if accepted else "skip")
            if accepted:
                self.on_notification(n)
        except Exception:  # noqa: BLE001 - never let the filter raise into libdbus
            log.exception("Notification filter error")

    def _accept(self, n):
        if not n.summary and not n.body:
            return False
        if n.app_name == self.own_app_name:
            return False
        if self.mode == MODE_SELECTED:
            if n.app_name not in self.allowed_apps and n.package not in self.allowed_apps:
                return False
        elif n.app_name in self.blocked_apps or n.package in self.blocked_apps:
            return False
        if not self.include_system:
            if n.category.startswith(_SYSTEM_CATEGORY_PREFIXES):
                return False
            if bool(n.hints.get("transient", False)) and n.kind == 0x7F and not n.hints.get("x-nemo-origin-package"):
                return False
        # Apps frequently re-publish identical notifications; drop repeats within a minute
        now = time.time()
        self._recent = {k: t for k, t in self._recent.items() if now - t < 60}
        key = n.key()
        if key in self._recent:
            return False
        self._recent[key] = now
        return True
