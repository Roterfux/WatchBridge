# WatchBridge - Huawei Watch GT 5 companion for Sailfish OS
# SPDX-License-Identifier: AGPL-3.0-or-later
"""BlueZ 5 D-Bus glue: discovery, pairing and the RFCOMM link to the watch.

The watch exposes its protocol as an RFCOMM service with a vendor UUID
(found through SDP, like Android's createRfcommSocketToServiceRecord). We let
BlueZ do the SDP lookup by registering an external client profile for that
UUID and calling Device1.ConnectProfile; BlueZ then hands us the connected
socket in Profile1.NewConnection. When BlueZ does not know the UUID (it only
browses public SDP records at pairing time) we fall back to our own SDP
search and RFCOMM socket, see rfcomm.py.
"""

import logging
import socket
import threading
import time

import dbus
import dbus.service
from gi.repository import GLib

from . import rfcomm

log = logging.getLogger(__name__)

BLUEZ = "org.bluez"
ADAPTER = "org.bluez.Adapter1"
DEVICE = "org.bluez.Device1"
PROFILE_MANAGER = "org.bluez.ProfileManager1"
PROPS = "org.freedesktop.DBus.Properties"
OBJ_MANAGER = "org.freedesktop.DBus.ObjectManager"

HUAWEI_SPP_UUID = "82ff3820-8411-400c-b85a-55bdb32cf060"
PROFILE_PATH = "/harbour/watchbridge/profile"

WATCH_NAME_HINTS = ("huawei watch", "watch gt")


def is_watch_name(name):
    n = (name or "").lower()
    return any(h in n for h in WATCH_NAME_HINTS)


def _addr_path(adapter_path, address):
    return "%s/dev_%s" % (adapter_path, address.upper().replace(":", "_"))


class _Profile(dbus.service.Object):
    def __init__(self, bus, path, owner):
        super().__init__(bus, path)
        self.owner = owner

    @dbus.service.method("org.bluez.Profile1", in_signature="", out_signature="")
    def Release(self):
        log.info("Profile released")

    @dbus.service.method("org.bluez.Profile1", in_signature="oha{sv}", out_signature="")
    def NewConnection(self, device_path, fd, properties):
        raw = fd.take()
        sock = socket.socket(fileno=raw)
        sock.setblocking(True)
        log.info("RFCOMM connection from %s", device_path)
        self.owner._on_new_connection(str(device_path), sock)

    @dbus.service.method("org.bluez.Profile1", in_signature="o", out_signature="")
    def RequestDisconnection(self, device_path):
        log.info("Disconnection requested for %s", device_path)
        self.owner._on_disconnect_requested(str(device_path))


