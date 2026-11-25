"""Print the phone's Bluetooth adapter and any Huawei/watch devices as BlueZ sees them.

Sailfish OS ships no bluetoothctl, so run this on the phone instead:
    ssh defaultuser@<phone-ip> 'python3 -' < .claude/skills/watchbridge-dev/scripts/btinfo.py
Pass a name fragment as the first argument to match other devices.
"""
import sys

import dbus

needle = (sys.argv[1] if len(sys.argv) > 1 else "").upper()
bus = dbus.SystemBus()
objs = dbus.Interface(bus.get_object("org.bluez", "/"), "org.freedesktop.DBus.ObjectManager").GetManagedObjects()
for path, ifaces in sorted(objs.items()):
    a = ifaces.get("org.bluez.Adapter1")
    if a:
        print("ADAPTER %s powered=%s discovering=%s" % (path, bool(a.get("Powered")), bool(a.get("Discovering"))))
    d = ifaces.get("org.bluez.Device1")
    if not d:
        continue
    name = str(d.get("Name", "")).upper()
    if needle and needle not in name:
        continue
    if not needle and "WATCH" not in name and "HUAWEI" not in name:
        continue
    print("DEVICE %s" % path)
    for k in ("Name", "Address", "Paired", "Bonded", "Trusted", "Connected", "ServicesResolved"):
        if k in d:
            print("  %s: %s" % (k, d[k]))
    for u in d.get("UUIDs", []):
        print("  UUID %s%s" % (u, "   <- Huawei service" if str(u).lower().startswith("82ff3820") else ""))
