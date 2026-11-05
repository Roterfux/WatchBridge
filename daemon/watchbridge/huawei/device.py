# WatchBridge - Huawei Watch GT 5 companion for Sailfish OS
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# Connection/initialisation logic ported from Gadgetbridge
# (HuaweiSupportProvider.java, AsynchronousResponse.java, HuaweiWeatherManager.java
# and the request classes), Copyright (C) 2024 Damien Gaignon, Martin.JM,
# Vitalii Tomin. Translated to Python and modified for WatchBridge, 2026.
# See NOTICE.md.
"""Talks to a Huawei watch over an established byte stream (RFCOMM socket)."""

import logging
import queue
import random
import socket
import struct
import threading
import time
import zlib

from . import commands as C
from . import filedownload as FDL
from . import fitness as F
from . import healthfiles as HF
from .filedownload import FD, SERVICE as FD_SERVICE
from .commands import DC, NC, Service, WC
from .crypto import HuaweiCrypto, generate_nonce, hexstr
from .hichain import HiChain, HiChainError, OP_AUTH, OP_BIND
from .packet import Params, StreamParser

log = logging.getLogger(__name__)

INIT_TIMEOUT = 5.0
FILE_TIMEOUT = 15.0  # answers to file download requests

# Expand capabilities (HuaweiState.java)
CAP_DICT_SLEEP_SYNC = 143   # sleep as a sequence-data file with stages and score
CAP_BED_TIME = 199          # stages start at bed time instead of fall-asleep time
# Gadgetbridge never times out the handshake requests before HiChain: the watch
# may hold its answer until the user confirms the pairing on its screen.
FIRST_AUTH_TIMEOUT = 90.0
AUTH_TIMEOUT = 10.0

# Readable names for the handshake steps, used in logs and error messages
_STEP_NAMES = {
    (Service.DEVICE_CONFIG, DC.LINK_PARAMS): "link parameters",
    (Service.DEVICE_CONFIG, DC.DEVICE_STATUS): "device status",
    (Service.DEVICE_CONFIG, DC.SECURITY_NEGOTIATION): "security negotiation",
    (Service.DEVICE_CONFIG, DC.PIN_CODE): "pin code",
    (Service.DEVICE_CONFIG, DC.HICHAIN): "HiChain",
}

# Connection states reported to the listener
STATE_CONNECTING = "connecting"
STATE_AUTHENTICATING = "authenticating"
STATE_INITIALIZING = "initializing"
STATE_CONNECTED = "connected"
STATE_DISCONNECTED = "disconnected"
STATE_AUTH_FAILED = "auth_failed"


class WatchError(Exception):
    pass


class Listener:
    """Callbacks from the watch. Invoked from worker threads."""

    def on_state(self, state, detail=""):
        pass

    def on_battery(self, level):
        pass

    def on_device_info(self, info):
        pass

    def on_find_phone(self, start):
        pass

    def on_weather_requested(self):
        pass

    def on_health_data(self, result):
        """A health sync finished (or stopped early, see result["error"])."""
        pass

    def on_call_action(self, action):
        """A button on the watch's call screen: C.CALL_ACTION_REJECT, C.CALL_ACTION_ACCEPT or an int."""
        pass


class DeviceStore:
    """Per-watch persistent values. Backed by a dict and a save callback."""

    def __init__(self, data, save):
        self.data = data
        self._save = save

    def get(self, key, default=None):
        return self.data.get(key, default)

    def set(self, key, value):
        self.data[key] = value
        self._save()

    def android_id(self):
        if not self.get("android_id"):
            self.set("android_id", hexstr(generate_nonce()))
        return self.get("android_id").encode("utf-8")

    def fake_mac(self):
        if not self.get("fake_mac"):
            self.set("fake_mac", ("FF:FF:FF" + "".join(":%02x" % random.randrange(255) for _ in range(3))).upper())
        return self.get("fake_mac")

    def auth_key(self):
        v = self.get("auth_key")
        return bytes.fromhex(v) if v else None

    def set_auth_key(self, key):
        self.set("auth_key", hexstr(key) if key else "")


class _Waiter:
    def __init__(self, key):
        self.key = key
        self.event = threading.Event()
        self.packet = None


