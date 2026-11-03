# WatchBridge - Huawei Watch GT 5 companion for Sailfish OS
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# Ported from Gadgetbridge (HuaweiTLV.java), Copyright (C) 2024 Damien Gaignon,
# Martin.JM, Vitalii Tomin.
# Translated to Python and modified for WatchBridge, 2026. See NOTICE.md.
"""Huawei tag/length/value container with 7-bit big-endian varint lengths."""

import struct

TAG_ENCRYPTION = 0x7C
TAG_IV = 0x7D
TAG_CIPHERTEXT = 0x7E
TAG_RESULT = 0x7F


class MissingTagError(KeyError):
    def __init__(self, tag):
        super().__init__("Missing tag: 0x%02x" % tag)
        self.tag = tag


class TLVParseError(ValueError):
    pass


def varint_encode(value):
    out = [value & 0x7F]
    value >>= 7
    while value:
        out.append((value & 0x7F) | 0x80)
        value >>= 7
    return bytes(reversed(out))


def varint_decode(buf, offset):
    """Returns (value, size)."""
    result = 0
    start = offset
    while True:
        if offset >= len(buf):
            raise TLVParseError("Truncated varint")
        b = buf[offset]
        result = (result << 7) | (b & 0x7F)
        offset += 1
        if not b & 0x80:
            return result, offset - start


class TLV:
    def __init__(self, items=None):
        self.items = list(items or [])  # list of (tag, bytes)

    # --- building -------------------------------------------------------
    def put(self, tag, value=None):
        """Mirror of the HuaweiTLV.put overloads. Ints must use the typed helpers."""
        if value is None:
            value = b""
        elif isinstance(value, TLV):
            value = value.serialize()
        elif isinstance(value, bool):
            value = b"\x01" if value else b"\x00"
        elif isinstance(value, str):
            value = value.encode("utf-8")
        elif isinstance(value, int):
            raise TypeError("Use put_byte/put_short/put_int/put_long for integers")
        self.items.append((tag & 0xFF, bytes(value)))
        return self

    def put_byte(self, tag, value):
        return self.put(tag, bytes([value & 0xFF]))

    def put_short(self, tag, value):
        return self.put(tag, struct.pack(">H", value & 0xFFFF))

    def put_int(self, tag, value):
        return self.put(tag, struct.pack(">I", value & 0xFFFFFFFF))

    def put_long(self, tag, value):
        return self.put(tag, struct.pack(">Q", value & 0xFFFFFFFFFFFFFFFF))

    # --- (de)serialisation ------------------------------------------------
    def serialize(self):
        out = bytearray()
        for tag, value in self.items:
            out.append(tag)
            out += varint_encode(len(value))
            out += value
        return bytes(out)

    @classmethod
    def parse(cls, buf, offset=0, length=None):
        buf = bytes(buf)
        if length is None:
            length = len(buf) - offset
        end = offset + length
        tlv = cls()
        pos = offset
        while pos < end:
            tag = buf[pos]
            pos += 1
            # An extra null byte may trail encrypted content; ignore it
            if pos == end and tag == 0:
                break
            size, n = varint_decode(buf, pos)
            pos += n
            if size > end - pos:
                raise TLVParseError("TLV element size %d exceeds remaining %d" % (size, end - pos))
            tlv.items.append((tag, buf[pos:pos + size]))
            pos += size
        return tlv

    # --- access -----------------------------------------------------------
    def contains(self, tag):
        return any(t == tag for t, _ in self.items)

    def get_bytes(self, tag, default=MissingTagError):
        for t, v in self.items:
            if t == tag:
                return v
        if default is MissingTagError:
            raise MissingTagError(tag)
        return default

    def get_byte(self, tag, default=MissingTagError):
        v = self.get_bytes(tag, None)
        if v is None or len(v) == 0:
            if default is MissingTagError:
                raise MissingTagError(tag)
            return default
        return v[0]

    def get_signed_byte(self, tag):
        b = self.get_byte(tag)
        return b - 256 if b > 127 else b

    def get_bool(self, tag, default=MissingTagError):
        v = self.get_byte(tag, None)
        if v is None:
            if default is MissingTagError:
                raise MissingTagError(tag)
            return default
        return v == 1

    def get_short(self, tag):
        return struct.unpack(">H", self.get_bytes(tag)[:2])[0]

    def get_int(self, tag, default=MissingTagError):
        v = self.get_bytes(tag, None)
        if v is None or len(v) < 4:
            if default is MissingTagError:
                raise MissingTagError(tag)
            return default
        return struct.unpack(">I", v[:4])[0]

    def get_as_int(self, tag, default=MissingTagError):
        """Big-endian unsigned integer of whatever width the value has."""
        v = self.get_bytes(tag, None)
        if v is None or len(v) == 0 or len(v) > 8:
            if default is MissingTagError:
                raise MissingTagError(tag)
            return default
        return int.from_bytes(v, "big")

    def get_string(self, tag, default=MissingTagError):
        v = self.get_bytes(tag, None)
        if v is None:
            if default is MissingTagError:
                raise MissingTagError(tag)
            return default
        return v.decode("utf-8", errors="replace")

    def get_object(self, tag):
        return TLV.parse(self.get_bytes(tag))

    def get_objects(self, tag):
        return [TLV.parse(v) for t, v in self.items if t == tag]

    def __eq__(self, other):
        return isinstance(other, TLV) and self.items == other.items

    def __len__(self):
        return len(self.serialize())

    def __repr__(self):
        if not self.items:
            return "TLV(empty)"
        return "TLV(" + ", ".join("%02x:%s" % (t, v.hex()) for t, v in self.items) + ")"
