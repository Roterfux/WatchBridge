// WatchBridge - SPDX-License-Identifier: AGPL-3.0-or-later
// A round watch drawn on a Canvas: live hands, a battery ring and a state glow.
import QtQuick 2.0
import Sailfish.Silica 1.0

Item {
    id: root

    property int battery: -1
    property string watchState: "unknown"
    property bool busy: false
    property date now: new Date()

    readonly property color accent: watchState === "connected" ? Theme.highlightColor
                                  : watchState === "auth_failed" ? "#ff6b5e"
                                  : Theme.secondaryHighlightColor
    readonly property color batteryColor: battery < 0 ? Theme.secondaryColor
                                        : battery <= 15 ? "#ff6b5e"
                                        : battery <= 35 ? "#ffb347" : "#4cd964"

    implicitWidth: Theme.itemSizeHuge * 2
    implicitHeight: implicitWidth

    Timer {
        interval: 1000; running: Qt.application.active; repeat: true
        onTriggered: { root.now = new Date(); canvas.requestPaint() }
    }
    onBatteryChanged: canvas.requestPaint()
    onWatchStateChanged: canvas.requestPaint()
    onAccentChanged: canvas.requestPaint()

    // Soft pulsing halo while connecting/pairing
    onBusyChanged: if (!busy) halo.opacity = 0

    Rectangle {
        id: halo
        anchors.centerIn: parent
        width: parent.width; height: width; radius: width / 2
        color: "transparent"
        border.width: Theme.paddingSmall
        border.color: root.accent
        opacity: 0
        SequentialAnimation on opacity {
            running: root.busy
            loops: Animation.Infinite
            NumberAnimation { from: 0.0; to: 0.5; duration: 900; easing.type: Easing.InOutQuad }
            NumberAnimation { from: 0.5; to: 0.0; duration: 900; easing.type: Easing.InOutQuad }
        }
    }

    Canvas {
        id: canvas
        anchors.fill: parent
        anchors.margins: Theme.paddingMedium
        antialiasing: true

        onPaint: {
            var ctx = getContext("2d")
            var w = width, h = height, cx = w / 2, cy = h / 2
            var r = Math.min(w, h) / 2
            ctx.reset()

            // Bezel
            ctx.beginPath()
            ctx.arc(cx, cy, r - 1, 0, 2 * Math.PI)
            ctx.fillStyle = "#1c1f24"
            ctx.fill()
            ctx.lineWidth = r * 0.04
            ctx.strokeStyle = "#3a3f47"
            ctx.stroke()

            // Battery track + arc
            var ringR = r * 0.86
            ctx.lineCap = "round"
            ctx.lineWidth = r * 0.07
            ctx.beginPath()
            ctx.arc(cx, cy, ringR, 0, 2 * Math.PI)
            ctx.strokeStyle = Qt.rgba(1, 1, 1, 0.08)
            ctx.stroke()
            if (root.battery >= 0) {
                ctx.beginPath()
                ctx.arc(cx, cy, ringR, -Math.PI / 2, -Math.PI / 2 + 2 * Math.PI * root.battery / 100)
                ctx.strokeStyle = root.batteryColor
                ctx.stroke()
            }

            // Hour ticks
            ctx.lineCap = "butt"
            for (var i = 0; i < 12; i++) {
                var a = i * Math.PI / 6
                var inner = r * (i % 3 === 0 ? 0.62 : 0.68)
                ctx.beginPath()
                ctx.moveTo(cx + Math.sin(a) * inner, cy - Math.cos(a) * inner)
                ctx.lineTo(cx + Math.sin(a) * r * 0.74, cy - Math.cos(a) * r * 0.74)
                ctx.lineWidth = i % 3 === 0 ? r * 0.03 : r * 0.015
                ctx.strokeStyle = Qt.rgba(1, 1, 1, i % 3 === 0 ? 0.85 : 0.4)
                ctx.stroke()
            }

            // Hands
            var t = root.now
            var hAng = ((t.getHours() % 12) + t.getMinutes() / 60) * Math.PI / 6
            var mAng = (t.getMinutes() + t.getSeconds() / 60) * Math.PI / 30
            var sAng = t.getSeconds() * Math.PI / 30
            function hand(angle, length, width, color) {
                ctx.beginPath()
                ctx.moveTo(cx - Math.sin(angle) * r * 0.08, cy + Math.cos(angle) * r * 0.08)
                ctx.lineTo(cx + Math.sin(angle) * length, cy - Math.cos(angle) * length)
                ctx.lineWidth = width
                ctx.lineCap = "round"
                ctx.strokeStyle = color
                ctx.stroke()
            }
            hand(hAng, r * 0.38, r * 0.05, "#ffffff")
            hand(mAng, r * 0.56, r * 0.035, "#ffffff")
            hand(sAng, r * 0.6, r * 0.012, root.accent)
            ctx.beginPath()
            ctx.arc(cx, cy, r * 0.035, 0, 2 * Math.PI)
            ctx.fillStyle = root.accent
            ctx.fill()
        }
    }

    Label {
        anchors { horizontalCenter: parent.horizontalCenter; top: parent.verticalCenter; topMargin: parent.height * 0.14 }
        text: root.battery >= 0 ? root.battery + " %" : ""
        font.pixelSize: Theme.fontSizeExtraSmall
        color: root.batteryColor
    }
}
