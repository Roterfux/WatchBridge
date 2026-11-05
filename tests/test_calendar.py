"""Calendar sync: Sailfish's calendar service, the file format and the exchange with the watch."""

import json
import os
import socket
import struct
import sys
import threading
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "daemon"))
sys.path.insert(0, os.path.dirname(__file__))

import stubs  # noqa: E402,F401
from watchbridge import phonecalendar as PC  # noqa: E402
from watchbridge.huawei import device as D  # noqa: E402
from watchbridge.huawei import p2p as P2P  # noqa: E402
from watchbridge.huawei import p2pcalendar as C  # noqa: E402
from watchbridge.huawei.tlv import TLV  # noqa: E402
from fake_watch import FakeWatch  # noqa: E402


def fields(instance="abc@example.com", start="2026-11-06T09:00:00+01:00", end="2026-11-06T10:00:00+01:00",
           all_day=False, color="#ff8000", title="Dentist", description="", location="", cancelled=False):
    return ("", instance, start, end, all_day, color, title, description, location, cancelled)


def event(n=1, start=1800000000000, title="Event", **kw):
    e = {"id": n, "start": start, "end": start + 3600000, "all_day": False, "color": -1, "title": title,
         "description": "", "location": ""}
    e.update(kw)
    return e


def request(major="M", minor=5, count=100, mode=2, days=7):
    return {"mode": mode, "major": major, "minor": minor, "count": count, "days": days}


def documents(content):
    flag = struct.unpack(">I", content[:4])[0]
    pos, docs = 4, []
    while pos < len(content):
        size = struct.unpack(">I", content[pos:pos + 4])[0]
        docs.append(json.loads(content[pos + 4:pos + 4 + size].decode("utf-8")))
        pos += 4 + size
    return flag, docs


class TestPhoneEvents(unittest.TestCase):
    def test_timed_event_in_utc_and_with_offset(self):
        a = PC.parse_event(fields(start="2026-11-06T08:00:00Z", end="2026-11-06T09:00:00Z"))
        b = PC.parse_event(fields())
        self.assertEqual(a["start"], b["start"])
        self.assertEqual(a["start"], 1793952000 * 1000)
        self.assertEqual(a["end"] - a["start"], 3600000)
        self.assertFalse(a["all_day"])

    def test_one_day_all_day_event_ends_at_the_next_midnight(self):
        e = PC.parse_event(fields(start="2026-11-06", end="2026-11-06", all_day=True))
        self.assertTrue(e["all_day"])
        self.assertEqual(time.localtime(e["start"] / 1000)[:6], (2026, 11, 6, 0, 0, 0))
        self.assertEqual(time.localtime(e["end"] / 1000)[:6], (2026, 11, 7, 0, 0, 0))

    def test_color_as_signed_argb(self):
        self.assertEqual(PC.parse_color("#ff8000"), 0xFFFF8000 - (1 << 32))
        self.assertEqual(PC.parse_color("rubbish"), 0)

    def test_cancelled_event_is_left_out(self):
        self.assertIsNone(PC.parse_event(fields(cancelled=True)))

    def test_occurrences_of_one_event_share_an_id(self):
        a = PC.parse_event(fields())
        b = PC.parse_event(fields(start="2026-11-13T09:00:00+01:00", end="2026-11-13T10:00:00+01:00"))
        self.assertEqual(a["id"], b["id"])
        self.assertNotEqual(a["start"], b["start"])

    def test_broken_event_does_not_stop_the_others(self):
        events = PC.parse_events([fields(start="yesterday-ish"), fields(instance="ok")])
        self.assertEqual(len(events), 1)


class FakeBus:
    def __init__(self):
        self.calls = []

    def add_signal_receiver(self, *a, **k):
        pass

    def call_async(self, service, path, iface, method, signature, args, reply, error, timeout=-1):
        self.calls.append((args, reply, error))


