// WatchBridge - SPDX-License-Identifier: AGPL-3.0-or-later
// Concentric progress rings, outermost first: one per daily goal.
import QtQuick 2.0
import Sailfish.Silica 1.0

ChartCanvas {
    id: rings

    // Progress of each ring, 1 = goal reached (more is drawn as a full ring)
    property var values: []
    property var colors: []
    // Ring thickness and the gap between rings, as fractions of the radius
    property real thickness: 0.16
    property real gap: 0.05

    // The usual goal colours, shared by the rings and their legends
    readonly property var palette: ["#4fb3ff", "#7fd36b", "#ffb347", "#b38cff"]

    // Goals as the config stores them (distance in m, sleep in min), with the daemon's defaults
    function goalsFrom(goals) {
        goals = goals || {}
        return { "steps": Math.max(1, goals.steps || 8000), "distance": Math.max(1, goals.distance || 5000),
                 "calories": Math.max(1, goals.calories || 350), "sleep": Math.max(1, goals.sleep || 420) }
    }
    // Ring values for one day of GetHealth: steps, distance, calories, sleep
    function dayValues(h, goals) {
        var g = goalsFrom(goals)
        h = h || {}
        return [(h.steps || 0) / g.steps, (h.distance || 0) / g.distance, (h.calories || 0) / g.calories,
                (h.sleep ? h.sleep.minutes || 0 : 0) / g.sleep]
    }

    implicitWidth: Theme.itemSizeHuge
    implicitHeight: width

    onValuesChanged: requestPaint()
    onColorsChanged: requestPaint()
    onWidthChanged: requestPaint()

    onPaint: {
        var ctx = getContext("2d")
        ctx.clearRect(0, 0, width, height)
        var outer = Math.min(width, height) / 2
        var line = outer * thickness
        var step = line + outer * gap
        ctx.lineCap = "round"
        ctx.lineWidth = line
        for (var i = 0; i < values.length; i++) {
            var r = outer - line / 2 - i * step
            if (r <= line / 2) break
            var color = colors[i] || palette[i % palette.length]
            ctx.strokeStyle = Theme.rgba(color, 0.2)
            ctx.beginPath()
            ctx.arc(width / 2, height / 2, r, 0, 2 * Math.PI, false)
            ctx.stroke()
            var v = Math.max(0, Math.min(1, values[i] || 0))
            if (v <= 0) continue
            // A colour object, not the string: Qt 5.6 can skip a string colour (see HealthPage alertColor)
            ctx.strokeStyle = Theme.rgba(color, 1)
            ctx.beginPath()
            // Clockwise from twelve o'clock
            ctx.arc(width / 2, height / 2, r, -Math.PI / 2, -Math.PI / 2 + 2 * Math.PI * v, false)
            ctx.stroke()
        }
    }
}
