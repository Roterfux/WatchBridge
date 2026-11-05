// WatchBridge - SPDX-License-Identifier: AGPL-3.0-or-later
// Labels under a chart. ticks: [{ "pos": 0..1 across the width, "text": "06" }]
import QtQuick 2.0
import Sailfish.Silica 1.0

Item {
    id: axis

    property var ticks: []

    height: Theme.fontSizeTiny * 1.5

    Repeater {
        model: axis.ticks
        Label {
            // Centred on its tick, but kept inside the chart's width
            x: Math.max(0, Math.min(axis.width - width, modelData.pos * axis.width - width / 2))
            text: modelData.text
            font.pixelSize: Theme.fontSizeTiny
            color: Theme.secondaryColor
        }
    }
}
