# WatchBridge - Huawei Watch GT 5 companion for Sailfish OS
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# Ported from Gadgetbridge (packets/DeviceConfig.java, Notifications.java,
# Weather.java, LocaleConfig.java, FindPhone.java), Copyright (C) 2024
# Damien Gaignon, Martin.JM and Gadgetbridge contributors.
"""Builders and parsers for the Huawei services used by WatchBridge."""

import os
import struct
import time

from .packet import Packet
from .tlv import TLV

RESULT_SUCCESS = 0x000186A0


class Service:
    DEVICE_CONFIG = 0x01
    NOTIFICATIONS = 0x02
    CALLS = 0x04
    FIND_PHONE = 0x0B
    LOCALE = 0x0C
    WEATHER = 0x0F
    ACCOUNT = 0x1A


class DC:
    """DeviceConfig command ids."""
    LINK_PARAMS = 0x01
    SUPPORTED_SERVICES = 0x02
    SUPPORTED_COMMANDS = 0x03
    DATE_FORMAT = 0x04
    TIME = 0x05
    PRODUCT_INFO = 0x07
    BATTERY = 0x08
    BOND = 0x0E
    BOND_PARAMS = 0x0F
    AUTH = 0x13
    DEVICE_STATUS = 0x16
    BATTERY_CHANGED = 0x27
    HICHAIN = 0x28
    PIN_CODE = 0x2C
    ACCEPT_AGREEMENT = 0x30
    SETTING_RELATED = 0x31
    TIMEZONE_ID = 0x32
    SECURITY_NEGOTIATION = 0x33
    CONNECT_STATUS = 0x35
    EXPAND_CAPABILITY = 0x37
    WEAR_STATUS = 0x3D
    SET_UP_DEVICE_STATUS = 0x3E
    REVERSE_CAPABILITIES = 0x3F


class AC:
    """AccountRelated command ids."""
    EXTENDED_ACCOUNT = 0x05
    ACCOUNT_SWITCH = 0x06


# Expand capability bits (HuaweiState.java)
CAP_MULTI_DEVICE = 109
CAP_DIFF_ACCOUNT_PAIRING_OPTIMIZATION = 0xAC
CAP_REVERSE_CAPABILITIES = 182


class NC:
    """Notifications command ids."""
    ACTION = 0x01
    CONSTRAINTS = 0x02
    STATE = 0x04
    REMOVE = 0x06
    WEAR_MESSAGE_PUSH = 0x08


class WC:
    """Weather command ids."""
    CURRENT = 0x01
    SUPPORT = 0x02
    DEVICE_REQUEST = 0x04
    UNIT = 0x05
    EXTENDED_SUPPORT = 0x06
    ERROR_SIMPLE = 0x07
    FORECAST = 0x08
    START = 0x09
    SUN_MOON_SUPPORT = 0x0A
    ERROR_EXTENDED = 0x0C


# --- DeviceConfig ------------------------------------------------------------

KNOWN_SUPPORTED_SERVICES = bytes([
    0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08, 0x09, 0x0A,
    0x0B, 0x0C, 0x0D, 0x0E, 0x0F, 0x10, 0x11, 0x12, 0x13, 0x14,
    0x15, 0x16, 0x17, 0x18, 0x19, 0x1A, 0x1B, 0x1D, 0x20,
    0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x2A, 0x2B, 0x2D, 0x2E,
    0x30, 0x32, 0x33, 0x34, 0x35,
])

