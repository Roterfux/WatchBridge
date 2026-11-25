# WatchBridge - Huawei Watch GT 5 companion for Sailfish OS
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The phone's battery saver and do-not-disturb switches.

Battery saver: mce on the system bus (get_psm_state, signal psm_state_ind).
Do not disturb: the dconf key /lipstick/do_not_disturb (what the status bar's moon icon shows).
dconf announces changes on the session bus with ca.desrt.dconf.Writer.Notify.
"""

import logging
import subprocess

import dbus

log = logging.getLogger(__name__)

MCE_SERVICE = "com.nokia.mce"
MCE_REQUEST_PATH = "/com/nokia/mce/request"
MCE_REQUEST_IFACE = "com.nokia.mce.request"
MCE_SIGNAL_PATH = "/com/nokia/mce/signal"
MCE_SIGNAL_IFACE = "com.nokia.mce.signal"
DND_KEY = "/lipstick/do_not_disturb"


def read_dconf_bool(key):
    """True/False for a dconf key, None if unset or dconf is missing."""
    try:
        out = subprocess.run(["dconf", "read", key], capture_output=True, text=True, timeout=3).stdout.strip()
    except (OSError, subprocess.SubprocessError) as e:
        log.debug("dconf read %s failed: %s", key, e)
        return None
    return {"true": True, "false": False}.get(out)


def dconf_touches(prefix, changes, key):
    """Whether a dconf Notify(prefix, changes) covers `key`."""
    paths = [str(prefix) + str(c) for c in changes] or [str(prefix)]
    return any(key.startswith(p) if p.endswith("/") else key == p for p in paths)


class PhoneState:
    def __init__(self, session_bus, system_bus, on_change):
        self.session_bus = session_bus
        self.system_bus = system_bus
        self.on_change = on_change
        self.power_save = False
        self.do_not_disturb = False

    def start(self):
        try:
            self.system_bus.add_signal_receiver(self._psm_changed, signal_name="psm_state_ind",
                                                dbus_interface=MCE_SIGNAL_IFACE, path=MCE_SIGNAL_PATH)
            self.system_bus.call_async(MCE_SERVICE, MCE_REQUEST_PATH, MCE_REQUEST_IFACE, "get_psm_state", "", (),
                                       self._psm_changed,
                                       lambda e: log.info("Battery saver state unknown: %s", e))
        except dbus.DBusException as e:
            log.warning("Cannot follow the battery saver: %s", e)
        try:
            self.session_bus.add_signal_receiver(self._dconf_changed, signal_name="Notify",
                                                 dbus_interface="ca.desrt.dconf.Writer")
        except dbus.DBusException as e:
            log.warning("Cannot follow do not disturb: %s", e)
        self._read_dnd()

    def _psm_changed(self, active):
        active = bool(active)
        if active != self.power_save:
            self.power_save = active
            log.info("Phone battery saver %s", "on" if active else "off")
            self.on_change()

    def _dconf_changed(self, prefix, changes, tag=""):
        if dconf_touches(prefix, changes, DND_KEY):
            self._read_dnd()

    def _read_dnd(self):
        value = bool(read_dconf_bool(DND_KEY))
        if value != self.do_not_disturb:
            self.do_not_disturb = value
            log.info("Phone do not disturb %s", "on" if value else "off")
            self.on_change()