class TestReader(unittest.TestCase):
    def make(self):
        self.timers = []
        bus = FakeBus()
        reader = PC.PhoneCalendar(bus, lambda s, fn: self.timers.append(fn) or len(self.timers), lambda t: None)
        self.results = []
        reader.fetch(7, lambda events, error: self.results.append((events, error)))
        return bus, reader

    def test_range_is_seven_days_from_today(self):
        bus, _ = self.make()
        start, end = bus.calls[0][0]
        self.assertRegex(start, r"^\d{4}-\d\d-\d\d$")
        self.assertRegex(end, r"^\d{4}-\d\d-\d\d$")
        self.assertGreater(end, start)

    def test_only_our_transaction_counts(self):
        bus, reader = self.make()
        bus.calls[0][1]("99-1")
        reader._result("other-client", [fields(instance="theirs")])
        self.assertEqual(self.results, [])
        reader._result("99-1", [fields()])
        self.assertEqual(len(self.results), 1)
        self.assertEqual(len(self.results[0][0]), 1)

    def test_result_before_the_reply(self):
        bus, reader = self.make()
        reader._result("99-1", [fields()])
        bus.calls[0][1]("99-1")
        self.assertEqual(len(self.results[0][0]), 1)

    def test_no_answer(self):
        bus, reader = self.make()
        bus.calls[0][1]("99-1")
        self.timers[0]()
        self.assertIsNone(self.results[0][0])
        self.assertIn("did not answer", self.results[0][1])

    def test_service_error(self):
        bus, _ = self.make()
        bus.calls[0][2]("no such service")
        self.assertIsNone(self.results[0][0])

    def test_empty_transaction_means_a_bad_range(self):
        bus, _ = self.make()
        bus.calls[0][1]("")
        self.assertIsNone(self.results[0][0])


class TestP2PPackets(unittest.TestCase):
    def test_ping_has_no_fingerprints(self):
        t = P2P.ping(7, "in.huawei.calendar").tlv
        self.assertEqual((t.get_byte(0x01), t.get_short(0x02)), (1, 7))
        self.assertEqual(t.get_string(0x03), "com.huawei.health")
        self.assertEqual(t.get_string(0x04), "in.huawei.calendar")
        self.assertFalse(t.contains(0x05))
        self.assertFalse(t.contains(0x08))

    def test_data_has_fingerprints(self):
        t = P2P.data(8, C.MODULE, C.PACKAGE, C.FINGERPRINT, b"\x01\x01\x01\x01").tlv
        self.assertEqual(t.get_string(0x05), "UniteDeviceManagement")
        self.assertEqual(t.get_string(0x06), "SystemApp")
        self.assertEqual(t.get_bytes(0x07), b"\x01\x01\x01\x01")

    def test_ack_code_is_an_int(self):
        self.assertEqual(P2P.ack(9, "a", "b").tlv.get_bytes(0x08), b"\x00\x00\x00\xcf")

    def test_sequence_wraps_below_short_max(self):
        self.assertEqual(P2P.next_sequence(1), 2)
        self.assertEqual(P2P.next_sequence(0x7FFE - 1), 0)


class TestRequest(unittest.TestCase):
    def body(self, tlv):
        return bytes([1]) + tlv.serialize()

    def test_parses_all_fields(self):
        r = C.parse_request(self.body(TLV().put_byte(1, 2).put(2, " abc ").put_short(3, 12).put_short(4, 200)
                                      .put_byte(5, 14)))
        self.assertEqual(r, {"mode": 2, "major": "abc", "minor": 12, "count": 200, "days": 14})
        self.assertTrue(C.wants_events(r))

    def test_zero_bytes_are_no_version(self):
        r = C.parse_request(self.body(TLV().put_byte(1, 2).put(2, "\0" * 64).put_short(3, 0).put_short(4, 500)))
        self.assertEqual(r["major"], "")

    def test_days_default_to_a_week(self):
        r = C.parse_request(self.body(TLV().put_byte(1, 2).put(2, "").put_short(3, 0).put_short(4, 50)))
        self.assertEqual(r["days"], 7)
        self.assertTrue(C.wants_events(r))

    def test_missing_fields_or_other_modes_want_nothing(self):
        self.assertFalse(C.wants_events(C.parse_request(self.body(TLV().put_byte(1, 2)))))
        self.assertFalse(C.wants_events(request(mode=1)))
        self.assertFalse(C.wants_events(request(minor=-1)))

    def test_other_commands_are_no_request(self):
        self.assertIsNone(C.parse_request(bytes([3]) + TLV().put(1, "id").serialize()))
        self.assertIsNone(C.parse_request(b""))

    def test_minus_one_as_a_short(self):
        r = C.parse_request(self.body(TLV().put_byte(1, 2).put(2, "x").put(3, b"\xff\xff").put_short(4, 1)))
        self.assertEqual(r["minor"], -1)