COMMANDS_PER_SERVICE = {
    0x01: [0x04, 0x07, 0x08, 0x09, 0x0A, 0x0D, 0x0E, 0x10, 0x11, 0x12, 0x13, 0x14, 0x1B, 0x1A, 0x1D, 0x21, 0x22, 0x23,
           0x24, 0x29, 0x2A, 0x2B, 0x32, 0x2E, 0x31, 0x30, 0x35, 0x36, 0x37, 0x2F],
    0x02: [0x01, 0x04, 0x05, 0x06, 0x07, 0x08],
    0x03: [0x01, 0x03, 0x04],
    0x04: [0x01],
    0x05: [0x01],
    0x06: [0x01],
    0x07: [0x01, 0x03, 0x05, 0x07, 0x08, 0x09, 0x0A, 0x0E, 0x10, 0x13, 0x16, 0x15, 0x17, 0x18, 0x1B, 0x1C, 0x1D, 0x1E,
           0x21, 0x22, 0x23, 0x24, 0x25, 0x28, 0x29, 0x06, 0x1F],
    0x08: [0x01, 0x02, 0x03],
    0x09: [0x01, 0x0B, 0x0C, 0x0D, 0x0E, 0x0F],
    0x0A: [0x01, 0x09, 0x0A],
    0x0B: [0x01, 0x03],
    0x0C: [0x01],
    0x0D: [0x01],
    0x0F: [0x01, 0x03, 0x05, 0x06, 0x07, 0x08, 0x0A, 0x0B, 0x0C],
    0x10: [0x01], 0x11: [0x01], 0x12: [0x01], 0x13: [0x01], 0x14: [0x01], 0x15: [0x01],
    0x16: [0x01, 0x03, 0x07],
    0x17: [0x01, 0x04, 0x06, 0x07, 0x0B, 0x0C, 0x10, 0x12, 0x15, 0x17],
    0x18: [0x01, 0x02, 0x04, 0x05, 0x06, 0x09],
    0x19: [0x01, 0x04],
    0x1A: [0x01, 0x03, 0x07, 0x05, 0x06],
    0x1B: [0x01, 0x0F, 0x19, 0x1A],
    0x1D: [0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08, 0x09, 0x0A],
    0x20: [0x01, 0x02, 0x03, 0x04, 0x09, 0x0A],
    0x22: [0x01],
    0x23: [0x02, 0x0B],
    0x24: [0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08, 0x09, 0x0A, 0x0B, 0x0C],
    0x25: [0x02, 0x04, 0x0E],
    0x26: [0x02, 0x03],
    0x27: [0x01, 0x0E],
    0x2A: [0x01, 0x06],
    0x2B: [0x12],
    0x2D: [0x01],
    0x2E: [0x01, 0x02, 0x03],
    0x30: [0x01],
    0x32: [0x01],
    0x33: [0x01, 0x02],
    0x34: [0x01],
    0x35: [0x03, 0x04],
}


def link_params():
    t = TLV().put(0x01).put(0x02).put(0x03).put(0x04)
    return Packet(Service.DEVICE_CONFIG, DC.LINK_PARAMS, t, encrypt=False, sliced=False)


def parse_link_params(tlv):
    v5 = tlv.get_bytes(0x05)
    return {
        "protocol_version": tlv.get_byte(0x01, 0),
        "slice_size": tlv.get_short(0x02) if tlv.contains(0x02) else 0xF4,
        "mtu": tlv.get_short(0x03) if tlv.contains(0x03) else 0x14,
        "interval": tlv.get_short(0x04) if tlv.contains(0x04) else 0,
        "auth_version": v5[1],
        "server_nonce": v5[2:18],
        "device_support_type": tlv.get_byte(0x07, 0),
        "auth_algo": tlv.get_byte(0x08, 0),
        "bond_state": tlv.get_byte(0x09, 0),
        "encrypt_method": tlv.get_byte(0x0C, 0),
    }


def device_status(ask_status=True):
    t = TLV().put(0x01) if ask_status else TLV().put_byte(0x02, 0x00)
    return Packet(Service.DEVICE_CONFIG, DC.DEVICE_STATUS, t, encrypt=False)


def parse_device_status(tlv):
    if tlv.contains(0x01):
        return tlv.get_signed_byte(0x01)
    return -1


