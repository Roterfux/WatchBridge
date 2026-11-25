// WatchBridge - SPDX-License-Identifier: AGPL-3.0-or-later
// One bar per day of a month. Arrays are indexed by day of the month (0 = the 1st); null = no data.
// Colours given to the Canvas are always colour objects: Qt 5.6 can skip string colours.
import QtQuick 2.0
import Sailfish.Silica 1.0

Item {
    id: chart

    property int days: 31
    property var values: []       // top of each bar
    property var lows: []         // optional: where each bar starts (a range), instead of the bottom
    property var inner: []        // optional: a darker part from the bottom (e.g. deep sleep)
    property var marks: []        // optional: a dot per day (e.g. resting heart rate)
    property var colors: []       // optional: a colour per day
    property color color: Theme.highlightColor
    property color markColor: "#ff6b5e"
    property real fade: 1         // bar opacity
    property real goal: 0         // a line; bars below it are drawn fainter
    property real minValue: 0     // value at the bottom edge
    property real maxValue: 0     // value at the top edge, 0 = the largest value
    property int today: -1        // index of today, shaded

    signal dayClicked(int index)

    height: Theme.itemSizeLarge

    onValuesChanged: canvas.requestPaint()
    onLowsChanged: canvas.requestPaint()
    onInnerChanged: canvas.requestPaint()
    onMarksChanged: canvas.requestPaint()
    onGoalChanged: canvas.requestPaint()
    onDaysChanged: canvas.requestPaint()
    onWidthChanged: canvas.requestPaint()

    function has(list, i) { return !!list && i < list.length && list[i] !== null && list[i] !== undefined }

    ChartCanvas {
        id: canvas
        anchors.fill: parent
        onPaint: {
            var ctx = getContext("2d")
            ctx.clearRect(0, 0, width, height)
            var n = Math.max(1, chart.days)
            var top = chart.maxValue
            if (!(top > 0)) {
                top = chart.goal
                for (var i = 0; i < n; i++) {
                    if (chart.has(chart.values, i)) top = Math.max(top, chart.values[i])
                    if (chart.has(chart.marks, i)) top = Math.max(top, chart.marks[i])
                }
            }
            var lo = chart.minValue
            if (!(top > lo)) top = lo + 1
            var h = height
            function y(v) { return h - (h - 2) * (Math.max(lo, Math.min(top, v)) - lo) / (top - lo) }
            var w = width / n
            var gap = Math.max(1, Math.round(w * 0.15))

            if (chart.today >= 0 && chart.today < n) {
                ctx.fillStyle = Theme.rgba(Theme.highlightBackgroundColor, 0.25)
                ctx.fillRect(chart.today * w, 0, w, h)
            }
            for (var d = 0; d < n; d++) {
                if (!chart.has(chart.values, d)) continue
                var v = chart.values[d]
                var c = chart.has(chart.colors, d) ? chart.colors[d] : chart.color
                var below = chart.goal > 0 && v < chart.goal
                ctx.fillStyle = Theme.rgba(c, chart.fade * (below ? 0.5 : 1))
                var bottom = chart.has(chart.lows, d) ? y(chart.lows[d]) : h
                var barTop = y(v)
                ctx.fillRect(d * w + gap / 2, barTop, w - gap, Math.max(2, bottom - barTop))
                if (chart.has(chart.inner, d)) {
                    ctx.fillStyle = Theme.rgba(Qt.darker(c, 1.8), chart.fade)
                    var innerTop = y(chart.inner[d])
                    ctx.fillRect(d * w + gap / 2, innerTop, w - gap, h - innerTop)
                }
            }
            ctx.fillStyle = Theme.rgba(chart.markColor, 1)
            var r = Math.max(2, Math.min(w / 2 - 1, Theme.paddingSmall / 1.5))
            for (var k = 0; k < n; k++) {
                if (!chart.has(chart.marks, k)) continue
                ctx.beginPath()
                ctx.arc(k * w + w / 2, y(chart.marks[k]), r, 0, 2 * Math.PI, false)
                ctx.fill()
            }
            if (chart.goal > 0) {
                ctx.fillStyle = Theme.rgba(Theme.primaryColor, 0.6)
                ctx.fillRect(0, Math.round(y(chart.goal)), width, 1)
            }
            ctx.fillStyle = Theme.rgba(Theme.secondaryColor, 0.4)
            ctx.fillRect(0, h - 1, width, 1)
        }
    }

    MouseArea {
        anchors.fill: parent
        onClicked: {
            var i = Math.floor(mouse.x / (width / Math.max(1, chart.days)))
            if (i >= 0 && i < chart.days && chart.has(chart.values, i)) chart.dayClicked(i)
        }
    }
}
