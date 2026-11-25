# WatchBridge - Huawei Watch GT 5 companion for Sailfish OS
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# Ported from Gadgetbridge (devices/huawei/packets/Watchface.java, FileUpload.java,
# service/devices/huawei/HuaweiWatchfaceManager.java, HuaweiUploadManager.java,
# HuaweiFwHelper.java, AsynchronousResponse.java (handleFileUpload, handleWatchface),
# devices/huawei/HuaweiPacket.java (serializeFileChunk)),
# Copyright (C) 2024 Vitalii Tomin, Damien Gaignon, Martin.JM.
# Translated to Python and modified for WatchBridge, 2026. See NOTICE.md.
"""Watch faces: the .hwt package format, the watch-face service (0x27) and the
file upload service (0x28) that carries the face to the watch."""

import hashlib
import io
import logging
import random
import struct
import xml.etree.ElementTree as ET
import zipfile

from .packet import Packet
from .tlv import TLV

log = logging.getLogger(__name__)

RESULT_SUCCESS = 0x000186A0

WATCHFACE_SERVICE = 0x27
UPLOAD_SERVICE = 0x28


class WF:
    """Watch-face service command ids."""
    PARAMS = 0x01
    LIST = 0x02          # DeviceWatchInfo
    OPERATION = 0x03
    CONFIRM = 0x05
    NAMES = 0x06


class UP:
    """File upload service command ids."""
    FILE_INFO = 0x02
    HASH = 0x03
    CONSULT = 0x04
    NEXT_CHUNK = 0x05    # the watch asks for the next part
    CHUNK = 0x06         # raw data from the phone
    RESULT = 0x07
    DEVICE_ERROR = 0x08


FILETYPE_WATCHFACE = 1

OPERATION_ACTIVATE = 1
OPERATION_DELETE = 2

# Error codes the watch reports for an upload (HuaweiSupportProvider.onInstallApp)
UPLOAD_ERRORS = {
    140004: "Too many watch faces are installed. Delete one on the watch first.",
    140008: "This watch face is already installed.",
    140009: "Not enough space on the watch.",
}

# description.xml <screen> -> "height*width" (HuaweiWatchfaceManager.Resolution)
SCREENS = {
    "HWHD01": "390*390", "HWHD02": "454*454", "HWHD03": "240*120", "HWHD04": "160*80",
    "HWHD05": "460*188", "HWHD06": "456*280", "HWHD07": "368*194", "HWHD08": "320*320",
    "HWHD09": "466*466", "HWHD10": "360*320", "HWHD11": "480*336", "HWHD12": "240*240",
    "HWHD13": "480*408", "HWHD14": "482*286",
    "HNHD01": "466*466", "HNHD02": "368*194", "HNHD03": "450*390", "HNHD04": "454*454",
    "HNHD05": "402*256", "QXHD01": "402*256", "QXHD02": "502*410",
}


class WatchfaceFileError(Exception):
    pass


# ------------------------------------------------------------------ .hwt files

