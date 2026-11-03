"""Protocol tests. Packet vectors are taken from Gadgetbridge's unit tests."""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "daemon"))

from watchbridge.huawei import aes, crypto  # noqa: E402
from watchbridge.huawei.packet import Packet, Params, StreamParser, crc16  # noqa: E402
from watchbridge.huawei.tlv import TLV, varint_decode, varint_encode  # noqa: E402
from watchbridge.huawei import commands  # noqa: E402

H = bytes.fromhex


def zero_params(crypted=True, slice_size=0xF4):
    p = Params()
    p.secret_key = bytes(16)
    p.transactions_crypted = crypted
    p.slice_size = slice_size
    return p


class TestAES(unittest.TestCase):
    def test_fips197(self):
        pt = H("00112233445566778899aabbccddeeff")
        for key, ct in (
            ("000102030405060708090a0b0c0d0e0f", "69c4e0d86a7b0430d8cdb78070b4c55a"),
            ("000102030405060708090a0b0c0d0e0f1011121314151617", "dda97ca4864cdfe06eaf70a0ec0d7191"),
            ("000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f", "8ea2b7ca516745bfeafc49904b496089"),
        ):
            a = aes.AES(H(key))
            self.assertEqual(a.encrypt_block(pt), H(ct))
            self.assertEqual(a.decrypt_block(H(ct)), pt)

    def test_gcm_vectors(self):
        # McGrew & Viega GCM spec, test cases 2, 3 and 6 (60 byte IV)
        self.assertEqual(aes.gcm_encrypt(bytes(16), bytes(12), bytes(16)),
                         H("0388dace60b6a392f328c2b971b2fe78ab6e47d42cec13bdf53a67b21257bddf"))
        k = H("feffe9928665731c6d6a8f9467308308")
        p = H("d9313225f88406e5a55909c5aff5269a86a7a9531534f7da2e4c303d8a318a72"
              "1c3c0c95956809532fcf0e2449a6b525b16aedf5aa0de657ba637b391aafd255")
        self.assertEqual(aes.gcm_encrypt(k, H("cafebabefacedbaddecaf888"), p),
                         H("42831ec2217774244b7221b784d0d49ce3aa212f2c02a4e035c17e2329aca12e"
                           "21d514b25466931c7d8f6a5aac84aa051ba30b396a0aac973d58e091473f5985"
                           "4d5c2af327cd64a62cf35abd2ba6fab4"))
        iv6 = H("9313225df88406e555909c5aff5269aa6a7a9538534f7da1e4c303d2a318a728"
                "c3c0c95156809539fcf0e2429a6b525416aedbf5a0de6a57a637b39b")
        aad = H("feedfacedeadbeeffeedfacedeadbeefabaddad2")
        out = aes.gcm_encrypt(k, iv6, p[:60], aad)
        self.assertEqual(out[-16:], H("619cc5aefffe0bfa462af43c1699d050"))
        self.assertEqual(aes.gcm_decrypt(k, iv6, out, aad), p[:60])
        with self.assertRaises(aes.AuthenticationError):
            aes.gcm_decrypt(k, iv6, out[:-1] + b"\x00", aad)

    def test_cbc_roundtrip(self):
        for n in (0, 1, 15, 16, 17, 100):
            data = os.urandom(n)
            self.assertEqual(aes.cbc_decrypt(bytes(16), bytes(16), aes.cbc_encrypt(bytes(16), bytes(16), data)), data)


class TestTLV(unittest.TestCase):
    def test_varint(self):
        for v in (0, 1, 127, 128, 300, 16383, 16384, 65535):
            enc = varint_encode(v)
            self.assertEqual(varint_decode(enc, 0), (v, len(enc)))
        self.assertEqual(varint_encode(128), b"\x81\x00")

    def test_roundtrip(self):
        t = TLV().put(0x01).put_short(0x02, 0x1234).put(0x81, TLV().put(0x03, "abc")).put(0x04, b"x" * 200)
        self.assertEqual(TLV.parse(t.serialize()), t)
        self.assertEqual(t.get_object(0x81).get_string(0x03), "abc")


