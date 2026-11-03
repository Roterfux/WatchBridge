// WatchBridge - SPDX-License-Identifier: AGPL-3.0-or-later
// Shown when the watch triggers "Find phone".
import QtQuick 2.0
import Sailfish.Silica 1.0

Page {
    id: page
    property var daemon

    Column {
        anchors.centerIn: parent
        width: parent.width - 2 * Theme.horizontalPageMargin
        spacing: Theme.paddingLarge * 2

        Icon {
            anchors.horizontalCenter: parent.horizontalCenter
            source: "image://theme/icon-l-ringtone"
            SequentialAnimation on scale {
                loops: Animation.Infinite
                NumberAnimation { from: 1.0; to: 1.25; duration: 500; easing.type: Easing.OutQuad }
                NumberAnimation { from: 1.25; to: 1.0; duration: 500; easing.type: Easing.InQuad }
            }
        }
        Label {
            width: parent.width
            horizontalAlignment: Text.AlignHCenter
            wrapMode: Text.Wrap
            font.pixelSize: Theme.fontSizeExtraLarge
            color: Theme.highlightColor
            text: qsTr("Here I am!")
        }
        Label {
            width: parent.width
            horizontalAlignment: Text.AlignHCenter
            wrapMode: Text.Wrap
            color: Theme.secondaryHighlightColor
            text: qsTr("Your watch is looking for this phone.")
        }
        Button {
            anchors.horizontalCenter: parent.horizontalCenter
            text: qsTr("Found it")
            onClicked: {
                daemon.stopFindPhone()
                pageStack.pop()
            }
        }
    }
}
