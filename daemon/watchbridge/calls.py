# WatchBridge - Huawei Watch GT 5 companion for Sailfish OS
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Follow phone calls through the Sailfish voice call manager (org.nemomobile.voicecall).

The manager lives at "/" on the session bus and announces changes of its call list with
voiceCallsChanged() (handler ids in the voiceCalls property). Each call is an object at
"/calls/<handler id>" with interface org.nemomobile.voicecall.VoiceCall, which emits
statusChanged(int status, string text) and offers answer() and hangup().
"""

import logging

import dbus

log = logging.getLogger(__name__)

SERVICE = "org.nemomobile.voicecall"
MANAGER_PATH = "/"
MANAGER_IFACE = "org.nemomobile.voicecall.VoiceCallManager"
CALL_IFACE = "org.nemomobile.voicecall.VoiceCall"
CALL_PATH_PREFIX = "/calls/"

# AbstractVoiceCallHandler::VoiceCallStatus
STATUS_NULL = 0
STATUS_ACTIVE = 1
STATUS_HELD = 2
STATUS_DIALING = 3
STATUS_ALERTING = 4
STATUS_INCOMING = 5
STATUS_WAITING = 6
STATUS_DISCONNECTED = 7
STATUS_REJECTED = 8
STATUS_IGNORED = 9

_RINGING = (STATUS_INCOMING, STATUS_WAITING)
_OVER = (STATUS_DISCONNECTED, STATUS_REJECTED, STATUS_IGNORED)


class _Call:
    def __init__(self, handler_id, number, incoming):
        self.id = handler_id
        self.number = number
        self.incoming = incoming
        self.announced = False  # on_incoming was called
        self.answered = False


class CallTracker:
    """Turns call-list and status updates into incoming / answered / ended events.

    Kept free of D-Bus so it can be tested; CallMonitor feeds it.
    """

    def __init__(self, on_incoming, on_answered, on_ended):
        self.on_incoming = on_incoming   # (handler_id, number)
        self.on_answered = on_answered   # (handler_id)
        self.on_ended = on_ended         # (handler_id, answered)
        self.calls = {}

    def ids(self):
        return set(self.calls)

    def added(self, handler_id, number, incoming, status):
        if handler_id in self.calls:
            return
        self.calls[handler_id] = _Call(handler_id, number or "", bool(incoming))
        self.status(handler_id, status)

    def removed(self, handler_id):
        call = self.calls.pop(handler_id, None)
        if call is not None and call.announced:
            self.on_ended(call.id, call.answered)

    def status(self, handler_id, status):
        call = self.calls.get(handler_id)
        if call is None:
            return
        if status in _RINGING and call.incoming and not call.announced:
            call.announced = True
            self.on_incoming(call.id, call.number)
        elif status in (STATUS_ACTIVE, STATUS_HELD) and call.announced and not call.answered:
            call.answered = True
            self.on_answered(call.id)
        elif status in _OVER:
            self.removed(handler_id)

    def number(self, handler_id, number):
        call = self.calls.get(handler_id)
        if call is not None and number:
            call.number = number


class CallMonitor:
    def __init__(self, bus, on_incoming, on_answered, on_ended):
        self.bus = bus
        self.tracker = CallTracker(on_incoming, on_answered, on_ended)
        self.available = False
        self._warned = False

    def start(self):
        self.bus.add_signal_receiver(self._calls_changed, "voiceCallsChanged", MANAGER_IFACE, SERVICE,
                                     MANAGER_PATH)
        self.bus.add_signal_receiver(self._status_changed, "statusChanged", CALL_IFACE, SERVICE,
                                     path_keyword="path")
        self._calls_changed()

    # ------------------------------------------------------------------ actions
    def answer(self, handler_id):
        self._call_method(handler_id, "answer")

    def hang_up(self, handler_id):
        self._call_method(handler_id, "hangup")

    def silence_ringtone(self):
        try:
            self._manager().silenceRingtone(reply_handler=lambda *a: None,
                                            error_handler=lambda e: log.warning("silenceRingtone: %s", e))
        except dbus.DBusException as e:
            log.warning("Could not silence the ringtone: %s", e)

    def _call_method(self, handler_id, method):
        if handler_id not in self.tracker.calls:
            log.info("Call %s is gone, not calling %s()", handler_id, method)
            return
        try:
            obj = self.bus.get_object(SERVICE, CALL_PATH_PREFIX + handler_id)
            getattr(dbus.Interface(obj, CALL_IFACE), method)(
                reply_handler=lambda *a: None,
                error_handler=lambda e: log.warning("Call %s(): %s", method, e))
        except dbus.DBusException as e:
            log.warning("Could not %s the call: %s", method, e)

    # ------------------------------------------------------------------ signals
    def _manager(self):
        return dbus.Interface(self.bus.get_object(SERVICE, MANAGER_PATH), MANAGER_IFACE)

    def _calls_changed(self, *args):
        try:
            props = dbus.Interface(self.bus.get_object(SERVICE, MANAGER_PATH), dbus.PROPERTIES_IFACE)
            current = [str(i) for i in props.Get(MANAGER_IFACE, "voiceCalls", timeout=3)]
            if not self.available:
                log.info("Following phone calls (voice call manager)")
            self.available = True
        except dbus.DBusException as e:
            if self.available or not self._warned:
                log.warning("Voice call manager not available: %s", e)
            self._warned = True
            self.available = False
            return
        for handler_id in self.tracker.ids() - set(current):
            self.tracker.removed(handler_id)
        for handler_id in current:
            if handler_id not in self.tracker.calls:
                self._add(handler_id)

    def _add(self, handler_id):
        try:
            obj = self.bus.get_object(SERVICE, CALL_PATH_PREFIX + handler_id)
            props = dbus.Interface(obj, CALL_IFACE).getProperties(timeout=3)
        except dbus.DBusException as e:
            log.warning("Could not read call %s: %s", handler_id, e)
            return
        status = int(props.get("status", STATUS_NULL))
        log.info("Call %s: %s, status %d", handler_id,
                 "incoming" if props.get("isIncoming") else "outgoing", status)
        self.tracker.added(handler_id, str(props.get("lineId", "")), bool(props.get("isIncoming", False)), status)

    def _status_changed(self, status, text="", path=None):
        if not path or not str(path).startswith(CALL_PATH_PREFIX):
            return
        handler_id = str(path)[len(CALL_PATH_PREFIX):]
        if handler_id == "active":
            return  # the same call, also published under its own id
        log.info("Call %s: status %d (%s)", handler_id, int(status), text)
        if handler_id not in self.tracker.calls:
            self._calls_changed()
        else:
            self.tracker.status(handler_id, int(status))