class WatchfacePackage:
    """A watch-face package (.hwt): a zip with description.xml, an optional preview
    (preview/cover.jpg) and the face itself in com.huawei.watchface (a zip holding
    watchface.bin, or on older faces the binary itself). HuaweiFwHelper.parseAsWatchFace."""

    def __init__(self, data):
        try:
            outer = zipfile.ZipFile(io.BytesIO(data))
        except zipfile.BadZipFile:
            raise WatchfaceFileError("This is not a watch face package (not a zip file)")
        names = set(outer.namelist())
        if "description.xml" not in names:
            raise WatchfaceFileError("This is not a watch face package (no description.xml)")
        self._parse_description(outer.read("description.xml"))
        self.preview = outer.read("preview/cover.jpg") if "preview/cover.jpg" in names else None
        inner_name = "com.honor.watchface" if self.honor else "com.huawei.watchface"
        if inner_name not in names:
            raise WatchfaceFileError("The package does not contain %s" % inner_name)
        inner = outer.read(inner_name)
        try:
            self.binary = zipfile.ZipFile(io.BytesIO(inner)).read("watchface.bin")
        except (zipfile.BadZipFile, KeyError):
            self.binary = inner  # older faces: already the binary
        if not self.binary:
            raise WatchfaceFileError("The watch face inside the package is empty")

    def _parse_description(self, raw):
        if raw.startswith(b"\xef\xbb\xbf"):
            raw = raw[3:]
        try:
            root = ET.fromstring(raw)
        except ET.ParseError as e:
            raise WatchfaceFileError("description.xml is not valid XML: %s" % e)
        self.honor = root.tag == "HnTheme"

        def text(tag):
            el = root.find(".//" + tag)
            return (el.text or "").strip() if el is not None else ""

        self.title = text("title") or text("title-cn") or "Watch face"
        self.author = text("author") or text("designer")
        self.version = text("version")
        self.screen = text("screen")

    @property
    def resolution(self):
        """"height*width" the face was made for, or "" if the screen id is unknown."""
        return SCREENS.get(self.screen, "")

    def fits(self, height, width):
        return self.resolution == "%d*%d" % (height, width)

    def info(self):
        return {"title": self.title, "author": self.author, "version": self.version,
                "screen": self.screen, "resolution": self.resolution, "size": len(self.binary),
                "honor": self.honor}


def random_file_name(version="1.0.0"):
    """Name the watch files the face under: id_version (HuaweiWatchfaceManager.getRandomName)."""
    return "%09d_%s" % (random.randrange(1000000000), version)


def _version_key(v):
    try:
        return tuple(int(x) for x in v.split("."))
    except ValueError:
        return (999,)


def supported_versions(params):
    """Face-format versions the watch accepts, oldest first (0x27/0x01 tags 1 and 6)."""
    if not params:
        return []
    found = {v.strip() for v in (params.get("other_versions") or "").split(",") if v.strip()}
    if params.get("max_version"):
        found.add(params["max_version"].strip())
    return sorted(found, key=_version_key)


def upload_version(params):
    """The version to register an uploaded face under.

    Every face from Huawei's store on a GT 5 carries one of the versions the watch lists in
    its params (2.1 .. 2.9), so register uploads the same way: the oldest supported version,
    or Gadgetbridge's fixed 1.0.0 when the watch names none. (A face made for the Huawei
    Watch 4 rendered garbled on a GT 5 under both 1.0.0 and 2.1.0, so the version was not
    the cause there; the file itself did not suit the watch.)
    """
    versions = supported_versions(params)
    return (versions[0] + ".0") if versions else "1.0.0"


# --------------------------------------------------------- watch-face service

def params_request():
    t = TLV()
    for tag in (0x01, 0x02, 0x03, 0x04, 0x05, 0x0E, 0x0F):
        t.put(tag)
    return Packet(WATCHFACE_SERVICE, WF.PARAMS, t)


def parse_params(tlv):
    return {
        "max_version": tlv.get_string(0x01, ""),
        "width": tlv.get_as_int(0x02, 0),
        "height": tlv.get_as_int(0x03, 0),
        "file_type": tlv.get_byte(0x04, 1),
        "sort": tlv.get_byte(0x05, 1),
        "other_versions": tlv.get_string(0x06, ""),
    }


def list_request():
    # 0x06: 3 = overseas, non-test
    return Packet(WATCHFACE_SERVICE, WF.LIST, TLV().put(0x01).put_byte(0x06, 0x03))


def parse_list(tlv):
    faces = []
    if tlv.contains(0x81):
        for sub in tlv.get_object(0x81).get_objects(0x82):
            kind = sub.get_byte(0x05, 0)
            faces.append({
                "file": sub.get_string(0x03, ""),
                "version": sub.get_string(0x04, ""),
                "current": bool(kind & 0x01),
                "factory": bool(kind & 0x02),
                "editable": bool(kind & 0x08),
                "trial": bool(kind & 0x40),
            })
    return faces