class Bluez:
    """`on_devices(list)`, `on_connection(address, sock)` and
    `on_device_connected(address, connected)` callbacks run on the main loop."""

    def __init__(self, bus, on_devices=None, on_connection=None, on_device_connected=None):
        self.bus = bus
        self.on_devices = on_devices or (lambda devices: None)
        self.on_connection = on_connection or (lambda address, sock: None)
        self.on_device_connected = on_device_connected or (lambda address, connected: None)
        self.adapter_path = None
        self.devices = {}  # path -> props
        self.scanning = False
        self._profile_registered = False
        self._last_connection = {}  # address -> monotonic time the last socket was delivered
        self._profile = _Profile(bus, PROFILE_PATH, self)
        self._refresh()
        bus.add_signal_receiver(self._interfaces_added, "InterfacesAdded", OBJ_MANAGER, BLUEZ)
        bus.add_signal_receiver(self._interfaces_removed, "InterfacesRemoved", OBJ_MANAGER, BLUEZ)
        bus.add_signal_receiver(self._properties_changed, "PropertiesChanged", PROPS, BLUEZ,
                                path_keyword="path")
        self._register_profile()

    # ---------------------------------------------------------------- objects
    def _manager(self):
        return dbus.Interface(self.bus.get_object(BLUEZ, "/"), OBJ_MANAGER)

    def _refresh(self):
        try:
            objects = self._manager().GetManagedObjects()
        except dbus.DBusException as e:
            log.error("BlueZ not available: %s", e)
            return
        for path, ifaces in objects.items():
            if ADAPTER in ifaces and self.adapter_path is None:
                self.adapter_path = str(path)
            if DEVICE in ifaces:
                self.devices[str(path)] = dict(ifaces[DEVICE])

    def _register_profile(self):
        if self._profile_registered:
            return
        try:
            mgr = dbus.Interface(self.bus.get_object(BLUEZ, "/org/bluez"), PROFILE_MANAGER)
            mgr.RegisterProfile(PROFILE_PATH, HUAWEI_SPP_UUID, {
                "Name": dbus.String("WatchBridge"),
                "Role": dbus.String("client"),
                "AutoConnect": dbus.Boolean(False),
            })
            self._profile_registered = True
            log.info("Registered BlueZ client profile for %s", HUAWEI_SPP_UUID)
        except dbus.DBusException as e:
            log.error("Could not register profile: %s", e)

    def _adapter(self):
        if self.adapter_path is None:
            self._refresh()
        if self.adapter_path is None:
            raise RuntimeError("No Bluetooth adapter")
        return dbus.Interface(self.bus.get_object(BLUEZ, self.adapter_path), ADAPTER)

    def _device(self, address, iface=DEVICE):
        return dbus.Interface(self.bus.get_object(BLUEZ, _addr_path(self.adapter_path, address)), iface)

    def powered(self):
        try:
            props = dbus.Interface(self.bus.get_object(BLUEZ, self.adapter_path), PROPS)
            return bool(props.Get(ADAPTER, "Powered"))
        except (dbus.DBusException, TypeError):
            return False

    def device_list(self):
        out = []
        for path, p in self.devices.items():
            if self.adapter_path and not path.startswith(self.adapter_path):
                continue
            name = str(p.get("Alias") or p.get("Name") or "")
            out.append({
                "address": str(p.get("Address", "")),
                "name": name,
                "paired": bool(p.get("Paired", False)),
                "connected": bool(p.get("Connected", False)),
                "rssi": int(p.get("RSSI", -999)),
                "isWatch": is_watch_name(name),
            })
        out.sort(key=lambda d: (not d["isWatch"], not d["paired"], -d["rssi"], d["name"]))
        return out

    def device_props(self, address):
        return self.devices.get(_addr_path(self.adapter_path or "", address), {})

    # ---------------------------------------------------------------- signals
    def _interfaces_added(self, path, ifaces):
        if DEVICE in ifaces:
            self.devices[str(path)] = dict(ifaces[DEVICE])
            self.on_devices(self.device_list())
        if ADAPTER in ifaces and self.adapter_path is None:
            self.adapter_path = str(path)

    def _interfaces_removed(self, path, ifaces):
        if DEVICE in ifaces and str(path) in self.devices:
            del self.devices[str(path)]
            self.on_devices(self.device_list())

    def _properties_changed(self, iface, changed, invalidated, path=None):
        if iface != DEVICE or path is None:
            return
        props = self.devices.setdefault(str(path), {})
        props.update(dict(changed))
        if "Connected" in changed:
            self.on_device_connected(str(props.get("Address", "")), bool(changed["Connected"]))
        self.on_devices(self.device_list())

    # ---------------------------------------------------------------- actions
    def start_scan(self):
        adapter = self._adapter()
        try:
            adapter.SetDiscoveryFilter({"Transport": dbus.String("auto")})
        except dbus.DBusException:
            pass
        adapter.StartDiscovery()
        self.scanning = True
        self.on_devices(self.device_list())

    def stop_scan(self):
        if not self.scanning:
            return
        self.scanning = False
        try:
            self._adapter().StopDiscovery()
        except dbus.DBusException as e:
            log.debug("StopDiscovery: %s", e)

    def pair(self, address, on_done, on_error):
        """Bluetooth-level bonding. The Sailfish system agent shows any confirmation dialog."""
        if self.adapter_path is None:
            self._refresh()
        if self.adapter_path is None:
            on_error("No Bluetooth adapter found - is Bluetooth switched on?")
            return
        props = self.device_props(address)
        if props.get("Paired"):
            self._trust(address)
            on_done()
            return
        dev = self._device(address)

        def done():
            self._trust(address)
            on_done()

        def failed(e):
            if "AlreadyExists" in e.get_dbus_name():
                done()
            else:
                on_error(e.get_dbus_message() or e.get_dbus_name())

        dev.Pair(reply_handler=done, error_handler=failed, timeout=90)

    def _trust(self, address):
        try:
            props = self._device(address, PROPS)
            props.Set(DEVICE, "Trusted", dbus.Boolean(True))
        except dbus.DBusException as e:
            log.warning("Could not trust %s: %s", address, e)

    def connect(self, address, on_error):
        """Ask BlueZ to open the watch's RFCOMM service; the socket arrives via NewConnection."""
        if self.adapter_path is None:
            self._refresh()
        if self.adapter_path is None:
            on_error("No Bluetooth adapter found - is Bluetooth switched on?")
            return
        # BlueZ may not have been running when the daemon started
        self._register_profile()
        uuids = [str(u).lower() for u in self.device_props(address).get("UUIDs", [])]
        log.info("Services BlueZ knows for %s: %s", address, ", ".join(uuids) or "none")
        if not self._profile_registered or HUAWEI_SPP_UUID not in uuids:
            # ConnectProfile would fail with "profile unavailable"; search for it ourselves
            log.info("Huawei service not in BlueZ's SDP cache, connecting directly")
            self._connect_direct(address, on_error)
            return
        dev = self._device(address)
        started = time.monotonic()

        def failed(e):
            name = e.get_dbus_name()
            if "AlreadyConnected" in name or "InProgress" in name:
                log.info("ConnectProfile: %s", name)
                return
            if self._last_connection.get(address.upper(), 0) >= started:
                # NewConnection already handed us the socket; the reply just came late
                # (e.g. a NoReply timeout). A fallback now would replace a working link.
                log.info("ConnectProfile reported %s after the connection was made, ignoring", name)
                return
            log.warning("ConnectProfile failed (%s: %s), trying a direct connection", name, e.get_dbus_message())
            self._connect_direct(address, on_error)

        dev.ConnectProfile(HUAWEI_SPP_UUID, reply_handler=lambda: None, error_handler=failed, timeout=25)

    def _connect_direct(self, address, on_error):
        """SDP search + RFCOMM socket in a thread (like Android); result on the main loop."""
        def work():
            try:
                sock = rfcomm.connect(address, HUAWEI_SPP_UUID)
            except (OSError, rfcomm.RfcommError) as e:
                reason = getattr(e, "strerror", None) or str(e)
                log.warning("Direct RFCOMM connection failed: %s", reason)
                GLib.idle_add(lambda: (on_error("Could not open the watch connection: %s" % reason), False)[1])
                return
            log.info("RFCOMM connection to %s open (direct)", address)
            GLib.idle_add(lambda: (self._connected(address, sock), False)[1])

        threading.Thread(target=work, daemon=True, name="rfcomm-connect").start()

    def disconnect_profile(self, address):
        try:
            self._device(address).DisconnectProfile(HUAWEI_SPP_UUID)
        except dbus.DBusException as e:
            log.debug("DisconnectProfile: %s", e)

    def remove(self, address):
        try:
            self._adapter().RemoveDevice(_addr_path(self.adapter_path, address))
        except (dbus.DBusException, RuntimeError) as e:
            log.warning("RemoveDevice: %s", e)

    # ------------------------------------------------------- profile callbacks
    def _on_new_connection(self, device_path, sock):
        address = str(self.devices.get(device_path, {}).get("Address", ""))
        if not address:
            address = device_path.rsplit("dev_", 1)[-1].replace("_", ":")
        self._connected(address, sock)

    def _connected(self, address, sock):
        self._last_connection[address.upper()] = time.monotonic()
        # Trusted lets the watch reconnect on its own (the bond may come from the watch, not Pair())
        if not self.device_props(address).get("Trusted"):
            self._trust(address)
        self.on_connection(address, sock)

    def _on_disconnect_requested(self, device_path):
        address = device_path.rsplit("dev_", 1)[-1].replace("_", ":")
        self.on_device_connected(address, False)
