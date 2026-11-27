# WatchBridge - Huawei Watch GT 5 companion for Sailfish OS
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Session D-Bus service used by the QML UI, and the glue between components.

Bus name:  harbour.watchbridge
Object:    /harbour/watchbridge
Interface: harbour.watchbridge.Daemon

All structured values are passed as JSON strings, which keeps the QML side
(Nemo.DBus) simple.
"""

import datetime
import json
import logging
import os
import threading
import time
import zlib

import dbus
import dbus.service
from gi.repository import GLib

from . import __version__, faceschedule as FS, weather
from .bluez import Bluez
from .calls import CallMonitor
from .config import Config
from .contacts import ContactNames
from .findphone import APP_NAME, NOTIFY_IFACE, NOTIFY_PATH, NOTIFY_SERVICE, PhoneRinger
from .huawei import alarms as A
from .huawei import commands as HC
from .huawei import device as D
from .huawei import p2pcalendar as CAL
from .huawei import watchface as WFP
from .notifications import NotificationMonitor
from .phonecalendar import PhoneCalendar
from .phonestate import PhoneState

log = logging.getLogger(__name__)

BUS_NAME = "harbour.watchbridge"
OBJECT_PATH = "/harbour/watchbridge"
IFACE = "harbour.watchbridge.Daemon"

RECONNECT_DELAYS = [5, 15, 30, 60, 120, 300, 600]   # then every 10 minutes, for as long as it takes
# Every 10 minutes: a watch that is not connected and has no attempt under way gets a fresh one, and an
# attempt that has hung (BlueZ answering "InProgress" and then nothing, a setup that stalled) is restarted
RECONNECT_WATCHDOG = 10 * 60
# A connection must last this long before the reconnect backoff starts over;
# otherwise a link the watch drops right after setup is retried every 5 s forever.
STABLE_CONNECTION = 60
WEATHER_MAX_AGE = 30 * 60
WEATHER_RETRY = 2 * 60            # after a failed download, e.g. no network yet after booting
CONTACTS_REFRESH = 6 * 3600       # re-read the caller names this often
CONTACTS_RETRY_UNKNOWN = 10 * 60  # after a call from an unknown number, re-read at most this often
WATCHFACE_MAX_SIZE = 32 * 1024 * 1024
CALENDAR_REFRESH = 30 * 60        # Sailfish announces no calendar changes, so compare this often
CALENDAR_ANSWER_TIMEOUT = 30      # for the watch to react to a sync request
CALENDAR_MAX_DAYS = 366
BATTERY_SUMMARY = "Watch battery low"
BATTERY_BODY = "%d %% left. Charge your watch soon."
BATTERY_HISTORY_MAX_DAYS = 31
BATTERY_POLL = 15 * 60            # the GT 5 announces no level changes, so ask this often
# The day/night face timer wakes at the next switch, but at least hourly, so a changed clock
# (summer time, another time zone) is noticed
FACE_SCHEDULE_MAX_WAIT = 3600
FACE_SCHEDULE_BUSY_RETRY = 120    # the switch came during an upload or a face-list read
# Power saving (the phone's battery saver, or always): longer gaps between wake-ups and transfers
SAVING_HEALTH_HOURS = 12
SAVING_BATTERY_POLL = 60 * 60
SAVING_WEATHER_MINUTES = 3 * 60
SAVING_CALENDAR = 2 * 3600
SAVING_RECONNECT = 30 * 60        # replaces the 10-minute retries once the quick ones are used up
SPOT_TICK = 60                    # phone-timed heart-rate / SpO2 checks are looked at once a minute
SPOT_HR_WINDOW = 2 * 60           # real-time heart rate stays on this long per check
SPOT_SPO2_WINDOW = 10 * 60        # automatic SpO2 stays on this long per check


class ReconnectBackoff:
    """Growing delays between reconnect attempts, reset only by a stable connection."""

    def __init__(self, delays=RECONNECT_DELAYS, stable=STABLE_CONNECTION):
        self.delays = delays
        self.stable = stable
        self.attempt = 0
        self._since = None

    def reset(self):
        self.attempt = 0

    def connected(self, now):
        self._since = now

    def disconnected(self, now):
        """Returns how long the connection lasted (None if it never got connected)."""
        if self._since is None:
            return None
        lasted, self._since = now - self._since, None
        if lasted >= self.stable:
            self.attempt = 0
        return lasted

    def next_delay(self):
        delay = self.delays[min(self.attempt, len(self.delays) - 1)]
        self.attempt += 1
        return delay

    @property
    def flapping(self):
        """True once more than one reconnect in a row was needed."""
        return self.attempt > 1


def _locale():
    lang = os.environ.get("LANG", "en_US").split(".")[0]
    if "_" in lang:
        language, country = lang.split("_", 1)
    else:
        language, country = lang, lang
    return "%s-%s" % (language or "en", (country or "US").upper())


def _clean_alarm(a):
    hour, minute = int(a["hour"]), int(a["minute"])
    if not (0 <= hour < 24 and 0 <= minute < 60):
        raise ValueError("time %r:%r" % (hour, minute))
    # The watch shows the name in a small space; Huawei's own app allows about 20 characters
    return {"enabled": bool(a.get("enabled", True)), "hour": hour, "minute": minute,
            "repeat": int(a.get("repeat", 0)) & 0x7F, "name": str(a.get("name") or "Alarm")[:20]}


class _MainLoopListener(D.Listener):
    """Forwards watch callbacks from protocol threads to the GLib main loop."""

    def __init__(self, service, watch_ref):
        self.service = service
        self.watch_ref = watch_ref

    def _post(self, fn, *args):
        GLib.idle_add(lambda: (fn(self.watch_ref(), *args), False)[1])

    def on_state(self, state, detail=""):
        self._post(self.service._watch_state, state, detail)

    def on_battery(self, level, charging=None):
        self._post(self.service._watch_battery, level, charging)

    def on_device_info(self, info):
        self._post(self.service._watch_info, info)

    def on_find_phone(self, start):
        self._post(self.service._watch_find_phone, start)

    def on_weather_requested(self):
        self._post(self.service._watch_weather_requested)

    def on_health_data(self, result):
        self._post(self.service._watch_health_data, result)

    def on_call_action(self, action):
        self._post(self.service._watch_call_action, action)

    def on_watchfaces(self, faces, error=""):
        self._post(self.service._watch_faces, faces, error)

    def on_upload(self, state, progress, error="", activated=False, file_name=""):
        self._post(self.service._watch_upload, state, progress, error, activated, file_name)

    def on_calendar_request(self, request):
        self._post(self.service._watch_calendar_request, request)

    def on_calendar_done(self, events, error=""):
        self._post(self.service._watch_calendar_done, events, error)

    def on_alarms(self, alarms, error=""):
        self._post(self.service._watch_alarms, alarms, error)


class Service(dbus.service.Object):
    # Defaults here, so tests that build a Service without __init__ get them too
    _phone = None                       # PhoneState: battery saver and do not disturb
    _battery_polled = 0.0               # monotonic time of the last battery poll
    _calendar_polled = 0.0              # monotonic time of the last timed calendar check
    _face_timer = None
    _spot_next = None           # per instance, made in _spot_tick
    _spot_end = None
    held_notifications = 0              # not sent to the watch because of do not disturb

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
        self._backoff = ReconnectBackoff()
        self._reconnect_source = None
        self._connect_started = 0       # monotonic time of the last connection attempt
        self._user_disconnected = False  # the user tapped Disconnect
        self._weather_source = None
        self._weather_busy = False
        self._weather_retry = None
        self._health = None
        self._health_error = ""
        self._health_syncing = False
        self._health_last_result = None
        self._call_on_watch = None      # handler id of the call shown on the watch
        self.missed_call = None         # latest missed call while Sailfish still shows it
        self.watchfaces = None          # faces on the watch (list), None until read
        self.watchfaces_loading = False
        self.watchfaces_error = ""
        self.upload = {"state": "idle", "progress": 0, "title": "", "error": ""}
        self._upload_preview = None     # preview of the face being sent, kept once installed
        self.calendar = {"syncing": False, "lastSync": 0, "events": 0, "error": ""}
        self.alarms = None              # the watch's alarms as last read, None until read
        self.alarms_loading = False
        self.alarms_error = ""
        self._battery_warned = False    # the low-battery notification was shown for this discharge
        self.battery_charging = None    # True/False once the watch has said so
        self._face_applied = None       # start of the day/night period whose face was last applied
        self._battery_notification = 0
        self._calendar_announce = False  # say so when the running sync ends (started by hand)
        self._calendar_try = 0           # tells a late timeout from the sync that is running
        self._phone_calendar = PhoneCalendar(session_bus)
        self._contacts = ContactNames()
        self._contacts_time = 0
        self._calls = CallMonitor(session_bus, self._on_incoming_call, self._on_call_answered, self._on_call_ended)
        self._open_health_store()
        # Check every 15 minutes whether an automatic health sync is due
        GLib.timeout_add_seconds(15 * 60, lambda: (self._maybe_sync_health(), True)[1])
        self._ringer = PhoneRinger(session_bus, system_bus, self._find_phone_timed_out)
        self._pairing = False
        self._bluez = Bluez(system_bus, on_devices=self._devices_changed, on_connection=self._on_rfcomm,
                            on_device_connected=self._bt_device_connected)
        self._notifications = NotificationMonitor(self._on_notification, on_app_seen=self._on_app_seen,
                                                  on_closed=self._on_notification_closed,
                                                  on_missed_call=self._on_missed_call)
        self._apply_notification_settings()
        self._notifications.start()
        try:
            self._calls.start()
        except dbus.DBusException as e:
            log.warning("Cannot follow phone calls: %s", e)
        try:
            self._phone_calendar.start()
        except dbus.DBusException as e:
            log.warning("Cannot read the calendar: %s", e)
        self._phone = PhoneState(session_bus, system_bus, self._phone_state_changed)
        self._phone.start()
        GLib.timeout_add_seconds(CALENDAR_REFRESH, lambda: (self._timed_calendar_sync(), True)[1])
        GLib.timeout_add_seconds(BATTERY_POLL, lambda: (self._poll_battery(), True)[1])
        GLib.timeout_add_seconds(SPOT_TICK, lambda: (self._spot_tick(), True)[1])
        self._arm_face_timer()
        GLib.timeout_add_seconds(RECONNECT_WATCHDOG, lambda: (self._reconnect_watchdog(), True)[1])
        # Not at once: the first run may show Sailfish's permission prompt
        GLib.timeout_add_seconds(15, lambda: (self._refresh_contacts(), False)[1])
        GLib.timeout_add_seconds(CONTACTS_REFRESH, lambda: (self._refresh_contacts(), True)[1])
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
        old_folder = self.config.data["health"].get("folder")
        old_hr = (self.config.data["health"].get("continuous_heart_rate"),
                  self.config.data["health"].get("heart_rate_mode"))
        old_saving = self._saving()
        old_watch_settings = self._watch_settings()
        old_calls = dict(self.config.data["calls"])
        old_calendar = dict(self.config.data["calendar"])
        old_faces = json.dumps(self.config.data.get("face_schedule"), sort_keys=True)
        self.config.update_public(changes)
        self._apply_notification_settings()
        if self.config.data["calls"] != old_calls:
            self._refresh_contacts()
        if self.config.data["calendar"] != old_calendar:
            self._sync_calendar()
        if json.dumps(self.config.data.get("face_schedule"), sort_keys=True) != old_faces:
            # A new choice applies right away, not only at the next switch
            self._face_applied = None
            self._check_face_schedule()
            self._arm_face_timer()
        if self.config.data["health"].get("folder") != old_folder:
            self._open_health_store()
            self._emit_status()
        new_hr = (self.config.data["health"].get("continuous_heart_rate"),
                  self.config.data["health"].get("heart_rate_mode"))
        if new_hr != old_hr and new_hr[0] is not None and self._ready():
            # Applied right away; otherwise at the next connection
            self.watch.settings["continuous_heart_rate"], self.watch.settings["heart_rate_mode"] = new_hr
            self.watch.set_automatic_heart_rate(bool(new_hr[0]), new_hr[1])
        if self._saving() != old_saving:
            self._saving_changed()
        if self.config.data["weather"] != old_weather:
            self._schedule_weather()
            self.weather_time = 0
            self._refresh_weather(push=True)
        new_watch_settings = self._watch_settings()
        if self.watch is not None:
            self.watch.settings.update(new_watch_settings)
            # Sent right away; otherwise at the next connection
            keys = set()
            if new_watch_settings["profile"] != old_watch_settings["profile"]:
                keys.add("profile")
            if new_watch_settings["move_reminder"] != old_watch_settings["move_reminder"]:
                keys.add("move_reminder")
            if (new_watch_settings["automatic_spo2"], new_watch_settings["low_spo2_alert"]) != \
                    (old_watch_settings["automatic_spo2"], old_watch_settings["low_spo2_alert"]):
                keys.add("spo2")
            if keys and self._ready():
                self.watch.apply_settings(keys)
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
        self._user_disconnected = False
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
        self._user_disconnected = False
        self._backoff.reset()
        self._connect()

    @dbus.service.method(IFACE, in_signature="", out_signature="")
    def Disconnect(self):
        # Stays disconnected until Connect: no retries, no watchdog, no reconnect when it comes in range
        self._user_disconnected = True
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
        self._ringer.stop()
        if self._ready():
            self.watch.stop_find_phone()
        self._emit_status()

    @dbus.service.method(IFACE, in_signature="", out_signature="")
    def SyncHealth(self):
        self._sync_health(announce=True)

    @dbus.service.method(IFACE, in_signature="", out_signature="")
    def SyncCalendar(self):
        self._sync_calendar(announce=True)

    @dbus.service.method(IFACE, in_signature="s", out_signature="s")
    def GetHealth(self, day):
        """Summary for one local date (YYYY-MM-DD, empty = today) as JSON."""
        if self._health is None:
            return json.dumps({"available": False, "error": self._health_error})
        try:
            summary = self._health.day_summary(str(day) or time.strftime("%Y-%m-%d"))
        except ValueError as e:
            return json.dumps({"available": True, "error": str(e)})
        summary["available"] = True
        return json.dumps(summary)

    @dbus.service.method(IFACE, in_signature="i", out_signature="s")
    def GetBatteryHistory(self, days):
        """The watch's battery level over the last `days` days: {"points": [[time, level], ...]}."""
        if self._health is None:
            return json.dumps({"available": False, "points": []})
        days = max(1, min(BATTERY_HISTORY_MAX_DAYS, int(days)))
        since = int(time.time()) - days * 86400
        return json.dumps({"available": True, "since": since, "points": self._health.battery_history(since)})

    # ----------------------------------------------------------------- alarms
    @dbus.service.method(IFACE, in_signature="", out_signature="")
    def RefreshAlarms(self):
        if not self._ready() or not self.watch.alarms_supported:
            return
        self.alarms_loading = True
        self._emit_status()
        self.watch.read_alarms()

    @dbus.service.method(IFACE, in_signature="s", out_signature="")
    def SetAlarms(self, alarms_json):
        """Replaces the watch's alarms: [{"enabled", "hour", "minute", "repeat", "name"}, ...]."""
        if not self._ready() or not self.watch.alarms_supported:
            self.Message("error", "Watch is not connected")
            return
        try:
            alarms = [_clean_alarm(a) for a in json.loads(alarms_json)]
        except (TypeError, ValueError, KeyError) as e:
            self.Message("error", "Invalid alarms: %s" % e)
            return
        if len(alarms) > A.MAX_ALARMS:
            self.Message("error", "The watch holds at most %d alarms" % A.MAX_ALARMS)
            return
        self.alarms_loading = True
        self._emit_status()
        self.watch.set_alarms(alarms)

    @dbus.service.method(IFACE, in_signature="s", out_signature="s")
    def GetHealthWeek(self, day):
        """Week overview, Monday to Sunday, for the week holding `day` (YYYY-MM-DD, empty = today)."""
        if self._health is None:
            return json.dumps({"available": False, "error": self._health_error})
        try:
            summary = self._health.week_summary(str(day) or time.strftime("%Y-%m-%d"))
        except ValueError as e:
            return json.dumps({"available": True, "error": str(e)})
        summary["available"] = True
        return json.dumps(summary)

    @dbus.service.method(IFACE, in_signature="s", out_signature="s")
    def GetHealthMonth(self, month):
        """Month overview (YYYY-MM, empty = this month) as JSON: one entry per day plus averages."""
        if self._health is None:
            return json.dumps({"available": False, "error": self._health_error})
        try:
            summary = self._health.month_summary(str(month) or time.strftime("%Y-%m"))
        except ValueError as e:
            return json.dumps({"available": True, "error": str(e)})
        summary["available"] = True
        return json.dumps(summary)

    # ------------------------------------------------------------ watch faces
    @dbus.service.method(IFACE, in_signature="s", out_signature="s")
    def InspectWatchface(self, path):
        """Reads a watch-face package and says whether it fits this watch (JSON)."""
        try:
            pkg = self._read_watchface(str(path))
        except WFP.WatchfaceFileError as e:
            return json.dumps({"ok": False, "error": str(e)})
        info = pkg.info()
        info["ok"] = True
        res = self._watch_resolution()
        info["fits"] = (not res) or info["resolution"] == res  # unknown watch: let the watch decide
        info["watchResolution"] = res
        info["preview"] = self._save_preview(pkg)
        return json.dumps(info)

    @dbus.service.method(IFACE, in_signature="s", out_signature="")
    def InstallWatchface(self, path):
        self.InstallWatchfaceVersion(path, "")

    @dbus.service.method(IFACE, in_signature="ss", out_signature="")
    def InstallWatchfaceVersion(self, path, version):
        """For trying faces out: register the face under a given format version (empty = auto)."""
        if not self._ready():
            self.Message("error", "Watch is not connected")
            return
        try:
            pkg = self._read_watchface(str(path))
            self.upload = {"state": "uploading", "progress": 0, "title": pkg.title, "error": ""}
            self.watch.upload_watchface(pkg.binary, str(version) or None)
            self._upload_preview = pkg.preview
        except (WFP.WatchfaceFileError, D.WatchError) as e:
            self.upload = {"state": "failed", "progress": 0, "title": "", "error": str(e)}
            self.Message("error", str(e))
        self._emit_status()

    @dbus.service.method(IFACE, in_signature="", out_signature="")
    def RefreshWatchfaces(self):
        if not self._ready() or self.watchfaces_loading or self.watch.uploading:
            return
        self.watchfaces_loading = True
        self._emit_status()
        self.watch.list_watchfaces()

    @dbus.service.method(IFACE, in_signature="ss", out_signature="")
    def SetWatchface(self, file_name, version):
        if self._ready():
            self.watchfaces_loading = True
            self.watch.watchface_operation(str(file_name), str(version), WFP.OPERATION_ACTIVATE)
            self._emit_status()

    @dbus.service.method(IFACE, in_signature="ss", out_signature="")
    def DeleteWatchface(self, file_name, version):
        if self._ready():
            self.watchfaces_loading = True
            self.watch.watchface_operation(str(file_name), str(version), WFP.OPERATION_DELETE)
            try:
                os.remove(self._face_preview_path(str(file_name)))
            except OSError:
                pass
            self._emit_status()

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
            "daemonVersion": __version__,
            "address": dev["address"],
            "name": dev["name"],
            "battery": self.battery,
            "batteryCharging": self.battery_charging,
            "info": self.info,
            "scanning": self._bluez.scanning,
            "bluetoothOn": self._bluez.powered(),
            "weather": self.weather_report.to_dict() if self.weather_report else None,
            "weatherTime": self.weather_time,
            "weatherError": self.weather_error,
            "notificationsForwarded": self.forwarded,
            "lastNotification": self.last_notification,
            "findingPhone": self._ringer.active,
            "phone": {
                "batterySaver": bool(self._phone and self._phone.power_save),
                "doNotDisturb": bool(self._phone and self._phone.do_not_disturb),
                "saving": self._saving(),
                "quiet": self._quiet(),
                "held": self.held_notifications,
            },
            "health": {
                "available": self._health is not None,
                "syncing": self._health_syncing,
                "lastSync": self.config.data["health"].get("last_sync", 0),
                "error": self._health_error,
                "lastResult": self._health_last_result,
                "folder": self._health.folder if self._health is not None else "",
            },
            "calls": {
                "available": self._calls.available,
                "names": self._contacts.state,       # off | loading | ready | failed
                "nameCount": self._contacts.count,
                "namesError": self._contacts.error,
                # {"caller", "text", "time"} from Sailfish's missed-call notification, or None
                "missed": self.missed_call,
            },
            "calendar": dict(self.calendar, supported=bool(self.watch and self.watch.calendar_supported)),
            "alarms": {
                "supported": bool(self.watch and self.watch.is_ready() and self.watch.alarms_supported),
                "list": self.alarms,
                "loading": self.alarms_loading,
                "error": self.alarms_error,
                "max": A.MAX_ALARMS,
            },
            "watchfaces": {
                "supported": bool(self.watch and self.watch.watchface_params),
                "resolution": self._watch_resolution(),
                "list": self.watchfaces,
                # Picture of the face on the watch now, if it was installed with WatchBridge
                "currentPreview": next((f.get("preview", "") for f in (self.watchfaces or []) if f.get("current")), ""),
                "loading": self.watchfaces_loading,
                "error": self.watchfaces_error,
                "upload": self.upload,
            },
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
            "continuous_heart_rate": self.config.data["health"].get("continuous_heart_rate"),
            "heart_rate_mode": self.config.data["health"].get("heart_rate_mode"),
            "automatic_spo2": self.config.data["health"].get("automatic_spo2"),
            "low_spo2_alert": self.config.data["health"].get("low_spo2_alert", 0),
            "move_reminder": dict(w.get("move_reminder") or {}),
            "profile": dict(self.config.data.get("profile") or {}),
        }

    def _connect(self):
        address = self.config.data["device"]["address"]
        if not address or self.watch is not None:
            return
        self._cancel_reconnect()
        # Every connect starts like the Disconnect button, which on the phone was what brought a lost
        # watch back: after a dropped link BlueZ may still hold the old profile connection, and
        # ConnectProfile then answers AlreadyConnected and no socket ever arrives
        self._bluez.disconnect_profile(address)
        if self.state not in ("pairing",):
            self._set_state("connecting", "")
        self._connect_started = time.monotonic()
        self._bluez.connect(address, self._connect_failed)

    def _reconnect_watchdog(self, now=None):
        """Makes sure a lost watch keeps being tried, whatever state the last attempt got stuck in."""
        now = time.monotonic() if now is None else now
        if not self.config.data["device"]["address"] or not self.config.data["auto_reconnect"] or self._pairing \
                or self._user_disconnected:
            return
        if self.state in ("connected", "auth_failed", "unpaired"):
            return      # auth_failed needs the user to pair again; retrying cannot fix it
        hung = now - self._connect_started >= RECONNECT_WATCHDOG
        if self.watch is not None:
            if self.state in ("authenticating", "initializing") and hung:
                log.warning("Watch setup hung in %s, starting over", self.state)
                self._disconnect_watch()
                self._set_state("disconnected", "")
                self._connect()
            return
        if self.state == "connecting" and hung:
            log.warning("Connection attempt hung for %d min, starting over", (now - self._connect_started) // 60)
            self._connect()
        elif self.state == "disconnected" and self._reconnect_source is None:
            log.info("No reconnect was scheduled, trying now")
            self._connect()

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
        if self.watch is not None and self.watch.is_alive():
            # A second socket for the same watch (e.g. BlueZ delivering after our direct
            # fallback already connected) would tear down the working session.
            log.info("Already connected to %s, closing the extra RFCOMM connection", address)
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
        self._connect_started = time.monotonic()    # the watchdog measures a hung setup from here
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
            self._backoff.connected(time.monotonic())
            self._pairing = False
            if not self.config.data["device"]["name"] and self.info.get("device_name"):
                self.config.data["device"]["name"] = self.info["device_name"]
                self.config.save()
            self._set_state("connected", "")
            self._refresh_weather(push=True)
            # Which face is on the watch, for the start page's picture
            GLib.timeout_add_seconds(5, lambda: (self.RefreshWatchfaces(), False)[1])
            GLib.timeout_add_seconds(8, lambda: (self._sync_calendar(first=True), False)[1])
            # Let the watch settle before a possibly long transfer
            GLib.timeout_add_seconds(20, lambda: (self._maybe_sync_health(), False)[1])
            return
        if state in (D.STATE_DISCONNECTED, D.STATE_AUTH_FAILED):
            # Clean up as Disconnect does: release the socket and BlueZ's side of the connection
            self.watch = None
            watch.stop()
            self._bluez.disconnect_profile(watch.address)
            if self._health_syncing:
                # The sync generator dies with the connection and never reports back
                self._health_syncing = False
                self._health_error = "The watch disconnected during the health sync"
            if self.upload.get("state") == "uploading":
                # Its failure report comes from the old connection and is ignored as stale
                self.upload = dict(self.upload, state="failed", error="The watch disconnected during the upload")
            self.calendar["syncing"] = False
            self._calendar_announce = False
            self.watchfaces_loading = False
            lasted = self._backoff.disconnected(time.monotonic())
            if lasted is not None and lasted < STABLE_CONNECTION:
                log.info("Connection lasted only %ds, keeping the reconnect backoff", lasted)
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

    def _poll_battery(self, now=None):
        now = time.monotonic() if now is None else now
        if self._saving() and now - self._battery_polled < SAVING_BATTERY_POLL - 60:
            return
        if self._ready() and not self.watch.uploading:
            self._battery_polled = now
            self.watch.read_battery()

    def _spot_tick(self, now=None):
        """Phone-timed heart-rate and SpO2 checks: switch measuring on for a while, then back."""
        now = time.monotonic() if now is None else now
        if "_spot_next" not in self.__dict__:
            self._spot_next, self._spot_end = {}, {}
        health = self.config.data["health"]
        for kind, every_key, window in (("heart_rate", "heart_rate_every", SPOT_HR_WINDOW),
                                        ("spo2", "spo2_every", SPOT_SPO2_WINDOW)):
            end = self._spot_end.get(kind)
            if end is not None and now >= end:
                self._spot_end.pop(kind)
                if self._ready():
                    self.watch.spot_check(kind, False)
            every = int(health.get(every_key) or 0)
            if every <= 0:
                self._spot_next.pop(kind, None)
                continue
            if kind in self._spot_end or self._saving() or not self._ready() or self.watch.uploading:
                continue
            if now >= self._spot_next.get(kind, 0):
                self._spot_next[kind] = now + every * 60
                self._spot_end[kind] = now + window
                self.watch.spot_check(kind, True)

    # ============================================================ phone state
    def _saving(self):
        """Power saving now: always, or while the phone's battery saver is on."""
        mode = (self.config.data.get("power_save") or {}).get("mode", "phone")
        if mode == "always":
            return True
        return mode == "phone" and bool(self._phone and self._phone.power_save)

    def _quiet(self, now=None):
        """Do not disturb now: notifications are kept off the watch."""
        dnd = self.config.data.get("do_not_disturb") or {}
        if dnd.get("follow_phone", True) and self._phone is not None and self._phone.do_not_disturb:
            return True
        if dnd.get("scheduled"):
            return FS.quiet_now(dnd.get("start"), dnd.get("end"), now or datetime.datetime.now())
        return False

    def _phone_state_changed(self):
        self._saving_changed()
        self._emit_status()

    def _saving_changed(self):
        """Weather has its own timer; everything else checks _saving() when it runs."""
        log.info("Power saving %s", "on" if self._saving() else "off")
        self._schedule_weather()

    def _watch_battery(self, watch, level, charging=None):
        self.battery = level
        if charging is not None:
            self.battery_charging = charging
        if self._health is not None:
            try:
                self._health.add_battery(level)
            except Exception as e:  # noqa: BLE001 - a full disk must not stop the daemon
                log.warning("Could not store the battery level: %s", e)
        self._check_low_battery(level)
        self._emit_status()

    def _check_low_battery(self, level):
        limit = int(self.config.data["watch"].get("low_battery_warning") or 0)
        if limit <= 0 or level < 0 or self.battery_charging:
            return
        if level <= limit and not self._battery_warned:
            self._battery_warned = True
            self._notify_phone(BATTERY_SUMMARY, BATTERY_BODY % level)
        elif level > limit + 2:
            # Charged again: warn again on the next discharge
            self._battery_warned = False

    def _notify_phone(self, summary, body):
        """A notification on the phone. Its app name keeps it from being forwarded to the watch."""
        hints = {"x-nemo-preview-summary": summary, "x-nemo-preview-body": body}

        def shown(notification_id):
            self._battery_notification = int(notification_id)

        self.session_bus.call_async(NOTIFY_SERVICE, NOTIFY_PATH, NOTIFY_IFACE, "Notify", "susssasa{sv}i",
                                    (APP_NAME, self._battery_notification, "harbour-watchbridge",
                                     summary, body, [], hints, -1),
                                    shown, lambda e: log.warning("Could not show a notification: %s", e))

    def _watch_alarms(self, watch, alarms, error):
        if watch is not self.watch:
            return
        self.alarms_loading = False
        if alarms is not None:
            self.alarms = alarms
        self.alarms_error = error or ("" if alarms is not None else "Could not read the watch's alarms")
        if error:
            self.Message("error", error)
        self._emit_status()

    def _watch_info(self, watch, info):
        self.info = info
        self._emit_status()

    def _bt_device_connected(self, address, connected):
        if address.upper() != self.config.data["device"]["address"].upper():
            return
        # Skip the shortcut while the link is flapping, so the backoff can do its job
        if connected and self.watch is None and self.state in ("disconnected",) \
                and self.config.data["auto_reconnect"] and not self._backoff.flapping \
                and not self._user_disconnected:
            # The watch came back into range; reconnect promptly
            self._cancel_reconnect()
            GLib.timeout_add_seconds(2, lambda: (self._connect(), False)[1])

    def _schedule_reconnect(self):
        if not self.config.data["auto_reconnect"] or not self.config.data["device"]["address"]:
            return
        self._cancel_reconnect()
        delay = self._backoff.next_delay()
        if delay >= RECONNECT_DELAYS[-1] and self._saving():
            delay = SAVING_RECONNECT
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
        if self._quiet():
            log.info("Do not disturb: not forwarding a notification from %s", n.app_name)
            self.held_notifications += 1
            self._emit_status()
            return
        log.info("Forwarding notification from %s", n.app_name)
        self.watch.send_notification(n.summary or n.app_name, n.body, sender=n.app_name, app_id=n.package,
                                     kind=n.kind, key=n.watch_key)
        self.forwarded += 1
        self.last_notification = n.to_dict()
        self._emit_status()

    def _on_notification_closed(self, n):
        notif = self.config.data["notifications"]
        if not notif["enabled"] or not notif.get("remove_dismissed", True) or not self._ready():
            return
        log.info("Removing a notification from %s from the watch (closed on the phone)", n.app_name)
        self.watch.remove_notification(n.watch_key, app_id=n.package, kind=n.kind)

    # ================================================================= health
    def _open_health_store(self):
        if self._health is not None:
            self._health.close()
            self._health = None
        try:
            from .health import HealthStore  # needs the sqlite3 module
            self._health = HealthStore(self.config.data["health"].get("folder") or None)
            self._health_error = ""
            log.info("Health data folder: %s", self._health.folder)
        except Exception as e:  # noqa: BLE001 - health is optional, the rest must keep working
            log.error("Health data storage unavailable: %s", e)
            self._health_error = "Health data storage unavailable: %s" % e

    def _maybe_sync_health(self):
        """Automatic sync: when connected, enabled and the last sync is older than the interval."""
        h = self.config.data["health"]
        if not h.get("enabled", True) or not self._ready() or self.watch.uploading:
            return  # (an upload takes the link for a few minutes; the next check catches up)
        hours = max(1, int(h.get("interval_hours") or 6))
        if self._saving():
            hours = max(hours, SAVING_HEALTH_HOURS)
        interval = hours * 3600
        if time.time() - h.get("last_sync", 0) >= interval:
            self._sync_health()

    def _sync_health(self, announce=False):
        if self._health is None:
            if announce:
                self.Message("error", self._health_error or "Health data storage unavailable")
            return
        if not self._ready():
            if announce:
                self.Message("error", "Watch is not connected")
            return
        if self._health_syncing:
            return
        now = time.time()
        first = now - max(1, int(self.config.data["health"].get("first_sync_days") or 7)) * 86400
        # Re-read the last stored minute/period: the watch may have filled them in since
        step_start = self._health.last_activity_time() or first
        sleep_start = self._health.last_sleep_end() or first
        # Each file has its own start: basic sleep periods during the day must not hide last night
        sleep_file_start = self._health.last_sleep_session_end() or first
        stress_start = self._health.last_stress_end() or first
        self._health_syncing = True
        self._health_error = ""
        self._emit_status()
        log.info("Health sync from %s (activity) / %s (sleep) / %s (TruSleep) / %s (stress)",
                 time.ctime(step_start), time.ctime(sleep_start), time.ctime(sleep_file_start),
                 time.ctime(stress_start))
        self.watch.sync_health(step_start, sleep_start, sleep_file_start, stress_start)

    def _watch_health_data(self, watch, result):
        if not self._health_syncing:
            return  # a sync that was abandoned when the link dropped
        self._health_syncing = False
        try:
            counts = self._health.add_sync_result(result)
        except Exception as e:  # noqa: BLE001 - e.g. disk full; keep the daemon alive
            log.exception("Could not store health data")
            self._health_error = "Could not store health data: %s" % e
            self._emit_status()
            return
        counts["totals"] = result.get("totals")
        counts["skipped"] = result.get("skipped", 0)
        counts["fileErrors"] = result.get("file_errors", [])
        self._health_last_result = counts
        self._health_error = result.get("error", "")
        if not result.get("error"):
            self.config.data["health"]["last_sync"] = int(result["end"])
            self.config.save()
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
        if self._saving():
            minutes = max(minutes, SAVING_WEATHER_MINUTES)

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
                # Not str(e) inside the lambda: Python unbinds `e` when the except block ends, so the
                # lambda raised NameError on the main loop, _weather_busy stayed True and the weather
                # never updated again until the service restarted
                message = str(e) or e.__class__.__name__
                GLib.idle_add(lambda: (self._weather_fetched(None, message, push, announce), False)[1])

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
            if self._weather_retry is None:
                def retry():
                    self._weather_retry = None
                    self._refresh_weather(push=True)
                    return False
                self._weather_retry = GLib.timeout_add_seconds(WEATHER_RETRY, retry)
        self._emit_status()

    def _watch_weather_requested(self, watch):
        if watch is self.watch:
            self._refresh_weather(push=True)

    # ================================================================== calls
    def _refresh_contacts(self):
        c = self.config.data["calls"]
        if not c.get("enabled", True) or not c.get("caller_names", True):
            self._contacts.clear()
            self._emit_status()
            return
        self._contacts_time = time.monotonic()
        self._contacts.refresh(done=lambda: GLib.idle_add(lambda: (self._emit_status(), False)[1]))
        self._emit_status()

    def _on_incoming_call(self, handler_id, number):
        if not self.config.data["calls"].get("enabled", True) or not self._ready():
            return
        if self._quiet() and not (self.config.data.get("do_not_disturb") or {}).get("calls", True):
            log.info("Do not disturb: incoming call not shown on the watch")
            return
        name = None
        if self.config.data["calls"].get("caller_names", True):
            name = self._contacts.lookup(number)
            if name is None and time.monotonic() - self._contacts_time > CONTACTS_RETRY_UNKNOWN:
                self._refresh_contacts()  # maybe a new contact; helps the next call
        shown = name or number or "Unknown number"
        if self.watch.send_incoming_call(shown, number):
            log.info("Incoming call shown on the watch (%s)", "contact" if name else "number only")
            self._call_on_watch = handler_id

    def _on_call_answered(self, handler_id):
        if handler_id == self._call_on_watch and self._ready():
            self.watch.end_call(answered=True)

    def _on_call_ended(self, handler_id, answered):
        if handler_id != self._call_on_watch:
            return
        self._call_on_watch = None
        if self._ready():
            self.watch.end_call()

    def _on_missed_call(self, n, active):
        if active:
            # Sailfish names the caller in the summary (contact name, or the number)
            self.missed_call = {"caller": n.summary, "text": n.body, "time": int(time.time())}
            log.info("Missed call notification (%s)", "updated" if n.replaces_id else "new")
        elif self.missed_call is not None:
            log.info("Missed calls cleared on the phone")
            self.missed_call = None
        self._emit_status()

    def _watch_call_action(self, watch, action):
        handler_id = self._call_on_watch
        if watch is not self.watch or handler_id is None:
            log.info("Call action %s from the watch, but no call is shown", action)
            return
        if action == HC.CALL_ACTION_REJECT:
            self._calls.hang_up(handler_id)
        elif action == HC.CALL_ACTION_ACCEPT:
            self._calls.answer(handler_id)
        else:
            # Not known from Gadgetbridge; most likely the watch's mute button
            log.info("Unknown call action %r from the watch, silencing the ringtone", action)
            self._calls.silence_ringtone()

    # =============================================================== calendar
    def _timed_calendar_sync(self, now=None):
        now = time.monotonic() if now is None else now
        if self._saving() and now - self._calendar_polled < SAVING_CALENDAR - 60:
            return
        self._calendar_polled = now
        self._sync_calendar()

    def _sync_calendar(self, first=False, announce=False):
        """Asks the watch to sync; only what changed goes over, if anything did."""
        if not self.config.data["calendar"].get("enabled", True):
            return
        if not self._ready() or not self.watch.calendar_supported or self.watch.uploading:
            if announce:
                self.Message("error", "The watch is not ready for a calendar sync")
            return
        self._calendar_announce = self._calendar_announce or announce
        self.watch.calendar_sync(first)
        self._calendar_started()

    def _calendar_started(self):
        self.calendar.update(syncing=True, error="")
        self._calendar_try += 1
        attempt = self._calendar_try

        def expired():
            if self.calendar["syncing"] and attempt == self._calendar_try:
                self._watch_calendar_done(self.watch, None, "The watch did not ask for the calendar")
            return False

        GLib.timeout_add_seconds(CALENDAR_ANSWER_TIMEOUT, expired)
        self._emit_status()

    def _watch_calendar_request(self, watch, request):
        if watch is not self.watch:
            return
        if not self.config.data["calendar"].get("enabled", True):
            watch.refuse_calendar(CAL.ANSWER_DISABLED)
            return
        if not CAL.wants_events(request):
            return
        self._calendar_started()
        days = max(1, min(request["days"], CALENDAR_MAX_DAYS))
        self._phone_calendar.fetch(days, lambda events, error: self._calendar_read(watch, request, events, error))

    def _calendar_read(self, watch, request, events, error):
        if watch is not self.watch:
            return
        if events is None:
            log.warning("Calendar: %s", error)
            watch.refuse_calendar(CAL.ANSWER_NO_PERMISSION)
            self._watch_calendar_done(watch, None, error)
            return
        log.info("Calendar: %d events on the phone", len(events))
        watch.send_calendar(request, events)

    def _watch_calendar_done(self, watch, events, error):
        if watch is not self.watch:
            return
        announce, self._calendar_announce = self._calendar_announce, False
        self.calendar.update(syncing=False, error=error)
        if events is not None:
            self.calendar.update(events=events, lastSync=int(time.time()))
        if announce:
            if error:
                self.Message("error", "Calendar sync failed: %s" % error)
            else:
                self.Message("info", "Calendar synchronised")
        self._emit_status()

    # ============================================================ watch faces
    def _watch_resolution(self):
        """"height*width" of the connected watch, as watch-face packages name it."""
        p = self.watch.watchface_params if self.watch is not None else None
        if not p or not p.get("width") or not p.get("height"):
            return ""
        return "%d*%d" % (p["height"], p["width"])

    def _read_watchface(self, path):
        path = path[len("file://"):] if path.startswith("file://") else path
        try:
            size = os.path.getsize(path)
            if size > WATCHFACE_MAX_SIZE:
                raise WFP.WatchfaceFileError("The file is too large for a watch face (%d MB)" % (size // 1048576))
            with open(path, "rb") as f:
                return WFP.WatchfacePackage(f.read())
        except OSError as e:
            raise WFP.WatchfaceFileError("Cannot read the file: %s" % e.strerror)

    def _save_preview(self, pkg):
        """Writes the package's preview where the UI can show it; returns its path or ""."""
        if not pkg.preview:
            return ""
        folder = os.path.join(os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache"),
                              "harbour-watchbridge")
        try:
            os.makedirs(folder, exist_ok=True)
            for old in os.listdir(folder):
                if old.startswith("preview-"):
                    os.remove(os.path.join(folder, old))
            # A new name per package, so the UI does not show a cached older image
            path = os.path.join(folder, "preview-%08x.jpg" % (zlib.crc32(pkg.preview) & 0xFFFFFFFF))
            with open(path, "wb") as f:
                f.write(pkg.preview)
            return path
        except OSError as e:
            log.warning("Could not save the watch face preview: %s", e)
            return ""

    @staticmethod
    def _face_preview_path(file_name):
        """Where the preview of a face installed with WatchBridge is kept (by its watch id)."""
        base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
        face_id = os.path.basename(file_name.split("_")[0])
        return os.path.join(base, "harbour-watchbridge", "faces", face_id + ".jpg")

    def _watch_faces(self, watch, faces, error):
        if watch is not self.watch:
            return
        self.watchfaces_loading = False
        self.watchfaces_error = error
        if faces is not None:
            for f in faces:
                path = self._face_preview_path(f["file"])
                f["preview"] = path if os.path.exists(path) else ""
            self.watchfaces = faces
        self._emit_status()
        self._check_face_schedule()

    def _arm_face_timer(self, delay=None):
        """One wake-up at the next day/night switch (instead of a check every minute)."""
        if self._face_timer is not None:
            GLib.source_remove(self._face_timer)
            self._face_timer = None
        schedule = self.config.data.get("face_schedule") or {}
        if not schedule.get("enabled"):
            return
        if delay is None:
            now = datetime.datetime.now()
            delay = int((FS.next_switch(schedule, now) - now).total_seconds()) + 5
        delay = max(5, min(int(delay), FACE_SCHEDULE_MAX_WAIT))

        def fire():
            self._face_timer = None
            busy = self._ready() and (self.watch.uploading or self.watchfaces_loading)
            self._check_face_schedule()
            # During an upload the switch waits a little; otherwise on to the next one
            self._arm_face_timer(FACE_SCHEDULE_BUSY_RETRY if busy else None)
            return False

        self._face_timer = GLib.timeout_add_seconds(delay, fire)

    def _check_face_schedule(self):
        """Show the day or the night face when the period changes (or on the first connection)."""
        if not self._ready() or self.watch.uploading or self.watchfaces_loading:
            return
        schedule = self.config.data.get("face_schedule") or {}
        face, self._face_applied, reason = FS.face_to_apply(schedule, datetime.datetime.now(),
                                                            self.watchfaces, self._face_applied)
        if face is None:
            return
        log.info("Face schedule: showing the %s (%s)", reason, face["file"])
        self.watchfaces_loading = True
        self.watch.watchface_operation(face["file"], face["version"], WFP.OPERATION_ACTIVATE)
        self._emit_status()

    def _watch_upload(self, watch, state, progress, error, activated, file_name=""):
        if watch is not self.watch:
            return
        self.upload = dict(self.upload, state=state, progress=progress, error=error)
        if state == "done" and file_name and self._upload_preview:
            path = self._face_preview_path(file_name)
            try:
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "wb") as f:
                    f.write(self._upload_preview)
            except OSError as e:
                log.warning("Could not keep the watch face preview: %s", e)
        if state in ("done", "failed"):
            self._upload_preview = None
        if state == "done":
            self.Message("info", "Watch face installed" + (" and activated" if activated else ""))
        elif state == "failed":
            self.Message("error", "Watch face upload failed: %s" % error)
        self._emit_status()

    # ============================================================= find phone
    def _watch_find_phone(self, watch, start):
        if watch is not self.watch:
            return
        if start:
            self._ringer.start()
        else:
            self._ringer.stop()
        self._emit_status()

    def _find_phone_timed_out(self):
        # Otherwise the watch keeps showing that it is looking for the phone
        if self._ready():
            self.watch.stop_find_phone()
        self._emit_status()
