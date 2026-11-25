# WatchBridge - Huawei Watch GT 5 companion for Sailfish OS
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Read the phone's calendar through Sailfish's calendardataservice.

The calendar lives in privileged storage, but this small session-bus service (started on
demand, gone two seconds after its last answer) may read it and hands out the occurrences in
a date range, recurring events already expanded. getEvents(start, end) returns a transaction
id; the events follow in the signal getEventsResult(id, events), which every client on the
bus receives, so the id has to be checked.

Each event is (calendarUid, instanceId, startTime, endTime, allDay, color, displayLabel,
description, location, cancelled). The service's introspection data is out of date (it shows
one field less), and it fills in neither calendarUid nor location. Timed events are ISO date
times with "Z" or an offset; all-day events are plain dates, and their end date is the last
day of the event (a one-day event starts and ends on the same date).
"""

import datetime
import logging
import re
import zlib

log = logging.getLogger(__name__)

SERVICE = "org.nemomobile.calendardataservice"
PATH = "/org/nemomobile/calendardataservice"
IFACE = "org.nemomobile.calendardataservice"

ANSWER_TIMEOUT = 20

_INSTANCE, _START, _END, _ALL_DAY, _COLOR, _TITLE, _DESCRIPTION, _LOCATION, _CANCELLED = 1, 2, 3, 4, 5, 6, 7, 8, 9


def _milliseconds(moment):
    return int(moment.timestamp()) * 1000


def parse_time(text):
    """Milliseconds since 1970 of an ISO date time; one without an offset is local time."""
    text = re.sub(r"\.\d+", "", str(text))  # Qt adds milliseconds when they are not zero
    for pattern in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S"):
        try:
            return _milliseconds(datetime.datetime.strptime(text, pattern))
        except ValueError:
            pass
    raise ValueError("Unknown time format")


def parse_day(text, next_day=False):
    """Local midnight of a date, or of the day after it, in milliseconds."""
    day = datetime.datetime.strptime(str(text)[:10], "%Y-%m-%d")
    return _milliseconds(day + datetime.timedelta(days=1) if next_day else day)


def parse_color(text):
    """"#rrggbb" as Android's signed ARGB integer, which the watch expects."""
    try:
        return (0xFF000000 | int(str(text).lstrip("#")[-6:], 16)) - (1 << 32)
    except ValueError:
        return 0


def parse_event(fields):
    """An event as a dict for the watch, or None for a cancelled one."""
    if len(fields) > _CANCELLED and fields[_CANCELLED]:
        return None
    instance = str(fields[_INSTANCE])
    all_day = bool(fields[_ALL_DAY])
    if all_day:
        start = parse_day(fields[_START])
        end = parse_day(fields[_END] or fields[_START], next_day=True)  # the watch wants the end's midnight
    else:
        start = parse_time(fields[_START])
        end = parse_time(fields[_END]) if fields[_END] else start
    return {
        "id": zlib.crc32(instance.encode("utf-8")) & 0x7FFFFFFF,
        "start": start,
        "end": end,
        "all_day": all_day,
        "color": parse_color(fields[_COLOR]),
        "title": str(fields[_TITLE]),
        "description": str(fields[_DESCRIPTION]),
        "location": str(fields[_LOCATION]),
    }


def parse_events(items):
    events = []
    broken = 0
    for fields in items:
        try:
            event = parse_event(fields)
        except (ValueError, IndexError):
            broken += 1
            continue
        if event is not None:
            events.append(event)
    if broken:
        log.warning("Calendar: skipped %d event(s) with unreadable times", broken)
    return events


class PhoneCalendar:
    """fetch() delivers done(events, error) on the main loop."""

    def __init__(self, bus, timeout_add=None, source_remove=None):
        if timeout_add is None:
            from gi.repository import GLib
            timeout_add, source_remove = GLib.timeout_add_seconds, GLib.source_remove
        self.bus = bus
        self._timeout_add = timeout_add
        self._source_remove = source_remove
        self._waiting = {}   # transaction id -> (done, timer)
        self._early = {}     # results that overtook the method's reply

    def start(self):
        # No sender given: the service comes and goes, and dbus-python would follow its owner
        self.bus.add_signal_receiver(self._result, "getEventsResult", IFACE, path=PATH)

    def fetch(self, days, done):
        today = datetime.date.today()
        args = (today.isoformat(), (today + datetime.timedelta(days=days)).isoformat())
        # call_async, not a proxy: a proxy would block the main loop while the service starts
        # and would stay bound to the instance that is gone two seconds later
        self.bus.call_async(SERVICE, PATH, IFACE, "getEvents", "ss", args,
                            lambda tx: self._started(str(tx), done),
                            lambda e: done(None, "The calendar service failed: %s" % e),
                            timeout=ANSWER_TIMEOUT)

    def _started(self, transaction, done):
        if not transaction:
            done(None, "The calendar service refused the date range")
            return
        if transaction in self._early:
            done(parse_events(self._early.pop(transaction)), "")
            return
        timer = self._timeout_add(ANSWER_TIMEOUT, lambda: self._expired(transaction))
        self._waiting[transaction] = (done, timer)

    def _expired(self, transaction):
        entry = self._waiting.pop(transaction, None)
        if entry is not None:
            entry[0](None, "The calendar service did not answer")
        return False

    def _result(self, transaction, items):
        transaction = str(transaction)
        entry = self._waiting.pop(transaction, None)
        if entry is None:
            # Usually another client's answer. Keep only the latest: ours can only overtake
            # the reply to the call that is running now
            self._early = {transaction: items}
            return
        done, timer = entry
        self._source_remove(timer)
        done(parse_events(items), "")
