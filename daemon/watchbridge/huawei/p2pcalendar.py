# WatchBridge - Huawei Watch GT 5 companion for Sailfish OS
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# Ported from Gadgetbridge (service/devices/huawei/p2p/HuaweiP2PCalendarService.java),
# Copyright (C) 2024 Me7c7.
# Translated to Python and modified for WatchBridge, 2026. See NOTICE.md.
"""Calendar sync with the watch's calendar app.

The phone pings the app and asks it to start a sync. The app answers with what it holds
(a version made of "major" and "minor"), how many events it takes and how many days ahead
it wants; the phone then uploads a JSON file with all events or only the changes.

Events are dicts from phonecalendar.py: id, start, end (milliseconds), all_day, color, title,
description, location.
"""

import json
import logging
import struct

from .tlv import TLV

log = logging.getLogger(__name__)

MODULE = "hw.unitedevice.calendarapp"
PACKAGE = "in.huawei.calendar"
FINGERPRINT = "SystemApp"
FILE_TYPE = 7

CMD_UPLOAD = 1      # phone -> watch calendar: this is the sync the watch answers
CMD_DOWNLOAD = 2
CMD_EVENT_STATE = 3  # watch -> phone: a reminder was snoozed or closed on the watch

START_SYNC = 1
ANSWER_MODE_3 = 3
ANSWER_NO_CHANGES = 4
ANSWER_NO_PERMISSION = 6
ANSWER_DISABLED = 7

SYNC_MODES = (2, 3)

OPERATION_ADD = 1
OPERATION_DELETE = 2
OPERATION_UPDATE = 3

EVENTS_PER_CHUNK = 10
DEFAULT_DAYS = 7

# The events carry no account or calendar of their own on Sailfish (calendardataservice
# leaves the calendar empty), but the watch expects the fields
ACCOUNT_NAME = "Sailfish OS"
ACCOUNT_TYPE = "LOCAL"
CALENDAR_NAME = "Calendar"
CALENDAR_ID = "1"

_JAVA_TRIM = "".join(chr(c) for c in range(0x21))


def command(cmd, value):
    """A one-tag TLV behind the command id (sendCalendarCmd)."""
    return bytes([cmd, 0x01, 0x01, value])


def _as_short(tlv, tag):
    raw = tlv.get_bytes(tag, None)
    if not raw:
        return -1
    value = int.from_bytes(raw[:4], "big")
    return value - 0x10000 if len(raw) == 2 and value >= 0x8000 else value


def parse_request(body):
    """The watch's answer to a sync request, or None for any other message."""
    if not body or body[0] != CMD_UPLOAD:
        return None
    t = TLV.parse(body, 1, len(body) - 1)
    major = t.get_string(0x02, None)
    return {
        "mode": t.get_byte(0x01, -1),
        # Java's trim(): a GT 5 without a version sends 64 zero bytes, which Python's strip() keeps
        "major": major.strip(_JAVA_TRIM) if major is not None else None,
        "minor": _as_short(t, 0x03),
        "count": _as_short(t, 0x04),
        "days": t.get_as_int(0x05, DEFAULT_DAYS),
    }


def wants_events(request):
    return request["mode"] in SYNC_MODES and request["major"] is not None \
        and request["minor"] != -1 and request["count"] != -1


def truncate(text, limit):
    """Gadgetbridge's truncateToHexBytes: over `limit` bytes it keeps about half of that."""
    raw = (text or "").encode("utf-8")
    if len(raw) <= limit:
        return text or ""
    keep = (limit + 1) // 2 + 1 - 3
    return raw[:keep].decode("utf-8", errors="ignore") + "..."


def _uuid(event):
    return "%d_%d" % (event["id"], event["start"])


