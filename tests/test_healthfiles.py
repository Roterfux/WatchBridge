"""Step 2 of the health sync: 0x2C file download, TruSleep sequence data and stress files."""

import csv
import os
import socket
import struct
import sys
import tempfile
import threading
import time
import unittest

sys.path.insert(0, os.path.dirname(__file__))
import stubs  # noqa: E402,F401

from watchbridge.health import HealthStore  # noqa: E402
from watchbridge.huawei import device as D  # noqa: E402
from watchbridge.huawei import filedownload as FDL  # noqa: E402
from watchbridge.huawei import healthfiles as HF  # noqa: E402
from watchbridge.huawei.packet import Params, encrypt_raw  # noqa: E402
from watchbridge.huawei.tlv import TLV  # noqa: E402
from fake_watch import FakeWatch  # noqa: E402

NIGHT = 1793750400  # some 23:00
BLOCK = 100  # file block size of the simulated watch (bursts are 100 bytes too)
SCORE, FALL_ASLEEP, WAKEUP, VALID, AVG_HR, MIN_SPO2 = 700013245, 700013686, 700013156, 700013786, 700013580, 700013340


def summary_tlv(fields):
    """Sleep summary TLV: containers of (dictionary id, data type, value)."""
    inner = TLV()
    for dict_id, (data_type, value) in fields.items():
        inner.put(0x82, TLV().put_int(0x03, dict_id).put_byte(0x04, data_type).put(0x05, value))
    return TLV().put(0x81, inner).serialize()


def details(*records):
    return b"".join(struct.pack("<iB3x", seconds, stage) for seconds, stage in records)


def sequence_file(*records):
    body = b""
    for start, end, summary, detail in records:
        body += struct.pack(">IIbbhi", start, end, 1, 2, len(summary), len(detail)) + bytes(16) + summary + detail
    return struct.pack(">IIhh", len(body), HF.SLEEP_DETAILS_CLASS, 1, 1) + bytes(20) + body


def night_file():
    summary = summary_tlv({
        FALL_ASLEEP: (3, struct.pack(">Q", NIGHT + 600)),
        WAKEUP: (3, struct.pack(">Q", NIGHT + 600 + 7 * 3600)),
        VALID: (1, b"\x01"),
        SCORE: (1, b"\x52"),                                     # 82
        AVG_HR: (1, b"\x38"),                                    # 56 bpm
        MIN_SPO2: (6, struct.pack(">d", 93.5)),
        700013999: (1, b"\x07"),                                 # unknown id: ignored
    })
    stages = details((5400, 1), (1800, 1), (3600, 3), (1200, 2), (600, 4), (12600, 1), (0, 1), (59, 2))
    return sequence_file((NIGHT, NIGHT + 8 * 3600, summary, stages))


def stress_file(*records):
    out = struct.pack(">qhh", 0, 0, 3) + bytes(36)
    for start, end, score, level in records:
        out += struct.pack(">IIiBBBBBB", start, end, 1, score, level, 0, 0, 0, 0) + bytes(48)
    return out


class TestParsers(unittest.TestCase):
    def test_sleep_file(self):
        (session,) = HF.parse_sleep_file(night_file())
        self.assertEqual(session["summary"], {"fall_asleep": NIGHT + 600, "wakeup_time": NIGHT + 600 + 7 * 3600,
                                              "valid_data": 1, "score": 82, "avg_heart_rate": 56, "min_spo2": 93.5})
        self.assertEqual(session["start"], NIGHT + 600)
        t = NIGHT + 600
        # Consecutive light periods merge; invalid records (0 s, not a whole minute) are skipped
        self.assertEqual(session["stages"], [(t, t + 7200, "light"), (t + 7200, t + 10800, "deep"),
                                             (t + 10800, t + 12000, "rem"), (t + 12000, t + 12600, "awake"),
                                             (t + 12600, t + 25200, "light")])

    def test_invalid_night_drops_unreliable_fields(self):
        summary = HF.parse_sleep_summary(summary_tlv({SCORE: (1, b"\x63"), AVG_HR: (1, b"\x40")}))
        self.assertEqual(summary, {"avg_heart_rate": 64})  # no valid_data: score is random on some watches

    def test_float_minus_one_means_missing(self):
        self.assertEqual(HF.parse_sleep_summary(summary_tlv({VALID: (1, b"\x01"), SCORE: (1, b"\xbf\x80\x00\x00")})),
                         {"valid_data": 1})

    def test_stress_file(self):
        data = stress_file((NIGHT + 7200, NIGHT + 7260, 41, 2), (0, 5, 1, 1), (NIGHT, NIGHT + 60, 25, 1))
        self.assertEqual(HF.parse_stress_file(data), [(NIGHT, NIGHT + 60, 25, 1), (NIGHT + 7200, NIGHT + 7260, 41, 2)])

    def test_stress_file_other_version(self):
        self.assertEqual(HF.parse_stress_file(struct.pack(">qhh", 0, 0, 2) + bytes(36 + 66)), [])

    def test_decode_block_plain_and_encrypted(self):
        params = Params()
        params.secret_key = bytes(16)
        raw = bytes([3]) + struct.pack(">I", 600) + b"\x00" + b"hello"
        self.assertEqual(FDL.decode_block(b"\x2c\x05" + raw, params), (3, 600, b"hello"))
        enc = encrypt_raw(params, raw).serialize()
        self.assertEqual(FDL.decode_block(b"\x2c\x05" + enc, params), (3, 600, b"hello"))

    def test_init_request_carries_dictionary_id(self):
        t = FDL.init_request(FDL.SEQUENCE_DATA_NAME, FDL.FileType.SEQUENCE_DATA, 1, 2, HF.SLEEP_DETAILS_CLASS).tlv
        self.assertEqual((t.get_string(0x01), t.get_byte(0x02), t.get_int(0x05), t.get_int(0x06), t.get_int(0x0C)),
                         ("sequence_data", 0x16, 1, 2, 700013))
        self.assertFalse(FDL.init_request(FDL.RRI_NAME, FDL.FileType.RRI, 1, 2, 700013).tlv.contains(0x0C))


