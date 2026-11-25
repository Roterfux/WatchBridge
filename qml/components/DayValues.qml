// WatchBridge - SPDX-License-Identifier: AGPL-3.0-or-later
// One small centred label per day under a chart (the week view has room for them).
import QtQuick 2.0
import Sailfish.Silica 1.0

Row {
    id: row

    property var values: []        // one string per day, "" for none
    property bool secondary: false

    x: Theme.horizontalPageMargin
    width: (parent ? parent.width : 0) - 2 * x

    Repeater {
        model: row.values
        Label {
            width: row.width / Math.max(1, row.values.length)
            horizontalAlignment: Text.AlignHCenter
            fontSizeMode: Text.HorizontalFit
            minimumPixelSize: Theme.fontSizeTiny * 0.8
            font.pixelSize: Theme.fontSizeTiny
            color: row.secondary ? Theme.secondaryColor : Theme.highlightColor
            text: modelData
        }
    }
}