class HuaweiWatch:
    def __init__(self, transport, address, store, listener=None, phone_model="Sailfish OS", settings=None,
                 device_name="HUAWEI WATCH"):
        self.transport = transport
        self.address = address
        self.device_name = device_name  # Bluetooth name of the watch, sent back in SetUpDeviceStatus
        self.store = store
        self.listener = listener or Listener()
        self.phone_model = phone_model
        self.settings = settings or {}
        self.params = Params()
        self.parser = StreamParser(self.params)
        self.protocol_version = 0
        self.commands = {}           # service -> [commands]
        self.expand_capabilities = b""
        self.notification_constraints = {}
        self.weather_settings = None
        self.battery = -1
        self.info = {}
        self.state = STATE_DISCONNECTED
        self._msg_id = 0
        self._msg_id_lock = threading.Lock()
        self._waiter = None
        self._waiter_lock = threading.Lock()
        self._send_lock = threading.Lock()
        self._jobs = queue.Queue()
        self._file_blocks = queue.Queue()   # 0x2C/0x05 data packets of a file download
        self.rri_new_sync = False           # stress file via service 0x2C (SettingRelated)
        self._running = False
        self._in_setup = False
        self._threads = []

    # ------------------------------------------------------------------ public
    def start(self, first_connection=None):
        """Starts reader/worker threads and the connect sequence."""
        if first_connection is None:
            first_connection = self.store.auth_key() is None
        self._running = True
        for target in (self._reader_loop, self._worker_loop):
            t = threading.Thread(target=target, daemon=True, name=target.__name__)
            t.start()
            self._threads.append(t)
        self.submit(lambda: self._connect_sequence(first_connection))

    def stop(self):
        self._running = False
        self._jobs.put(None)
        self._file_blocks.put(None)  # wake a download waiting for data
        # close() alone neither wakes the reader blocked in recv() nor releases
        # the RFCOMM channel (the next connect then fails with EBUSY)
        try:
            self.transport.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            self.transport.close()
        except OSError:
            pass
        self._fail_waiter()

    def submit(self, job):
        self._jobs.put(job)

    def is_ready(self):
        return self.state == STATE_CONNECTED

    def is_alive(self):
        """True from start() until the link is closed (handshake included)."""
        return self._running

    def send_notification(self, title, body, sender="", app_id="", kind=C.NotificationType.GENERIC, key=None):
        self.submit(lambda: self._send_notification(title, body, sender, app_id, kind, key))

    def send_weather(self, report):
        self.submit(lambda: self._send_weather(report))

    def send_incoming_call(self, name, number):
        """Shows the call screen on the watch. Sent at once from the calling thread, not
        queued: the worker may be busy with a health sync and a call cannot wait."""
        if not self.is_ready() or not self.supports(0x02, NC.ACTION):
            log.info("Call not shown on the watch (not connected or unsupported)")
            return False
        cons = self.notification_constraints
        number_format = cons.get("incoming_number_format") if cons.get("incoming_number") else None
        self._send_safely(C.call_notification(self._next_msg_id(), name or number, number,
                                              cons.get("content_format", 0x02), number_format))
        return True

    def end_call(self, answered=False):
        """Takes the call screen off the watch: answered on the phone, rejected or ended."""
        if not self.is_ready() or not self.supports(0x02, NC.ACTION):
            return
        kind = C.NotificationType.STOP
        if answered and self.supports_expand(74):
            kind = C.NotificationType.START_CALL
        self._send_safely(C.stop_call_notification(self._next_msg_id(), kind,
                                                   self.notification_constraints.get("content_format", 0x02)))

    def _send_safely(self, packet):
        try:
            self._send(packet)
        except OSError as e:
            log.warning("Could not send %02x/%02x: %s", packet.service, packet.command, e)

    def sync_time(self):
        self.submit(self._sync_time)

    def stop_find_phone(self):
        self.submit(lambda: self._send(C.find_phone_stop()))

    def set_automatic_heart_rate(self, enabled):
        self.submit(lambda: self._set_automatic_heart_rate(enabled))

    def _set_automatic_heart_rate(self, enabled):
        if not self.supports(F.SERVICE, 0x17):
            log.info("The watch does not support switching continuous heart rate")
            return
        reply = self.request(F.automatic_heart_rate(enabled), 2.0)
        log.info("Continuous heart rate %s: %s", "on" if enabled else "off",
                 "ok" if reply is not None and reply.tlv.get_as_int(0x7F, C.RESULT_SUCCESS) == C.RESULT_SUCCESS
                 else "no confirmation (%r)" % (reply.tlv if reply is not None else None))

    def sync_health(self, step_start, sleep_start, sleep_file_start=None, stress_start=None):
        """Fetch totals, per-minute activity since step_start, basic sleep since sleep_start,
        and the TruSleep and stress files since their own start times (None = skip).

        Runs one request per job, so notifications queued meanwhile are not held up
        by a long first sync. The result arrives via Listener.on_health_data.
        """
        steps = self._health_steps(int(step_start), int(sleep_start),
                                   None if sleep_file_start is None else int(sleep_file_start),
                                   None if stress_start is None else int(stress_start))

        def advance():
            try:
                next(steps)
            except StopIteration:
                return
            self.submit(advance)

        self.submit(advance)

    # ----------------------------------------------------------------- plumbing
    def _set_state(self, state, detail=""):
        self.state = state
        log.info("State: %s %s", state, detail)
        self.listener.on_state(state, detail)

    def _reader_loop(self):
        while self._running:
            try:
                data = self.transport.recv(4096)
            except OSError as e:
                log.info("Socket closed: %s", e)
                data = b""
            if not data:
                break
            log.debug("<< %s", data.hex())
            for packet in self.parser.feed(data):
                self._dispatch(packet)
        if self._running:
            self._running = False
            self._jobs.put(None)
            self._file_blocks.put(None)
            self._fail_waiter()
            if not self._in_setup:
                # During setup the connect sequence reports the failing step itself
                self._set_state(STATE_DISCONNECTED)

    def _worker_loop(self):
        while True:
            job = self._jobs.get()
            if job is None or not self._running:
                return
            try:
                job()
            except Exception:  # noqa: BLE001 - keep the worker alive
                log.exception("Job failed")

    def _dispatch(self, packet):
        key = (packet.service, packet.command)
        if key == (FD_SERVICE, FD.BLOCK):
            # File data arrives in bursts, not as an answer to a single request
            self._file_blocks.put(packet)
            return
        with self._waiter_lock:
            waiter = self._waiter
            if waiter is not None and waiter.key == key:
                waiter.packet = packet
                self._waiter = None
                waiter.event.set()
                return
        self._handle_async(packet)

    def _fail_waiter(self):
        with self._waiter_lock:
            waiter, self._waiter = self._waiter, None
        if waiter:
            waiter.event.set()

    def _send(self, packet):
        mtu = max(self.params.mtu, 20)
        # Serialised under the lock too: call notifications are sent from the main
        # thread while the worker may be sending, and encryption uses shared params
        with self._send_lock:
            frames = packet.serialize(self.params)
            for frame in frames:
                log.debug(">> %s", frame.hex())
                for i in range(0, len(frame), mtu):
                    self.transport.sendall(frame[i:i + mtu])

    def request(self, packet, timeout=INIT_TIMEOUT):
        """Send a packet and wait for the reply with the same service/command."""
        waiter = _Waiter((packet.service, packet.command))
        with self._waiter_lock:
            self._waiter = waiter
        self._send(packet)
        if not waiter.event.wait(timeout):
            with self._waiter_lock:
                if self._waiter is waiter:
                    self._waiter = None
            log.warning("Timeout waiting for %02x/%02x", packet.service, packet.command)
            return None
        return waiter.packet

    def _require(self, packet, timeout=INIT_TIMEOUT):
        reply = self.request(packet, timeout)
        if reply is None:
            key = (packet.service, packet.command)
            step = _STEP_NAMES.get(key, "%02x/%02x" % key)
            if not self._running:
                raise WatchError("The watch closed the connection during the %s step" % step)
            raise WatchError("The watch did not answer the %s request" % step)
        return reply

    def supports(self, service, command):
        return command in self.commands.get(service, ())

    def supports_expand(self, bit):
        caps = self.expand_capabilities
        return bit < len(caps) * 8 and bool(caps[bit // 8] & (1 << (bit % 8)))

    # ------------------------------------------------------------- connecting
    def _connect_sequence(self, first_connection):
        self._in_setup = True
        try:
            # On first pairing the watch may ask for a confirmation at any step
            self._set_state(STATE_AUTHENTICATING, "confirm_on_watch" if first_connection else "")
            self._authenticate(first_connection)
            self._set_state(STATE_INITIALIZING)
            self._configure()
            self._initialize_services()
            self._set_state(STATE_CONNECTED)
        except HiChainError as e:
            log.error("Authentication failed: %s", e)
            self._set_state(STATE_AUTH_FAILED, str(e))
            self.stop()
        except (WatchError, OSError) as e:
            # Timeouts and dropped links are retried by the caller; only HiChain
            # rejections mean the pairing itself is broken.
            if isinstance(e, OSError):
                e = "The connection to the watch broke: %s" % (e.strerror or e)
            log.error("Connection setup failed: %s", e)
            self._set_state(STATE_DISCONNECTED, str(e))
            self.stop()
        except Exception as e:  # noqa: BLE001 - e.g. a malformed reply; never hang in "authenticating"
            log.exception("Connection setup failed")
            self._set_state(STATE_DISCONNECTED, "Unexpected error during setup: %s" % e)
            self.stop()
        finally:
            self._in_setup = False

    def _authenticate(self, first_connection):
        p = self.params
        timeout = FIRST_AUTH_TIMEOUT if first_connection else AUTH_TIMEOUT
        log.info("Handshake start (%s)", "first pairing" if first_connection else "stored pairing")
        link = C.parse_link_params(self._require(C.link_params(), timeout).tlv)
        log.info("Link params: %s", {k: (v.hex() if isinstance(v, bytes) else v) for k, v in link.items()})
        self.protocol_version = link["protocol_version"]
        p.device_support_type = link["device_support_type"]
        p.slice_size = link["slice_size"]
        p.mtu = link["mtu"] or 65535
        p.auth_version = link["auth_version"]
        p.auth_algo = link["auth_algo"]
        p.encrypt_method = link["encrypt_method"]
        server_nonce = link["server_nonce"]

        reply = self.request(C.device_status(True), timeout)
        status = C.parse_device_status(reply.tlv) if reply else -1
        log.info("Device status: %d", status)
        if status not in (-1, 0, 1):
            log.warning("Unexpected device status %d, trying HiChain anyway", status)

        if p.device_support_type in (0x01, 0x02, 0x03, 0x04):
            p.auth_mode = 4 if p.device_support_type == 4 else 2
            nego = self._require(C.security_negotiation(p.auth_mode, self.store.android_id(), self.phone_model,
                                                        p.encrypt_method), timeout)
            auth_type, _ = C.parse_security_negotiation(nego.tlv)
            log.info("Security negotiation: auth type %#x (%r)", auth_type, nego.tlv)
            if auth_type == 0x0186A0 or (auth_type ^ 0x01) == 0x04 or (auth_type ^ 0x02) == 0x04:
                self._auth_hichain(first_connection, timeout)
            elif auth_type in (0x01, 0x02):
                self._auth_lite(server_nonce, lite=True)
            else:
                raise HiChainError("Unsupported auth type %#x" % auth_type)
        else:
            self._auth_lite(server_nonce, lite=False)

    def _request_pin(self, timeout=FIRST_AUTH_TIMEOUT):
        reply = self._require(C.pin_code_request(), timeout)
        p = self.params
        hc = HuaweiCrypto(p.auth_version, p.auth_algo, p.device_support_type, p.auth_mode)
        return hc.decrypt_pin_code(p.encrypt_method, reply.tlv.get_bytes(0x01), reply.tlv.get_bytes(0x02))

    def _run_hichain(self, chain, timeout):
        name = "auth" if chain.op == OP_AUTH else "bind"
        while True:
            log.info("HiChain %s: sending step %d", name, chain.step)
            reply = self.request(chain.create_request(), timeout)
            if reply is None:
                # A missing answer is a link problem, not a rejected pairing
                if not self._running:
                    raise WatchError("The watch closed the connection during HiChain %s step %d"
                                     % (name, chain.step))
                raise WatchError("The watch did not answer HiChain %s step %d" % (name, chain.step))
            if chain.process_response(reply.tlv):
                log.info("HiChain %s finished", name)
                return

    def _auth_hichain(self, first_connection, timeout):
        android_id = self.store.android_id()
        if first_connection:
            self.params.pin_code = self._request_pin(timeout)
            log.info("Got pin code, running HiChain auth (first pairing)")
            chain = HiChain(OP_AUTH, android_id, pin_code=self.params.pin_code)
            self._run_hichain(chain, timeout)
            if not chain.auth_token:
                raise HiChainError("Watch did not provide an auth token")
            self.store.set_auth_key(chain.auth_token)
        stored = self.store.auth_key()
        if stored is None:
            raise HiChainError("No stored pairing, pair again")
        chain = HiChain(OP_BIND, android_id, stored_key=stored)
        self._run_hichain(chain, timeout)
        self.params.secret_key = chain.final_key

    def _auth_lite(self, server_nonce, lite):
        """HiChain Lite (auth types 1/2) and the legacy 'normal' mode."""
        p = self.params
        key = self.store.auth_key()
        if key is None:
            key = generate_nonce()
            self.store.set_auth_key(key)
        p.secret_key = key
        if lite and p.pin_code is None and p.auth_version != 0x02:
            p.pin_code = self._request_pin()

        hc = HuaweiCrypto(p.auth_version, p.auth_algo, p.device_support_type, p.auth_mode)
        client_nonce = generate_nonce()
        double_nonce = bytes(server_nonce) + client_nonce
        digest_key = None
        if p.auth_mode == 0x02:
            digest_key = p.secret_key if p.auth_version == 0x02 else p.pin_code
        digest = hc.digest_challenge(digest_key, double_nonce)
        if digest is None:
            raise HiChainError("Cannot compute auth challenge")
        p.first_key = digest[32:48]
        nonce = p.auth_version.to_bytes(2, "big") + client_nonce
        reply = self._require(C.auth_request(p, digest[:32], nonce))
        expected = hc.digest_response(digest_key, double_nonce)[:32]
        if reply.tlv.get_bytes(0x01, b"") != expected:
            raise HiChainError("Challenge answer mismatch")

        if not lite:
            return  # Bluetooth classic devices in normal mode do not bond
        mac = self.store.fake_mac()
        serial = mac.replace(":", "")[6:12].encode("utf-8")
        reply = self._require(C.bond_params_request(serial, mac.encode("utf-8")))
        p.encryption_counter = reply.tlv.get_int(0x09, 0)
        iv = p.get_iv()
        enc_key = p.first_key if p.auth_mode == 0x02 else hc.create_secret_key(self.address)
        bond_key = HuaweiCrypto.encrypt_bonding_key(p.encrypt_method, p.secret_key, enc_key, iv)
        self.request(C.bond_request(serial, bond_key, iv))

    def _configure(self):
        reply = self.request(C.product_info())
        if reply is not None:
            self.info = C.parse_product_info(reply.tlv)
            log.info("Product info: %s", self.info)
        self._sync_time()
        self._read_battery()

        reply = self._require(C.supported_services())
        services = C.parse_supported_services(reply.tlv)
        for packet in C.supported_commands_batches(self.params, services):
            reply = self.request(packet)
            if reply is not None:
                try:
                    self.commands.update(C.parse_supported_commands(reply.tlv))
                except (KeyError, ValueError) as e:
                    log.warning("Could not parse supported commands: %s", e)
        if self.supports(0x01, DC.EXPAND_CAPABILITY):
            reply = self.request(C.expand_capability())
            if reply is not None:
                self.expand_capabilities = reply.tlv.get_bytes(0x01, b"")
        log.info("Supported commands: %s", {"%02x" % s: [("%02x" % c) for c in cmds]
                                            for s, cmds in sorted(self.commands.items())})
        log.info("Expand capabilities: %s", self.expand_capabilities.hex())
        self.info["features"] = {
            "notifications": self.supports(0x02, NC.ACTION),
            "weather": self.supports(0x0F, WC.CURRENT),
            "weather_forecast": self.supports(0x0F, WC.FORECAST),
        }
        self.listener.on_device_info(dict(self.info))

    def _initialize_services(self):
        # Same order and conditions as Gadgetbridge's initializeDynamicServices. The
        # watch keeps its "pairing" screen up (and drops the link after ~20 s) until
        # it has been told who it belongs to.
        if self.supports(Service.ACCOUNT, C.AC.EXTENDED_ACCOUNT) and self.supports(Service.ACCOUNT, C.AC.ACCOUNT_SWITCH):
            self.request(C.extended_account(self.supports_expand(C.CAP_DIFF_ACCOUNT_PAIRING_OPTIMIZATION)), 2.0)
        if self.supports(0x01, DC.SETTING_RELATED):
            reply = self.request(C.setting_related(), 2.0)
            if reply is not None and reply.tlv.contains(0x02):
                # Bits of tag 2: which files use the new (0x2C) download
                self.rri_new_sync = bool(reply.tlv.get_byte(0x02) & 0x04)
                log.info("Setting related: file support 0x%02x", reply.tlv.get_byte(0x02))
        if self.supports(0x01, DC.ACCEPT_AGREEMENT):
            self.request(C.accept_agreement(), 2.0)
        if self.supports_expand(C.CAP_REVERSE_CAPABILITIES):
            self.request(C.reverse_capabilities(), 2.0)
        if self.supports_expand(C.CAP_MULTI_DEVICE):
            self._send(C.set_up_device_status(self.device_name))  # the watch never answers this one
            time.sleep(0.05)
            self.request(C.wear_status(), 2.0)
        if self.supports(0x01, DC.CONNECT_STATUS):
            self.request(C.connect_status(), 2.0)
        # Tell the watch the phone handles heart-rate data (Gadgetbridge sends both)
        if self.supports(0x17, 0x17):
            self.request(F.notify_heart_rate_capability(), 2.0)
        if self.supports(F.SERVICE, 0x23):
            self.request(F.notify_rest_heart_rate_capability(), 2.0)
        # None = leave the watch's own setting alone
        if self.settings.get("continuous_heart_rate") is not None:
            self._set_automatic_heart_rate(self.settings["continuous_heart_rate"])
        if self.supports(0x02, NC.ACTION) and self.protocol_version == 2:
            reply = self.request(C.notification_constraints())
            if reply is not None:
                try:
                    self.notification_constraints = C.parse_notification_constraints(reply.tlv)
                except (KeyError, ValueError) as e:
                    log.warning("Could not parse notification constraints: %s", e)
        if self.supports(0x02, NC.STATE):
            self.request(C.notification_state(self.settings.get("notifications_enabled", True)))
        if self.supports(0x01, DC.TIMEZONE_ID):
            self.request(C.timezone_id())
        if self.supports(0x0C, 0x01):
            self.request(C.language(self.settings.get("locale", "en-US"), self.settings.get("imperial", False)))
        if self.supports(0x01, DC.DATE_FORMAT):
            self.request(C.date_format(self.settings.get("date_format", 3), 2 if self.settings.get("24h", True) else 1))

    def _sync_time(self):
        reply = self.request(C.set_time())
        if reply is not None and reply.tlv.contains(0x01):
            diff = abs(int(time.time()) - reply.tlv.get_int(0x01))
            if diff > 0:
                self.request(C.set_time())

    def _read_battery(self):
        reply = self.request(C.battery_level())
        if reply is not None:
            self._update_battery(C.parse_battery(reply.tlv))

    def _update_battery(self, level):
        if level is not None and level >= 0:
            self.battery = level
            self.listener.on_battery(level)

    # ------------------------------------------------------------ async packets
    def _handle_async(self, packet):
        if self.params.secret_key is None:
            return  # ignore everything until authenticated (as Gadgetbridge does)
        key = (packet.service, packet.command)
        log.debug("Async packet %02x/%02x %r", packet.service, packet.command, packet.tlv)
        if key == (Service.DEVICE_CONFIG, DC.BATTERY_CHANGED):
            self._update_battery(C.parse_battery(packet.tlv))
        elif key == (Service.WEATHER, WC.DEVICE_REQUEST):
            if packet.tlv.get_int(0x7F, -1) == 0x000186AA:
                self.listener.on_weather_requested()
            else:
                self.submit(lambda: self._send(C.weather_device_ack()))
        elif key == (Service.FIND_PHONE, 0x01):
            self.listener.on_find_phone(packet.tlv.get_bool(0x01, False))
        elif key == (Service.CALLS, C.CALL_ANSWER):
            action = C.parse_call_action(packet.tlv)
            log.info("Call screen on the watch: %s", action)
            self.listener.on_call_action(action)

    # ---------------------------------------------------------- file download
    def _download_file(self, name, file_type, start, end, dict_id=0):
        """Generator, use with `yield from`; returns the file contents (b"" if empty).

        Raises FileDownloadError when the watch refuses or stalls, WatchError when the
        link is gone. Follows Gadgetbridge's HuaweiFileDownloadManager (new sync only).
        """
        reply = self.request(FDL.init_request(name, file_type, max(start, F.EARLIEST), end, dict_id), FILE_TIMEOUT)
        if reply is None:
            self._check_link("the download request for " + name)
            raise FDL.FileDownloadError("The watch did not answer the download request for %s" % name)
        init = FDL.parse_init(reply.tlv)
        log.info("File %s: id %d, %s bytes", name, init["file_id"], init["size"])
        if init["name"] and init["name"] != name:
            raise FDL.FileDownloadError("The watch offered %s instead of %s" % (init["name"], name))
        if init["size"] is None:
            # Seen when the watch has no data of this kind (Gadgetbridge: "invalid file size")
            raise FDL.FileDownloadError("The watch reported no valid size for %s" % name)
        file_id, size = init["file_id"], init["size"]
        if size == 0:
            self.request(FDL.complete_request(file_id), 2.0)
            return b""
        yield
        reply = self.request(FDL.info_request(file_id), FILE_TIMEOUT)
        if reply is None:
            self._check_link("the file info for " + name)
            raise FDL.FileDownloadError("The watch did not answer the file info for %s" % name)
        info = FDL.parse_info(reply.tlv)
        timeout = max(info["timeout"], 5)
        max_block = info["max_block"] or 4096
        data = bytearray()
        while len(data) < size:
            block_start = len(data)
            block = min(size - block_start, max_block)
            while not self._file_blocks.empty():  # drop leftovers of an aborted download
                self._file_blocks.get_nowait()
            self._send(FDL.block_request(file_id, block_start, block, info["no_encrypt"], dict_id))
            while len(data) - block_start < block:
                try:
                    pkt = self._file_blocks.get(timeout=timeout)
                except queue.Empty:
                    raise FDL.FileDownloadError("No data for %s for %d s (%d of %d bytes)"
                                                % (name, timeout, len(data), size))
                if pkt is None:
                    raise WatchError("The connection closed during the download of %s" % name)
                got_id, offset, chunk = FDL.decode_block(pkt.payload, self.params)
                if got_id != file_id:
                    raise FDL.FileDownloadError("Data for file id %d during the download of id %d" % (got_id, file_id))
                if offset != len(data):
                    log.warning("File %s: block at offset %d, expected %d", name, offset, len(data))
                data += chunk
            yield
        if len(data) > size:
            log.warning("File %s is %d bytes, %d were announced", name, len(data), size)
        self.request(FDL.complete_request(file_id), 2.0)
        log.info("Downloaded %s: %d bytes", name, len(data))
        return bytes(data[:size])

    def _check_link(self, what):
        if not self._running:
            raise WatchError("The connection closed during " + what)

    def _health_files(self, result, sleep_file_start, stress_start, end):
        """Generator: TruSleep (sleep stages + score) and stress files. A refused or broken
        file is reported in result["file_errors"]; only a lost link ends the sync."""
        if sleep_file_start is not None and self.is_ready():
            # Gadgetbridge downloadDictTrueSleepData: TruSleep plus the dictionary sleep sync
            if self.supports(F.SERVICE, 0x16) and self.supports_expand(CAP_DICT_SLEEP_SYNC):
                try:
                    data = yield from self._download_file(FDL.SEQUENCE_DATA_NAME, FDL.FileType.SEQUENCE_DATA,
                                                          sleep_file_start, end, HF.SLEEP_DETAILS_CLASS)
                    if data:
                        result["sleep_sessions"] = HF.parse_sleep_file(data, self.supports_expand(CAP_BED_TIME))
                        log.info("Health sync: %d sleep session(s) from the TruSleep file",
                                 len(result["sleep_sessions"]))
                except (FDL.FileDownloadError, HF.HealthFileError, KeyError, ValueError, struct.error) as e:
                    log.warning("Health sync: sleep file failed: %s", e)
                    result["file_errors"].append("sleep: %s" % e)
            else:
                log.info("Health sync: this watch has no TruSleep sequence data (old sleep files not supported)")
        if stress_start is not None and self.is_ready() and self.supports(0x20, 0x09):
            if not self.rri_new_sync:
                log.info("Health sync: stress uses the old file download, not supported")
                return
            try:
                data = yield from self._download_file(FDL.RRI_NAME, FDL.FileType.RRI, stress_start, end)
                if data:
                    result["stress"] = HF.parse_stress_file(data)
                    log.info("Health sync: %d stress measurement(s)", len(result["stress"]))
            except (FDL.FileDownloadError, HF.HealthFileError, KeyError, ValueError, struct.error) as e:
                log.warning("Health sync: stress file failed: %s", e)
                result["file_errors"].append("stress: %s" % e)

    # ------------------------------------------------------------------ health
    def _health_steps(self, step_start, sleep_start, sleep_file_start=None, stress_start=None):
        """Generator: one request per step (see sync_health), same order as Gadgetbridge:
        sleep count + messages, step count + messages, today's totals, then the files."""
        end = int(time.time())
        result = {"totals": None, "samples": [], "sleep": [], "sleep_sessions": [], "stress": [],
                  "file_errors": [], "skipped": 0, "error": "",
                  "step_start": step_start, "sleep_start": sleep_start, "end": end}
        try:
            for key, count_cmd, data_cmd, start in (
                    ("sleep", F.FC.SLEEP_COUNT, F.FC.SLEEP_DATA, sleep_start),
                    ("activity", F.FC.STEP_COUNT, F.FC.STEP_DATA, step_start)):
                if not self.is_ready():
                    raise WatchError("The watch is not connected")
                reply = self.request(F.message_count_request(count_cmd, max(start, F.EARLIEST), end))
                if reply is None:
                    log.info("Health sync: no answer to the %s count request, skipping it", key)
                    continue
                count = F.parse_message_count(reply.tlv)
                log.info("Health sync: %d %s message(s) since %s", count, key, time.ctime(start))
                yield
                for index in range(count):
                    if not self.is_ready():
                        raise WatchError("The watch disconnected during the health sync")
                    reply = self.request(F.message_data_request(data_cmd, index))
                    if reply is None:
                        raise WatchError("The watch did not answer %s message %d of %d" % (key, index + 1, count))
                    try:
                        if key == "sleep":
                            number, periods = F.parse_sleep_data(reply.tlv)
                            result["sleep"].extend(periods)
                        else:
                            number, samples, bad = F.parse_step_data(reply.tlv)
                            result["samples"].extend(samples)
                            result["skipped"] += bad
                        if number != index:
                            log.warning("Health sync: got %s message %d, asked for %d", key, number, index)
                    except (KeyError, ValueError, IndexError, struct.error) as e:
                        log.warning("Health sync: skipping unreadable %s message %d: %s %r", key, index, e, reply.tlv)
                        result["skipped"] += 1
                    yield
            if self.is_ready():
                reply = self.request(F.totals_request())
                if reply is not None:
                    try:
                        result["totals"] = F.parse_totals(reply.tlv)
                    except (KeyError, ValueError, struct.error) as e:
                        log.warning("Health sync: unreadable totals: %s %r", e, reply.tlv)
            yield from self._health_files(result, sleep_file_start, stress_start, end)
        except WatchError as e:
            result["error"] = str(e)
        except Exception as e:  # noqa: BLE001 - always report back, or the UI shows "syncing" forever
            log.exception("Health sync failed")
            result["error"] = "Health sync failed: %s" % e
        log.info("Health sync done: %d minute(s), %d sleep period(s), totals %s%s",
                 len(result["samples"]), len(result["sleep"]), result["totals"],
                 (", error: " + result["error"]) if result["error"] else "")
        # Fields this watch sends that we don't decode yet: worth reporting, they
        # differ between models (Gadgetbridge logs each one as "Unknown tag")
        unknown = {}
        known = {}
        for s in result["samples"]:
            for key in s:
                if key not in ("time", "unknown"):
                    known[key] = known.get(key, 0) + 1
            for bitmap, bit, value in s.get("unknown", ()):
                u = unknown.setdefault((bitmap, bit), [0, value, value])
                u[0] += 1
                u[1] = min(u[1], value)
                u[2] = max(u[2], value)
        if result["samples"]:
            log.info("Health sync: minutes per field %s", known)
        for (bitmap, bit), (count, lo, hi) in sorted(unknown.items()):
            log.info("Health sync: unknown activity field bitmap %d bit 0x%02x in %d minute(s), values %d..%d",
                     bitmap, bit, count, lo, hi)
        self.listener.on_health_data(result)

    # ----------------------------------------------------------- notifications
    def _next_msg_id(self):
        with self._msg_id_lock:  # used by the worker and, for calls, the main thread
            self._msg_id = self._msg_id + 1 if self._msg_id < 256 else 0
            return self._msg_id

    def _send_notification(self, title, body, sender, app_id, kind, key):
        if not self.is_ready() or not self.supports(0x02, NC.ACTION):
            log.info("Notification dropped (not connected or unsupported)")
            return
        cons = self.notification_constraints
        # Gadgetbridge falls back to its tiny default constraint table; a generous
        # limit is friendlier when the watch did not report one.
        max_len = cons.get("content_length") or 500
        if body and len(body) > max_len:
            body = body[:max(max_len - 0x0D, 1)] + "..."
        params = {
            "supports_reply": self.supports_expand(89),
            "supports_repeated_notify": self.supports_expand(94),
            "supports_remove_single": self.supports_expand(120),
            "supports_timestamp": self.supports_expand(77),
            "key": key or "",
            "id": zlib.crc32(key.encode("utf-8")) & 0x7FFFFFFF if key else 0,
            "channel_id": "",
            "when": int(time.time() * 1000),
        }
        packet = C.notification(self._next_msg_id(), kind, title, sender or title, body, app_id,
                                cons.get("content_format", 0x02), params)
        self.request(packet, 3.0)

    # ------------------------------------------------------------------ weather
    def _send_weather(self, report):
        if not self.is_ready() or not self.supports(0x0F, WC.CURRENT):
            log.info("Weather not sent (not connected or unsupported)")
            return False
        if report is None:
            if self.supports(0x0F, WC.ERROR_SIMPLE) or self.supports(0x0F, WC.ERROR_EXTENDED):
                self.request(C.weather_error(self.supports(0x0F, WC.ERROR_EXTENDED), 2), 2.0)
            return False
        s = C.new_weather_settings()
        s["uv_index"] = self.supports_expand(0x2F)
        s["extended_hourly"] = self.supports_expand(0xC0)
        reply = self.request(C.weather_start(), 2.0)
        if reply is None or not C.parse_weather_start(reply.tlv):
            log.warning("Watch refused weather start")
            return False
        s["weather"] = True
        if self.supports(0x0F, WC.UNIT):
            self.request(C.weather_unit(report.fahrenheit), 2.0)
        reply = self.request(C.weather_support())
        if reply is not None and reply.tlv.contains(0x01):
            C.apply_weather_support(s, reply.tlv)
        if self.supports(0x0F, WC.EXTENDED_SUPPORT):
            reply = self.request(C.weather_extended_support())
            if reply is not None and reply.tlv.contains(0x01):
                C.apply_weather_extended_support(s, reply.tlv)
        if self.supports(0x0F, WC.SUN_MOON_SUPPORT):
            reply = self.request(C.weather_sun_moon_support())
            if reply is not None and reply.tlv.contains(0x01):
                C.apply_weather_sun_moon_support(s, reply.tlv)
        self.weather_settings = s
        log.info("Weather settings: %s", s)
        self.request(C.current_weather(s, report))
        if self.supports(0x0F, WC.FORECAST):
            self.request(C.weather_forecast(s, report))
        return True