class TestFile(unittest.TestCase):
    def test_truncate_like_gadgetbridge(self):
        self.assertEqual(C.truncate("short", 64), "short")
        self.assertEqual(C.truncate(None, 64), "")
        self.assertEqual(C.truncate("x" * 65, 64), "x" * 30 + "...")
        self.assertEqual(C.truncate("é" * 40, 64), "é" * 15 + "...")      # 30 bytes of two-byte letters
        self.assertEqual(C.truncate("é" * 40 + "a", 65), "é" * 15 + "...")  # never half a letter

    def test_empty_file(self):
        flag, docs = documents(C.file_content("M", 0, [], True))
        self.assertEqual(flag, 0)
        self.assertEqual(docs, [{"major": "M", "minor": 0, "scheduleList": []}])

    def test_chunks_of_ten_and_their_minor_numbers(self):
        schedule = [C.event_json(event(i), C.OPERATION_ADD) for i in range(25)]
        flag, docs = documents(C.file_content("M", 9, schedule, False))
        self.assertEqual(flag, 1)
        self.assertEqual([len(d["scheduleList"]) for d in docs], [10, 10, 5])
        self.assertEqual([d["minor"] for d in docs], [10, 30, 45])  # size * (index + 1), added up

    def test_event_fields(self):
        j = C.event_json(event(5, title="Zahnarzt ü", all_day=True, color=-32768), C.OPERATION_UPDATE)
        self.assertEqual(j["event_id"], "5")
        self.assertEqual(j["event_uuid"], "5_1800000000000")
        self.assertEqual((j["all_day"], j["operation"], j["state"], j["has_alarm"]), (1, 3, -1, 0))
        self.assertEqual(j["calendar_color"], -32768)
        self.assertEqual(documents(C.file_content("M", 0, [j], True))[1][0]["scheduleList"][0]["title"], "Zahnarzt ü")

    def test_deleted_event_carries_only_its_ids(self):
        j = C.deleted_json(event(5))
        self.assertEqual((j["operation"], j["state"], j["dtstart"], j["title"]), (2, 0, 0, ""))
        self.assertEqual(j["event_uuid"], "5_1800000000000")


class TestBuild(unittest.TestCase):
    def test_first_sync_sends_everything(self):
        s = C.CalendarSync("phone")
        flag, docs = documents(s.build(request(major="", minor=0), [event(1), event(2)]))
        self.assertEqual(flag, 0)
        self.assertEqual(docs[0]["major"], "phone")
        self.assertEqual(len(docs[0]["scheduleList"]), 2)
        self.assertEqual(s.count, 2)

    def test_after_a_reconnect_the_watch_is_emptied_first(self):
        s = C.CalendarSync("phone")
        flag, docs = documents(s.build(request(minor=5), [event(1)]))
        self.assertEqual((flag, docs[0]["minor"], docs[0]["scheduleList"]), (0, 0, []))
        self.assertTrue(s.wants_full_sync)
        flag, docs = documents(s.build(request(minor=0), [event(1)]))
        self.assertEqual(len(docs[0]["scheduleList"]), 1)
        self.assertFalse(s.wants_full_sync)

    def test_no_endless_emptying_when_the_watch_keeps_its_version(self):
        s = C.CalendarSync("phone")
        s.build(request(minor=5), [event(1)])
        _, docs = documents(s.build(request(minor=5), [event(1)]))
        self.assertEqual(len(docs[0]["scheduleList"]), 1)

    def test_nothing_to_do(self):
        s = C.CalendarSync("phone")
        s.build(request(minor=0), [event(1)])
        self.assertIsNone(s.build(request(minor=1), [event(1)]))

    def test_empty_calendar_on_an_empty_watch(self):
        self.assertIsNone(C.CalendarSync("phone").build(request(minor=0), []))

    def test_changes_only(self):
        s = C.CalendarSync("phone")
        s.build(request(minor=0), [event(1), event(2), event(3)])
        content = s.build(request(minor=3), [event(1), event(2, title="Moved"), event(4)])
        flag, docs = documents(content)
        self.assertEqual(flag, 1)
        ops = [(e["operation"], e["event_id"]) for e in docs[0]["scheduleList"]]
        self.assertEqual(ops, [(3, "2"), (1, "4"), (2, "3")])

    def test_soonest_events_when_the_watch_takes_fewer(self):
        s = C.CalendarSync("phone")
        events = [event(i, start=1800000000000 + (5 - i) * 3600000) for i in range(5)]
        _, docs = documents(s.build(request(minor=0, count=2), events))
        self.assertEqual([e["event_id"] for e in docs[0]["scheduleList"]], ["4", "3"])

    def test_too_many_changes_send_everything(self):
        s = C.CalendarSync("phone")
        s.build(request(minor=0, count=2), [event(1), event(2)])
        flag, docs = documents(s.build(request(minor=2, count=2), [event(3), event(4)]))
        self.assertEqual(flag, 0)
        self.assertEqual(sorted(e["event_id"] for e in docs[0]["scheduleList"]), ["3", "4"])

    def test_a_moved_occurrence_is_a_new_one(self):
        s = C.CalendarSync("phone")
        s.build(request(minor=0), [event(1)])
        _, docs = documents(s.build(request(minor=1), [event(1, start=1800000000000 + 86400000)]))
        self.assertEqual(sorted(e["operation"] for e in docs[0]["scheduleList"]), [1, 2])