def security_negotiation(auth_mode, device_uuid, phone_model, encrypt_method):
    t = TLV().put_byte(0x01, auth_mode)
    if auth_mode in (0x02, 0x04):
        t.put_byte(0x02, 0x01)  # force "not reconnected"
    t.put(0x05, device_uuid).put_byte(0x03, 0x01).put_byte(0x04, 0x00)
    if auth_mode == 0x04:
        t.put(0x06).put(0x07, phone_model)
    if encrypt_method == 1:
        t.put_byte(0x0D, 0x01)
    return Packet(Service.DEVICE_CONFIG, DC.SECURITY_NEGOTIATION, t, encrypt=False)


def parse_security_negotiation(tlv):
    """Returns (auth_type, response_nonce) exactly as Gadgetbridge derives them."""
    auth_type = -1
    pw = -1
    if tlv.contains(0x01):
        b = tlv.get_byte(0x01)
        if b == 0x01:
            auth_type = 0x0186A0
        if b == 0x04:
            pw = 4
    if tlv.contains(0x02):
        auth_type = tlv.get_signed_byte(0x02)
        if pw != -1:
            auth_type ^= pw
    if tlv.contains(0x7F):
        b = tlv.get_bytes(0x7F)[0]
        auth_type = b - 256 if b > 127 else b
    return auth_type, tlv.get_bytes(0x03, None)


def extended_account(pairing_optimization, account=""):
    """AccountRelated.SendExtendedAccountToDevice; no Huawei account -> 0x00."""
    t = TLV()
    if account:
        t.put(0x01, account)
    else:
        t.put_byte(0x01, 0x00)
    if pairing_optimization:
        t.put_byte(0x03, 0x01)
    return Packet(Service.ACCOUNT, AC.EXTENDED_ACCOUNT, t)


def setting_related():
    t = TLV()
    for tag in range(0x01, 0x07):
        t.put(tag)
    return Packet(Service.DEVICE_CONFIG, DC.SETTING_RELATED, t)


def reverse_capabilities():
    """Capabilities of the phone side, the bit set Gadgetbridge announces."""
    return Packet(Service.DEVICE_CONFIG, DC.REVERSE_CAPABILITIES,
                  TLV().put(0x01, bytes([0xFD, 0xF7, 0x33, 0xFA, 0x29, 0x37])))


def set_up_device_status(device_name, relationship=1):
    """Tells the watch which phone it belongs to (1 = main device). Never answered."""
    t = TLV().put_byte(0x01, relationship).put(0x02, device_name).put_byte(0x03, 0x00)
    return Packet(Service.DEVICE_CONFIG, DC.SET_UP_DEVICE_STATUS, t)


def wear_status():
    return Packet(Service.DEVICE_CONFIG, DC.WEAR_STATUS, TLV().put(0x01))


def connect_status():
    return Packet(Service.DEVICE_CONFIG, DC.CONNECT_STATUS, TLV().put_byte(0x01, 0x01))


def pin_code_request():
    return Packet(Service.DEVICE_CONFIG, DC.PIN_CODE, TLV().put(0x01), encrypt=False)


def auth_request(params, challenge, nonce):
    t = TLV().put(0x01, challenge).put(0x02, nonce)
    if params.auth_mode == 0x02:
        t.put_byte(0x03, params.auth_algo)
    return Packet(Service.DEVICE_CONFIG, DC.AUTH, t, encrypt=False)


def bond_params_request(client_serial, mac):
    t = TLV().put(0x01).put(0x03, client_serial).put_byte(0x04, 0x02).put(0x05).put(0x07, mac).put(0x09)
    return Packet(Service.DEVICE_CONFIG, DC.BOND_PARAMS, t, encrypt=False)


def bond_request(client_serial, key, iv):
    t = TLV().put(0x01).put_byte(0x03, 0x00).put(0x05, client_serial).put(0x06, key).put(0x07, iv)
    return Packet(Service.DEVICE_CONFIG, DC.BOND, t, encrypt=False)


def product_info():
    t = TLV()
    for tag in (0x01, 0x02, 0x07, 0x09, 0x0A, 0x11, 0x12, 0x16, 0x1A, 0x1D, 0x1E, 0x1F, 0x20, 0x21, 0x22, 0x23):
        t.put(tag)
    return Packet(Service.DEVICE_CONFIG, DC.PRODUCT_INFO, t)


