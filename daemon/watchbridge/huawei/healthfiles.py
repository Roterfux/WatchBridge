# WatchBridge - Huawei Watch GT 5 companion for Sailfish OS
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# Ported from Gadgetbridge (devices/huawei/HuaweiSequenceDataFileParser.java,
# HuaweiSequenceDataParserBase.java, HuaweiTrueSleepSequenceDataParser.java,
# HuaweiStressParser.java and HuaweiSleepSessionProvider.kt),
# Copyright (C) 2025 Me7c7 and Gadgetbridge contributors.
# Translated to Python and modified for WatchBridge, 2026. See NOTICE.md.
"""Parsers for health files downloaded from the watch.

Sleep ("TruSleep") on newer watches arrives as a sequence-data file for the
sleep-details dictionary class: one record per sleep session, each with a TLV
summary (score, efficiency, heart rate, SpO2, breathing ...) and a list of
stages. Stress arrives as an RRI file with one 66-byte record per measurement.
"""

import logging
import struct

from .tlv import TLV

log = logging.getLogger(__name__)

SLEEP_DETAILS_CLASS = 700013

# Stage codes in the sleep details (HuaweiSleepSessionProvider.sleepStageToActivityKind)
STAGES = {1: "light", 2: "rem", 3: "deep", 4: "awake", 5: "nap"}

# Summary dictionary ids -> (field name, kind, valid range or None)
# kind "time" = unix seconds, "int", "float" (HuaweiTrueSleepSequenceDataParser.fillData)
SUMMARY_FIELDS = {
    700013686: ("fall_asleep", "time", None),
    700013298: ("bed_time", "time", None),
    700013973: ("rising_time", "time", None),
    700013156: ("wakeup_time", "time", None),
    700013786: ("valid_data", "int", None),
    700013254: ("quality", "int", None),
    700013679: ("deep_part", "int", None),
    700013721: ("snore_freq", "int", None),
    700013245: ("score", "int", None),
    700013713: ("latency", "int", None),
    700013232: ("efficiency", "int", None),
    700013436: ("min_heart_rate", "int", (0, 255)),
    700013502: ("max_heart_rate", "int", (0, 255)),
    700013340: ("min_spo2", "float", None),
    700013026: ("max_spo2", "float", None),
    700013646: ("min_breath_rate", "int", None),
    700013492: ("max_breath_rate", "int", None),
    700013824: ("hrv_day_to_baseline", "int", (0, 30)),
    700013355: ("max_hrv_baseline", "int", (0, 200)),
    700013305: ("min_hrv_baseline", "int", (0, 200)),
    700013878: ("avg_hrv", "int", (0, 200)),
    700013236: ("breath_rate_day_to_baseline", "int", (0, 30)),
    700013225: ("max_breath_rate_baseline", "int", (0, 80)),
    700013839: ("min_breath_rate_baseline", "int", (0, 80)),
    700013886: ("avg_breath_rate", "int", (0, 80)),
    700013718: ("spo2_day_to_baseline", "int", (0, 30)),
    700013227: ("max_spo2_baseline", "int", (0, 100)),
    700013633: ("min_spo2_baseline", "int", (0, 100)),
    700013468: ("avg_spo2", "int", (0, 100)),
    700013810: ("heart_rate_day_to_baseline", "int", (0, 30)),
    700013841: ("max_heart_rate_baseline", "int", (0, 255)),
    700013722: ("min_heart_rate_baseline", "int", (0, 255)),
    700013580: ("avg_heart_rate", "int", (0, 255)),
    700013759: ("rdi", "int", (0, 100)),
    700013635: ("wake_count", "int", None),
    700013670: ("turn_over_count", "int", None),
    700013821: ("prepare_sleep_time", "time", None),
    700013925: ("wake_up_feeling", "int", None),
    700013697: ("sleep_version", "int", (0, 100)),
}

# Fields that are random on some watches when the night is not valid (correctSummary)
_INVALID_NIGHT_FIELDS = ("bed_time", "rising_time", "score", "quality", "deep_part", "snore_freq",
                         "efficiency", "latency", "prepare_sleep_time")


class HealthFileError(ValueError):
    pass


# --- sequence data ---------------------------------------------------------------------

def parse_sequence_file(data):
    """Returns {"dict_id", "file_type", "version", "records": [...]}; each record has
    start, end, data_version, summary_type, summary (bytes or None), details (bytes or None)."""
    data = bytes(data)
    if len(data) < 32:
        raise HealthFileError("Sequence file too short (%d bytes)" % len(data))
    _size, dict_id, file_type, version = struct.unpack(">IIhh", data[:12])
    pos = 32
    records = []
    while len(data) - pos >= 32:
        start, end, data_version, summary_type, summary_len, detail_len = struct.unpack(
            ">IIbbhi", data[pos:pos + 16])
        pos += 32  # 16 bytes of fields + 16 bytes extra data
        summary = None
        if data_version == 1:
            if len(data) - pos < summary_len:
                log.error("Sequence record summary length %d exceeds the file", summary_len)
            else:
                summary = data[pos:pos + summary_len]
                pos += summary_len
        details = None
        if detail_len <= 0 or detail_len > 20 * 1025 * 1024:
            log.error("Sequence record detail length %d is invalid", detail_len)
        else:
            details = data[pos:pos + detail_len]
            if len(details) < detail_len:
                log.error("Sequence record detail length %d exceeds the file", detail_len)
            pos += detail_len
        records.append({"start": start, "end": end, "data_version": data_version,
                        "summary_type": summary_type, "summary": summary, "details": details})
    if pos < len(data):
        log.warning("Sequence file: %d trailing bytes", len(data) - pos)
    return {"dict_id": dict_id, "file_type": file_type, "version": version, "records": records}


