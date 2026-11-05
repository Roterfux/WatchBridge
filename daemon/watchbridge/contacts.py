# WatchBridge - Huawei Watch GT 5 companion for Sailfish OS
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Caller names for the watch's call screen.

The contacts are in Sailfish's privileged storage, so the names come from a small helper
(/usr/libexec/harbour-watchbridge/contact-names) that sailjail starts with the Contacts
permission. The result stays in memory and is never written to disk or logged.
"""

import json
import logging
import re
import subprocess
import threading

log = logging.getLogger(__name__)

# Must match the Exec line of harbour-watchbridge-contacts.desktop exactly: sailjail compares
# them, and it only starts ELF binaries, so the script is run by python3, not directly.
HELPER = ["/usr/bin/sailjail", "-p", "harbour-watchbridge-contacts.desktop",
          "/usr/bin/python3", "/usr/libexec/harbour-watchbridge/contact-names"]
# Long enough for the user to answer Sailfish's permission prompt the first time
HELPER_TIMEOUT = 180

# Compare the last digits only, so "+43 664 1234567", "00436641234567" and "06641234567" match
_MATCH_DIGITS = 9


def number_key(number):
    digits = re.sub(r"\D", "", number or "")
    return digits[-_MATCH_DIGITS:]


class ContactNames:
    def __init__(self, command=None, run_async=True):
        self.command = command or HELPER
        self.run_async = run_async
        self.state = "off"      # off | loading | ready | failed
        self.error = ""
        self.count = 0
        self._names = {}
        self._lock = threading.Lock()
        self._busy = False

    def lookup(self, number):
        key = number_key(number)
        if len(key) < 3:
            return None
        with self._lock:
            return self._names.get(key)

    def clear(self):
        with self._lock:
            self._names = {}
        self.state, self.error, self.count = "off", "", 0

    def refresh(self, done=None):
        """Re-reads the contacts in the background; `done()` is called from that thread."""
        if self._busy:
            return
        self._busy = True
        if self.state != "ready":
            self.state = "loading"
        if self.run_async:
            threading.Thread(target=self._load, args=(done,), daemon=True, name="contact-names").start()
        else:
            self._load(done)

    def _load(self, done):
        try:
            names = self._run()
            with self._lock:
                self._names = names
            self.state, self.error, self.count = "ready", "", len(names)
            log.info("Caller names: %d phone numbers", len(names))
        except Exception as e:  # noqa: BLE001 - names are optional, calls must keep working
            log.warning("Caller names unavailable: %s", e)
            self.error = str(e)
            if self.state != "ready":  # keep older names if a refresh fails
                self.state = "failed"
        finally:
            self._busy = False
            if done is not None:
                done()

    def _run(self):
        try:
            proc = subprocess.run(self.command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                  timeout=HELPER_TIMEOUT, check=False)
        except FileNotFoundError:
            raise RuntimeError("The contact helper is not installed")
        except subprocess.TimeoutExpired:
            raise RuntimeError("No answer to the Contacts permission request")
        if proc.returncode != 0:
            lines = proc.stderr.decode("utf-8", "replace").strip().splitlines()
            # sailjail logs its own refusals to the system log, not to stderr
            raise RuntimeError("The contact helper failed (%d): %s"
                               % (proc.returncode, lines[-1] if lines else "sailjail refused to start it"))
        data = json.loads(proc.stdout.decode("utf-8"))
        names = {}
        for number, name in data.get("contacts", []):
            key = number_key(number)
            if len(key) >= 3 and key not in names:
                names[key] = name
        return names
