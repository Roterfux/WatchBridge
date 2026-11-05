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


class _Raw:
    """A packet body that is not TLV (Packet only calls serialize())."""

    def __init__(self, data):
        self.data = data

    def serialize(self):
        return self.data


class FakeWatch:
    def __init__(self, sock, pin=b"123456", auth_token=None, device_support_type=4, encrypt_method=1,
                 confirm_delay=0.0, drop_at=None, health=None, files=None, file_block=300,
                 upload_unit=300, upload_window=1000, upload_no_encrypt=0, upload_refuse=None):
        self.sock = sock
        self.pin = pin
        self.confirm_delay = confirm_delay  # seconds the "user" takes to tap the checkmark
        self.drop_at = drop_at              # (service, command) at which the watch hangs up
        # Stored health records: {"totals": (steps, kcal, m), "steps": [{"base": t, "minutes":
        # [(offset, data bytes)]}], "sleep": [{"periods": [(type, start, minutes)]}]}
        self.health = health or {}
        self.fitness_requests = []
        self._step_window = self._sleep_window = []
        # Files served over 0x2C, by name; block size forces several RequestBlocks
        self.files = files or {}
        self.file_block = file_block
        self.file_requests = []     # (command, TLV) of every 0x2C request
        self._file_ids = {}
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
        # Watch faces (service 0x27) and the upload (0x28)
        self.faces = [{"file": "100000001", "version": "1.0.0", "type": 0x03, "name": "Classic"}]
        self.upload_unit = upload_unit        # bytes per 0x28/0x06 packet
        self.upload_window = upload_window    # bytes asked for per 0x28/0x05
        self.upload_no_encrypt = upload_no_encrypt
        self.upload_refuse = upload_refuse    # error code for the file info, e.g. 140004
        self.upload = None                    # {"name", "size", "data", "hash", ...}
        self.uploaded = []                    # (file name, bytes) of completed uploads
        self.chunk_packets = 0
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

    def _files(self, c, t):
        """File download, service 0x2C (new sync)."""
        self.file_requests.append((c, t))
        if c == 0x01:
            name = t.get_string(0x01)
            data = self.files.get(name)
            fid = self._file_ids.setdefault(name, len(self._file_ids) + 1)
            size = 0xFFFFFFFF if data is None else len(data)
            return self._send(0x2C, 1, TLV().put(0x01, name).put_byte(0x02, t.get_byte(0x02)).put_byte(0x03, fid)
                              .put_int(0x04, size), True)
        if c == 0x03:
            return self._send(0x2C, 3, TLV().put_byte(0x01, t.get_byte(0x01)).put_byte(0x02, 5)
                              .put_short(0x03, 100).put_int(0x04, self.file_block).put_byte(0x05, 0), True)
        if c == 0x04:
            fid, offset, size = t.get_byte(0x01), t.get_int(0x02), t.get_int(0x03)
            data = next(d for n, d in self.files.items() if self._file_ids.get(n) == fid)
            self._send(0x2C, 4, OK, True)
            # The block arrives as several raw 0x2C/0x05 packets of `burst` bytes, encrypted
            for pos in range(offset, offset + size, 100):
                chunk = data[pos:min(pos + 100, offset + size)]
                self._send(0x2C, 5, _Raw(bytes([fid]) + struct.pack(">I", pos) + b"\x00" + chunk), True)
            return None
        return self._send(0x2C, c, OK, True)

    def _watchfaces(self, c, t):
        if c == 0x01:
            # As a GT 5 (firmware 6.0.0.23) answers
            return self._send(0x27, 0x01, TLV().put(0x01, "2.9").put_short(0x02, 466).put_short(0x03, 466)
                              .put_byte(0x04, 1).put_byte(0x05, 0).put(0x06, "2.1,2.2,2.3,2.4,2.5,2.6,2.7,2.8"),
                              True)
        if c == 0x02:
            lst = TLV()
            for f in self.faces:
                lst.put(0x82, TLV().put(0x03, f["file"]).put(0x04, f["version"]).put_byte(0x05, f["type"]))
            return self._send(0x27, 0x02, TLV().put(0x81, lst), True)
        if c == 0x06:
            names = TLV()
            for sub in t.get_object(0x82).get_objects(0x83):
                face = [f for f in self.faces if f["file"] == sub.get_string(0x04)]
                if face:
                    names.put(0x83, TLV().put(0x04, face[0]["file"]).put(0x05, face[0]["name"]))
            return self._send(0x27, 0x06, TLV().put(0x82, names), True)
        if c == 0x03:
            name, op = t.get_string(0x01), t.get_byte(0x03)
            if op == 1:
                for f in self.faces:
                    f["type"] = (f["type"] & ~0x01) | (0x01 if f["file"] == name else 0)
            elif op == 2:
                self.faces = [f for f in self.faces if f["file"] != name]
            return self._send(0x27, 0x03, OK, True)
        if c == 0x05:
            return None  # the phone confirms our install report
        return self._send(0x27, c, OK, True)

    def _upload(self, c, t, pkt):
        if c == 0x02:
            if self.upload_refuse:
                return self._send(0x28, 0x02, TLV().put_int(0x7F, self.upload_refuse), True)
            name = t.get_string(0x01)
            self.upload = {"name": name, "size": t.get_int(0x02), "data": bytearray(t.get_int(0x02)),
                           "got": set(), "id": 9, "face": (t.get_string(0x05), t.get_string(0x06))}
            self._send(0x28, 0x02, OK, True)
            return self._send(0x28, 0x03, TLV().put_byte(0x01, 9), True)  # "send the hash"
        if c == 0x03:
            self.upload["hash"] = t.get_bytes(0x03)
            consult = TLV().put_byte(0x01, 9).put(0x02, "2.0").put_byte(0x03, 5).put_byte(0x04, 0) \
                .put_short(0x05, self.upload_unit).put_int(0x06, self.upload_window).put_byte(0x07, 0) \
                .put_int(0x08, 0).put_byte(0x09, self.upload_no_encrypt)
            return self._send(0x28, 0x04, consult, True)
        if c == 0x04:
            self.upload["ack"] = t
            return self._ask_next(0)
        if c == 0x06:
            return self._chunk(pkt)
        return None  # 0x07 ack: done

    def _ask_next(self, offset):
        size = min(self.upload_window, self.upload["size"] - offset)
        self.upload["window"] = (offset, offset + size)
        return self._send(0x28, 0x05, TLV().put_byte(0x01, 9).put_int(0x02, offset).put_int(0x03, size), True)

    def _chunk(self, pkt):
        body = pkt.payload[2:]
        if body[:3] == b"\x7c\x01\x01":  # encrypted: an encryption TLV around the raw chunk
            tlv = TLV.parse(body)
            body = crypto.decrypt(self.params.use_gcm(), tlv.get_bytes(0x7E), self.params.secret_key,
                                  tlv.get_bytes(0x7D))
            self.upload["encrypted"] = True
        file_id, _index, offset = struct.unpack(">BBI", body[:6])
        data = body[6:]
        assert file_id == 9
        self.chunk_packets += 1
        self.upload["data"][offset:offset + len(data)] = data
        self.upload["got"].update(range(offset, offset + len(data)))
        start, end = self.upload["window"]
        if not all(i in self.upload["got"] for i in range(start, end)):
            return None
        if end < self.upload["size"]:
            return self._ask_next(end)
        data = bytes(self.upload["data"])
        import hashlib
        assert hashlib.sha256(data).digest() == self.upload["hash"], "hash mismatch"
        self.uploaded.append((self.upload["name"], data))
        name, version = self.upload["face"]
        self.faces.append({"file": name, "version": version, "type": 0x00, "name": "Uploaded face"})
        self._send(0x28, 0x07, TLV().put_byte(0x01, 9).put_byte(0x02, 1), True)
        # Installed: ask the phone to confirm and to make it the current face
        return self._send(0x27, 0x05, TLV().put(0x01, name).put(0x02, version).put_byte(0x03, 0x02), True)

    def _service(self, pkt):
        s, c, t = pkt.service, pkt.command, pkt.tlv
        if s == 0x07:
            return self._fitness(c, t)
        if s == 0x2C:
            return self._files(c, t)
        if s == 0x27:
            return self._watchfaces(c, t)
        if s == 0x28:
            return self._upload(c, t, pkt)
        if (s, c) == (0x01, 0x31):
            return self._send(s, c, TLV().put_byte(0x02, 0x04 | 0x02), True)  # RRI and TruSleep new sync
        if (s, c) == (0x01, 0x07):
            return self._send(s, c, TLV().put(0x03, "HW1").put(0x07, "5.0.0.110").put(0x09, "SN123")
                              .put(0x0A, "HUAWEI WATCH GT 5 ").put(0x11, "HUAWEI WATCH GT 5-ABC"), True)
        if (s, c) == (0x01, 0x05):
            return self._send(s, c, TLV().put(0x01, t.get_bytes(0x01)), True)
        if (s, c) == (0x01, 0x08):
            return self._send(s, c, TLV().put_byte(0x01, 87), True)
        if (s, c) == (0x01, 0x02):
            from watchbridge.huawei.commands import KNOWN_SUPPORTED_SERVICES
            bitmap = bytes(1 if x in (0x02, 0x07, 0x0B, 0x0C, 0x0F, 0x20, 0x27) else 0 for x in KNOWN_SUPPORTED_SERVICES)
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
            for bit in (0x2F, 74, 77, 94, 120, 143):  # 74: "call started"; 143: TruSleep as sequence data
                caps[bit // 8] |= 1 << (bit % 8)
            return self._send(s, c, TLV().put(0x01, bytes(caps)), True)
        if (s, c) == (0x02, 0x02):
            inner = TLV().put(0x91, TLV().put_byte(0x12, 0x01).put_byte(0x13, 0x02).put_short(0x14, 0x01F4)) \
                .put(0x91, TLV().put_byte(0x12, 0x07).put_byte(0x13, 0x01).put_short(0x14, 0x0020))  # incoming number
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
