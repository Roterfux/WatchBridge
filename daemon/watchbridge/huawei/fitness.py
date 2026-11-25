# WatchBridge - Huawei Watch GT 5 companion for Sailfish OS
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# Ported from Gadgetbridge (devices/huawei/packets/FitnessData.java, the requests
# GetFitnessTotalsRequest, GetStepDataCountRequest, GetStepDataRequest,
# GetSleepDataCountRequest, GetSleepDataRequest, SendFitnessUserInfoRequest,
# SetActivityReminderRequest, SetAutomaticSpoRequest, SetSpO2LowAlert and HuaweiSampleProvider.java),
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


REALTIME_HEART_RATE = 0x1C


def realtime_heart_rate(enabled):
    """FitnessData.EnableRealtimeHeartRate (0x07/0x1c): continuous measurement in real-time mode
    (about every second) instead of the smart mode of 0x07/0x17, which measures less often at rest."""
    return Packet(SERVICE, REALTIME_HEART_RATE, TLV().put_byte(0x01, 1 if enabled else 0))


def notify_rest_heart_rate_capability():
    """FitnessData.NotifyRestHeartRate (0x07/0x23): the phone can take resting heart rate.
    Gadgetbridge's put(0x01, 0x01) is a Java int, so the value is four bytes."""
    return Packet(SERVICE, 0x23, TLV().put_int(0x01, 0x01))


def notify_heart_rate_capability():
    """Workout.NotifyHeartRate (0x17/0x17): the phone trusts the watch's heart rate."""
    return Packet(0x17, 0x17, TLV().put_int(0x01, 0x03))


USER_INFO = 0x02
ACTIVITY_REMINDER = 0x07
AUTOMATIC_SPO2 = 0x24
LOW_SPO2_ALERT = 0x25

GENDER_MALE, GENDER_FEMALE, GENDER_UNKNOWN = 1, 2, 3
# Stride factors Gadgetbridge sends with the height ("bmi" walk/run)
WALK_CF, RUN_CF = 0.42, 0.83


def _java_round(x):
    """Math.round: halves go up, unlike Python's round()."""
    return int(x + 0.5) if x >= 0 else -int(-x + 0.5)


def user_info(height_cm, weight_kg, age, birthday, gender, unknown_gender_supported, precision_weight_supported):
    """FitnessData.UserInfo (0x07/0x02): the body the watch computes calories and distance for.

    birthday is (year, month, day). Byte-sized values are sent the way Java's (byte) casts them.
    """
    height = int(height_cm)
    t = (TLV().put_byte(0x01, height)
         .put_byte(0x02, int(weight_kg))
         .put_byte(0x03, int(age)))
    year, month, day = birthday
    t.put_int(0x04, (year << 16) + (month << 8) + day)
    if gender in (GENDER_MALE, GENDER_FEMALE) or (gender == GENDER_UNKNOWN and unknown_gender_supported):
        t.put_byte(0x05, gender)
    t.put_byte(0x06, _java_round(WALK_CF * height)).put_byte(0x07, _java_round(RUN_CF * height))
    if precision_weight_supported:
        t.put_int(0x0B, _java_round(weight_kg * 100))
    return Packet(SERVICE, USER_INFO, t)


def activity_reminder(enabled, interval_minutes, start, end, days):
    """FitnessData.ActivityReminder (0x07/0x07): the move reminder after sitting too long.

    start and end are (hour, minute); days is a weekday mask (Monday = bit 0 ... Sunday = bit 6).
    """
    return Packet(SERVICE, ACTIVITY_REMINDER, TLV().put(0x81, TLV()
                                                        .put(0x02, bool(enabled))
                                                        .put_byte(0x03, int(interval_minutes))
                                                        .put(0x04, bytes([start[0] % 24, start[1] % 60]))
                                                        .put(0x05, bytes([end[0] % 24, end[1] % 60]))
                                                        .put_byte(0x06, int(days) & 0x7F)))


def automatic_spo2(enabled):
    """FitnessData.EnableAutomaticSpo (0x07/0x24): blood oxygen measured through the day.
    The watch does not answer it (Gadgetbridge: addToResponse = false)."""
    return Packet(SERVICE, AUTOMATIC_SPO2, TLV().put(0x01, bool(enabled)))


def low_spo2_alert(threshold):
    """FitnessData.LowSpoAlert (0x07/0x25): warn below threshold %, 0 = off. Not answered either."""
    t = TLV().put(0x01, threshold > 0)
    if threshold > 0:
        t.put_byte(0x02, int(threshold))
    return Packet(SERVICE, LOW_SPO2_ALERT, t)


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
