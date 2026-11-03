# WatchBridge - Huawei Watch GT 5 companion for Sailfish OS
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Direct RFCOMM connection to a service UUID, like Android's
createRfcommSocketToServiceRecord: an SDP search for the UUID finds the
RFCOMM channel, then a plain RFCOMM socket is opened to it.

BlueZ's ConnectProfile only works when the UUID was seen in the SDP browse
done at pairing time; vendor records outside the public browse group are
missed there, but a search by UUID still finds them.

Python's socket module is used when built with Bluetooth support, otherwise
the sockets are created through libc.
"""

import ctypes
import errno
import logging
import os
import socket
import struct
import uuid as uuidlib

log = logging.getLogger(__name__)

AF_BLUETOOTH = 31
BTPROTO_L2CAP = 0
BTPROTO_RFCOMM = 3
SOL_BLUETOOTH = 274
BT_SECURITY = 4
BT_SECURITY_MEDIUM = 2
SDP_PSM = 1
UUID_RFCOMM = 0x0003
ATTR_PROTOCOL_DESCRIPTOR_LIST = 0x0004

CONNECT_TIMEOUT = 20.0


class RfcommError(Exception):
    pass


# ------------------------------------------------------------------ sockets
def _native():
    return hasattr(socket, "AF_BLUETOOTH") and hasattr(socket, "BTPROTO_RFCOMM")


def _bdaddr(address):
    return bytes.fromhex(address.replace(":", ""))[::-1]


def _libc_connect(sock_type, proto, sockaddr, timeout):
    libc = ctypes.CDLL(None, use_errno=True)
    fd = libc.socket(AF_BLUETOOTH, sock_type, proto)
    if fd < 0:
        e = ctypes.get_errno()
        raise RfcommError("Bluetooth socket: %s" % os.strerror(e))
    try:
        _set_security(fd, libc)
        tv = struct.pack("ll", int(timeout), 0)  # struct timeval; bounds the blocking connect()
        libc.setsockopt(fd, socket.SOL_SOCKET, socket.SO_SNDTIMEO, tv, len(tv))
        buf = ctypes.create_string_buffer(sockaddr, len(sockaddr) + 1)
        if libc.connect(fd, buf, len(sockaddr) + 1) != 0:
            e = ctypes.get_errno()
            raise RfcommError(os.strerror(e) if e != errno.EINPROGRESS else "Connection timed out")
        s = socket.socket(fileno=fd)
        fd = -1
        s.setblocking(True)
        return s
    finally:
        if fd >= 0:
            os.close(fd)


def _set_security(fd_or_sock, libc=None):
    value = struct.pack("BB", BT_SECURITY_MEDIUM, 0)
    try:
        if libc is None:
            fd_or_sock.setsockopt(SOL_BLUETOOTH, BT_SECURITY, value)
        else:
            libc.setsockopt(fd_or_sock, SOL_BLUETOOTH, BT_SECURITY, value, len(value))
    except OSError as e:
        log.debug("BT_SECURITY: %s", e)


def _connect_l2cap(address, psm, timeout):
    if _native():
        s = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_SEQPACKET, socket.BTPROTO_L2CAP)
        s.settimeout(timeout)
        try:
            s.connect((address, psm))
        except OSError:
            s.close()
            raise
        return s
    sockaddr = struct.pack("<HH6sHB", AF_BLUETOOTH, psm, _bdaddr(address), 0, 0)
    s = _libc_connect(socket.SOCK_SEQPACKET, BTPROTO_L2CAP, sockaddr, timeout)
    s.settimeout(timeout)
    return s


def _connect_rfcomm(address, channel, timeout):
    if _native():
        s = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM)
        _set_security(s)
        s.settimeout(timeout)
        try:
            s.connect((address, channel))
        except OSError:
            s.close()
            raise
        s.settimeout(None)
        return s
    sockaddr = struct.pack("<H6sB", AF_BLUETOOTH, _bdaddr(address), channel)
    return _libc_connect(socket.SOCK_STREAM, BTPROTO_RFCOMM, sockaddr, timeout)


# ---------------------------------------------------------------------- SDP
def _parse_element(data, pos):
    """Returns (value, next_pos). Sequences become lists, UUIDs ints (16/32 bit) or bytes."""
    header = data[pos]
    kind, size_idx = header >> 3, header & 0x07
    pos += 1
    if kind == 0:
        return None, pos
    if size_idx < 5:
        length = (1, 2, 4, 8, 16)[size_idx]
    else:
        n = (1, 2, 4)[size_idx - 5]
        length = int.from_bytes(data[pos:pos + n], "big")
        pos += n
    raw = data[pos:pos + length]
    if len(raw) != length:
        raise RfcommError("Truncated SDP data")
    end = pos + length
    if kind in (1, 2):  # unsigned / signed integer
        return int.from_bytes(raw, "big", signed=(kind == 2)), end
    if kind == 3:  # UUID
        return (int.from_bytes(raw, "big") if length <= 4 else bytes(raw)), end
    if kind in (6, 7):  # sequence / alternative
        items, p = [], pos
        while p < end:
            item, p = _parse_element(data, p)
            items.append(item)
        return items, end
    if kind == 5:
        return bool(raw[0]), end
    return bytes(raw), end  # string / URL


def _search_attributes(sock, service_uuid):
    pattern = b"\x35\x11\x1c" + uuidlib.UUID(service_uuid).bytes
    attrs = b"\x35\x05\x0a\x00\x00\xff\xff"  # all attributes
    result = b""
    cont = b"\x00"
    tid = 1
    while True:
        params = pattern + struct.pack(">H", 0xFFFF) + attrs + cont
        sock.send(struct.pack(">BHH", 0x06, tid, len(params)) + params)
        reply = sock.recv(4096)
        if len(reply) < 7:
            raise RfcommError("Short SDP reply")
        pdu, rtid, plen = struct.unpack(">BHH", reply[:5])
        if pdu == 0x01:
            raise RfcommError("SDP error %d" % struct.unpack(">H", reply[5:7])[0])
        if pdu != 0x07 or rtid != tid:
            raise RfcommError("Unexpected SDP reply %#x" % pdu)
        count = struct.unpack(">H", reply[5:7])[0]
        result += reply[7:7 + count]
        cont_len = reply[7 + count]
        if cont_len == 0:
            return result
        cont = reply[7 + count:8 + count + cont_len]
        tid += 1


def find_channel(address, service_uuid, timeout=CONNECT_TIMEOUT):
    """SDP search for `service_uuid`; returns its RFCOMM channel."""
    sock = _connect_l2cap(address, SDP_PSM, timeout)
    try:
        data = _search_attributes(sock, service_uuid)
    finally:
        sock.close()
    if not data:
        raise RfcommError("The watch does not offer service %s" % service_uuid)
    records, _ = _parse_element(data, 0)
    for record in records or []:
        attrs = dict(zip(record[0::2], record[1::2]))
        for proto in attrs.get(ATTR_PROTOCOL_DESCRIPTOR_LIST) or []:
            if isinstance(proto, list) and len(proto) >= 2 and proto[0] == UUID_RFCOMM:
                return int(proto[1])
    raise RfcommError("No RFCOMM channel in the SDP record of %s" % service_uuid)


def connect(address, service_uuid, timeout=CONNECT_TIMEOUT):
    """Blocking: SDP lookup + RFCOMM connect. Returns a connected socket."""
    channel = find_channel(address, service_uuid, timeout)
    log.info("SDP: %s is on RFCOMM channel %d (%s sockets)", service_uuid, channel,
             "native" if _native() else "libc")
    return _connect_rfcomm(address, channel, timeout)
