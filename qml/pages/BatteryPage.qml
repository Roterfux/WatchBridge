// WatchBridge - SPDX-License-Identifier: AGPL-3.0-or-later
// The watch's battery level over the last day, week or month.
import QtQuick 2.0
import Sailfish.Silica 1.0
import "../components"

Page {
    id: page

    property var daemon
    property int days: 7
    property var points: []
    property int since: 0
    property bool loading: true

    readonly property int level: daemon.status.battery !== undefined ? daemon.status.battery : -1
    readonly property var ranges: [1, 7, 30]
    readonly property color lineColor: "#7fd36b"

    function load() {
        loading = true
        daemon.getBatteryHistory(days, function(r) {
            page.since = r.since || Math.round(Date.now() / 1000) - page.days * 86400
            page.points = r.points || []
            page.loading = false
        })
    }
    onDaysChanged: load()
    onLevelChanged: load()
    Component.onCompleted: load()

    // Axis labels: hours for one day, dates otherwise
    readonly property var ticks: {
        var out = []
        var span = days * 86400
        var now = Date.now() / 1000
        var start = now - span
        var d = new Date(start * 1000)
        if (days === 1) {
            d.setMinutes(0, 0, 0)
            for (var h = 0; h <= 24; h++) {
                var t = d.getTime() / 1000 + h * 3600
                if (t > start && t < now && new Date(t * 1000).getHours() % 6 === 0)
                    out.push({ "pos": (t - start) / span, "text": Qt.formatTime(new Date(t * 1000), "hh:mm") })
            }
        } else {
            d.setHours(0, 0, 0, 0)
            var step = days > 7 ? 7 : 1
            for (var i = 1; i <= days; i++) {
                var day = new Date(d.getFullYear(), d.getMonth(), d.getDate() + i)
                var ts = day.getTime() / 1000
                if (ts < now && i % step === 0)
                    out.push({ "pos": (ts - start) / span, "text": Qt.formatDate(day, "d.M.") })
            }
        }
        return out
    }

    SilicaFlickable {
        anchors.fill: parent
        contentHeight: column.height + Theme.paddingLarge

        Column {
            id: column
            width: parent.width
            spacing: Theme.paddingMedium

            PageHeader {
                title: qsTr("Watch battery")
                description: page.level >= 0 ? qsTr("%1 % now").arg(page.level) : ""
            }

            ComboBox {
                label: qsTr("Show")
                currentIndex: Math.max(0, page.ranges.indexOf(page.days))
                menu: ContextMenu {
                    MenuItem { text: qsTr("Last day") }
                    MenuItem { text: qsTr("Last week") }
                    MenuItem { text: qsTr("Last month") }
                }
                onCurrentIndexChanged: page.days = page.ranges[currentIndex]
            }

            ChartCanvas {
                id: chart
                x: Theme.horizontalPageMargin
                width: parent.width - 2 * x
                height: Theme.itemSizeHuge * 1.5
                visible: page.points.length > 0
                property var pts: page.points
                onPtsChanged: requestPaint()
                onPaint: {
                    var ctx = getContext("2d")
                    ctx.clearRect(0, 0, width, height)
                    var start = page.since, now = Date.now() / 1000, span = Math.max(1, now - start)
                    function x(t) { return width * (t - start) / span }
                    function y(v) { return height - 2 - (height - 4) * v / 100 }
                    // Guides at 20, 50 and 80 %
                    ctx.fillStyle = Theme.rgba(Theme.secondaryColor, 0.25)
                    var guides = [20, 50, 80]
                    for (var g = 0; g < guides.length; g++) ctx.fillRect(0, Math.round(y(guides[g])), width, 1)
                    if (pts.length === 0) return
                    // A step line: the level holds until the next reading, the last one until now
                    ctx.strokeStyle = Theme.rgba(page.lineColor, 1)
                    ctx.lineWidth = Math.max(3, Theme.paddingSmall / 2)
                    ctx.lineJoin = "round"
                    ctx.beginPath()
                    ctx.moveTo(x(pts[0][0]), y(pts[0][1]))
                    for (var i = 1; i < pts.length; i++) {
                        ctx.lineTo(x(pts[i][0]), y(pts[i - 1][1]))
                        ctx.lineTo(x(pts[i][0]), y(pts[i][1]))
                    }
                    ctx.lineTo(x(now), y(pts[pts.length - 1][1]))
                    ctx.stroke()
                }
            }
            TimeAxis {
                x: Theme.horizontalPageMargin
                width: parent.width - 2 * x
                visible: chart.visible
                ticks: page.ticks
            }
            Label {
                x: Theme.horizontalPageMargin
                width: parent.width - 2 * x
                visible: chart.visible
                wrapMode: Text.Wrap
                font.pixelSize: Theme.fontSizeExtraSmall
                color: Theme.secondaryColor
                text: qsTr("Lines at 20, 50 and 80 %. Recorded while the watch is connected.")
            }
        }

        ViewPlaceholder {
            enabled: !page.loading && page.points.length === 0
            text: qsTr("No battery readings yet")
            hintText: qsTr("The level is recorded from now on while the watch is connected.")
        }

        VerticalScrollDecorator {}
    }
}
