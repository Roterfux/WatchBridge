// WatchBridge - SPDX-License-Identifier: AGPL-3.0-or-later
// Steps, heart rate and sleep for one day, from the data synced off the watch.
import QtQuick 2.0
import Sailfish.Silica 1.0
import "../components"

Page {
    id: page

    property var daemon
    property string day: dateKey(new Date())
    property var h: ({})
    property bool loading: true

    // Time axis of the day charts (steps, heart rate)
    readonly property var dayTicks: [{ "pos": 0, "text": "00" }, { "pos": 0.25, "text": "06" },
                                     { "pos": 0.5, "text": "12" }, { "pos": 0.75, "text": "18" },
                                     { "pos": 1, "text": "24" }]
    // Time axis of the sleep chart: whole hours between the first and the last period
    readonly property var sleepTicks: {
        var p = h.sleep && h.sleep.periods ? h.sleep.periods : []
        if (p.length === 0) return []
        var first = p[0][0], last = p[p.length - 1][1]
        var span = Math.max(1, last - first)
        var step = span > 8 * 3600 ? 2 : 1
        var d = new Date(first * 1000)
        d.setMinutes(0, 0, 0)
        d = new Date(d.getTime() + 3600000)
        var out = []
        while (d.getTime() / 1000 < last) {
            if (d.getHours() % step === 0)
                out.push({ "pos": (d.getTime() / 1000 - first) / span, "text": Qt.formatTime(d, "hh:mm") })
            d = new Date(d.getTime() + 3600000)
        }
        return out
    }

    function stageColor(stage) {
        return stage === "awake" ? "#ff6b5e"
             : stage === "deep" ? Theme.highlightColor
             : stage === "rem" ? Theme.rgba(Theme.highlightColor, 0.7)
             : Theme.rgba(Theme.highlightColor, 0.4)
    }
    // Faint vertical lines at the axis ticks
    function drawGrid(ctx, width, height, ticks) {
        ctx.strokeStyle = Theme.rgba(Theme.secondaryColor, 0.25)
        ctx.lineWidth = 1
        ctx.beginPath()
        for (var i = 0; i < ticks.length; i++) {
            if (ticks[i].pos <= 0 || ticks[i].pos >= 1) continue
            var x = Math.round(ticks[i].pos * width) + 0.5
            ctx.moveTo(x, 0)
            ctx.lineTo(x, height)
        }
        ctx.stroke()
    }

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
                    page.drawGrid(ctx, width, height, page.dayTicks)
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
            TimeAxis {
                x: Theme.horizontalPageMargin
                width: parent.width - 2 * x
                visible: page.hasData
                ticks: page.dayTicks
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
                    page.drawGrid(ctx, width, height, page.dayTicks)
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
            TimeAxis {
                x: Theme.horizontalPageMargin
                width: parent.width - 2 * x
                visible: hrChart.visible
                ticks: page.dayTicks
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
            // Hypnogram: awake on top, then REM, light and deep at the bottom
            Canvas {
                id: sleepChart
                x: Theme.horizontalPageMargin
                width: parent.width - 2 * x
                height: Theme.itemSizeLarge
                visible: page.hasData && !!h.sleep && h.sleep.minutes > 0
                property var night: h.sleep || {}
                readonly property var rows: ({ "awake": 0, "rem": 1, "light": 2, "nap": 2, "deep": 3 })
                onNightChanged: requestPaint()
                onPaint: {
                    var ctx = getContext("2d")
                    ctx.clearRect(0, 0, width, height)
                    var periods = night.periods || []
                    if (periods.length === 0) return
                    page.drawGrid(ctx, width, height, page.sleepTicks)
                    var first = periods[0][0], last = periods[periods.length - 1][1]
                    var span = Math.max(1, last - first)
                    var rowH = height / 4
                    for (var i = 0; i < periods.length; i++) {
                        var stage = periods[i][2]
                        var row = rows[stage] !== undefined ? rows[stage] : 2
                        ctx.fillStyle = page.stageColor(stage)
                        var x = width * (periods[i][0] - first) / span
                        var w = Math.max(1, width * (periods[i][1] - periods[i][0]) / span)
                        ctx.fillRect(x, row * rowH + 1, w, rowH - 2)
                    }
                }
            }
            TimeAxis {
                x: Theme.horizontalPageMargin
                width: parent.width - 2 * x
                visible: sleepChart.visible
                ticks: page.sleepTicks
            }
            // Legend, top to bottom in the order of the chart's rows
            Flow {
                x: Theme.horizontalPageMargin
                width: parent.width - 2 * x
                spacing: Theme.paddingLarge
                visible: sleepChart.visible
                Repeater {
                    model: [["awake", qsTr("Awake")], ["rem", qsTr("REM")], ["light", qsTr("Light")],
                            ["deep", qsTr("Deep")]]
                    Row {
                        spacing: Theme.paddingSmall
                        Rectangle {
                            anchors.verticalCenter: parent.verticalCenter
                            width: Theme.fontSizeExtraSmall
                            height: width
                            radius: 2
                            color: page.stageColor(modelData[0])
                        }
                        Label {
                            text: modelData[1]
                            font.pixelSize: Theme.fontSizeExtraSmall
                            color: Theme.secondaryColor
                        }
                    }
                }
            }
            DetailItem {
                visible: page.hasData && !!h.sleep && h.sleep.score !== null && h.sleep.score !== undefined
                label: qsTr("Sleep score")
                value: h.sleep ? String(h.sleep.score) : ""
            }
            DetailItem {
                visible: page.hasData && !!h.sleep && !!h.sleep.summary && !!h.sleep.summary.efficiency
                label: qsTr("Efficiency")
                value: h.sleep && h.sleep.summary ? h.sleep.summary.efficiency + " %" : ""
            }
            DetailItem {
                visible: page.hasData && !!h.sleep && !!h.sleep.summary && h.sleep.summary.latency !== undefined
                label: qsTr("Time to fall asleep")
                value: h.sleep && h.sleep.summary ? duration(h.sleep.summary.latency || 0) : ""
            }
            Repeater {
                model: [["deep", qsTr("Deep sleep")], ["rem", qsTr("REM sleep")],
                        ["light", qsTr("Light sleep")], ["nap", qsTr("Nap")], ["awake", qsTr("Awake")]]
                DetailItem {
                    visible: page.hasData && !!h.sleep && !!h.sleep.byType && !!h.sleep.byType[modelData[0]]
                    label: modelData[1]
                    value: h.sleep && h.sleep.byType ? duration(h.sleep.byType[modelData[0]] || 0) : ""
                }
            }
            DetailItem {
                visible: page.hasData && !!h.sleep && !!h.sleep.summary && !!h.sleep.summary.avg_breath_rate
                label: qsTr("Breathing rate")
                value: h.sleep && h.sleep.summary ? qsTr("%1 /min").arg(h.sleep.summary.avg_breath_rate) : ""
            }

            // --------------------------------------------------------- stress
            SectionHeader { text: qsTr("Stress"); visible: page.hasData && !!h.stress && h.stress.count > 0 }
            Canvas {
                x: Theme.horizontalPageMargin
                width: parent.width - 2 * x
                height: Theme.itemSizeMedium
                visible: page.hasData && !!h.stress && h.stress.count > 0
                property var points: h.stress ? h.stress.points : []
                onPointsChanged: requestPaint()
                onPaint: {
                    var ctx = getContext("2d")
                    ctx.clearRect(0, 0, width, height)
                    for (var i = 0; i < points.length; i++) {
                        var v = points[i][1]
                        // Huawei's bands: relaxed < 30, normal < 60, medium < 80, high
                        ctx.fillStyle = v < 30 ? "#4fb3ff" : v < 60 ? "#7fd36b" : v < 80 ? "#ffb347" : "#ff6b5e"
                        var x = width * points[i][0] / 86400
                        var bh = height * v / 100
                        ctx.fillRect(x - 1, height - bh, 3, bh)
                    }
                }
            }
            DetailItem {
                visible: page.hasData && !!h.stress && h.stress.count > 0
                label: qsTr("Average / highest")
                value: h.stress ? qsTr("%1 / %2").arg(h.stress.avg).arg(h.stress.max) : ""
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
