"""Watch faces: .hwt packages, the watch-face service and the file upload."""

import io
import os
import socket
import sys
import threading
import time
import unittest
import zipfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "daemon"))
sys.path.insert(0, os.path.dirname(__file__))

from watchbridge.huawei import device as D  # noqa: E402
from watchbridge.huawei import watchface as W  # noqa: E402
from fake_watch import FakeWatch  # noqa: E402

DESCRIPTION = """﻿<?xml version="1.0" encoding="UTF-8"?>
<HwTheme>
    <title>Night Sky</title>
    <title-cn>夜空</title-cn>
    <author>Someone</author>
    <version>1.2.0</version>
    <screen>HWHD09</screen>
</HwTheme>
"""


def make_hwt(binary=b"\x01FACE" * 600, description=DESCRIPTION, inner_zip=True, preview=b"\xff\xd8JPEG"):
    if inner_zip:
        inner = io.BytesIO()
        with zipfile.ZipFile(inner, "w") as z:
            z.writestr("watchface.bin", binary)
        inner = inner.getvalue()
    else:
        inner = binary
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        z.writestr("description.xml", description.encode("utf-8"))
        if preview:
            z.writestr("preview/cover.jpg", preview)
        z.writestr("com.huawei.watchface", inner)
    return out.getvalue()


class TestPackage(unittest.TestCase):
    def test_parses_description_preview_and_binary(self):
        pkg = W.WatchfacePackage(make_hwt())
        self.assertEqual((pkg.title, pkg.author, pkg.version, pkg.screen), ("Night Sky", "Someone", "1.2.0", "HWHD09"))
        self.assertEqual(pkg.resolution, "466*466")
        self.assertTrue(pkg.fits(466, 466))
        self.assertFalse(pkg.fits(454, 454))
        self.assertEqual(pkg.binary, b"\x01FACE" * 600)
        self.assertEqual(pkg.preview, b"\xff\xd8JPEG")

    def test_older_package_holds_the_binary_directly(self):
        pkg = W.WatchfacePackage(make_hwt(binary=b"RAWBIN" * 10, inner_zip=False, preview=None))
        self.assertEqual(pkg.binary, b"RAWBIN" * 10)
        self.assertIsNone(pkg.preview)

    def test_rejects_other_files(self):
        with self.assertRaises(W.WatchfaceFileError):
            W.WatchfacePackage(b"not a zip at all")
        out = io.BytesIO()
        with zipfile.ZipFile(out, "w") as z:
            z.writestr("readme.txt", "hi")
        with self.assertRaises(W.WatchfaceFileError):
            W.WatchfacePackage(out.getvalue())

    def test_random_file_name(self):
        self.assertRegex(W.random_file_name(), r"^\d{9}_1\.0\.0$")
        self.assertRegex(W.random_file_name("2.1.0"), r"^\d{9}_2\.1\.0$")

    def test_upload_version_from_watch_params(self):
        gt5 = {"max_version": "2.9", "other_versions": "2.1,2.2,2.3,2.4,2.5,2.6,2.7,2.8,2.10"}
        self.assertEqual(W.supported_versions(gt5)[0], "2.1")
        self.assertEqual(W.supported_versions(gt5)[-1], "2.10")  # numeric, not text order
        self.assertEqual(W.upload_version(gt5), "2.1.0")
        self.assertEqual(W.upload_version({"max_version": "1.6", "other_versions": ""}), "1.6.0")
        self.assertEqual(W.upload_version(None), "1.0.0")


class Recorder(D.Listener):
    def __init__(self):
        self.connected = threading.Event()
        self.faces = None
        self.face_lists = 0
        self.uploads = []
        self.finished = threading.Event()

    def on_state(self, state, detail=""):
        if state == D.STATE_CONNECTED:
            self.connected.set()

    def on_watchfaces(self, faces, error=""):
        self.faces = faces
        self.face_lists += 1

    def on_upload(self, state, progress, error="", activated=False, file_name=""):
        self.uploads.append((state, progress, error, activated))
        self.file_name = file_name
        if state in ("done", "failed"):
            self.finished.set()