def parse_product_info(tlv):
    return {
        "hardware_version": tlv.get_string(0x03, ""),
        "software_version": tlv.get_string(0x07, ""),
        "serial_number": tlv.get_string(0x09, ""),
        "model": tlv.get_string(0x0A, "").strip(),
        "device_name": tlv.get_string(0x11, ""),
    }


def local_zone_id():
    tz = os.environ.get("TZ", "").lstrip(":")
    if tz and "/" in tz:
        return tz
    try:
        target = os.path.realpath("/etc/localtime")
        if "zoneinfo/" in target:
            return target.split("zoneinfo/", 1)[1]
    except OSError:
        pass
    try:
        with open("/etc/timezone") as f:
            return f.read().strip() or "UTC"
    except OSError:
        return "UTC"


def _java_div(a, b):
    q = abs(a) // abs(b)
    return q if (a >= 0) == (b > 0) else -q


def time_and_zone(now=None, zone_id=None):
    """HuaweiUtil.getTimeAndZoneId: int epoch, hour byte, minute byte, zone id."""
    if now is None:
        now = time.time()
    offset = time.localtime(now).tm_gmtoff
    hours = (_java_div(-offset, 3600) + 128) if offset < 0 else _java_div(offset, 3600)
    minutes_total = _java_div(offset, 60)
    minutes = minutes_total - _java_div(minutes_total, 60) * 60
    zone = (zone_id or local_zone_id()).encode("utf-8")
    return struct.pack(">I", int(now) & 0xFFFFFFFF) + bytes([hours & 0xFF, minutes & 0xFF]) + zone


def set_time(now=None):
    tz = time_and_zone(now)
    t = TLV().put(0x01, tz[0:4]).put(0x02, tz[4:6])
    return Packet(Service.DEVICE_CONFIG, DC.TIME, t)


def timezone_id(now=None):
    tz = time_and_zone(now)
    t = TLV().put(0x01, tz[0:4]).put(0x02, tz[4:6]).put(0x03, tz[6:])
    return Packet(Service.DEVICE_CONFIG, DC.TIMEZONE_ID, t)


def date_format(date_fmt, time_fmt):
    """date: 1 year first, 2 month first, 3 day first. time: 1 = 12h, 2 = 24h."""
    t = TLV().put(0x81, TLV().put_byte(0x02, date_fmt).put_byte(0x03, time_fmt))
    return Packet(Service.DEVICE_CONFIG, DC.DATE_FORMAT, t)


def battery_level():
    return Packet(Service.DEVICE_CONFIG, DC.BATTERY, TLV().put(0x01))


def parse_battery(tlv):
    return tlv.get_byte(0x01, -1)


def supported_services():
    return Packet(Service.DEVICE_CONFIG, DC.SUPPORTED_SERVICES, TLV().put(0x01, KNOWN_SUPPORTED_SERVICES))


def parse_supported_services(tlv):
    bitmap = tlv.get_bytes(0x02)
    active = [0x01]
    for i, flag in enumerate(bitmap):
        if flag == 1 and i < len(KNOWN_SUPPORTED_SERVICES):
            active.append(KNOWN_SUPPORTED_SERVICES[i])
    return active


def supported_commands_batches(params, services):
    """Split the supported-commands query into packets that fit a slice."""
    max_size = params.slice_size - 32
    max_size = max_size - (max_size % 16) - 4
    batches = []
    pending = [s for s in services if s in COMMANDS_PER_SERVICE]
    while pending:
        inner = TLV()
        while pending:
            cmds = bytes(COMMANDS_PER_SERVICE[pending[0]])
            if len(inner) + len(cmds) + 5 > max_size and inner.items:
                break
            inner.put_byte(0x02, pending[0]).put(0x03, cmds)
            pending.pop(0)
        batches.append(Packet(Service.DEVICE_CONFIG, DC.SUPPORTED_COMMANDS, TLV().put(0x81, inner)))
    return batches