class Recorder(D.Listener):
    def __init__(self, events=None):
        self.connected = threading.Event()
        self.events = events if events is not None else []
        self.requests = []
        self.done = []
        self.finished = threading.Event()
        self.answer = True
        self.watch = None

    def on_state(self, state, detail=""):
        if state == D.STATE_CONNECTED:
            self.connected.set()

    def on_calendar_request(self, request):
        self.requests.append(request)
        if self.answer:
            self.watch.send_calendar(request, list(self.events))

    def on_calendar_done(self, events, error=""):
        self.done.append((events, error))
        self.finished.set()


def wait_for(cond, timeout=10.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False


class TestExchange(unittest.TestCase):
    def connect(self, events=None, caps=None, **kw):
        phone, watch_sock = socket.socketpair()
        watch = FakeWatch(watch_sock, **kw).start()
        rec = Recorder(events)
        dev = D.HuaweiWatch(phone, "AA:BB:CC:DD:EE:FF", D.DeviceStore({}, lambda: None), rec)
        rec.watch = dev
        self.addCleanup(dev.stop)
        self.addCleanup(watch_sock.close)
        dev.start()
        self.assertTrue(rec.connected.wait(10))
        return dev, watch, rec

    def sync(self, dev, rec, first=False):
        rec.finished.clear()
        dev.calendar_sync(first)
        self.assertTrue(rec.finished.wait(10), rec.done)

    def test_supported_by_capability_bits(self):
        dev, _, _ = self.connect()
        self.assertTrue(dev.calendar_supported)
        caps = bytearray(dev.expand_capabilities)
        caps[184 // 8] |= 1 << (184 % 8)     # Huawei's own calendar service: not ours to sync
        dev.expand_capabilities = bytes(caps)
        self.assertFalse(dev.calendar_supported)

    def test_first_sync_reaches_the_calendar_app(self):
        dev, watch, rec = self.connect([event(1, title="Dentist"), event(2)])
        self.sync(dev, rec, first=True)
        self.assertEqual(rec.done, [(2, "")])
        self.assertEqual(watch.calendar_commands, [bytes([2, 1, 1, 1]), bytes([1, 1, 1, 1])])
        self.assertEqual(sorted(e["title"] for e in watch.calendar_events.values()), ["Dentist", "Event"])
        # A watch without a version gets the phone's id, not its own zero bytes back
        self.assertEqual(watch.calendar_major, dev.store.android_id().decode("utf-8"))
        info = watch.calendar_info
        self.assertRegex(info.get_string(0x01), r"^calendar_data_\d+\.json$")
        self.assertEqual(info.get_byte(0x03), 7)
        self.assertEqual(info.get_string(0x08), "hw.unitedevice.calendarapp")
        self.assertEqual(info.get_string(0x09), "in.huawei.calendar")
        self.assertTrue(info.contains(0x0A))
        self.assertEqual(info.get_string(0x0B), "UniteDeviceManagement")
        self.assertEqual(info.get_string(0x0C), "SystemApp")
        self.assertFalse(info.contains(0x05))     # no face name on a calendar file
        self.assertFalse(dev.uploading)

    def test_next_sync_sends_only_changes(self):
        dev, watch, rec = self.connect([event(1), event(2)])
        self.sync(dev, rec)
        rec.events[:] = [event(1), event(3)]
        self.sync(dev, rec)
        self.assertFalse(watch.calendar_files[-1]["full"])
        self.assertEqual(sorted(e["event_id"] for e in watch.calendar_events.values()), ["1", "3"])
        self.assertEqual(rec.done[-1], (2, ""))

    def test_no_changes_tell_the_watch_and_send_no_file(self):
        dev, watch, rec = self.connect([event(1)])
        self.sync(dev, rec)
        self.sync(dev, rec)
        self.assertEqual(len(watch.calendar_files), 1)
        self.assertTrue(wait_for(lambda: bytes([1, 1, 1, 4]) in watch.calendar_commands))
        self.assertEqual(rec.done[-1], (1, ""))

    def test_reconnect_empties_the_watch_then_fills_it(self):
        dev, watch, rec = self.connect([event(1)], calendar_major="old", calendar_minor=8)
        watch.calendar_events = {"stale": {"event_uuid": "stale"}}
        self.sync(dev, rec)
        self.assertEqual([len(f["documents"][0]["scheduleList"]) for f in watch.calendar_files], [0, 1])
        self.assertEqual(list(watch.calendar_events), ["1_1800000000000"])
        self.assertEqual(rec.done, [(1, "")])

    def test_watch_that_keeps_its_version_is_not_emptied_forever(self):
        dev, watch, rec = self.connect([event(1)], calendar_major="old", calendar_minor=8)
        watch.calendar_keeps_minor = True
        self.sync(dev, rec)
        self.assertEqual(len(watch.calendar_files), 2)
        self.assertEqual(rec.done, [(1, "")])

    def test_watch_can_ask_by_itself_and_gets_an_ack(self):
        dev, watch, rec = self.connect([event(1)])
        watch.calendar_ask()
        self.assertTrue(rec.finished.wait(10))
        self.assertEqual(len(watch.calendar_events), 1)
        ack = watch.calendar_answers[0]
        self.assertEqual((ack.get_byte(0x01), ack.get_short(0x02)), (3, 77))
        self.assertEqual(ack.get_string(0x03), "hw.unitedevice.calendarapp")
        self.assertEqual(ack.get_string(0x04), "in.huawei.calendar")
        self.assertEqual(ack.get_bytes(0x08), b"\x00\x00\x00\xcf")

    def test_mode_3_is_answered_before_the_events(self):
        dev, watch, rec = self.connect([event(1)])
        watch.calendar_ask(mode=3)
        self.assertTrue(rec.finished.wait(10))
        self.assertTrue(wait_for(lambda: bytes([1, 1, 1, 3]) in watch.calendar_commands))

    def test_refusing(self):
        dev, watch, rec = self.connect()
        rec.answer = False
        dev.calendar_sync()
        self.assertTrue(wait_for(lambda: rec.requests))
        dev.refuse_calendar(C.ANSWER_DISABLED)
        self.assertTrue(wait_for(lambda: bytes([1, 1, 1, 7]) in watch.calendar_commands))
        self.assertEqual(watch.calendar_files, [])

    def test_calendar_app_missing(self):
        dev, watch, rec = self.connect(calendar_present=False)
        self.sync(dev, rec)
        self.assertEqual(rec.done[0][0], None)
        self.assertIn("did not answer", rec.done[0][1])
        self.assertEqual(watch.calendar_commands, [])

    def test_failed_upload_starts_over(self):
        dev, watch, rec = self.connect([event(1)], upload_refuse=140009)
        self.sync(dev, rec)
        self.assertIsNone(rec.done[0][0])
        self.assertTrue(rec.done[0][1])
        self.assertIsNone(dev._calendar.last)
        self.assertFalse(dev.uploading)

    def test_busy_with_a_watch_face(self):
        dev, watch, rec = self.connect([event(1)], upload_window=200, upload_unit=50)
        dev.upload_watchface(os.urandom(20000))
        self.sync(dev, rec)
        self.assertEqual(rec.done[0], (None, "The watch is busy with an upload"))
        self.assertEqual(watch.calendar_files, [])

    def test_face_upload_still_works_after_a_calendar_upload(self):
        dev, watch, rec = self.connect([event(1)])
        self.sync(dev, rec)
        dev.upload_watchface(b"FACE" * 100)
        self.assertTrue(wait_for(lambda: len(watch.uploaded) == 2))


if __name__ == "__main__":
    unittest.main()
