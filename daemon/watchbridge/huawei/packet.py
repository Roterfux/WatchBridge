# WatchBridge - Huawei Watch GT 5 companion for Sailfish OS
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# Ported from Gadgetbridge (HuaweiPacket.java, CheckSums.java), Copyright (C)
# 2015-2025 Andreas Shimokawa, Carsten Pfeiffer, Damien Gaignon, Daniele Gobbetti,
# José Rebelo, Martin.JM, Petr Vaněk, vappster.
# Translated to Python and modified for WatchBridge, 2026. See NOTICE.md.
"""Huawei link framing: 0x5A magic, length, slicing, CRC16 and TLV encryption."""

import logging
import math
import struct

from . import crypto
from .tlv import TLV, TAG_ENCRYPTION, TAG_IV, TAG_CIPHERTEXT

log = logging.getLogger(__name__)

HUAWEI_MAGIC = 0x5A

# (service, command) pairs whose payload is not TLV encoded
_RAW_PAYLOADS = {(0x0A, 0x05), (0x28, 0x06), (0x2C, 0x05), (0x1C, 0x05)}


class ParseError(Exception):
    pass


def crc16(data, crc=0x0000):
    for b in data:
        crc = ((crc >> 8) | (crc << 8)) & 0xFFFF
        crc ^= b
        crc ^= (crc & 0xFF) >> 4
        crc ^= (crc << 12) & 0xFFFF
        crc ^= ((crc & 0xFF) << 5) & 0xFFFF
    return crc & 0xFFFF


class Params:
    """Link parameters negotiated with the watch (HuaweiPacket.ParamsProvider)."""

    def __init__(self):
        self.auth_version = 0
        self.device_support_type = 0
        self.secret_key = None
        self.slice_size = 0xF4
        self.transactions_crypted = True
        self.mtu = 65535
        self.encryption_counter = 0
        self.pin_code = None
        self.interval = 0
        self.auth_algo = 0
        self.encrypt_method = 0
        self.first_key = None
        self.auth_mode = 0

    def use_gcm(self):
        return self.encrypt_method == 0x01 or self.device_support_type == 0x04

    def get_iv(self):
        if self.device_support_type == 0x04:
            return crypto.generate_nonce()
        iv, self.encryption_counter = crypto.initialization_vector(self.encryption_counter)
        return iv


def encrypt_raw(params, data, iv=None):
    if iv is None:
        iv = params.get_iv()
    ct = crypto.encrypt(params.use_gcm(), data, params.secret_key, iv)
    return TLV().put_byte(TAG_ENCRYPTION, 0x01).put(TAG_IV, iv).put(TAG_CIPHERTEXT, ct)


def decrypt_tlv(params, tlv):
    plain = crypto.decrypt(params.use_gcm(), tlv.get_bytes(TAG_CIPHERTEXT), params.secret_key, tlv.get_bytes(TAG_IV))
    return TLV.parse(plain)


class Packet:
    """An outgoing (or decoded incoming) service/command message."""

    def __init__(self, service, command, tlv=None, encrypt=True, sliced=True):
        self.service = service
        self.command = command
        self.tlv = tlv if tlv is not None else TLV()
        self.encrypt = encrypt
        self.sliced = sliced
        self.payload = None  # raw payload for non-TLV packets
        self.was_encrypted = False

    def __repr__(self):
        return "Packet(%02x/%02x, %r)" % (self.service, self.command, self.tlv)

    def serialize(self, params, iv=None):
        if self.encrypt and params.transactions_crypted:
            body = encrypt_raw(params, self.tlv.serialize(), iv).serialize()
        else:
            body = self.tlv.serialize()
        if self.sliced:
            return self._serialize_sliced(params, body)
        return self._serialize_unsliced(body)

    def _serialize_unsliced(self, body):
        frame = bytearray([HUAWEI_MAGIC])
        frame += struct.pack(">H", (2 + len(body) + 1) & 0xFFFF)
        frame += bytes([0x00, self.service, self.command])
        frame += body
        frame += struct.pack(">H", crc16(frame))
        return [bytes(frame)]

    def _serialize_sliced(self, params, body):
        header_len, body_header_len, footer_len = 5, 2, 2
        max_body = params.slice_size - header_len - footer_len
        count = int(math.ceil((len(body) + body_header_len) / float(max_body)))
        if count == 1:
            return self._serialize_unsliced(body)
        out = []
        pos = 0
        slice_flag = 0x01
        flag = 0
        for i in range(count):
            remaining = len(body) - pos
            packet_size = min(params.slice_size, remaining + header_len + footer_len)
            content_size = packet_size - header_len - footer_len
            frame = bytearray([HUAWEI_MAGIC])
            frame += struct.pack(">H", (packet_size - header_len) & 0xFFFF)
            if i == count - 1:
                slice_flag = 0x03
            frame += bytes([slice_flag, flag & 0xFF])
            flag += 1
            if slice_flag == 0x01:
                frame += bytes([self.service, self.command])
                slice_flag = 0x02
                content_size -= 2
            frame += body[pos:pos + content_size]
            pos += content_size
            frame += struct.pack(">H", crc16(frame))
            out.append(bytes(frame))
        return out


class StreamParser:
    """Reassembles frames from the RFCOMM byte stream into Packets."""

    def __init__(self, params):
        self.params = params
        self._partial = b""
        self._slices = None

    def reset(self):
        self._partial = b""
        self._slices = None

    def feed(self, data):
        """Feed received bytes, returns a list of complete Packets."""
        packets = []
        data = self._partial + bytes(data)
        self._partial = b""
        while data:
            try:
                consumed, packet = self._parse_one(data)
            except ParseError as e:
                log.warning("Dropping data after parse error: %s", e)
                self.reset()
                return packets
            if consumed == 0:
                self._partial = data
                break
            data = data[consumed:]
            if packet is not None:
                packets.append(packet)
        return packets

    def _parse_one(self, data):
        if data[0] != HUAWEI_MAGIC:
            raise ParseError("Magic mismatch: 0x%02x" % data[0])
        if len(data) < 3:
            return 0, None
        expected = struct.unpack(">h", data[1:3])[0]
        if expected < 0:
            raise ParseError("Negative length")
        if expected + 2 > len(data) - 3:
            return 0, None
        slice_flag = data[3]
        add_len = 2 if slice_flag in (1, 2, 3) else 1
        payload = data[3 + add_len:3 + expected]
        checksum = struct.unpack(">H", data[3 + expected:5 + expected])[0]
        consumed = 5 + expected
        if crc16(data[:3 + expected]) != checksum:
            raise ParseError("Checksum mismatch")

        if slice_flag in (1, 2, 3):
            self._slices = (self._slices or b"") + payload
            if slice_flag != 3:
                return consumed, None
            payload = self._slices
            self._slices = None

        if len(payload) < 2:
            raise ParseError("Payload too short")
        packet = Packet(payload[0], payload[1], encrypt=False)
        if (packet.service, packet.command) in _RAW_PAYLOADS:
            packet.payload = payload
            return consumed, packet
        packet.tlv = TLV.parse(payload, 2, len(payload) - 2)
        if self.params.secret_key is not None and packet.tlv.contains(TAG_ENCRYPTION) \
                and packet.tlv.get_bool(TAG_ENCRYPTION):
            try:
                packet.tlv = decrypt_tlv(self.params, packet.tlv)
                packet.was_encrypted = True
            except Exception as e:  # noqa: BLE001 - skip just this frame
                log.warning("Could not decrypt %02x/%02x: %s", packet.service, packet.command, e)
                return consumed, None
        return consumed, packet
