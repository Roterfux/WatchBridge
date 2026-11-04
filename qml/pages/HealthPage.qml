// WatchBridge - SPDX-License-Identifier: AGPL-3.0-or-later
// Steps, heart rate and sleep for one day, from the data synced off the watch.
import QtQuick 2.0
import Sailfish.Silica 1.0

Page {
    id: page

    property var daemon
    property string day: dateKey(new Date())
    property var h: ({})
    property bool loading: true

    readonly property var hs: daemon.status.health || {}
    readonly property int lastSync: hs.lastSync || 0
    readonly property bool isToday: day === dateKey(new Date())
    readonly property bool hasData: (h.minutes || 0) > 0 || (h.sleep && h.sleep.minutes > 0)

    function dateKey(d) { return Qt.formatDate(d, "yyyy-MM-dd") }
    function parseDay(key) {
        var p = key.split("-")
        return new Date(parseInt(p[0], 10), parseInt(p[1], 10) - 1, parseInt(p[2], 10), 12, 0, 0)
    }
    function shift(days) {
        var d = parseDay(day)
        d.setDate(d.getDate() + days)
        day = dateKey(d)
    }
    function load() {
        loading = true
        daemon.getHealth(day, function(r) { page.h = r; page.loading = false })
    }
    function dayTitle() {
        var today = new Date()
        var yesterday = new Date(today.getFullYear(), today.getMonth(), today.getDate() - 1, 12)
        if (isToday) return qsTr("Today")
        if (day === dateKey(yesterday)) return qsTr("Yesterday")
        return Qt.formatDate(parseDay(day), "ddd d MMM yyyy")
    }
    function duration(minutes) {
        var hh = Math.floor(minutes / 60), mm = minutes % 60
        return hh > 0 ? qsTr("%1 h %2 min").arg(hh).arg(mm) : qsTr("%1 min").arg(mm)
    }
    function clock(ts) { return Qt.formatTime(new Date(ts * 1000), "hh:mm") }
    function ago(ts) {
        if (!ts) return qsTr("never")
        var mins = Math.round((Date.now() / 1000 - ts) / 60)
        if (mins < 1) return qsTr("just now")
        if (mins < 60) return qsTr("%n min ago", "", mins)
        if (mins < 48 * 60) return qsTr("%n h ago", "", Math.round(mins / 60))
        return qsTr("%n day(s) ago", "", Math.round(mins / 1440))
    }

    onDayChanged: load()
    onLastSyncChanged: load()   // a sync finished: show the new data
    Component.onCompleted: load()

    SilicaFlickable {
        anchors.fill: parent
        contentHeight: column.height + Theme.paddingLarge

        PullDownMenu {
            busy: !!hs.syncing
            MenuItem {
                text: qsTr("Open data folder")
                visible: !!hs.folder
                onClicked: Qt.openUrlExternally("file://" + hs.folder)
            }
            MenuItem {
                text: hs.syncing ? qsTr("Syncing…") : qsTr("Sync now")
                enabled: daemon.connected && !hs.syncing
                onClicked: daemon.syncHealth()
            }
        }

        Column {
            id: column
            width: parent.width
            spacing: Theme.paddingMedium

            PageHeader {
                title: qsTr("Health")
                description: hs.syncing ? qsTr("Syncing with the watch…")
                             : hs.error ? hs.error
                             : qsTr("Last sync %1").arg(ago(page.lastSync))
            }

            // ------------------------------------------------- day navigation
            Item {
                width: parent.width
                height: Theme.itemSizeSmall
                IconButton {
                    anchors { left: parent.left; leftMargin: Theme.horizontalPageMargin; verticalCenter: parent.verticalCenter }
                    icon.source: "image://theme/icon-m-left"
                    onClicked: page.shift(-1)
                }
                Label {
                    anchors.centerIn: parent
                    text: page.dayTitle()
                    color: Theme.highlightColor
                    font.pixelSize: Theme.fontSizeLarge
                }
                IconButton {
                    anchors { right: parent.right; rightMargin: Theme.horizontalPageMargin; verticalCenter: parent.verticalCenter }
                    icon.source: "image://theme/icon-m-right"
                    enabled: !page.isToday
                    onClicked: page.shift(1)
                }
            }

            Label {
                x: Theme.horizontalPageMargin
                width: parent.width - 2 * x
                visible: h.available === false
                wrapMode: Text.Wrap
                color: "#ff6b5e"
                text: h.error || ""
            }

            // ---------------------------------------------------------- steps
            Column {
                width: parent.width
                visible: page.hasData
                Label {
                    anchors.horizontalCenter: parent.horizontalCenter
                    text: Number(h.steps || 0).toLocaleString(Qt.locale(), "f", 0)
                    font.pixelSize: Theme.fontSizeHuge
                    color: Theme.highlightColor
                }
                Label {
                    anchors.horizontalCenter: parent.horizontalCenter
                    text: qsTr("steps · %1 km · %2 kcal").arg(((h.distance || 0) / 1000).toFixed(1)).arg(h.calories || 0)
                    color: Theme.secondaryHighlightColor
                }
            }

            Canvas {
                id: stepChart
                x: Theme.horizontalPageMargin
                width: parent.width - 2 * x
                height: Theme.itemSizeLarge
                visible: page.hasData
                property var bars: h.hourlySteps || []
                onBarsChanged: requestPaint()
                onPaint: {
                    var ctx = getContext("2d")
                    ctx.clearRect(0, 0, width, height)
                    var max = 1
                    for (var i = 0; i < bars.length; i++) max = Math.max(max, bars[i])
                    var w = width / 24
                    ctx.fillStyle = Theme.highlightColor
                    for (var j = 0; j < bars.length; j++) {
                        var bh = (height - 2) * bars[j] / max
                        ctx.fillRect(j * w + 1, height - bh, w - 2, bh)
                    }
                    ctx.fillStyle = Theme.rgba(Theme.secondaryColor, 0.4)
                    ctx.fillRect(0, height - 1, width, 1)
                }
            }
            Row {
                x: Theme.horizontalPageMargin
                width: parent.width - 2 * x
                visible: page.hasData
                Repeater {
                    model: ["00", "06", "12", "18"]
                    Label {
                        width: parent.width / 4
                        text: modelData
                        font.pixelSize: Theme.fontSizeTiny
                        color: Theme.secondaryColor
                    }
                }
            }

            // ----------------------------------------------------- heart rate
            SectionHeader { text: qsTr("Heart rate"); visible: page.hasData }
            Canvas {
                id: hrChart
                x: Theme.horizontalPageMargin
                width: parent.width - 2 * x
                height: Theme.itemSizeExtraLarge
                visible: page.hasData && (h.heartRate || []).length > 0
                property var points: h.heartRate || []
                onPointsChanged: requestPaint()
                onPaint: {
                    var ctx = getContext("2d")
                    ctx.clearRect(0, 0, width, height)
                    if (points.length === 0) return
                    var lo = h.heartRateMin - 5, hi = h.heartRateMax + 5
                    ctx.strokeStyle = "#ff6b5e"
                    ctx.lineWidth = Math.max(2, Theme.paddingSmall / 3)
                    ctx.beginPath()
                    for (var i = 0; i < points.length; i++) {
                        var x = width * points[i][0] / 86400
                        var y = height - height * (points[i][1] - lo) / (hi - lo)
                        // Gaps of more than 20 minutes are not drawn as lines
                        if (i === 0 || points[i][0] - points[i - 1][0] > 1200) ctx.moveTo(x, y)
                        else ctx.lineTo(x, y)
                    }
                    ctx.stroke()
                }
            }
            DetailItem {
                visible: page.hasData && h.heartRateAvg !== null && h.heartRateAvg !== undefined
                label: qsTr("Min / avg / max")
                value: qsTr("%1 / %2 / %3 bpm").arg(h.heartRateMin).arg(h.heartRateAvg).arg(h.heartRateMax)
            }
            DetailItem {
                visible: page.hasData && !!h.restingHeartRate
                label: qsTr("Resting")
                value: qsTr("%1 bpm").arg(h.restingHeartRate)
            }
            DetailItem {
                visible: page.hasData && !!h.spo2Min
                label: qsTr("Lowest SpO₂")
                value: h.spo2Min + " %"
            }
            Label {
                x: Theme.horizontalPageMargin
                width: parent.width - 2 * x
                visible: page.hasData && !(h.heartRate || []).length
                wrapMode: Text.Wrap
                font.pixelSize: Theme.fontSizeSmall
                color: Theme.secondaryColor
                text: qsTr("No heart rate readings for this day.")
            }

            // ---------------------------------------------------------- sleep
            SectionHeader { text: qsTr("Sleep"); visible: page.hasData }
            Label {
                x: Theme.horizontalPageMargin
                width: parent.width - 2 * x
                visible: page.hasData
                wrapMode: Text.Wrap
                text: h.sleep && h.sleep.minutes > 0
                      ? qsTr("%1 · %2 – %3").arg(duration(h.sleep.minutes)).arg(clock(h.sleep.start)).arg(clock(h.sleep.end))
                      : qsTr("No sleep recorded for the night before this day.")
                color: h.sleep && h.sleep.minutes > 0 ? Theme.highlightColor : Theme.secondaryColor
            }
            Canvas {
                id: sleepChart
                x: Theme.horizontalPageMargin
                width: parent.width - 2 * x
                height: Theme.itemSizeExtraSmall
                visible: page.hasData && !!h.sleep && h.sleep.minutes > 0
                property var night: h.sleep || {}
                onNightChanged: requestPaint()
                onPaint: {
                    var ctx = getContext("2d")
                    ctx.clearRect(0, 0, width, height)
                    var periods = night.periods || []
                    if (periods.length === 0) return
                    var span = Math.max(1, night.end - night.start)
                    for (var i = 0; i < periods.length; i++) {
                        var deep = periods[i][2] === "deep"
                        ctx.fillStyle = deep ? Theme.highlightColor : Theme.rgba(Theme.highlightColor, 0.4)
                        var x = width * (periods[i][0] - night.start) / span
                        var w = Math.max(1, width * (periods[i][1] - periods[i][0]) / span)
                        ctx.fillRect(x, deep ? 0 : height / 3, w, deep ? height : height * 2 / 3)
                    }
                }
            }
            DetailItem {
                visible: page.hasData && !!h.sleep && !!h.sleep.byType && !!h.sleep.byType.deep
                label: qsTr("Deep sleep")
                value: h.sleep && h.sleep.byType ? duration(h.sleep.byType.deep || 0) : ""
            }
            DetailItem {
                visible: page.hasData && !!h.sleep && !!h.sleep.byType && !!h.sleep.byType.light
                label: qsTr("Light sleep")
                value: h.sleep && h.sleep.byType ? duration(h.sleep.byType.light || 0) : ""
            }
        }

        ViewPlaceholder {
            enabled: !page.loading && !page.hasData && h.available !== false
            text: qsTr("No health data for this day")
            hintText: daemon.connected ? qsTr("Pull down to sync with the watch.")
                                       : qsTr("Connect the watch to sync its data.")
        }

        VerticalScrollDecorator {}
    }
}