class Recorder(D.Listener):
    def __init__(self):
        self.connected = threading.Event()
        self.health = threading.Event()
        self.result = None

    def on_state(self, state, detail=""):
        if state == D.STATE_CONNECTED:
            self.connected.set()

    def on_health_data(self, result):
        self.result = result
        self.health.set()


class TestFileSync(unittest.TestCase):
    def sync(self, files):
        phone_sock, watch_sock = socket.socketpair()
        watch = FakeWatch(watch_sock, files=files, file_block=BLOCK).start()
        rec = Recorder()
        dev = D.HuaweiWatch(phone_sock, "AA:BB:CC:DD:EE:FF", D.DeviceStore({}, lambda: None), rec)
        self.addCleanup(dev.stop)
        self.addCleanup(watch_sock.close)
        dev.start()
        self.assertTrue(rec.connected.wait(10))
        # Start times as the service computes them (time.time() based floats)
        dev.sync_health(NIGHT - 86400.5, NIGHT - 86400.5, NIGHT - 86400.5, NIGHT - 86400.5)
        self.assertTrue(rec.health.wait(15))
        return rec.result, watch

    def test_sleep_and_stress_files(self):
        sleep = night_file()
        stress = stress_file(*[(NIGHT + 600 * i, NIGHT + 600 * i + 60, 20 + i, 1) for i in range(10)])
        self.assertGreater(len(sleep), 2 * BLOCK)  # several RequestBlocks
        r, watch = self.sync({"sequence_data": sleep, "rrisqi_data.bin": stress})
        self.assertEqual(r["error"], "")
        self.assertEqual(r["file_errors"], [])
        self.assertEqual(r["sleep_sessions"][0]["summary"]["score"], 82)
        self.assertEqual(len(r["stress"]), 10)
        commands = [c for c, _ in watch.file_requests]
        self.assertEqual(commands.count(0x01), 2)                 # one init per file
        self.assertEqual(commands.count(0x06), 2)                 # and one complete
        self.assertEqual(commands.count(0x04), -(-len(sleep) // BLOCK) - (-len(stress) // BLOCK))
        init = watch.file_requests[0][1]
        self.assertEqual(init.get_int(0x0C), HF.SLEEP_DETAILS_CLASS)

    def test_missing_file_is_reported_not_fatal(self):
        r, _ = self.sync({"rrisqi_data.bin": stress_file((NIGHT, NIGHT + 60, 30, 1))})
        self.assertEqual(r["error"], "")
        self.assertEqual(len(r["file_errors"]), 1)
        self.assertIn("sleep", r["file_errors"][0])
        self.assertEqual(r["stress"], [(NIGHT, NIGHT + 60, 30, 1)])


class TestStore(unittest.TestCase):
    def test_trusleep_night_stress_and_csv(self):
        folder = tempfile.mkdtemp()
        store = HealthStore(folder)
        self.addCleanup(store.close)
        sessions = HF.parse_sleep_file(night_file())
        stress = [(NIGHT + 36000, NIGHT + 36060, 30, 1), (NIGHT + 39600, NIGHT + 39660, 50, 2)]
        # A basic "sleep" period in the same night must not be added on top of the stages
        basic = [(NIGHT + 3600, NIGHT + 7200, 0x06)]
        counts = store.add_sync_result({"samples": [], "sleep": basic, "sleep_sessions": sessions,
                                        "stress": stress, "totals": None, "end": NIGHT + 40000})
        self.assertEqual((counts["sleepSessions"], counts["stress"]), (1, 2))
        day = time.strftime("%Y-%m-%d", time.localtime(NIGHT + 8 * 3600))
        night = store.day_summary(day)["sleep"]
        self.assertEqual(night["source"], "trusleep")
        self.assertEqual(night["minutes"], 410)                   # 7 h minus 10 min awake
        self.assertEqual((night["byType"]["awake"], night["byType"]["rem"], night["score"]), (10, 20, 82))
        self.assertEqual(store.last_sleep_session_end(), NIGHT + 600 + 7 * 3600)
        stress_day = store.day_summary(time.strftime("%Y-%m-%d", time.localtime(NIGHT + 39660)))["stress"]
        self.assertEqual((stress_day["avg"], stress_day["max"]), (40, 50))
        with open(os.path.join(folder, "sleep-sessions.csv"), encoding="utf-8") as f:
            row = next(csv.DictReader(f))
        self.assertEqual((row["score"], row["avg_heart_rate"], row["minutes"]), ("82", "56", "420"))
        with open(os.path.join(folder, "stress.csv"), encoding="utf-8") as f:
            self.assertEqual(len(list(csv.reader(f))), 3)
        # Downloading the same night again replaces its stages instead of adding
        store.add_sync_result({"samples": [], "sleep": [], "sleep_sessions": sessions, "totals": None,
                               "end": NIGHT + 40000})
        self.assertEqual(store.day_summary(day)["sleep"]["minutes"], 410)


if __name__ == "__main__":
    unittest.main()
