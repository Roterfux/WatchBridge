#!/bin/sh
# Start the daemon on a private session bus (no BlueZ available) and call every
# method the QML UI uses. Run as: dbus-run-session -- sh tools/smoke-daemon.sh [project dir]
cd "${1:-$(dirname "$0")/..}"
export PYTHONPATH=$(pwd)/daemon PYTHONDONTWRITEBYTECODE=1 XDG_CONFIG_HOME=$(mktemp -d)
# The health store writes to ~/Documents/WatchBridge; keep it out of the real home
export HOME=$(mktemp -d)
python3 -m watchbridge -v >/tmp/watchbridge.log 2>&1 &
PID=$!

call() {
    gdbus call --session --dest harbour.watchbridge --object-path /harbour/watchbridge \
        --method harbour.watchbridge.Daemon."$@" 2>&1 | cut -c1-160
}

for i in 1 2 3 4 5 6 7 8 9 10; do
    sleep 0.5
    call GetStatus >/dev/null && break
done
FAIL=0
for m in GetStatus GetSettings GetDevices StartScan StopScan Connect Disconnect SendTestNotification \
         RefreshWeather SyncTime StopFindPhone "SetSettings '{\"weather\":{\"fahrenheit\":true}}'" \
         SyncHealth "GetHealth ''" "GetHealth '2026-11-04'" "GetHealth 'not-a-date'" \
         "SetSettings '{\"health\":{\"interval_hours\":3}}'" \
         "Forget false" "Pair 'AA:BB:CC:DD:EE:FF' 'HUAWEI WATCH GT 5'"; do
    out=$(eval call $m)
    echo "$m -> $out"
    case "$out" in *Error*) FAIL=1 ;; esac
done
# A stand-in for lipstick plus an app posting a notification; the monitor must see it
python3 - <<'EOF'
import dbus, dbus.service, dbus.mainloop.glib
from gi.repository import GLib
dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
bus = dbus.SessionBus()
class Srv(dbus.service.Object):
    @dbus.service.method("org.freedesktop.Notifications", in_signature="susssasa{sv}i", out_signature="u")
    def Notify(self, app, rid, icon, summary, body, actions, hints, timeout):
        return 1
name = dbus.service.BusName("org.freedesktop.Notifications", bus)
srv = Srv(bus, "/org/freedesktop/Notifications")
loop = GLib.MainLoop()
def send():
    n = dbus.Interface(dbus.SessionBus().get_object("org.freedesktop.Notifications", "/org/freedesktop/Notifications"),
                       "org.freedesktop.Notifications")
    n.Notify("Messages", dbus.UInt32(0), "", "Bob", "Hi there", dbus.Array([], "s"),
             {"category": "x-nemo.messaging.sms"}, 5000, reply_handler=lambda r: loop.quit(),
             error_handler=lambda e: (print("Notify failed", e), loop.quit()))
    return False
GLib.idle_add(send)
loop.run()
EOF
sleep 1
grep -q "Notification from 'Messages' (x-nemo.messaging.sms): forward" /tmp/watchbridge.log \
    && echo "--- notification monitor: OK" || { echo "--- notification monitor: NOT SEEN"; FAIL=1; }
echo "--- final status: $(call GetStatus | cut -c1-120)"
if kill -0 $PID 2>/dev/null; then echo "--- daemon alive: yes"; else echo "--- daemon alive: NO"; FAIL=1; fi
kill $PID 2>/dev/null
echo "--- log"; grep -v PyGIDeprecationWarning /tmp/watchbridge.log | grep -v unix_signal_add
exit $FAIL
