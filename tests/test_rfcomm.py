"""SDP lookup used for the direct RFCOMM connection."""

import os
import struct
import sys
import unittest
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "daemon"))

from watchbridge import rfcomm  # noqa: E402

HUAWEI_SPP_UUID = "82ff3820-8411-400c-b85a-55bdb32cf060"  # as in bluez.py (needs dbus to import)


def seq_(*items):
    body = b"".join(items)
    if len(body) < 256:
        return b"\x35" + bytes([len(body)]) + body
    return b"\x36" + struct.pack(">H", len(body)) + body


def u16(v):
    return b"\x09" + struct.pack(">H", v)


def u8(v):
    return b"\x08" + bytes([v])


def uuid16(v):
    return b"\x19" + struct.pack(">H", v)


def uuid128(s):
    return b"\x1c" + uuid.UUID(s).bytes


def text(s):
    b = s.encode()
    return b"\x25" + bytes([len(b)]) + b


def huawei_record(channel):
    return seq_(
        u16(0x0000), b"\x0a\x00\x01\x00\x0b",                      # record handle
        u16(0x0001), seq_(uuid128(HUAWEI_SPP_UUID)),               # service class ids
        u16(0x0004), seq_(seq_(uuid16(0x0100)), seq_(uuid16(0x0003), u8(channel))),
        u16(0x0100), text("HUAWEI WATCH SPP"),
    )


class FakeSdpSocket:
    """Answers ServiceSearchAttributeRequests, splitting the answer in `chunks` parts."""

    def __init__(self, attribute_lists, chunks=1):
        self.data = attribute_lists
        self.chunks = chunks
        self.sent = []
        self._replies = []

    def send(self, pdu):
        self.sent.append(pdu)
        pid, tid, _ = struct.unpack(">BHH", pdu[:5])
        assert pid == 0x06
        assert uuid.UUID(HUAWEI_SPP_UUID).bytes in pdu
        # our continuation state is a one-byte offset, the first request has none
        offset = 0 if pdu.endswith(b"\x00") else pdu[-1]
        part = (len(self.data) + self.chunks - 1) // self.chunks
        chunk = self.data[offset:offset + part]
        nxt = offset + len(chunk)
        cont = b"\x00" if nxt >= len(self.data) else b"\x01" + bytes([nxt])
        params = struct.pack(">H", len(chunk)) + chunk + cont
        self._replies.append(struct.pack(">BHH", 0x07, tid, len(params)) + params)

    def recv(self, n):
        return self._replies.pop(0)

    def close(self):
        pass


class TestSdp(unittest.TestCase):
    def lookup(self, fake):
        orig = rfcomm._connect_l2cap
        rfcomm._connect_l2cap = lambda address, psm, timeout: fake
        try:
            return rfcomm.find_channel("AA:BB:CC:DD:EE:FF", HUAWEI_SPP_UUID)
        finally:
            rfcomm._connect_l2cap = orig

    def test_finds_rfcomm_channel(self):
        self.assertEqual(self.lookup(FakeSdpSocket(seq_(huawei_record(7)))), 7)

    def test_continuation_state(self):
        fake = FakeSdpSocket(seq_(huawei_record(12)), chunks=3)
        self.assertEqual(self.lookup(fake), 12)
        self.assertEqual(len(fake.sent), 3)

    def test_service_missing(self):
        with self.assertRaises(rfcomm.RfcommError):
            self.lookup(FakeSdpSocket(b""))

    def test_bdaddr_is_little_endian(self):
        self.assertEqual(rfcomm._bdaddr("AA:BB:CC:DD:EE:01"), bytes([0x01, 0xEE, 0xDD, 0xCC, 0xBB, 0xAA]))


if __name__ == "__main__":
    unittest.main()