def names_request(files):
    lst = TLV()
    for name in files:
        lst.put(0x83, TLV().put(0x04, name))
    return Packet(WATCHFACE_SERVICE, WF.NAMES, TLV().put_byte(0x01, 0x01).put(0x82, lst))


def parse_names(tlv):
    out = {}
    if tlv.contains(0x82):
        for sub in tlv.get_object(0x82).get_objects(0x83):
            out[sub.get_string(0x04, "")] = sub.get_string(0x05, "")
    return out


def operation_request(file_name, version, operation):
    t = TLV().put(0x01, file_name).put(0x02, version).put_byte(0x03, operation)
    return Packet(WATCHFACE_SERVICE, WF.OPERATION, t)


def confirm_request(file_name, version):
    t = TLV().put(0x01, file_name).put(0x02, version).put_int(0x7F, RESULT_SUCCESS)
    return Packet(WATCHFACE_SERVICE, WF.CONFIRM, t)


# --------------------------------------------------------------- file upload

def file_info_request(file_name, size, file_type=FILETYPE_WATCHFACE, packages=None):
    """`packages`: (source, destination, source fingerprint, destination fingerprint) when
    the file is for an app on the watch."""
    t = TLV().put(0x01, file_name).put_int(0x02, size).put_byte(0x03, file_type)
    if file_type == FILETYPE_WATCHFACE:
        name, _, version = file_name.partition("_")
        t.put(0x05, name).put(0x06, version)
    if packages is not None:
        source, destination, source_print, destination_print = packages
        t.put(0x08, source).put(0x09, destination).put(0x0A).put(0x0B, source_print).put(0x0C, destination_print)
    return Packet(UPLOAD_SERVICE, UP.FILE_INFO, t)


def hash_request(file_id, sha256):
    return Packet(UPLOAD_SERVICE, UP.HASH, TLV().put_byte(0x01, file_id).put(0x03, sha256))


def consult_ack(file_id, no_encrypt):
    t = TLV().put_int(0x7F, RESULT_SUCCESS).put_byte(0x01, file_id)
    if no_encrypt:
        t.put_byte(0x09, 0x01)  # files go unencrypted although the link is encrypted
    return Packet(UPLOAD_SERVICE, UP.CONSULT, t)


def parse_consult(tlv):
    return {
        "file_id": tlv.get_byte(0x01, 0),
        "protocol": tlv.get_string(0x02, ""),
        "wait_time": tlv.get_as_int(0x03, 0),
        "bitmap": tlv.get_as_int(0x04, 0),
        "unit_size": tlv.get_as_int(0x05, 0),
        "max_apply_size": tlv.get_as_int(0x06, 0),
        "interval": tlv.get_as_int(0x07, 0),
        "received": tlv.get_as_int(0x08, 0),
        "no_encrypt": tlv.get_byte(0x09, 0),
    }


def chunk_packets(file_id, data, offset, unit_size, encrypt):
    """The part the watch asked for, in unit_size pieces: file id, piece index,
    offset (big endian), data (HuaweiPacket.serializeFileChunk)."""
    out = []
    pos = 0
    index = 0
    while pos < len(data):
        piece = data[pos:pos + unit_size]
        body = struct.pack(">BBI", file_id, index & 0xFF, offset + pos) + piece
        out.append(Packet.raw_packet(UPLOAD_SERVICE, UP.CHUNK, body, encrypt=encrypt))
        pos += len(piece)
        index += 1
    return out


def result_ack(file_id):
    return Packet(UPLOAD_SERVICE, UP.RESULT, TLV().put_int(0x7F, RESULT_SUCCESS).put_byte(0x01, file_id))


class UploadError(Exception):
    def __init__(self, message, code=None):
        super().__init__(message)
        self.code = code


