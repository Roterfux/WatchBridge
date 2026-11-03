# WatchBridge - Huawei Watch GT 5 companion for Sailfish OS
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Session D-Bus service used by the QML UI, and the glue between components.

Bus name:  harbour.watchbridge
Object:    /harbour/watchbridge
Interface: harbour.watchbridge.Daemon

All structured values are passed as JSON strings, which keeps the QML side
(Nemo.DBus) simple.
"""

import json
import logging
import os
import threading
import time

import dbus
import dbus.service
from gi.repository import GLib

from . import weather
from .bluez import Bluez
from .config import Config
from .huawei import device as D
from .notifications import NotificationMonitor

log = logging.getLogger(__name__)

BUS_NAME = "harbour.watchbridge"
OBJECT_PATH = "/harbour/watchbridge"
IFACE = "harbour.watchbridge.Daemon"

RECONNECT_DELAYS = [5, 15, 30, 60, 120, 300]
WEATHER_MAX_AGE = 30 * 60


def _locale():
    lang = os.environ.get("LANG", "en_US").split(".")[0]
    if "_" in lang:
        language, country = lang.split("_", 1)
    else:
        language, country = lang, lang
    return "%s-%s" % (language or "en", (country or "US").upper())


class _MainLoopListener(D.Listener):
    """Forwards watch callbacks from protocol threads to the GLib main loop."""

    def __init__(self, service, watch_ref):
        self.service = service
        self.watch_ref = watch_ref

    def _post(self, fn, *args):
        GLib.idle_add(lambda: (fn(self.watch_ref(), *args), False)[1])

    def on_state(self, state, detail=""):
        self._post(self.service._watch_state, state, detail)

    def on_battery(self, level):
        self._post(self.service._watch_battery, level)

    def on_device_info(self, info):
        self._post(self.service._watch_info, info)

    def on_find_phone(self, start):
        self._post(self.service._watch_find_phone, start)

    def on_weather_requested(self):
        self._post(self.service._watch_weather_requested)


class Service(dbus.service.Object):
    def __init__(self, session_bus, system_bus, config=None):
        self.session_bus = session_bus
        # Keep our own reference: dbus.service.Object.__init__ manages self._name
        # itself, and if the BusName is garbage collected the name is released.
        self._bus_name_ref = dbus.service.BusName(BUS_NAME, session_bus)
        super().__init__(bus_name=self._bus_name_ref, object_path=OBJECT_PATH)
        self.config = config or Config()
        self.watch = None
        self.state = "unpaired" if not self.config.data["device"]["address"] else "disconnected"
        self.detail = ""
        self.battery = -1
        self.info = {}
        self.weather_report = None
        self.weather_time = 0
        self.weather_error = ""
        self.forwarded = 0
        self.last_notification = None
        self._reconnect_attempt = 0
        self._reconnect_source = None
        self._weather_source = None
        self._weather_busy = False
        self._ngf_id = None
        self._pairing = False
        self._bluez = Bluez(system_bus, on_devices=self._devices_changed, on_connection=self._on_rfcomm,
                            on_device_connected=self._bt_device_connected)
        self._notifications = NotificationMonitor(self._on_notification, on_app_seen=self._on_app_seen)
        self._apply_notification_settings()
        self._notifications.start()
        self._schedule_weather()
        if self.config.data["device"]["address"] and self.config.data["auto_reconnect"]:
            GLib.timeout_add_seconds(2, lambda: (self._connect(), False)[1])

    # =============================================================== D-Bus API
    @dbus.service.method(IFACE, in_signature="", out_signature="s")
    def GetStatus(self):
        return json.dumps(self._status())

    @dbus.service.method(IFACE, in_signature="", out_signature="s")
    def GetSettings(self):
        return json.dumps(self.config.public())

    @dbus.service.method(IFACE, in_signature="s", out_signature="")
    def SetSettings(self, changes_json):
        changes = json.loads(changes_json)
        old_weather = dict(self.config.data["weather"])
        self.config.update_public(changes)
        self._apply_notification_settings()
        if self.config.data["weather"] != old_weather:
            self._schedule_weather()
            self.weather_time = 0
            self._refresh_weather(push=True)
        if "watch" in changes and self.watch is not None:
            self.watch.settings.update(self._watch_settings())
        self._emit_status()

    @dbus.service.method(IFACE, in_signature="", out_signature="s")
    def GetDevices(self):
        return json.dumps(self._bluez.device_list())

    @dbus.service.method(IFACE, in_signature="", out_signature="")
    def StartScan(self):
        try:
            self._bluez.start_scan()
            GLib.timeout_add_seconds(60, lambda: (self._bluez.stop_scan(), False)[1])
        except Exception as e:  # noqa: BLE001
            self.Message("error", "Could not start scanning: %s" % e)

    @dbus.service.method(IFACE, in_signature="", out_signature="")
    def StopScan(self):
        self._bluez.stop_scan()

    @dbus.service.method(IFACE, in_signature="ss", out_signature="")
    def Pair(self, address, name):
        """Bond with the watch over Bluetooth, then run the Huawei first-time auth."""
        address = address.upper()
        self._bluez.stop_scan()
        self._disconnect_watch()
        dev = self.config.data["device"]
        if dev.get("address") and dev["address"] != address:
            self.config.forget_device()
            dev = self.config.data["device"]
        dev["address"] = address
        dev["name"] = name or dev.get("name") or "Huawei Watch"
        dev["auth_key"] = ""  # force a fresh HiChain auth
        self.config.save()
        self._pairing = True
        self._set_state("pairing", "bluetooth")

        def ok():
            self._set_state("connecting", "")
            self._connect()

        def failed(msg):
            self._pairing = False
            self._set_state("auth_failed", "Bluetooth pairing failed: %s" % msg)

        try:
            self._bluez.pair(address, ok, failed)
        except Exception as e:  # noqa: BLE001 - never leave the UI stuck in "pairing"
            log.exception("Pairing could not be started")
            failed(str(e))

    @dbus.service.method(IFACE, in_signature="", out_signature="")
    def Connect(self):
        self._reconnect_attempt = 0
        self._connect()

    @dbus.service.method(IFACE, in_signature="", out_signature="")
    def Disconnect(self):
        self._cancel_reconnect()
        self._disconnect_watch()
        self._set_state("disconnected", "")

    @dbus.service.method(IFACE, in_signature="b", out_signature="")
    def Forget(self, unpair_bluetooth):
        address = self.config.data["device"]["address"]
        self._cancel_reconnect()
        self._disconnect_watch()
        if address and unpair_bluetooth:
            self._bluez.remove(address)
        self.config.forget_device()
        self.battery = -1
        self.info = {}
        self._set_state("unpaired", "")

    @dbus.service.method(IFACE, in_signature="", out_signature="")
    def SendTestNotification(self):
        if not self._ready():
            self.Message("error", "Watch is not connected")
            return
        self.watch.send_notification("WatchBridge", "Notifications from Sailfish OS are working \U0001F44B",
                                     sender="WatchBridge", app_id="harbour-watchbridge", key="test-%d" % time.time())
        self.Message("info", "Test notification sent")

    @dbus.service.method(IFACE, in_signature="", out_signature="")
    def RefreshWeather(self):
        self.weather_time = 0
        self._refresh_weather(push=True, announce=True)

    @dbus.service.method(IFACE, in_signature="", out_signature="")
    def SyncTime(self):
        if self._ready():
            self.watch.sync_time()
            self.Message("info", "Time synchronised")

    @dbus.service.method(IFACE, in_signature="", out_signature="")
    def StopFindPhone(self):
        self._stop_ringing()
        if self._ready():
            self.watch.stop_find_phone()

    @dbus.service.signal(IFACE, signature="s")
    def StatusChanged(self, status_json):
        pass

    @dbus.service.signal(IFACE, signature="s")
    def DevicesChanged(self, devices_json):
        pass

    @dbus.service.signal(IFACE, signature="ss")
    def Message(self, level, text):
        pass

    # ================================================================== status
    def _status(self):
        dev = self.config.data["device"]
        return {
            "state": self.state,
            "detail": self.detail,
            "address": dev["address"],
            "name": dev["name"],
            "battery": self.battery,
            "info": self.info,
            "scanning": self._bluez.scanning,
            "bluetoothOn": self._bluez.powered(),
            "weather": self.weather_report.to_dict() if self.weather_report else None,
            "weatherTime": self.weather_time,
            "weatherError": self.weather_error,
            "notificationsForwarded": self.forwarded,
            "lastNotification": self.last_notification,
        }

    def _emit_status(self):
        self.StatusChanged(json.dumps(self._status()))

    def _set_state(self, state, detail=""):
        self.state = state
        self.detail = detail
        self._emit_status()

    def _ready(self):
        return self.watch is not None and self.watch.is_ready()

    def _devices_changed(self, devices):
        self.DevicesChanged(json.dumps(devices))

    # ============================================================== connection
    def _watch_settings(self):
        w = self.config.data["watch"]
        return {
            "notifications_enabled": self.config.data["notifications"]["enabled"],
            "locale": _locale(),
            "imperial": self.config.data["weather"]["fahrenheit"],
            "24h": w["time_24h"],
            "date_format": w["date_format"],
        }

    def _connect(self):
        address = self.config.data["device"]["address"]
        if not address or self.watch is not None:
            return
        self._cancel_reconnect()
        if self.state not in ("pairing",):
            self._set_state("connecting", "")
        self._bluez.connect(address, self._connect_failed)

    def _connect_failed(self, message):
        log.warning("Connect failed: %s", message)
        was_pairing, self._pairing = self._pairing, False
        if was_pairing:
            # Retrying in the background would only run into the watch's pairing timeout
            self._set_state("auth_failed", message)
            return
        self._set_state("disconnected", message)
        self._schedule_reconnect()

    def _on_rfcomm(self, address, sock):
        if address.upper() != self.config.data["device"]["address"].upper():
            log.warning("Ignoring RFCOMM connection from unexpected device %s", address)
            sock.close()
            return
        if self.watch is not None:
            self.watch.stop()
        dev = self.config.data["device"]
        store = D.DeviceStore(dev, self.config.save)
        holder = {}
        listener = _MainLoopListener(self, lambda: holder.get("watch"))
        watch = D.HuaweiWatch(sock, address, store, listener, phone_model="Sailfish OS",
                              settings=self._watch_settings(), device_name=dev["name"] or "HUAWEI WATCH")
        holder["watch"] = watch
        self.watch = watch
        watch.start(first_connection=not dev.get("auth_key"))

    def _disconnect_watch(self):
        if self.watch is not None:
            watch, self.watch = self.watch, None
            watch.stop()
            self._bluez.disconnect_profile(watch.address)

    def _watch_state(self, watch, state, detail):
        if watch is not self.watch:
            return  # stale callback from an old connection
        if state == "authenticating" and detail == "confirm_on_watch":
            self._set_state("authenticating", "confirm_on_watch")
            return
        if state == D.STATE_CONNECTED:
            self._reconnect_attempt = 0
            self._pairing = False
            if not self.config.data["device"]["name"] and self.info.get("device_name"):
                self.config.data["device"]["name"] = self.info["device_name"]
                self.config.save()
            self._set_state("connected", "")
            self._refresh_weather(push=True)
            return
        if state in (D.STATE_DISCONNECTED, D.STATE_AUTH_FAILED):
            self.watch = None
            was_pairing = self._pairing
            self._pairing = False
            if state == D.STATE_AUTH_FAILED:
                hint = "Pairing failed - make sure the watch is reset/unpaired and try again" if was_pairing \
                    else "The watch rejected the stored pairing. Pair it again."
                self._set_state("auth_failed", detail or hint)
                return
            if was_pairing and not self.config.data["device"].get("auth_key"):
                # Retrying a first pairing in the background only confuses the
                # watch's pairing screen; let the user start it again instead.
                log.warning("First pairing failed: %s", detail)
                self._set_state("auth_failed", detail or "Pairing did not complete")
                return
            self._set_state("disconnected", detail)
            self._schedule_reconnect()
            return
        self._set_state(state, detail)

    def _watch_battery(self, watch, level):
        self.battery = level
        self._emit_status()

    def _watch_info(self, watch, info):
        self.info = info
        self._emit_status()

    def _bt_device_connected(self, address, connected):
        if address.upper() != self.config.data["device"]["address"].upper():
            return
        if connected and self.watch is None and self.state in ("disconnected",) \
                and self.config.data["auto_reconnect"]:
            # The watch came back into range; reconnect promptly
            self._cancel_reconnect()
            GLib.timeout_add_seconds(2, lambda: (self._connect(), False)[1])

    def _schedule_reconnect(self):
        if not self.config.data["auto_reconnect"] or not self.config.data["device"]["address"]:
            return
        self._cancel_reconnect()
        delay = RECONNECT_DELAYS[min(self._reconnect_attempt, len(RECONNECT_DELAYS) - 1)]
        self._reconnect_attempt += 1
        log.info("Reconnecting in %ds", delay)

        def fire():
            self._reconnect_source = None
            self._connect()
            return False

        self._reconnect_source = GLib.timeout_add_seconds(delay, fire)

    def _cancel_reconnect(self):
        if self._reconnect_source is not None:
            GLib.source_remove(self._reconnect_source)
            self._reconnect_source = None

    # ========================================================== notifications
    def _apply_notification_settings(self):
        n = self.config.data["notifications"]
        self._notifications.mode = n.get("mode", "all")
        self._notifications.blocked_apps = set(n.get("blocked_apps", []))
        self._notifications.allowed_apps = set(n.get("allowed_apps", []))
        self._notifications.include_system = bool(n.get("include_system", False))

    def _on_app_seen(self, app_name, package):
        try:
            self.config.remember_app(app_name, package, time.time())
        except OSError as e:
            log.warning("Could not save the list of seen apps: %s", e)

    def _on_notification(self, n):
        if not self.config.data["notifications"]["enabled"] or not self._ready():
            return
        log.info("Forwarding notification from %s", n.app_name)
        self.watch.send_notification(n.summary or n.app_name, n.body, sender=n.app_name, app_id=n.package,
                                     kind=n.kind, key="%s:%d:%s" % (n.app_name, n.replaces_id, n.summary))
        self.forwarded += 1
        self.last_notification = n.to_dict()
        self._emit_status()

    # ================================================================ weather
    def _schedule_weather(self):
        if self._weather_source is not None:
            GLib.source_remove(self._weather_source)
            self._weather_source = None
        w = self.config.data["weather"]
        if not w["enabled"]:
            return
        minutes = max(15, int(w.get("interval_minutes") or 60))

        def tick():
            self._refresh_weather(push=True)
            return True

        self._weather_source = GLib.timeout_add_seconds(minutes * 60, tick)

    def _refresh_weather(self, push=True, announce=False):
        w = self.config.data["weather"]
        if not w["enabled"]:
            if push and self._ready():
                self.watch.send_weather(None)
            return
        if w["latitude"] is None or w["longitude"] is None:
            self.weather_error = "Choose a weather location in the settings"
            self._emit_status()
            if push and self._ready():
                self.watch.send_weather(None)
            return
        if self.weather_report is not None and time.time() - self.weather_time < WEATHER_MAX_AGE:
            if push and self._ready():
                self.watch.send_weather(self.weather_report)
                if announce:
                    self.Message("info", "Weather sent to the watch")
            return
        if self._weather_busy:
            return
        self._weather_busy = True

        def work():
            try:
                report = weather.fetch(float(w["latitude"]), float(w["longitude"]), w["location"], w["fahrenheit"])
                GLib.idle_add(lambda: (self._weather_fetched(report, None, push, announce), False)[1])
            except Exception as e:  # noqa: BLE001
                log.warning("Weather fetch failed: %s", e)
                GLib.idle_add(lambda: (self._weather_fetched(None, str(e), push, announce), False)[1])

        threading.Thread(target=work, daemon=True).start()

    def _weather_fetched(self, report, error, push, announce):
        self._weather_busy = False
        if report is not None:
            self.weather_report = report
            self.weather_time = time.time()
            self.weather_error = ""
            if push and self._ready():
                self.watch.send_weather(report)
                if announce:
                    self.Message("info", "Weather sent to the watch")
        else:
            self.weather_error = error or "Unknown error"
            if announce:
                self.Message("error", "Weather update failed: %s" % self.weather_error)
        self._emit_status()

    def _watch_weather_requested(self, watch):
        if watch is self.watch:
            self._refresh_weather(push=True)

    # ============================================================= find phone
    def _watch_find_phone(self, watch, start):
        if start:
            self._start_ringing()
            self.Message("findphone", "Your watch is looking for this phone")
        else:
            self._stop_ringing()

    def _ngf(self):
        obj = self.session_bus.get_object("com.nokia.NonGraphicFeedback1.Backend", "/com/nokia/NonGraphicFeedback1")
        return dbus.Interface(obj, "com.nokia.NonGraphicFeedback1")

    def _start_ringing(self):
        try:
            self._ngf_id = self._ngf().Play("ringtone", {"sound.repeat": dbus.Boolean(True, variant_level=1)})
            GLib.timeout_add_seconds(30, lambda: (self._stop_ringing(), False)[1])
        except dbus.DBusException as e:
            log.warning("Could not play find-phone sound: %s", e)

    def _stop_ringing(self):
        if self._ngf_id is not None:
            try:
                self._ngf().Stop(dbus.UInt32(self._ngf_id))
            except dbus.DBusException:
                pass
            self._ngf_id = None
