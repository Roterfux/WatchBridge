"""A simulated Huawei Watch GT 5 speaking the watch side of the protocol.

Used to exercise the daemon's pairing (HiChain auth + bind), initialisation,
notification and weather code paths end to end over a socket pair.
"""

import json
import os
import socket
import struct
import threading
import time

from watchbridge.huawei import aes, crypto
from watchbridge.huawei.packet import Packet, Params, StreamParser
from watchbridge.huawei.tlv import TLV

OK = TLV().put_int(0x7F, 0x000186A0)


class FakeWatch:
    def __init__(self, sock, pin=b"123456", auth_token=None, device_support_type=4, encrypt_method=1,
                 confirm_delay=0.0, drop_at=None, health=None):
        self.sock = sock
        self.pin = pin
        self.confirm_delay = confirm_delay  # seconds the "user" takes to tap the checkmark
        self.drop_at = drop_at              # (service, command) at which the watch hangs up
        # Stored health records: {"totals": (steps, kcal, m), "steps": [{"base": t, "minutes":
        # [(offset, data bytes)]}], "sleep": [{"periods": [(type, start, minutes)]}]}
        self.health = health or {}
        self.fitness_requests = []
        self._step_window = self._sleep_window = []
        self.auth_token = auth_token  # known token = already paired
        self.params = Params()
        self.params.device_support_type = device_support_type
        self.params.encrypt_method = encrypt_method
        self.params.auth_version = 3
        self.parser = StreamParser(self.params)
        self.auth_id = os.urandom(8).hex().upper().encode()
        self.received = []          # decoded packets after auth
        self.notifications = []
        self.forecasts = []
        self.chain = {}
        self.thread = threading.Thread(target=self._loop, daemon=True)

    def start(self):
        self.thread.start()
        return self

    def _send(self, service, command, tlv, encrypt):
        pkt = Packet(service, command, tlv, encrypt=encrypt and self.params.secret_key is not None)
        for frame in pkt.serialize(self.params):
            self.sock.sendall(frame)

    def _loop(self):
        while True:
            try:
                data = self.sock.recv(4096)
            except OSError:
                return
            if not data:
                return
            for pkt in self.parser.feed(data):
                self.handle(pkt)

    def push(self, service, command, tlv):
        """Send an unsolicited (async) packet to the phone."""
        self._send(service, command, tlv, True)

    # ---------------------------------------------------------------- handlers
    def handle(self, pkt):
        key = (pkt.service, pkt.command)
        if self.params.secret_key is not None:
            self.received.append(pkt)
        if key == self.drop_at:
            self.sock.shutdown(socket.SHUT_RDWR)
            return
        if key == (0x01, 0x01):
            nonce = b"\x00\x03" + os.urandom(16)
            t = TLV().put_byte(0x01, 2).put_short(0x02, 0xF4).put_short(0x03, 0x0200).put_short(0x04, 0x10) \
                .put(0x05, nonce).put_byte(0x07, self.params.device_support_type).put_byte(0x08, 0) \
                .put_byte(0x0C, self.params.encrypt_method)
            return self._send(1, 1, t, False)
        if key == (0x01, 0x16):
            return self._send(1, 0x16, TLV().put_byte(0x01, 0x01), False)
        if key == (0x01, 0x33):
            time.sleep(self.confirm_delay)  # the watch waits for the user's confirmation
            return self._send(1, 0x33, TLV().put_byte(0x01, 0x01), False)  # -> 0x186A0 HiChain
        if key == (0x01, 0x2C):
            iv = os.urandom(16)
            enc = crypto.encrypt(self.params.encrypt_method == 1, self.pin, crypto.DIGEST_SECRET_V3, iv)
            return self._send(1, 0x2C, TLV().put(0x01, enc).put(0x02, iv), False)
        if key == (0x01, 0x28):
            return self._hichain(pkt.tlv)
        return self._service(pkt)

    def _hichain_reply(self, payload=None, done=False):
        if done:
            return self._send(1, 0x28, TLV().put_byte(0x04, 0x01).put(0x01, "ok"), False)
        value = json.dumps({"payload": payload})
        self._send(1, 0x28, TLV().put_byte(0x04, 0x00).put(0x01, value), False)

    def _hichain(self, tlv):
        op = tlv.get_byte(0x02)
        payload = json.loads(tlv.get_string(0x01))["payload"]
        c = self.chain
        if "isoSalt" in payload:
            if op == 2 and self.auth_token is None:
                return self._hichain_reply({"errorCode": 7})
            key = crypto.sha256(crypto.hexstr(self.pin).encode()) if op == 1 else self.auth_token
            c.clear()
            c["rand_phone"] = bytes.fromhex(payload["isoSalt"])
            c["id_phone"] = bytes.fromhex(payload["peerAuthId"])
            c["rand_watch"] = os.urandom(16)
            c["psk"] = crypto.hmac_sha256(key, bytes.fromhex(payload["seed"]))
            token = crypto.hmac_sha256(c["psk"], c["rand_watch"] + c["rand_phone"] + c["id_phone"] + self.auth_id)
            return self._hichain_reply({"isoSalt": crypto.hexstr(c["rand_watch"]),
                                        "peerAuthId": crypto.hexstr(self.auth_id),
                                        "peerUserType": 0, "token": crypto.hexstr(token)})
        if "token" in payload:
            expect = crypto.hmac_sha256(c["psk"], c["rand_phone"] + c["rand_watch"] + self.auth_id + c["id_phone"])
            if bytes.fromhex(payload["token"]) != expect:
                return self._hichain_reply({"errorCode": 1})
            c["session"] = crypto.hkdf_sha256(c["psk"], c["rand_phone"] + c["rand_watch"],
                                              b"hichain_iso_session_key", 32)
            return self._hichain_reply({"returnCodeMac": crypto.hexstr(crypto.hmac_sha256(c["psk"], bytes(4)))})
        if "encData" in payload:
            challenge = aes.gcm_decrypt(c["session"], bytes.fromhex(payload["nonce"]),
                                        bytes.fromhex(payload["encData"]), b"hichain_iso_exchange")
            self.auth_token = os.urandom(32)
            nonce = os.urandom(12)
            enc = aes.gcm_encrypt(c["session"], nonce, self.auth_token, challenge)
            return self._hichain_reply({"nonce": crypto.hexstr(nonce), "encAuthToken": crypto.hexstr(enc)})
        if "encResult" in payload:
            aes.gcm_decrypt(c["session"], bytes.fromhex(payload["nonce"]), bytes.fromhex(payload["encResult"]),
                            b"hichain_iso_result")
            self._hichain_reply(done=True)
            if op == 2:
                self.params.secret_key = crypto.hkdf_sha256(c["session"], c["rand_phone"] + c["rand_watch"],
                                                            b"hichain_return_key", 32)
            return None
        return self._hichain_reply({"errorCode": 2})

    def _fitness(self, c, t):
        """FitnessData (0x07) with the records in self.health."""
        h = self.health
        self.fitness_requests.append((c, t))
        if c == 0x03:
            steps, calories, distance = h.get("totals", (0, 0, 0))
            # Two containers, as real watches split the totals by activity type
            inner = TLV().put(0x83, TLV().put_int(0x05, steps - 100).put_short(0x06, calories).put_int(0x07, distance)) \
                .put(0x83, TLV().put_int(0x05, 100))
            return self._send(7, c, TLV().put(0x81, inner), True)
        if c in (0x0A, 0x0C):
            # Like the real watch: only messages that reach past the requested start
            start = t.get_int(0x03)
            if c == 0x0A:
                self._step_window = [m for m in h.get("steps", []) if m["base"] + 3600 > start]
                count = len(self._step_window)
            else:
                self._sleep_window = [m for m in h.get("sleep", [])
                                      if max(s + 60 * n for _, s, n in m["periods"]) > start]
                count = len(self._sleep_window)
            return self._send(7, c, TLV().put(0x81, TLV().put_short(0x02, count)), True)
        if c in (0x0B, 0x0D):
            index = t.get_object(0x81).get_short(0x02)
            if c == 0x0B:
                m = self._step_window[index]
                inner = TLV().put_short(0x02, index).put_int(0x03, m["base"])
                for offset, data in m["minutes"]:
                    inner.put(0x84, TLV().put_byte(0x05, offset).put(0x06, data))
            else:
                m = self._sleep_window[index]
                inner = TLV().put_short(0x02, index)
                for kind, start, minutes in m["periods"]:
                    inner.put(0x83, TLV().put_byte(0x04, kind).put(0x05, struct.pack(">IH", start, minutes)))
            return self._send(7, c, TLV().put(0x81, inner), True)
        return self._send(7, c, OK, True)

    def _service(self, pkt):
        s, c, t = pkt.service, pkt.command, pkt.tlv
        if s == 0x07:
            return self._fitness(c, t)
        if (s, c) == (0x01, 0x07):
            return self._send(s, c, TLV().put(0x03, "HW1").put(0x07, "5.0.0.110").put(0x09, "SN123")
                              .put(0x0A, "HUAWEI WATCH GT 5 ").put(0x11, "HUAWEI WATCH GT 5-ABC"), True)
        if (s, c) == (0x01, 0x05):
            return self._send(s, c, TLV().put(0x01, t.get_bytes(0x01)), True)
        if (s, c) == (0x01, 0x08):
            return self._send(s, c, TLV().put_byte(0x01, 87), True)
        if (s, c) == (0x01, 0x02):
            from watchbridge.huawei.commands import KNOWN_SUPPORTED_SERVICES
            bitmap = bytes(1 if x in (0x02, 0x0B, 0x0C, 0x0F) else 0 for x in KNOWN_SUPPORTED_SERVICES)
            return self._send(s, c, TLV().put(0x02, bitmap), True)
        if (s, c) == (0x01, 0x03):
            out = TLV()
            for tag, value in t.get_object(0x81).items:
                if tag == 0x02:
                    out.put(0x02, value)
                elif tag == 0x03:
                    out.put(0x04, bytes([1]) * len(value))
            return self._send(s, c, TLV().put(0x81, out), True)
        if (s, c) == (0x01, 0x37):
            caps = bytearray(32)
            for bit in (0x2F, 77, 94, 120):
                caps[bit // 8] |= 1 << (bit % 8)
            return self._send(s, c, TLV().put(0x01, bytes(caps)), True)
        if (s, c) == (0x02, 0x02):
            inner = TLV().put(0x91, TLV().put_byte(0x12, 0x01).put_byte(0x13, 0x02).put_short(0x14, 0x01F4))
            return self._send(s, c, TLV().put(0x81, TLV().put(0x82, TLV().put(0x90, inner))), True)
        if (s, c) == (0x02, 0x01):
            self.notifications.append(t)
        if (s, c) == (0x0F, 0x02):
            return self._send(s, c, TLV().put_byte(0x01, 0xFF), True)
        if (s, c) == (0x0F, 0x06):
            return self._send(s, c, TLV().put_short(0x01, 0x0007), True)
        if (s, c) == (0x0F, 0x0A):
            return self._send(s, c, TLV().put_int(0x01, 0x03), True)
        if (s, c) == (0x0F, 0x08):
            self.forecasts.append(t)
        if (s, c) == (0x0F, 0x04):
            return None  # ack from the phone, nothing to answer
        return self._send(s, c, OK, True)