class TestPacket(unittest.TestCase):
    def test_crc(self):
        self.assertEqual(crc16(H("5a000700 7f7f01020304".replace(" ", ""))), 0x40B6)

    def test_unencrypted_unsliced(self):
        p = Packet(0x01, 0x02, TLV().put_int(0x03, 0x05060708), encrypt=False, sliced=False)
        self.assertEqual(p.serialize(zero_params()), [H("5a0009000102030405060708a4f0")])

    def test_encrypted_unsliced(self):
        p = Packet(0x01, 0x02, TLV().put_int(0x03, 0x05060708), sliced=False)
        self.assertEqual(p.serialize(zero_params(), iv=bytes(16)), [H(
            "5a002a0001027c01017d1000000000000000000000000000000000"
            "7e103b89fc79d9055eed5235fe16a08a4d5393c7")])

    def test_unencrypted_sliced(self):
        t = TLV()
        for tag in (1, 2, 3, 4):
            t.put_int(tag, 0)
        out = Packet(0x01, 0x02, t, encrypt=False).serialize(zero_params(False, 0x10))
        self.assertEqual(out, [H("5a000b0100010201040000000002cc98"),
                               H("5a000b0201040000000003040000fad3"),
                               H("5a000a03020000040400000000 37ca".replace(" ", ""))])
        parsed = StreamParser(zero_params(False, 0x10)).feed(b"".join(out))
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0].tlv, t)

    def test_notification_state_request(self):
        pkt = commands.notification_state(True)
        self.assertEqual(pkt.serialize(zero_params(), iv=bytes(16)), [H(
            "5a002a0002047c01017d1000000000000000000000000000000000"
            "7e10d9c4aa7da35c42ab2dc2e773c04c975a4123")])

    def test_parse_encrypted_find_phone(self):
        data = H("5a002a000b017c01017d10000000000000000000000000000000007e10"
                 "2800996f2acb623ae6542854f8ab5483f4f4")
        parser = StreamParser(zero_params())
        # feed in awkward chunks to exercise reassembly
        pkts = parser.feed(data[:5]) + parser.feed(data[5:20]) + parser.feed(data[20:])
        self.assertEqual(len(pkts), 1)
        self.assertEqual((pkts[0].service, pkts[0].command), (0x0B, 0x01))
        self.assertTrue(pkts[0].was_encrypted)
        self.assertEqual(pkts[0].tlv, TLV().put(0x01, False))

    def test_parse_concatenated(self):
        frame = H("5a000700 7f7f01020304 40b6".replace(" ", ""))
        pkts = StreamParser(zero_params()).feed(frame * 3)
        self.assertEqual(len(pkts), 3)
        self.assertEqual(pkts[2].tlv.get_short(0x01), 0x0304)

    def test_gcm_packet_roundtrip(self):
        p = zero_params()
        p.device_support_type = 4
        p.secret_key = os.urandom(32)
        t = TLV().put(0x01, "hello").put_byte(0x02, 7)
        frames = Packet(0x0F, 0x01, t).serialize(p)
        pkts = StreamParser(p).feed(b"".join(frames))
        self.assertEqual(pkts[0].tlv, t)


class TestNotificationPacket(unittest.TestCase):
    def test_action_request_tlv(self):
        pkt = commands.notification(
            msg_id=1, notification_type=0x02, title="Title", sender="Sender", body="Body",
            source_app_id="SourceApp", encoding=0x02, params=None)
        expected = TLV().put_short(0x01, 1).put_byte(0x02, 0x02).put(0x03, True).put(
            0x84, TLV().put(0x8C, TLV()
                            .put(0x8D, TLV().put_byte(0x0E, 3).put_byte(0x0F, 2).put(0x10, "Title"))
                            .put(0x8D, TLV().put_byte(0x0E, 2).put_byte(0x0F, 2).put(0x10, "Sender"))
                            .put(0x8D, TLV().put_byte(0x0E, 1).put_byte(0x0F, 2).put(0x10, "Body")))
        ).put(0x11, "SourceApp")
        self.assertEqual(pkt.tlv, expected)


class TestHiChainResponse(unittest.TestCase):
    def test_nul_terminated_json_from_real_watch(self):
        # Captured from a Watch GT 5: the JSON in tag 0x01 ends with a NUL byte
        from watchbridge.huawei.hichain import HiChain
        body = b'{"authForm":0,"payload":{"isoSalt":"80","token":"45","peerAuthId":"41","peerUserType":0,' \
               b'"operationCode":1},"message":32769}\x00'
        tlv = TLV().put(0x01, body).put_byte(0x02, 1).put_byte(0x04, 0x00).put_byte(0x05, 0x00)
        step, payload, error = HiChain.parse_response(tlv)
        self.assertEqual((step, error, payload["isoSalt"]), (1, 0, "80"))


if __name__ == "__main__":
    unittest.main()
