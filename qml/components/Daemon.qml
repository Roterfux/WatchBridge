// WatchBridge - SPDX-License-Identifier: AGPL-3.0-or-later
// Thin wrapper around the daemon's session bus API. Values arrive as JSON.
import QtQuick 2.0
import Sailfish.Silica 1.0
import Nemo.DBus 2.0

Item {
    id: daemon

    // ----------------------------------------------------------- ring colours
    // Steps, distance, calories and sleep: the activity rings, their legends and the week and month
    // charts. "ambience" (the default) derives them from the ambience's highlight colour, so they
    // change with it; "classic" keeps fixed blue, green, orange and violet.
    readonly property var classicRingColors: ["#4fb3ff", "#7fd36b", "#ffb347", "#b38cff"]
    readonly property bool ambienceRings: !settings.health || settings.health.ring_colors !== "classic"
    readonly property var ringColors: ambienceRings ? ambienceColors(Theme.highlightColor, Theme.colorScheme)
                                                    : classicRingColors
    // Hue steps from the ambience colour, in degrees: near enough to belong to it, far enough apart
    // to tell the rings from each other
    readonly property var ringHueSteps: [0, 40, 80, -50]

    function ambienceColors(base, scheme) {
        var r = base.r, g = base.g, b = base.b
        var max = Math.max(r, g, b), min = Math.min(r, g, b)
        var h = 0, s = 0, l = (max + min) / 2
        if (max !== min) {
            var d = max - min
            s = l > 0.5 ? d / (2 - max - min) : d / (max + min)
            h = max === r ? (g - b) / d + (g < b ? 6 : 0) : max === g ? (b - r) / d + 2 : (r - g) / d + 4
            h /= 6
        }
        // Grey ambiences still get colours; keep them readable on light and on dark ambiences
        s = Math.max(0.5, Math.min(0.85, s))
        l = scheme === Theme.DarkOnLight ? Math.max(0.35, Math.min(0.5, l)) : Math.max(0.55, Math.min(0.72, l))
        var out = []
        for (var i = 0; i < ringHueSteps.length; i++)
            out.push(Qt.hsla((h + ringHueSteps[i] / 360 + 1) % 1, s, l, 1))
        return out
    }

    property var status: ({})
    property var settings: ({})
    property var devices: []
    property bool available: false
    // Last D-Bus error while the service is unreachable, shown to the user
    property string lastError: ""

    readonly property string watchState: status.state || "unknown"
    readonly property bool connected: watchState === "connected"
    readonly property bool paired: !!status.address
    readonly property bool busy: ["pairing", "connecting", "authenticating", "initializing"].indexOf(watchState) >= 0
    readonly property var weather: status.weather || null
    // The watch is making the phone ring
    readonly property bool findingPhone: !!status.findingPhone

    signal message(string level, string text)

    function _call(method, args, cb) {
        dbusIface.typedCall(method, args || [],
                      function(result) { daemon.available = true; daemon.lastError = ""; if (cb) cb(result) },
                      function(error, text) {
                          console.warn("WatchBridge D-Bus", method, "failed:", error, text)
                          daemon.lastError = (text || error || qsTr("no answer")).toString()
                      })
    }

    function refresh() {
        _call("GetStatus", [], function(json) { status = JSON.parse(json) })
        _call("GetSettings", [], function(json) { settings = JSON.parse(json) })
    }
    function reloadSettings(cb) {
        _call("GetSettings", [], function(json) { settings = JSON.parse(json); if (cb) cb() })
    }
    function refreshDevices() { _call("GetDevices", [], function(json) { devices = JSON.parse(json) }) }

    function startScan() { _call("StartScan"); refreshDevices() }
    function stopScan() { _call("StopScan") }
    function pair(address, name) {
        _call("Pair", [{ "type": "s", "value": address }, { "type": "s", "value": name || "" }])
    }
    function connectWatch() { _call("Connect") }
    function disconnectWatch() { _call("Disconnect") }
    function forget(unpairBluetooth) { _call("Forget", [{ "type": "b", "value": unpairBluetooth }]) }
    function sendTestNotification() { _call("SendTestNotification") }
    function refreshWeather() { _call("RefreshWeather") }
    function syncTime() { _call("SyncTime") }
    function stopFindPhone() { _call("StopFindPhone") }
    function syncHealth() { _call("SyncHealth") }
    function syncCalendar() { _call("SyncCalendar") }
    // Summary for one local date ("yyyy-MM-dd"), delivered to cb as an object
    function getHealth(day, cb) {
        _call("GetHealth", [{ "type": "s", "value": day }], function(json) { cb(JSON.parse(json)) })
    }
    // The watch's battery over the last `days` days: { points: [[time, level], ...] }
    function getBatteryHistory(days, cb) {
        _call("GetBatteryHistory", [{ "type": "i", "value": days }], function(json) { cb(JSON.parse(json)) })
    }
    // Alarms on the watch (status.alarms holds the list as last read)
    function refreshAlarms() { _call("RefreshAlarms") }
    function setAlarms(list) { _call("SetAlarms", [{ "type": "s", "value": JSON.stringify(list) }]) }
    // Week overview (Monday to Sunday) for the week holding `day` ("yyyy-MM-dd")
    function getHealthWeek(day, cb) {
        _call("GetHealthWeek", [{ "type": "s", "value": day }], function(json) { cb(JSON.parse(json)) })
    }
    // Month overview ("yyyy-MM"): one entry per day with data, plus averages
    function getHealthMonth(month, cb) {
        _call("GetHealthMonth", [{ "type": "s", "value": month }], function(json) { cb(JSON.parse(json)) })
    }

    // Watch faces
    function refreshWatchfaces() { _call("RefreshWatchfaces") }
    function inspectWatchface(path, cb) {
        _call("InspectWatchface", [{ "type": "s", "value": path }], function(json) { cb(JSON.parse(json)) })
    }
    function installWatchface(path) { _call("InstallWatchface", [{ "type": "s", "value": path }]) }
    function setWatchface(file, version) {
        _call("SetWatchface", [{ "type": "s", "value": file }, { "type": "s", "value": version }])
    }
    function deleteWatchface(file, version) {
        _call("DeleteWatchface", [{ "type": "s", "value": file }, { "type": "s", "value": version }])
    }

    // Merge a partial settings object, e.g. { "weather": { "fahrenheit": true } }
    function updateSettings(changes) {
        _call("SetSettings", [{ "type": "s", "value": JSON.stringify(changes) }], function() {
            _call("GetSettings", [], function(json) { settings = JSON.parse(json) })
        })
    }

    function stateText(state, detail) {
        switch (state) {
        case "connected": return qsTr("Connected")
        case "connecting": return qsTr("Connecting…")
        case "pairing": return qsTr("Pairing over Bluetooth…")
        case "authenticating":
            return detail === "confirm_on_watch" ? qsTr("Confirm the pairing on your watch")
                                                 : qsTr("Authenticating…")
        case "initializing": return qsTr("Setting up the watch…")
        case "disconnected": return qsTr("Disconnected")
        case "auth_failed": return qsTr("Pairing failed")
        case "unpaired": return qsTr("No watch paired")
        default: return available ? qsTr("Unknown") : qsTr("Starting service…")
        }
    }

    DBusInterface {
        id: dbusIface
        bus: DBus.SessionBus
        service: "harbour.watchbridge"
        path: "/harbour/watchbridge"
        iface: "harbour.watchbridge.Daemon"
        signalsEnabled: true

        function statusChanged(json) {
            daemon.available = true
            daemon.status = JSON.parse(json)
        }
        function devicesChanged(json) { daemon.devices = JSON.parse(json) }
        function message(level, text) { daemon.message(level, text) }
    }

    // D-Bus activation starts the daemon on the first call; poll until it answers.
    Timer {
        interval: daemon.available ? 30000 : 2000
        running: true
        repeat: true
        triggeredOnStart: true
        onTriggered: daemon.refresh()
    }
}