def wait_for(cond, timeout=10.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False


class TestUpload(unittest.TestCase):
    def connect(self, **kw):
        phone, watch_sock = socket.socketpair()
        watch = FakeWatch(watch_sock, **kw).start()
        rec = Recorder()
        dev = D.HuaweiWatch(phone, "AA:BB:CC:DD:EE:FF", D.DeviceStore({}, lambda: None), rec)
        self.addCleanup(dev.stop)
        self.addCleanup(watch_sock.close)
        dev.start()
        self.assertTrue(rec.connected.wait(10))
        return dev, watch, rec

    def test_params_and_list(self):
        dev, watch, rec = self.connect()
        self.assertEqual((dev.watchface_params["width"], dev.watchface_params["height"]), (466, 466))
        dev.list_watchfaces()
        self.assertTrue(wait_for(lambda: rec.faces is not None))
        self.assertEqual(rec.faces, [{"file": "100000001", "version": "1.0.0", "current": True, "factory": True,
                                      "editable": False, "trial": False, "name": "Classic"}])

    def test_upload_encrypted_then_activated(self):
        dev, watch, rec = self.connect(upload_unit=300, upload_window=1000)
        binary = os.urandom(2500)  # three 0x28/0x05 rounds, several pieces each
        dev.upload_watchface(binary)
        self.assertTrue(rec.finished.wait(15), rec.uploads)
        self.assertEqual(rec.uploads[-1][0], "done", rec.uploads)
        self.assertTrue(rec.uploads[-1][3])                       # the watch asked to activate it
        self.assertEqual(watch.uploaded[0][1], binary)            # bytes and SHA-256 match
        self.assertTrue(watch.upload["encrypted"])
        self.assertEqual(watch.chunk_packets, 10)                 # windows 1000+1000+500 in 300-byte pieces
        name, version = watch.upload["face"]
        self.assertRegex(name, r"^\d{9}$")
        # Registered under the oldest format version the watch supports, not Gadgetbridge's 1.0.0
        self.assertEqual(version, "2.1.0")
        self.assertEqual(watch.upload["name"], name + "_2.1.0")
        self.assertEqual(rec.file_name, name + "_2.1.0")  # the service keeps the preview under it
        # The new face became the current one, and the list was read again
        self.assertTrue(wait_for(lambda: rec.faces and any(f["current"] and f["file"] == name for f in rec.faces)))
        self.assertFalse(dev.uploading)

    def test_upload_without_chunk_encryption(self):
        dev, watch, rec = self.connect(upload_no_encrypt=1, upload_window=4096, upload_unit=1000)
        binary = os.urandom(3000)
        dev.upload_watchface(binary)
        self.assertTrue(rec.finished.wait(15), rec.uploads)
        self.assertEqual(watch.uploaded[0][1], binary)
        self.assertNotIn("encrypted", watch.upload)
        self.assertEqual(watch.upload["ack"].get_byte(0x09), 0x01)  # told the watch: plain files

    def test_watch_refuses(self):
        dev, watch, rec = self.connect(upload_refuse=140004)
        dev.upload_watchface(b"x" * 100)
        self.assertTrue(rec.finished.wait(10))
        state, _progress, error, _ = rec.uploads[-1]
        self.assertEqual(state, "failed")
        self.assertIn("Too many watch faces", error)
        self.assertFalse(dev.uploading)

    def test_only_one_upload_at_a_time(self):
        dev, watch, rec = self.connect(upload_window=500, upload_unit=100)
        dev.upload_watchface(os.urandom(5000))
        with self.assertRaises(D.WatchError):
            dev.upload_watchface(b"second")
        self.assertTrue(rec.finished.wait(20))


if __name__ == "__main__":
    unittest.main()
