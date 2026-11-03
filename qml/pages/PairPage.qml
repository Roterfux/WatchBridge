// WatchBridge - SPDX-License-Identifier: AGPL-3.0-or-later
// Step 1: discover the watch. Step 2 (PairingProgressPage) bonds and authenticates.
import QtQuick 2.0
import Sailfish.Silica 1.0

Page {
    id: page

    property var daemon
    property bool showAll: false

    readonly property var shown: {
        var out = []
        for (var i = 0; i < daemon.devices.length; i++) {
            var d = daemon.devices[i]
            if (showAll || d.isWatch) out.push(d)
        }
        return out
    }

    onStatusChanged: {
        if (status === PageStatus.Active) daemon.startScan()
        else if (status === PageStatus.Deactivating) daemon.stopScan()
    }

    SilicaListView {
        id: list
        anchors.fill: parent
        model: page.shown

        PullDownMenu {
            busy: daemon.status.scanning
            MenuItem {
                text: page.showAll ? qsTr("Show only watches") : qsTr("Show all devices")
                onClicked: page.showAll = !page.showAll
            }
            MenuItem {
                text: qsTr("Scan again")
                onClicked: daemon.startScan()
            }
        }

        header: Column {
            width: list.width
            spacing: Theme.paddingMedium

            PageHeader {
                title: qsTr("Pair a watch")
                description: daemon.status.scanning ? qsTr("Searching…") : qsTr("Search finished")
            }

            Repeater {
                model: [
                    qsTr("On the watch, open Settings → System & updates → Reset if it is still paired with another phone."),
                    qsTr("Keep the watch close to the phone with Bluetooth on. A new watch shows a pairing screen automatically."),
                    qsTr("Tap your watch below. Accept the Bluetooth request on the phone, then confirm on the watch.")
                ]
                Row {
                    x: Theme.horizontalPageMargin
                    width: parent.width - 2 * x
                    spacing: Theme.paddingMedium
                    Rectangle {
                        width: Theme.iconSizeSmall; height: width; radius: width / 2
                        color: Theme.rgba(Theme.highlightBackgroundColor, 0.3)
                        Label {
                            anchors.centerIn: parent
                            text: index + 1
                            font.pixelSize: Theme.fontSizeExtraSmall
                            color: Theme.highlightColor
                        }
                    }
                    Label {
                        width: parent.width - Theme.iconSizeSmall - Theme.paddingMedium
                        wrapMode: Text.Wrap
                        font.pixelSize: Theme.fontSizeSmall
                        color: Theme.secondaryHighlightColor
                        text: modelData
                    }
                }
            }

            Label {
                x: Theme.horizontalPageMargin
                visible: daemon.status.bluetoothOn === false
                text: qsTr("Bluetooth is off. Turn it on in the top menu.")
                color: "#ff6b5e"
            }

            SectionHeader { text: qsTr("Nearby") }
        }

        delegate: ListItem {
            id: item
            contentHeight: Theme.itemSizeMedium
            onClicked: pageStack.push(Qt.resolvedUrl("PairingProgressPage.qml"),
                                      { daemon: daemon, address: modelData.address, name: modelData.name })

            Icon {
                id: icon
                x: Theme.horizontalPageMargin
                anchors.verticalCenter: parent.verticalCenter
                source: modelData.isWatch ? "image://theme/icon-m-clock" : "image://theme/icon-m-bluetooth-device"
                color: item.highlighted ? Theme.highlightColor : Theme.primaryColor
            }
            Column {
                anchors { left: icon.right; leftMargin: Theme.paddingMedium; right: rssiLabel.left
                          rightMargin: Theme.paddingMedium; verticalCenter: parent.verticalCenter }
                Label {
                    width: parent.width
                    truncationMode: TruncationMode.Fade
                    text: modelData.name || modelData.address
                    color: item.highlighted || modelData.isWatch ? Theme.highlightColor : Theme.primaryColor
                }
                Label {
                    width: parent.width
                    font.pixelSize: Theme.fontSizeExtraSmall
                    color: Theme.secondaryColor
                    text: modelData.address + (modelData.paired ? " · " + qsTr("paired") : "")
                }
            }
            Label {
                id: rssiLabel
                anchors { right: parent.right; rightMargin: Theme.horizontalPageMargin; verticalCenter: parent.verticalCenter }
                visible: modelData.rssi > -999
                text: modelData.rssi + " dBm"
                font.pixelSize: Theme.fontSizeExtraSmall
                color: Theme.secondaryColor
            }
        }

        ViewPlaceholder {
            enabled: list.count === 0
            text: daemon.status.scanning ? qsTr("Looking for watches…") : qsTr("No watch found")
            hintText: page.showAll ? "" : qsTr("Pull down to show all Bluetooth devices")
        }

        BusyIndicator {
            anchors { horizontalCenter: parent.horizontalCenter; bottom: parent.bottom; bottomMargin: Theme.paddingLarge * 2 }
            size: BusyIndicatorSize.Medium
            running: daemon.status.scanning && list.count > 0
        }

        VerticalScrollDecorator {}
    }
}
