// WatchBridge - SPDX-License-Identifier: AGPL-3.0-or-later
// An image cut to a circle, like a round watch display.
import QtQuick 2.0
import QtGraphicalEffects 1.0

Item {
    id: root

    property alias source: image.source
    readonly property bool ready: image.status === Image.Ready

    Image {
        id: image
        anchors.fill: parent
        fillMode: Image.PreserveAspectCrop
        asynchronous: true
        smooth: true
        visible: false   // drawn through the mask
    }
    Rectangle {
        id: mask
        anchors.fill: parent
        radius: width / 2
        visible: false
    }
    OpacityMask {
        anchors.fill: parent
        source: image
        maskSource: mask
        visible: root.ready
    }
}