def parse_supported_commands(tlv):
    """Returns {service: [commands]}."""
    result = {}
    service = None
    for tag, value in tlv.get_object(0x81).items:
        if tag == 0x02:
            service = value[0]
        elif tag == 0x04 and service is not None:
            known = COMMANDS_PER_SERVICE.get(service, [])
            result[service] = [known[i] for i, f in enumerate(value) if f == 1 and i < len(known)]
    return result


def expand_capability():
    return Packet(Service.DEVICE_CONFIG, DC.EXPAND_CAPABILITY, TLV().put(0x01))


def accept_agreement(now_ms=None):
    ts = str(int(now_ms if now_ms is not None else time.time() * 1000))
    lst = TLV()
    for name in ("software_update_service_statement", "device_information_management", "user_license_agreement"):
        lst.put(0x82, TLV().put(0x03, name).put_byte(0x04, 0x01).put(0x05, "20230508-20230508-0-0").put(0x06, ts))
    return Packet(Service.DEVICE_CONFIG, DC.ACCEPT_AGREEMENT, TLV().put(0x81, lst))


def language(locale_str, imperial=False):
    t = TLV().put(0x01, locale_str).put_byte(0x02, 0x01 if imperial else 0x00)
    return Packet(Service.LOCALE, 0x01, t)


# --- Notifications -------------------------------------------------------------

class NotificationType:
    CALL = 0x01
    SMS = 0x02
    STOP = 0x0C
    MISSED_CALL = 0x0E
    EMAIL = 0x0F
    GENERIC = 0x7F


class TextType:
    TEXT = 0x01
    SENDER = 0x02
    TITLE = 0x03


def notification(msg_id, notification_type, title, sender, body, source_app_id, encoding=0x02, params=None):
    """NotificationActionRequest. `params` is a dict of additional parameters."""
    t = TLV().put_short(0x01, msg_id).put_byte(0x02, notification_type).put(0x03, True)
    sub = TLV()
    for text_type, value in ((TextType.TITLE, title), (TextType.SENDER, sender), (TextType.TEXT, body)):
        el = TLV().put_byte(0x0E, text_type).put_byte(0x0F, encoding)
        if value:
            el.put(0x10, value)
        sub.put(0x8D, el)
    t.put(0x84, TLV().put(0x8C, sub))
    if source_app_id is not None:
        t.put(0x11, source_app_id[:127])
    if params:
        if params.get("category"):
            t.put(0x12, params["category"])
        if params.get("supports_reply"):
            t.put(0x18, params.get("reply_key", ""))
        if params.get("supports_timestamp"):
            t.put_int(0x15, int(time.time()))
        if params.get("supports_repeated_notify") or params.get("supports_remove_single"):
            t.put(0x19, params.get("key", ""))
            t.put_int(0x1A, params.get("id", 0))
            t.put(0x1B, params.get("channel_id", ""))
        if params.get("when"):
            t.put_long(0x32, params["when"])
    return Packet(Service.NOTIFICATIONS, NC.ACTION, t)


def notification_remove(msg_type, source_app_id, key, notification_id, channel_id, category=None):
    t = TLV().put_byte(0x01, msg_type).put(0x02, source_app_id).put(0x03, key).put_int(0x04, notification_id) \
        .put(0x05, channel_id)
    if category:
        t.put(0x06, category)
    return Packet(Service.NOTIFICATIONS, NC.REMOVE, t)


def notification_state(enabled):
    t = TLV().put(0x81, TLV().put(0x02, bool(enabled)).put(0x03, bool(enabled)))
    return Packet(Service.NOTIFICATIONS, NC.STATE, t)


def wear_message_push(dnd_when_not_worn):
    # Value sent is the opposite of the switch status
    return Packet(Service.NOTIFICATIONS, NC.WEAR_MESSAGE_PUSH, TLV().put(0x01, not dnd_when_not_worn))


def notification_constraints():
    return Packet(Service.NOTIFICATIONS, NC.CONSTRAINTS, TLV().put(0x01))


