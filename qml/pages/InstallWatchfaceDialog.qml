// WatchBridge - SPDX-License-Identifier: AGPL-3.0-or-later
// Shows a picked watch-face package and installs it on the watch.
import QtQuick 2.0
import Sailfish.Silica 1.0
import "../components"

Dialog {
    id: dialog

    property var daemon
    property string path
    property var info: ({})

    readonly property bool usable: !!info.ok && info.fits !== false
    canAccept: usable && daemon.connected
    onAccepted: daemon.installWatchface(path)

    SilicaFlickable {
        anchors.fill: parent
        contentHeight: column.height + Theme.paddingLarge

        Column {
            id: column
            width: parent.width
            spacing: Theme.paddingMedium

            DialogHeader {
                acceptText: qsTr("Install")
                title: dialog.usable ? qsTr("Install on the watch?") : ""
            }

            RoundImage {
                // Round, like the watch
                visible: !!dialog.info.preview
                anchors.horizontalCenter: parent.horizontalCenter
                width: Math.min(parent.width * 0.6, Theme.itemSizeHuge * 2.5)
                height: width
                source: dialog.info.preview ? "file://" + dialog.info.preview : ""
            }

            Label {
                x: Theme.horizontalPageMargin
                width: parent.width - 2 * x
                visible: !!dialog.info.ok
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.Wrap
                font.pixelSize: Theme.fontSizeLarge
                color: Theme.highlightColor
                text: dialog.info.title || ""
            }

            DetailItem {
                visible: !!dialog.info.author
                label: qsTr("Made by")
                value: dialog.info.author || ""
            }
            DetailItem {
                visible: !!dialog.info.version
                label: qsTr("Version")
                value: dialog.info.version || ""
            }
            DetailItem {
                visible: !!dialog.info.ok
                label: qsTr("Made for")
                value: dialog.info.resolution ? dialog.info.resolution.replace("*", " × ")
                                              : (dialog.info.screen || qsTr("unknown screen"))
            }
            DetailItem {
                visible: !!dialog.info.ok
                label: qsTr("Size")
                value: (dialog.info.size / 1048576).toFixed(1) + " MB"
            }

            Label {
                x: Theme.horizontalPageMargin
                width: parent.width - 2 * x
                wrapMode: Text.Wrap
                font.pixelSize: Theme.fontSizeSmall
                color: dialog.usable ? Theme.secondaryHighlightColor : "#ff6b5e"
                text: !dialog.info.ok ? (dialog.info.error || qsTr("This file cannot be read."))
                      : dialog.info.fits === false
                        ? qsTr("This face was made for a %1 screen; your watch has %2.")
                              .arg((dialog.info.resolution || dialog.info.screen || "?").replace("*", " × "))
                              .arg((dialog.info.watchResolution || "?").replace("*", " × "))
                      : !daemon.connected ? qsTr("Connect the watch to install it.")
                      : qsTr("Sending it takes a minute or two; keep the watch close to the phone.")
            }
        }
    }
}
