# WatchBridge - Huawei Watch GT 5 companion for Sailfish OS
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# Ported from Gadgetbridge (GetHiChainRequest.java, DeviceConfig.HiChain),
# Copyright (C) 2024 Damien Gaignon, Martin.JM and Gadgetbridge contributors.
"""HiChain ISO authentication used by HarmonyOS watches such as the Watch GT 5.

Operation 1 ("auth") runs on the very first connection: a PSK derived from the
pin code the watch hands us lets both sides agree on a session key, and the
watch then delivers a long-term auth token which we store.

Operation 2 ("bind") runs on every connection: the stored token is used as PSK
input and the resulting key encrypts all further traffic.
"""

import json
import logging
import os
import time

from . import aes, crypto
from .commands import DC, Service
from .packet import Packet
from .tlv import TLV

log = logging.getLogger(__name__)

GROUP_ID = "7B0BC0CBCE474F6C238D9661C63400B797B166EA7849B3A370FC73A9A236E989"
PKG_NAME = "com.huawei.devicegroupmanage"

OP_AUTH = 0x01
OP_BIND = 0x02


class HiChainError(Exception):
    pass


def _dumps(obj):
    # org.json compact output, insertion ordered
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False)


class HiChain:
    def __init__(self, operation_code, self_auth_id, pin_code=None, stored_key=None, request_id=None):
        if operation_code == OP_AUTH and pin_code is None:
            raise HiChainError("Auth operation needs the pin code")
        if operation_code == OP_BIND and stored_key is None:
            raise HiChainError("Bind operation needs the stored auth token")
        self.op = operation_code
        self.self_auth_id = bytes(self_auth_id)
        self.pin_code = pin_code
        self.stored_key = stored_key
        self.request_id = request_id if request_id is not None else int(time.time() * 1000)
        self.step = 1
        self.seed = None
        self.rand_self = None
        self.rand_peer = None
        self.auth_id_peer = None
        self.psk = None
        self.session_key = None
        self.challenge = None
        # Results
        self.auth_token = None   # set after OP_AUTH step 3
        self.final_key = None    # set after OP_BIND step 4
        self.finished = False

    # -- request creation ---------------------------------------------------
    def _envelope(self, message_id):
        if self.op == OP_BIND:
            message_id |= 0x10
        payload = {"version": {"minVersion": "1.0.0", "currentVersion": "2.0.16"}}
        value = {"authForm": 0, "payload": payload, "groupAndModuleVersion": "2.0.1", "message": message_id}
        if self.op == OP_AUTH:
            dev_id = self.self_auth_id.decode("utf-8")
            value.update({
                "requestId": str(self.request_id),
                "groupId": GROUP_ID,
                "groupName": "health_group_name",
                "groupOp": 2,
                "groupType": 256,
                "peerDeviceId": dev_id,
                "connDeviceId": dev_id,
                "appId": "com.huawei.health",
                "ownerName": "",
            })
        return value, payload

    def _packet(self, value):
        t = TLV().put(0x01, _dumps(value)).put_byte(0x02, self.op).put_long(0x03, self.request_id)
        return Packet(Service.DEVICE_CONFIG, DC.HICHAIN, t, encrypt=False, sliced=True)

    def create_request(self):
        message_id = self.step
        if self.step == 1:
            self.seed = os.urandom(32)
            self.rand_self = os.urandom(16)
            value, payload = self._envelope(message_id)
            payload.update({
                "isoSalt": crypto.hexstr(self.rand_self),
                "peerAuthId": crypto.hexstr(self.self_auth_id),
                "operationCode": self.op,
                "seed": crypto.hexstr(self.seed),
                "peerUserType": 0,
            })
            if self.op == OP_BIND:
                payload.update({"pkgName": PKG_NAME, "serviceType": GROUP_ID, "keyLength": 0x20})
                value["isDeviceLevel"] = False
            return self._packet(value)

        if self.step == 2:
            message = self.rand_self + self.rand_peer + self.auth_id_peer + self.self_auth_id
            token = crypto.hmac_sha256(self.psk, message)
            value, payload = self._envelope(message_id)
            payload.update({"peerAuthId": crypto.hexstr(self.self_auth_id), "token": crypto.hexstr(token)})
            if self.op == OP_BIND:
                value["isDeviceLevel"] = False
            return self._packet(value)

        if self.step == 3:
            salt = self.rand_self + self.rand_peer
            self.session_key = crypto.hkdf_sha256(self.psk, salt, b"hichain_iso_session_key", 32)
            if self.op == OP_AUTH:
                nonce = os.urandom(12)
                self.challenge = os.urandom(16)
                enc = aes.gcm_encrypt(self.session_key, nonce, self.challenge, b"hichain_iso_exchange")
                value, payload = self._envelope(message_id)
                payload.update({"nonce": crypto.hexstr(nonce), "encData": crypto.hexstr(enc)})
                return self._packet(value)
            # Bind skips step 3, but keeps the step-3 message id (as Gadgetbridge does)
            self.step = 4

        if self.step == 4:
            nonce = os.urandom(12)
            enc = aes.gcm_encrypt(self.session_key, nonce, b"\x00\x00\x00\x00", b"hichain_iso_result")
            value, payload = self._envelope(message_id)
            payload.update({"nonce": crypto.hexstr(nonce), "encResult": crypto.hexstr(enc), "operationCode": self.op})
            return self._packet(value)

        raise HiChainError("Invalid step %d" % self.step)

    # -- response handling --------------------------------------------------
    @staticmethod
    def parse_response(tlv):
        """Returns (step, payload_dict, error_code)."""
        if not tlv.contains(0x04):
            raise HiChainError("Unsupported HiChain framing (Honor PAKE devices are not supported)")
        if tlv.get_byte(0x04) != 0x00:
            return 4, {}, 0
        # The watch NUL-terminates the JSON; like org.json, ignore anything after the object
        value, _ = json.JSONDecoder().raw_decode(tlv.get_string(0x01).strip("\x00 \r\n"))
        payload = value.get("payload", {})
        error = int(payload.get("errorCode", 0))
        if "isoSalt" in payload:
            return 1, payload, error
        if "returnCodeMac" in payload:
            return 2, payload, error
        if "encAuthToken" in payload:
            return 3, payload, error
        return 0, payload, error

    def process_response(self, tlv):
        """Consume the watch's answer. Returns True once this operation is complete."""
        step, payload, error = self.parse_response(tlv)
        if error:
            log.warning("HiChain error payload: %s", payload)
            raise HiChainError("Watch reported HiChain error %d" % error)
        if step == 4:
            if self.op == OP_BIND:
                salt = self.rand_self + self.rand_peer
                self.final_key = crypto.hkdf_sha256(self.session_key, salt, b"hichain_return_key", 32)
            self.finished = True
            return True

        if step == 1:
            self.auth_id_peer = bytes.fromhex(payload["peerAuthId"])
            self.rand_peer = bytes.fromhex(payload["isoSalt"])
            peer_token = bytes.fromhex(payload["token"])
            if self.op == OP_AUTH:
                key = crypto.sha256(crypto.hexstr(self.pin_code).encode("utf-8"))
            else:
                key = self.stored_key
            self.psk = crypto.hmac_sha256(key, self.seed)
            message = self.rand_peer + self.rand_self + self.self_auth_id + self.auth_id_peer
            if crypto.hmac_sha256(self.psk, message) != peer_token:
                raise HiChainError("Peer token check failed (wrong pin or stale pairing)")
        elif step == 2:
            expected = crypto.hmac_sha256(self.psk, b"\x00\x00\x00\x00")
            if bytes.fromhex(payload["returnCodeMac"]) != expected:
                raise HiChainError("returnCodeMac check failed")
        elif step == 3:
            if self.op == OP_AUTH:
                self.auth_token = aes.gcm_decrypt(self.session_key, bytes.fromhex(payload["nonce"]),
                                                  bytes.fromhex(payload["encAuthToken"]), self.challenge)
        else:
            raise HiChainError("Unexpected HiChain response")
        self.step = step + 1
        return False