def _read_int(value):
    if not value or len(value) > 4:
        return None
    if value == b"\xbf\x80\x00\x00":  # float -1 sent as an integer: "no value"
        return None
    return int.from_bytes(value, "big")


def _value(data_type, value, kind):
    """Gadgetbridge getValueAsLong/getValueAsDouble: 1/2/4 = int, 3 = long, 6 = double."""
    if data_type in (1, 2, 4):
        return _read_int(value)
    if data_type == 3:
        return int.from_bytes(value, "big") if value and len(value) <= 8 else None
    if data_type == 6 and value and len(value) <= 8:
        d = struct.unpack(">d", value.rjust(8, b"\0"))[0]
        return d if kind == "float" else int(d)
    return None


def parse_dict_summary(summary):
    """Decode a TLV summary into {dictionary id: (data type, raw value)}."""
    out = {}
    for _tag, outer in TLV.parse(summary).items:
        if not _tag & 0x80:
            continue
        for _tag2, inner in TLV.parse(outer).items:
            if not _tag2 & 0x80:
                continue
            tv = TLV.parse(inner)
            try:
                out[tv.get_as_int(0x03)] = (tv.get_as_int(0x04), tv.get_bytes(0x05))
            except (KeyError, ValueError) as e:
                log.warning("Sequence summary entry without id/type/value: %s", e)
    return out


def parse_sleep_summary(summary):
    """Sleep summary fields (see SUMMARY_FIELDS); missing or out-of-range values are omitted."""
    out = {}
    for dict_id, (data_type, raw) in parse_dict_summary(summary).items():
        field = SUMMARY_FIELDS.get(dict_id)
        if field is None:
            continue
        name, kind, valid = field
        v = _value(data_type, raw, kind)
        if v is None or v < 0:
            continue
        if valid and not valid[0] <= v <= valid[1]:
            continue
        out[name] = v
    if "valid_data" not in out:
        for name in _INVALID_NIGHT_FIELDS:
            out.pop(name, None)
    return out


def parse_sleep_stages(details, start):
    """Stage periods [(start, end, stage name)] from the 8-byte little-endian detail records."""
    if not details or len(details) % 4:
        return []
    periods = []
    t = start
    for pos in range(0, len(details) - 7, 8):
        duration, status = struct.unpack("<iB", details[pos:pos + 5])
        if duration <= 0 or status == 0 or duration % 60 or duration // 60 > 1440:
            log.debug("Skipping sleep detail record duration %d status %d", duration, status)
            continue
        name = STAGES.get(status, "stage-%d" % status)
        if periods and periods[-1][2] == name and periods[-1][1] == t:
            periods[-1] = (periods[-1][0], t + duration, name)
        else:
            periods.append((t, t + duration, name))
        t += duration
    return periods


def parse_sleep_file(data, supports_bed_time=False):
    """Returns [{"summary": {...}, "start": t, "end": t, "stages": [(start, end, stage)]}]."""
    sessions = []
    seq = parse_sequence_file(data)
    for rec in seq["records"]:
        if rec["data_version"] != 1 or rec["summary_type"] != 2 or seq["file_type"] == 2 or not rec["summary"]:
            log.info("Skipping sleep record with version %d / summary type %d",
                     rec["data_version"], rec["summary_type"])
            continue
        summary = parse_sleep_summary(rec["summary"])
        if supports_bed_time and "valid_data" in summary and summary.get("bed_time"):
            first = summary["bed_time"]
        else:
            first = summary.get("fall_asleep", rec["start"])
        first -= first % 60
        stages = parse_sleep_stages(rec["details"], first)
        end = summary.get("wakeup_time") or (stages[-1][1] if stages else rec["end"])
        sessions.append({"start": summary.get("fall_asleep", first), "end": end, "summary": summary,
                         "stages": stages})
    return sessions


# --- stress ---------------------------------------------------------------------------

def parse_stress_file(data):
    """Stress measurements [(start, end, score, level)] from an RRI file (version 3 only)."""
    data = bytes(data)
    if len(data) < 48:
        raise HealthFileError("Stress file too short (%d bytes)" % len(data))
    _size, _bitmap, version = struct.unpack(">qhh", data[:12])
    if version != 3:
        log.warning("Stress file version %d is not supported", version)
        return []
    out = []
    for pos in range(48, len(data) - 65, 66):
        start, end, _algorithm, score, level = struct.unpack(">IIiBB", data[pos:pos + 14])
        if start == 0 or end == 0:
            continue
        out.append((start, end, score, level))
    out.sort(key=lambda r: r[1])
    return out