class Upload:
    """The phone's side of an upload, driven by the watch's 0x28 (and 0x27/0x05) packets.

    start() returns the first packet; handle() takes each packet from the watch and
    returns the packets to send. Raises UploadError when the watch refuses.
    Order (AsynchronousResponse.handleFileUpload): file info -> the watch asks for the
    hash (0x03) -> consult (0x04) with the unit size -> repeated next-chunk requests
    (0x05) -> result (0x07) -> for faces, a confirm (0x27/0x05) that may ask to activate it.
    """

    def __init__(self, data, file_name=None, file_type=FILETYPE_WATCHFACE, links_encrypted=True, packages=None):
        self.data = bytes(data)
        self.sha256 = hashlib.sha256(self.data).digest()
        self.file_name = file_name or random_file_name()
        self.file_type = file_type
        self.links_encrypted = links_encrypted
        self.packages = packages
        self.file_id = 0
        self.unit_size = 0
        self.encrypt_chunks = links_encrypted
        self.sent = 0               # bytes the watch has confirmed or asked past
        self.uploaded = False       # 0x28/0x07 received
        self.confirmed = False      # 0x27/0x05 received (faces only)
        self.activated = False

    @property
    def progress(self):
        return int(100 * self.sent / len(self.data)) if self.data else 100

    @property
    def done(self):
        return self.uploaded and (self.confirmed or self.file_type != FILETYPE_WATCHFACE)

    def start(self):
        return [file_info_request(self.file_name, len(self.data), self.file_type, self.packages)]

    def handle(self, packet):
        s, c, t = packet.service, packet.command, packet.tlv
        if s == WATCHFACE_SERVICE and c == WF.CONFIRM:
            return self._confirm(t)
        if s != UPLOAD_SERVICE:
            return []
        if c == UP.FILE_INFO:
            result = t.get_as_int(0x7F, RESULT_SUCCESS)
            if result != RESULT_SUCCESS:
                raise UploadError(UPLOAD_ERRORS.get(result, "The watch refused the file (error %d)" % result),
                                  result)
            return []
        if c == UP.HASH:
            self.file_id = t.get_byte(0x01, 0)
            return [hash_request(self.file_id, self.sha256)]
        if c == UP.CONSULT:
            p = parse_consult(t)
            self.unit_size = p["unit_size"] or 1000
            self.encrypt_chunks = self.links_encrypted and not p["no_encrypt"]
            log.info("Upload: unit size %d, %s chunks, protocol %s", self.unit_size,
                     "encrypted" if self.encrypt_chunks else "plain", p["protocol"] or "?")
            return [consult_ack(self.file_id, p["no_encrypt"])]
        if c == UP.NEXT_CHUNK:
            offset = t.get_as_int(0x02, 0)
            size = t.get_as_int(0x03, 0)
            if offset > len(self.data) or size <= 0:
                raise UploadError("The watch asked for bytes %d+%d of a %d byte file" % (offset, size, len(self.data)))
            self.sent = offset
            return chunk_packets(self.file_id, self.data[offset:offset + size], offset, self.unit_size,
                                 self.encrypt_chunks)
        if c == UP.RESULT:
            self.uploaded = True
            self.sent = len(self.data)
            return [result_ack(self.file_id)]
        if c == UP.DEVICE_ERROR:
            code = t.get_as_int(0x7F, 0)
            raise UploadError(UPLOAD_ERRORS.get(code, "The watch stopped the upload (error %d)" % code), code)
        return []

    def _confirm(self, t):
        name = t.get_string(0x01, "")
        version = t.get_string(0x02, "")
        report = t.get_as_int(0x03, 0)
        self.confirmed = True
        out = [confirm_request(name, version)]
        if report == 0x02:  # make the new face the current one
            self.activated = True
            out.append(operation_request(name, version, OPERATION_ACTIVATE))
        return out