def parse_notification_constraints(tlv):
    """Returns dict with content_format/content_length (+ incoming number info)."""
    out = {}
    container = tlv.get_object(0x81).get_object(0x82).get_object(0x90)
    for sub in container.get_objects(0x91):
        kind = sub.get_byte(0x12, 0)
        if kind == 0x01:
            out["content_format"] = 0x02  # Always 0x02 even if gadget reports 0x03
            out["content_length"] = sub.get_as_int(0x14, 0) & 0xFFFF
        elif kind == 0x07:
            out["incoming_number"] = True
            out["incoming_number_format"] = sub.get_as_int(0x13, 0x02) & 0xFFFF
    return out


# --- Calls / find phone --------------------------------------------------------

def find_phone_stop():
    return Packet(Service.FIND_PHONE, 0x02, TLV().put_byte(0x01, 0x02))


# --- Weather -------------------------------------------------------------------

class Icon:
    SUNNY = 0x00
    CLOUDY = 0x01
    OVERCAST = 0x02
    SHOWERS = 0x03
    THUNDERSTORMS = 0x04
    THUNDER_AND_HAIL = 0x05
    SLEET = 0x06
    LIGHT_RAIN = 0x07
    RAIN = 0x08
    HEAVY_RAIN = 0x09
    RAIN_STORM = 0x0A
    HEAVY_RAIN_STORMS = 0x0B
    SEVERE_RAIN_STORMS = 0x0C
    SNOW_FLURRIES = 0x0D
    LIGHT_SNOW = 0x0E
    SNOW = 0x0F
    HEAVY_SNOW = 0x10
    SNOWSTORMS = 0x11
    FOG = 0x12
    FREEZING_RAIN = 0x13
    DUST_STORM = 0x14
    DUST = 0x1D
    SAND = 0x1E
    WINDY = 0x23
    HAZY = 0x35
    UNKNOWN = 0x63


def new_weather_settings():
    return {
        "weather": False, "wind": False, "pm25": False, "temperature": False, "location_name": False,
        "current_temperature": False, "unit": False, "aqi": False,
        "time": False, "source": False, "icon": False, "extended_hourly": False,
        "sun_rise_set": False, "moon_phase": False, "uv_index": False,
    }


def weather_start():
    return Packet(Service.WEATHER, WC.START, TLV().put_byte(0x01, 0x03))


def parse_weather_start(tlv):
    code = tlv.get_int(0x7F, -1)
    return code in (0x000186A0, 0x000186A3)


def weather_support():
    return Packet(Service.WEATHER, WC.SUPPORT, TLV().put(0x01))


def apply_weather_support(settings, tlv):
    b = tlv.get_byte(0x01)
    for bit, key in enumerate(("weather", "wind", "pm25", "temperature", "location_name",
                               "current_temperature", "unit", "aqi")):
        settings[key] = bool(b & (1 << bit))


def weather_extended_support():
    return Packet(Service.WEATHER, WC.EXTENDED_SUPPORT, TLV().put(0x01))


def apply_weather_extended_support(settings, tlv):
    b = tlv.get_short(0x01)
    settings["time"] = bool(b & 0x01)
    settings["source"] = bool(b & 0x02)
    settings["icon"] = bool(b & 0x04)


def weather_sun_moon_support():
    return Packet(Service.WEATHER, WC.SUN_MOON_SUPPORT, TLV().put(0x01))


def apply_weather_sun_moon_support(settings, tlv):
    b = tlv.get_as_int(0x01)
    settings["sun_rise_set"] = bool(b & 0x01)
    settings["moon_phase"] = bool(b & 0x02)


def weather_unit(fahrenheit=False):
    return Packet(Service.WEATHER, WC.UNIT, TLV().put_byte(0x01, 1 if fahrenheit else 0))


def weather_device_ack():
    return Packet(Service.WEATHER, WC.DEVICE_REQUEST, TLV().put_int(0x01, RESULT_SUCCESS), encrypt=False)


