# WatchBridge - Huawei Watch GT 5 companion for Sailfish OS
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Persistent settings (~/.config/harbour-watchbridge/config.json)."""

import copy
import json
import logging
import os

log = logging.getLogger(__name__)

APP_NAME = "harbour-watchbridge"

DEFAULTS = {
    "device": {
        "address": "",
        "name": "",
        # protocol secrets, managed by the daemon
        "android_id": "",
        "fake_mac": "",
        "auth_key": "",
    },
    "auto_reconnect": True,
    "notifications": {
        "enabled": True,
        "blocked_apps": [],
        "include_system": False,
    },
    "weather": {
        "enabled": True,
        "location": "",
        "latitude": None,
        "longitude": None,
        "fahrenheit": False,
        "interval_minutes": 60,
    },
    "watch": {
        "time_24h": True,
        "date_format": 3,  # 1 = Y/M/D, 2 = M/D/Y, 3 = D/M/Y
    },
}

# Keys the UI may not read or change
_PRIVATE_DEVICE_KEYS = ("android_id", "fake_mac", "auth_key")


def _config_dir():
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base, APP_NAME)


def _merge(base, override):
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _merge(base[k], v)
        else:
            base[k] = v
    return base


class Config:
    def __init__(self, path=None):
        self.path = path or os.path.join(_config_dir(), "config.json")
        self.data = copy.deepcopy(DEFAULTS)
        self.load()

    def load(self):
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                _merge(self.data, json.load(f))
        except FileNotFoundError:
            pass
        except (OSError, ValueError) as e:
            log.error("Could not read %s: %s", self.path, e)

    def save(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp = self.path + ".tmp"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=2, sort_keys=True)
        os.replace(tmp, self.path)

    def public(self):
        """Settings safe to hand to the UI (no pairing secrets)."""
        d = copy.deepcopy(self.data)
        for key in _PRIVATE_DEVICE_KEYS:
            d["device"].pop(key, None)
        return d

    def update_public(self, changes):
        changes = copy.deepcopy(changes)
        dev = changes.pop("device", None)
        if isinstance(dev, dict):
            # The UI may rename the watch, everything else is daemon managed
            if "name" in dev:
                self.data["device"]["name"] = str(dev["name"])
        _merge(self.data, {k: v for k, v in changes.items() if k in DEFAULTS})
        self.save()

    def forget_device(self):
        self.data["device"] = copy.deepcopy(DEFAULTS["device"])
        self.save()
