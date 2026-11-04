# WatchBridge - Huawei Watch GT 5 companion for Sailfish OS
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# Ported from Gadgetbridge (devices/huawei/packets/FitnessData.java, the requests
# GetFitnessTotalsRequest, GetStepDataCountRequest, GetStepDataRequest,
# GetSleepDataCountRequest, GetSleepDataRequest and HuaweiSampleProvider.java),
# Copyright (C) 2024 Damien Gaignon, Martin.JM, Vitalii Tomin.
# Translated to Python and modified for WatchBridge, 2026. See NOTICE.md.
"""FitnessData service (0x07): daily totals, per-minute activity and basic sleep.

The watch keeps its records until a phone asks for them. A sync asks how many
messages cover a time range (MessageCount), then fetches them one by one by
index (MessageData). Each step message holds up to an hour of one-minute
samples; each sleep message holds a list of sleep periods.
"""

from .packet import Packet
from .tlv import TLV

SERVICE = 0x07


class FC:
    """FitnessData command ids."""
    TOTALS = 0x03
    STEP_COUNT = 0x0A
    STEP_DATA = 0x0B
    SLEEP_COUNT = 0x0C
    SLEEP_DATA = 0x0D


# Basic sleep period types (HuaweiSampleProvider.RawTypes)
SLEEP_TYPES = {0x06: "light", 0x07: "deep"}

# Some watches reject a start time of 0 (Gadgetbridge uses 2000-01-01)
EARLIEST = 946684800


class FitnessParseError(ValueError):
    pass


# --- requests ------------------------------------------------------------------

def totals_request():
    return Packet(SERVICE, FC.TOTALS, TLV().put(0x01))


def message_count_request(command, start, end):
    """command is FC.STEP_COUNT or FC.SLEEP_COUNT; start/end are unix seconds."""
    t = TLV().put(0x81).put_int(0x03, start).put_int(0x04, end)
    return Packet(SERVICE, command, t)


def message_data_request(command, index):
    """command is FC.STEP_DATA or FC.SLEEP_DATA; index counts from 0."""
    return Packet(SERVICE, command, TLV().put(0x81, TLV().put_short(0x02, index)))


def automatic_heart_rate(enabled):
    """FitnessData.EnableAutomaticHeartrate (0x07/0x17): continuous heart-rate measurement."""
    return Packet(SERVICE, 0x17, TLV().put_byte(0x01, 1 if enabled else 0))


def notify_rest_heart_rate_capability():
    """FitnessData.NotifyRestHeartRate (0x07/0x23): the phone can take resting heart rate.
    Gadgetbridge's put(0x01, 0x01) is a Java int, so the value is four bytes."""
    return Packet(SERVICE, 0x23, TLV().put_int(0x01, 0x01))


def notify_heart_rate_capability():
    """Workout.NotifyHeartRate (0x17/0x17): the phone trusts the watch's heart rate."""
    return Packet(0x17, 0x17, TLV().put_int(0x01, 0x03))


# --- responses -----------------------------------------------------------------

def parse_totals(tlv):
    """Today's totals: steps, calories (kcal) and distance (m), summed over containers."""
    out = {"steps": 0, "calories": 0, "distance": 0}
    for c in tlv.get_object(0x81).get_objects(0x83):
        for key, tag in (("steps", 0x05), ("calories", 0x06), ("distance", 0x07)):
            if c.contains(tag):
                out[key] += c.get_as_int(tag, 0)
    return out


def parse_message_count(tlv):
    return tlv.get_object(0x81).get_short(0x02)


# Feature bitmap 1, bit -> field; the listed bits carry one byte, the others two
_BITMAP1 = {0x02: "steps", 0x04: "calories", 0x08: "distance", 0x40: "heart_rate"}
_SINGLE_BYTE_BITMAP1 = (0x20, 0x40)
# Feature bitmap 2 (present when bit 0x80 of bitmap 1 is set), one byte each
_BITMAP2 = {0x01: "spo2", 0x02: "resting_heart_rate"}


def parse_step_bytes(data):
    """Decode one minute of activity. Returns a dict with the fields present.

    Raises FitnessParseError for truncated data, as Gadgetbridge drops those
    minutes too. Values are read unsigned (Gadgetbridge's Java bytes would turn
    a heart rate above 127 negative).
    """
    data = bytes(data)
    if not data:
        raise FitnessParseError("Data is missing feature bitmap.")
    i = 0
    bitmap1 = data[i]
    i += 1
    bitmap2 = 0
    if bitmap1 & 0x80:
        if len(data) <= i:
            raise FitnessParseError("Data is missing second feature bitmap.")
        bitmap2 = data[i]
        i += 1
    out = {}
    unknown = []
    bit = 1
    while bit < 0x80:
        if bitmap1 & bit:
            width = 1 if bit in _SINGLE_BYTE_BITMAP1 else 2
            if len(data) < i + width:
                raise FitnessParseError("Data is too short for selected features.")
            value = int.from_bytes(data[i:i + width], "big")
            i += width
            if bit in _BITMAP1:
                out[_BITMAP1[bit]] = value
            else:
                unknown.append((1, bit, value))
        bit <<= 1
    bit = 1
    while bit < 0x100:
        if bitmap2 & bit:
            if len(data) < i + 1:
                raise FitnessParseError("Data is too short for selected features.")
            value = data[i]
            i += 1
            if bit in _BITMAP2:
                out[_BITMAP2[bit]] = value
            else:
                unknown.append((2, bit, value))
        bit <<= 1
    out["unknown"] = unknown
    return out


def parse_step_data(tlv):
    """Returns (message index, [sample dict with "time" plus the parsed fields])."""
    container = tlv.get_object(0x81)
    number = container.get_short(0x02)
    base = container.get_int(0x03)
    samples = []
    errors = 0
    for sub in container.get_objects(0x84):
        timestamp = base + 60 * sub.get_byte(0x05)
        try:
            fields = parse_step_bytes(sub.get_bytes(0x06))
        except FitnessParseError:
            errors += 1
            continue
        fields["time"] = timestamp
        samples.append(fields)
    return number, samples, errors


def parse_sleep_data(tlv):
    """Returns (message index, [(start, end, type byte)]) with unix seconds."""
    container = tlv.get_object(0x81)
    number = container.get_short(0x02)
    periods = []
    for sub in container.get_objects(0x83):
        raw = sub.get_bytes(0x05)
        if len(raw) < 6:
            continue  # Gadgetbridge would read garbage here; skip instead
        start = int.from_bytes(raw[0:4], "big")
        minutes = int.from_bytes(raw[4:6], "big")
        periods.append((start, start + 60 * minutes, sub.get_byte(0x04)))
    return number, periods