def weather_error(extended, error_code):
    """error_code: 0 network, 1 gps permission, 2 weather disabled."""
    if extended:
        return Packet(Service.WEATHER, WC.ERROR_EXTENDED, TLV().put(0x81, TLV().put_byte(0x02, error_code)))
    return Packet(Service.WEATHER, WC.ERROR_SIMPLE, TLV().put_byte(0x01, error_code))


def _wind_direction(degrees):
    """no wind - 0, NE - 1, E - 2, SE - 3, S - 4, SW - 5, W - 6, NW - 7, N - 8"""
    if degrees is None or degrees < 0 or degrees > 360:
        return 0
    val = int(degrees / 45.0 + 0.5) % 8
    return 8 if val == 0 else val


def current_weather(settings, w):
    """`w` is a watchbridge.weather.WeatherReport."""
    t = TLV()
    t81 = TLV()
    if settings["icon"] and w.icon is not None:
        t81.put_byte(0x02, w.icon)
    if settings["wind"]:
        wind = (w.wind_beaufort or 0) & 0xFF
        if w.wind_direction is not None:
            wind |= _wind_direction(w.wind_direction) << 8
        t81.put_short(0x03, wind)
    if settings["icon"] or settings["wind"]:
        t.put(0x81, t81)
    if settings["temperature"] and w.temp_min is not None and w.temp_max is not None:
        t.put(0x85, TLV().put_byte(0x06, w.temp_min).put_byte(0x07, w.temp_max))
    if settings["location_name"] and w.location:
        t.put(0x08, w.location)
    if settings["current_temperature"] and w.temperature is not None:
        t.put_byte(0x09, w.temperature)
    if settings["unit"]:
        t.put_byte(0x0A, 1 if w.fahrenheit else 0)
    if settings["time"] and w.observation_time:
        t.put_int(0x0C, w.observation_time)
    if settings["source"]:
        t.put(0x0E, w.source or "WatchBridge")
    if settings["uv_index"] and w.uv_index is not None:
        t.put_byte(0x0F, int(round(w.uv_index)))
    if settings["extended_hourly"]:
        if w.humidity is not None:
            t.put_byte(0x10, w.humidity)
        if w.wind_speed is not None:
            t.put_int(0x11, int(round(w.wind_speed)))
        if w.feels_like is not None:
            t.put_int(0x12, w.feels_like)
    return Packet(Service.WEATHER, WC.CURRENT, t)


def weather_forecast(settings, w):
    t = TLV()
    if w.hourly:
        hours = TLV()
        for h in w.hourly[:24]:
            ht = TLV().put_int(0x03, h.timestamp)
            if settings["icon"] and h.icon is not None:
                ht.put_byte(0x04, h.icon)
            if (settings["temperature"] or settings["current_temperature"]) and h.temperature is not None:
                ht.put_byte(0x05, h.temperature)
            if settings["extended_hourly"]:
                if h.precipitation is not None:
                    ht.put_byte(0x06, h.precipitation)
                if h.uv_index is not None:
                    ht.put_byte(0x07, int(round(h.uv_index)))
            hours.put(0x82, ht)
        t.put(0x81, hours)
    if w.daily:
        days = TLV()
        for d in w.daily[:8]:
            dt = TLV().put_int(0x12, d.timestamp)
            if settings["icon"] and d.icon is not None:
                dt.put_byte(0x13, d.icon)
            if settings["temperature"]:
                if d.temp_max is not None:
                    dt.put_byte(0x14, d.temp_max)
                if d.temp_min is not None:
                    dt.put_byte(0x15, d.temp_min)
            if settings["sun_rise_set"]:
                if d.sunrise:
                    dt.put_int(0x16, d.sunrise)
                if d.sunset:
                    dt.put_int(0x17, d.sunset)
            if settings["moon_phase"] and d.moon_phase:
                dt.put_byte(0x1E, d.moon_phase)
            days.put(0x91, dt)
        t.put(0x90, days)
    return Packet(Service.WEATHER, WC.FORECAST, t)
