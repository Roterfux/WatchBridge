# WatchBridge - Huawei Watch GT 5 companion for Sailfish OS
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Make the phone findable: ring through NGF and show a notification.

The phone is most likely lying somewhere with the app closed, so nothing here depends on the
UI. Tapping the notification stops the ring through the daemon's own D-Bus method (lipstick
calls the method named in the x-nemo-remote-action hints).

Everything goes through call_async, so the main loop never waits for ngfd or lipstick. Their
replies can arrive after the ring was stopped; a late sound or notification is then stopped
as soon as its id is known.
"""

import logging

import dbus

log = logging.getLogger(__name__)

# ngfd is on the system bus, unlike the notifications
NGF_SERVICE = "com.nokia.NonGraphicFeedback1.Backend"
NGF_PATH = "/com/nokia/NonGraphicFeedback1"
NGF_IFACE = "com.nokia.NonGraphicFeedback1"
# The alarm sound: "ringtone" follows the profile's ring volume, "clock" plays at a fixed full
# volume, and a lost phone is often a silent one
NGF_EVENT = "clock"

NOTIFY_SERVICE = "org.freedesktop.Notifications"
NOTIFY_PATH = "/org/freedesktop/Notifications"
NOTIFY_IFACE = "org.freedesktop.Notifications"

RING_TIME = 30  # seconds, unless the watch or the user stops it first

APP_NAME = "WatchBridge"   # NotificationMonitor skips this name, so the watch is not told about it
SUMMARY = "Here I am!"
BODY = "Your watch is looking for this phone. Tap to stop the ringing."
STOP_CALL = "harbour.watchbridge /harbour/watchbridge harbour.watchbridge.Daemon StopFindPhone"


def notification_args():
    """Arguments of Notify (susssasa{sv}i): an alert that stays until the ring ends."""
    hints = {
        "x-nemo-preview-summary": SUMMARY,
        "x-nemo-preview-body": BODY,
        "x-nemo-remote-action-default": STOP_CALL,
        "x-nemo-remote-action-stop": STOP_CALL,
        "urgency": dbus.Byte(2),
    }
    return (APP_NAME, 0, "harbour-watchbridge", SUMMARY, BODY, ["default", "", "stop", "Found it"], hints, 0)


class PhoneRinger:
    """start() and stop() run on the main loop; on_timeout() follows a ring nobody stopped."""

    def __init__(self, session_bus, system_bus, on_timeout, timeout_add=None, source_remove=None):
        if timeout_add is None:
            from gi.repository import GLib
            timeout_add, source_remove = GLib.timeout_add_seconds, GLib.source_remove
        self.session_bus = session_bus
        self.system_bus = system_bus
        self.on_timeout = on_timeout
        self._timeout_add = timeout_add
        self._source_remove = source_remove
        self.active = False
        self._ring = 0            # which ring a late reply belongs to
        self._timer = None
        self._sound = None        # ngfd's id of the running sound
        self._notification = None

    def start(self):
        if self.active:
            return  # the watch repeats itself; a new timer here would only extend the ring
        self.active = True
        self._ring += 1
        ring = self._ring
        self._timer = self._timeout_add(RING_TIME, self._expired)
        log.info("Find phone: ringing")
        self.system_bus.call_async(NGF_SERVICE, NGF_PATH, NGF_IFACE, "Play", "sa{sv}",
                                   (NGF_EVENT, {"sound.repeat": dbus.Boolean(True)}),
                                   lambda sound: self._playing(ring, int(sound)),
                                   lambda e: log.warning("Could not play the find-phone sound: %s", e))
        self.session_bus.call_async(NOTIFY_SERVICE, NOTIFY_PATH, NOTIFY_IFACE, "Notify", "susssasa{sv}i",
                                    notification_args(),
                                    lambda notification: self._shown(ring, int(notification)),
                                    lambda e: log.warning("Could not show the find-phone notification: %s", e))

    def stop(self):
        if not self.active:
            return
        self.active = False
        log.info("Find phone: stopped")
        if self._timer is not None:
            self._source_remove(self._timer)
            self._timer = None
        if self._sound is not None:
            self._stop_sound(self._sound)
            self._sound = None
        if self._notification is not None:
            self._close_notification(self._notification)
            self._notification = None

    def _expired(self):
        self._timer = None
        self.stop()
        self.on_timeout()
        return False

    def _current(self, ring):
        return self.active and ring == self._ring

    def _playing(self, ring, sound):
        if self._current(ring):
            self._sound = sound
        else:
            self._stop_sound(sound)

    def _shown(self, ring, notification):
        if self._current(ring):
            self._notification = notification
        else:
            self._close_notification(notification)

    def _stop_sound(self, sound):
        self.system_bus.call_async(NGF_SERVICE, NGF_PATH, NGF_IFACE, "Stop", "u", (dbus.UInt32(sound),),
                                   lambda *a: None,
                                   lambda e: log.warning("Could not stop the find-phone sound: %s", e))

    def _close_notification(self, notification):
        self.session_bus.call_async(NOTIFY_SERVICE, NOTIFY_PATH, NOTIFY_IFACE, "CloseNotification", "u",
                                    (dbus.UInt32(notification),), lambda *a: None,
                                    lambda e: log.warning("Could not close the find-phone notification: %s", e))
