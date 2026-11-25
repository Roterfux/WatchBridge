# WatchBridge - Huawei Watch GT 5 companion for Sailfish OS
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# Ported from Gadgetbridge (devices/huawei/packets/P2P.java,
# service/devices/huawei/HuaweiP2PManager.java, p2p/HuaweiBaseP2PService.java),
# Copyright (C) 2024-2025 Me7c7, José Rebelo.
# Translated to Python and modified for WatchBridge, 2026. See NOTICE.md.
"""P2P messages (service 0x34): an app on the phone talking to an app on the watch.

Every message names its source and destination package. A ping asks whether the other
side is there, data carries the app's own bytes, and an ack answers either one under the
same sequence number. The watch never answers these as a normal request/reply pair.
"""

from .packet import Packet
from .tlv import TLV

SERVICE = 0x34
COMMAND = 0x01

CMD_PING = 1
CMD_DATA = 2
CMD_ACK = 3

PING_PACKAGE = "com.huawei.health"          # pings always come from Huawei Health
LOCAL_FINGERPRINT = "UniteDeviceManagement"

CODE_PRESENT = 0xCA   # the watch's answer to a ping when the app is there
CODE_RECEIVED = 0xCF  # our answer to a ping or data from the watch

_MAX_SEQUENCE = 0x7FFF - 1


def next_sequence(sequence):
    return (sequence + 1) % _MAX_SEQUENCE


def _packet(command, sequence, source, destination, fingerprints=None, data=None, code=None):
    t = TLV().put_byte(0x01, command).put_short(0x02, sequence).put(0x03, source).put(0x04, destination)
    if fingerprints is not None:
        t.put(0x05, fingerprints[0]).put(0x06, fingerprints[1])
    if data:
        t.put(0x07, data)
    if code is not None:
        t.put_int(0x08, code)
    return Packet(SERVICE, COMMAND, t)


def ping(sequence, destination):
    return _packet(CMD_PING, sequence, PING_PACKAGE, destination)


def data(sequence, source, destination, destination_fingerprint, body):
    return _packet(CMD_DATA, sequence, source, destination, (LOCAL_FINGERPRINT, destination_fingerprint), body)


def ack(sequence, source, destination, code=CODE_RECEIVED):
    return _packet(CMD_ACK, sequence, source, destination, code=code)


# The watch's battery manager (Gadgetbridge HuaweiP2PBatteryService) sends JSON when charging
# starts or stops, e.g. {"type":"battery","chargingStatus":"ON","powerValue":87,...}
BATTERY_PACKAGE = "com.huawei.BatteryEventMgr"


def parse_battery_event(data):
    """(level or None, charging or None) from a battery event, None if it is something else."""
    import json
    try:
        text = data.decode("utf-8", errors="replace").strip("\x00 \r\n")
        obj, _ = json.JSONDecoder().raw_decode(text)    # lenient like org.json about trailing bytes
    except ValueError:
        return None
    if not isinstance(obj, dict) or obj.get("type") != "battery":
        return None
    level = obj.get("powerValue")
    level = int(level) if isinstance(level, (int, float)) and 0 <= level <= 100 else None
    status = obj.get("chargingStatus")
    charging = None if status is None else str(status).upper() == "ON"
    return level, charging


def parse(tlv):
    return {
        "command": tlv.get_byte(0x01, 0),
        "sequence": tlv.get_as_int(0x02, 0),
        "source": tlv.get_string(0x03, ""),
        "destination": tlv.get_string(0x04, ""),
        "data": tlv.get_bytes(0x07, b""),
        # A byte from the watch, an int from the phone (P2P.java)
        "code": tlv.get_as_int(0x08, 0),
    }
