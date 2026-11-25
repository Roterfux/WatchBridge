// WatchBridge - SPDX-License-Identifier: AGPL-3.0-or-later
import QtQuick 2.0
import Sailfish.Silica 1.0
import "../components"

CoverBackground {
    id: cover
    property var daemon
    readonly property var st: daemon.status
    readonly property var wx: daemon.weather
    readonly property var hs: st.health || {}
    readonly property int lastSync: hs.lastSync || 0

    // Today's summary from the last health sync (steps, last night, latest heart rate)
    property var today: null

    function loadToday() {
        if (!daemon.available || !daemon.paired) return
        daemon.getHealth(Qt.formatDate(new Date(), "yyyy-MM-dd"), function(r) {
            cover.today = r.available === false ? null : r
        })
    }

    onLastSyncChanged: loadToday()
    // Covers are only drawn while visible; refresh then (the date may have changed too)
    onStatusChanged: if (status === Cover.Active) loadToday()
    Connections {
        target: daemon
        onAvailableChanged: cover.loadToday()
    }

    readonly property bool hasSteps: !!today && (today.minutes > 0 || !!today.totalsUpdated)
    readonly property var night: today && today.sleep && today.sleep.minutes > 0 ? today.sleep : null
    readonly property var lastHeartRate: {
        var hr = today && today.heartRate ? today.heartRate : []
        return hr.length > 0 ? hr[hr.length - 1] : null   // [seconds since midnight, bpm]
    }

    function sleepText(n) {
        return qsTr("%1 h %2 min").arg(Math.floor(n.minutes / 60)).arg(n.minutes % 60)
    }

    Column {
        anchors {
            top: parent.top; topMargin: Theme.paddingMedium
            left: parent.left; leftMargin: Theme.paddingMedium
            right: parent.right; rightMargin: Theme.paddingMedium
        }
        spacing: Theme.paddingSmall

        WatchFace {
            anchors.horizontalCenter: parent.horizontalCenter
            width: cover.width * 0.38
            height: width
            battery: st.battery !== undefined ? st.battery : -1
            watchState: daemon.watchState
            busy: daemon.busy
            showBatteryText: false  // the status line below names the percentage
        }
        Label {
            width: parent.width
            horizontalAlignment: Text.AlignHCenter
            truncationMode: TruncationMode.Fade
            font.pixelSize: Theme.fontSizeSmall
            color: Theme.highlightColor
            text: !daemon.paired ? qsTr("No watch")
                  : daemon.connected && st.battery >= 0
                    ? qsTr("%1 · %2 %").arg(daemon.stateText(daemon.watchState, "")).arg(st.battery)
                    : daemon.stateText(daemon.watchState, "")
        }

        // ------------------------------------------------------- missed call
        CoverInfo {
            readonly property var missed: (st.calls || {}).missed || null
            visible: !!missed
            label: qsTr("Missed") + (missed ? " " + Qt.formatTime(new Date(missed.time * 1000), "hh:mm") : "")
            value: missed ? missed.caller : ""
            valueColor: Theme.highlightColor
        }

        // ------------------------------------------------------------ health
        Column {
            width: parent.width
            visible: daemon.paired && (cover.hasSteps || !!cover.night || !!cover.lastHeartRate || !!cover.hs.syncing)

            CoverInfo {
                visible: cover.hasSteps
                label: qsTr("Steps")
                value: cover.hasSteps ? Number(cover.today.steps || 0).toLocaleString(Qt.locale(), "f", 0) : ""
            }
            CoverInfo {
                visible: !!cover.night
                label: qsTr("Sleep")
                value: cover.night ? cover.sleepText(cover.night) : ""
            }
            CoverInfo {
                visible: !!cover.lastHeartRate
                label: qsTr("Heart rate")
                value: cover.lastHeartRate ? qsTr("%1 bpm").arg(cover.lastHeartRate[1]) : ""
            }
            Label {
                visible: !!cover.hs.syncing
                width: parent.width
                horizontalAlignment: Text.AlignHCenter
                font.pixelSize: Theme.fontSizeExtraSmall
                color: Theme.secondaryColor
                text: qsTr("Syncing health data…")
            }
        }

        // ----------------------------------------------------------- weather
        Row {
            anchors.horizontalCenter: parent.horizontalCenter
            spacing: Theme.paddingSmall
            visible: !!wx
            WeatherGlyph { code: wx ? wx.code : null; font.pixelSize: Theme.fontSizeMedium }
            Label {
                anchors.verticalCenter: parent.verticalCenter
                text: wx ? wx.temperature + "°" : ""
                font.pixelSize: Theme.fontSizeMedium
            }
        }
    }

    CoverActionList {
        enabled: daemon.paired && daemon.connected
        CoverAction {
            iconSource: "image://theme/icon-cover-refresh"
            onTriggered: daemon.refreshWeather()
        }
        CoverAction {
            iconSource: "image://theme/icon-cover-sync"
            onTriggered: daemon.syncHealth()
        }
    }
    CoverActionList {
        enabled: daemon.paired && !daemon.connected && !daemon.busy
        CoverAction {
            iconSource: "image://theme/icon-cover-sync"
            onTriggered: daemon.connectWatch()
        }
    }
}
