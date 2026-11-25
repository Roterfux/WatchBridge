// WatchBridge - SPDX-License-Identifier: AGPL-3.0-or-later
// One "label ... value" line on the cover
import QtQuick 2.0
import Sailfish.Silica 1.0

Item {
    property alias label: labelText.text
    property alias value: valueText.text
    property alias valueColor: valueText.color

    width: parent ? parent.width : 0
    height: Math.max(labelText.height, valueText.height)

    Label {
        id: labelText
        anchors.left: parent.left
        width: Math.min(implicitWidth, parent.width * 0.45)
        truncationMode: TruncationMode.Fade
        font.pixelSize: Theme.fontSizeExtraSmall
        color: Theme.secondaryColor
    }
    Label {
        id: valueText
        anchors { right: parent.right; left: labelText.right; leftMargin: Theme.paddingSmall }
        horizontalAlignment: Text.AlignRight
        truncationMode: TruncationMode.Fade
        font.pixelSize: Theme.fontSizeExtraSmall
        color: Theme.primaryColor
    }
}
