// WatchBridge - SPDX-License-Identifier: AGPL-3.0-or-later
// Thin wrapper around the daemon's session bus API. Values arrive as JSON.
import QtQuick 2.0
import Nemo.DBus 2.0

Item {
    id: daemon

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
    // Summary for one local date ("yyyy-MM-dd"), delivered to cb as an object
    function getHealth(day, cb) {
        _call("GetHealth", [{ "type": "s", "value": day }], function(json) { cb(JSON.parse(json)) })
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
