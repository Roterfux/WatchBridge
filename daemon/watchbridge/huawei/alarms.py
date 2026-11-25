# WatchBridge - Huawei Watch GT 5 companion for Sailfish OS
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# Based on Gadgetbridge (https://codeberg.org/Freeyourgadget/Gadgetbridge):
#   devices/huawei/packets/Alarms.java, service/devices/huawei/requests/AlarmsRequest.java,
#   GetEventAlarmList.java
#   Copyright (C) 2024 Damien Gaignon, Martin.JM and Gadgetbridge contributors
# Translated to Python and modified for WatchBridge, 2026.
"""Alarms service 0x08: the watch's event alarms (up to five).

The phone always sends the whole list; the watch replaces its own with it. The smart alarm
(0x08/0x02) is not offered: the Watch GT 5 does not list that command.
"""

from .packet import Packet
from .tlv import TLV

SERVICE = 0x08
SET_EVENT_ALARMS = 0x01
SET_SMART_ALARM = 0x02
EVENT_ALARM_LIST = 0x03

MAX_ALARMS = 5
# Repeat bits, as in Gadgetbridge's Alarm: Monday = bit 0 ... Sunday = bit 6, 0 = once
MONDAY, SUNDAY = 0x01, 0x40


def _alarm_tlv(index, alarm):
    hour, minute = int(alarm["hour"]) % 24, int(alarm["minute"]) % 60
    return (TLV()
            .put_byte(0x03, index)
            .put(0x04, bool(alarm.get("enabled")))
            .put_short(0x05, (hour << 8) | minute)
            .put_byte(0x06, int(alarm.get("repeat", 0)) & 0x7F)
            .put(0x07, str(alarm.get("name") or "Alarm")))


def set_event_alarms(alarms):
    """EventAlarmsRequest: the full list; index 1..5 by position. Empty = all off."""
    inner = TLV()
    for i, alarm in enumerate(alarms[:MAX_ALARMS]):
        inner.put(0x82, _alarm_tlv(i + 1, alarm))
    if not alarms:
        inner.put(0x82, TLV().put_byte(0x03, 0x01))   # as Gadgetbridge: disables them all
    return Packet(SERVICE, SET_EVENT_ALARMS, TLV().put(0x81, inner))


def event_alarm_list_request():
    return Packet(SERVICE, EVENT_ALARM_LIST, TLV().put(0x01))


def parse_event_alarm_list(tlv):
    """[{index, enabled, hour, minute, repeat, name}] sorted by index."""
    out = []
    if not tlv.contains(0x81):
        return out
    for sub in tlv.get_object(0x81).get_objects(0x82):
        enabled = sub.get_bool(0x04, False)
        hour = minute = 0
        if sub.contains(0x05):
            value = sub.get_short(0x05)
            hour, minute = (value >> 8) & 0xFF, value & 0xFF
        out.append({
            "index": sub.get_byte(0x03),
            "enabled": enabled,
            "hour": hour,
            "minute": minute,
            "repeat": sub.get_byte(0x06, 0),
            "name": sub.get_string(0x07, ""),
        })
    out.sort(key=lambda a: a["index"])
    return out