def event_json(event, operation):
    return {
        "account_name": truncate(ACCOUNT_NAME, 64),
        "account_type": truncate(ACCOUNT_TYPE, 64),
        "all_day": 1 if event["all_day"] else 0,
        "calendar_color": event["color"],
        "calendar_displayName": truncate(CALENDAR_NAME, 64),
        "calendar_id": CALENDAR_ID,
        "description": truncate(event["description"], 512),
        "dtend": event["end"],
        "dtstart": event["start"],
        "event_id": str(event["id"]),
        "event_location": truncate(event["location"], 256),
        "event_uuid": _uuid(event),
        "has_alarm": 0,   # Sailfish's calendar service does not hand out the reminders
        "minutes": "",
        "operation": operation,
        "rrule": "",      # recurring events arrive as single occurrences
        "state": -1,
        "title": truncate(event["title"], 500),
    }


def deleted_json(event):
    return {
        "account_name": "",
        "account_type": "",
        "all_day": 0,
        "calendar_color": 0,
        "calendar_displayName": "",
        "calendar_id": "",
        "description": "",
        "dtend": 0,
        "dtstart": 0,
        "event_id": str(event["id"]),
        "event_location": "",
        "event_uuid": _uuid(event),
        "has_alarm": 0,
        "minutes": "",
        "operation": OPERATION_DELETE,
        "rrule": "",
        "state": 0,
        "title": "",
    }


def _dump(major, minor, schedule):
    text = json.dumps({"major": major, "minor": minor, "scheduleList": schedule},
                      ensure_ascii=False, separators=(",", ":"))
    return text.encode("utf-8")


def file_content(major, minor, schedule, full):
    """Sync flag (0 full, 1 changes), then JSON documents of ten events, each behind its length."""
    out = bytearray(struct.pack(">I", 0 if full else 1))
    if not schedule:
        doc = _dump(major, minor, schedule)
        return bytes(out + struct.pack(">I", len(doc)) + doc)
    minor = 0
    for index, first in enumerate(range(0, len(schedule), EVENTS_PER_CHUNK)):
        chunk = schedule[first:first + EVENTS_PER_CHUNK]
        minor += len(chunk) * (index + 1)
        doc = _dump(major, minor, chunk)
        out += struct.pack(">I", len(doc)) + doc
    return bytes(out)


class CalendarSync:
    """Remembers what the watch holds during one connection and builds the files for it."""

    def __init__(self, phone_id):
        self.phone_id = phone_id
        self.last = None        # {(id, start): event} on the watch; None = not known yet
        self._cleared = False

    @property
    def count(self):
        return len(self.last or {})

    @property
    def wants_full_sync(self):
        """After emptying the watch: ask again, it now reports version 0 and takes everything."""
        return self.last is None

    def forget(self):
        self.last = None

    def _changes(self, current):
        known = dict(self.last)
        added, updated = [], []
        for key, event in current.items():
            before = known.pop(key, None)
            if before is None:
                added.append(event)
            elif before != event:
                updated.append(event)
        return ([event_json(e, OPERATION_UPDATE) for e in updated]
                + [event_json(e, OPERATION_ADD) for e in added]
                + [deleted_json(e) for e in known.values()])

    def build(self, request, events):
        """The file for the watch, or None when it is up to date (syncCalendarEvents)."""
        limit = max(request["count"], 0)
        events = sorted(events, key=lambda e: (e["start"], e["id"]))[:limit]  # the soonest ones
        current = {(e["id"], e["start"]): e for e in events}
        major, minor = request["major"], request["minor"]
        if major and self.last is not None and minor != 0:
            schedule = self._changes(current)
            if not schedule:
                return None
            if len(schedule) <= limit:
                self.last = current
                return file_content(major, minor, schedule, False)
            # Too many changes for one file. Gadgetbridge cuts them off, which would leave
            # the watch out of step with self.last; sending everything again keeps it right
        elif self.last is None and minor != 0 and not self._cleared:
            # The watch still has events from an earlier connection, and this connection
            # cannot know which: empty it, then it asks again with version 0.
            self._cleared = True
            return file_content(major or self.phone_id, 0, [], True)
        schedule = [event_json(e, OPERATION_ADD) for e in events]
        self.last = current
        if not schedule:
            if minor == 0 and major:
                return None
            minor = 0
        else:
            minor += 1
        return file_content(major or self.phone_id, minor, schedule, True)
