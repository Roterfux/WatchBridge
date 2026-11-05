# WatchBridge - Huawei Watch GT 5 companion for Sailfish OS
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# Ported from Gadgetbridge (devices/huawei/packets/FileDownloadService2C.java,
# service/devices/huawei/HuaweiFileDownloadManager.java and the requests
# GetFileDownloadInitRequest, GetFileInfoRequest, GetFileBlockRequest,
# GetFileDownloadCompleteRequest), Copyright (C) 2024 Martin.JM.
# Translated to Python and modified for WatchBridge, 2026. See NOTICE.md.
"""File download over service 0x2C ("new sync"), used for sleep, stress and more.

    phone  FileDownloadInit (name, type, time range[, dictionary id])
    watch  -> file id and size (0 = nothing to download)
    phone  FileInfo
    watch  -> timeout, burst size, max block size, whether blocks are unencrypted
    phone  RequestBlock (offset, size) ... the watch answers with several 0x2C/0x05
           data packets (raw payload, optionally an encrypted TLV) until the block is full
    phone  FileDownloadComplete (status 1 = ok)

The older service 0x0A variant is not ported: the Watch GT 5 uses 0x2C.
"""

import struct

from . import crypto
from .packet import Packet
from .tlv import TAG_CIPHERTEXT, TAG_ENCRYPTION, TAG_IV, TLV

SERVICE = 0x2C


class FD:
    INIT = 0x01
    HASH = 0x02
    INFO = 0x03
    REQUEST_BLOCK = 0x04
    BLOCK = 0x05
    COMPLETE = 0x06


class FileType:
    SLEEP_STATE = 0x0E
    SLEEP_DATA = 0x0F
    RRI = 0x10
    GPS = 0x11
    PDR = 0x12
    SEQUENCE_DATA = 0x16
    ECG_ANALYSIS_DATA = 0x18


SEQUENCE_DATA_NAME = "sequence_data"
RRI_NAME = "rrisqi_data.bin"


class FileDownloadError(Exception):
    pass


def init_request(filename, file_type, start, end, dict_id=0):
    t = TLV().put(0x01, filename).put_byte(0x02, file_type).put_int(0x05, start).put_int(0x06, end)
    if dict_id > 0 and file_type == FileType.SEQUENCE_DATA:
        t.put_int(0x0C, dict_id)
    return Packet(SERVICE, FD.INIT, t)


def parse_init(tlv):
    """Returns dict(name, type, file_id, size). size is None if the watch reported -1."""
    size = tlv.get_int(0x04)
    return {
        "name": tlv.get_string(0x01, ""),
        "type": tlv.get_byte(0x02, 0),
        "file_id": tlv.get_byte(0x03),
        "size": None if size == 0xFFFFFFFF else size,
    }


def info_request(file_id):
    return Packet(SERVICE, FD.INFO, TLV().put_byte(0x01, file_id).put(0x02).put(0x03).put(0x04).put(0x05))


def parse_info(tlv):
    return {
        "file_id": tlv.get_byte(0x01),
        "timeout": tlv.get_byte(0x02, 0),          # seconds without data before giving up
        "burst": tlv.get_short(0x03) if tlv.contains(0x03) else 0,
        "max_block": tlv.get_int(0x04),            # bytes per RequestBlock
        "no_encrypt": tlv.get_bool(0x05, False),   # RequestBlock must be sent unencrypted
    }


def block_request(file_id, offset, size, no_encrypt, dict_id=0):
    t = TLV().put_byte(0x01, file_id).put_int(0x02, offset).put_int(0x03, size)
    if dict_id > 0 and file_id == FileType.SEQUENCE_DATA:
        # Gadgetbridge compares the *file id* here, not the type; kept as is
        t.put_int(0x04, dict_id)
    return Packet(SERVICE, FD.REQUEST_BLOCK, t, encrypt=not no_encrypt)


def complete_request(file_id, status=1):
    return Packet(SERVICE, FD.COMPLETE, TLV().put_byte(0x01, file_id).put_byte(0x02, status))


def decode_block(payload, params):
    """Decode a 0x2C/0x05 raw payload (starts with service and command bytes).

    Returns (file_id, offset, data). The body is either plain or an encrypted TLV.
    """
    body = bytes(payload[2:])
    if body[:3] == bytes([TAG_ENCRYPTION, 0x01, 0x01]):
        tlv = TLV.parse(body)
        body = crypto.decrypt(params.use_gcm(), tlv.get_bytes(TAG_CIPHERTEXT), params.secret_key,
                              tlv.get_bytes(TAG_IV))
    if len(body) < 6:
        raise FileDownloadError("File block too short (%d bytes)" % len(body))
    file_id = body[0]
    offset = struct.unpack(">I", body[1:5])[0]
    return file_id, offset, body[6:]
