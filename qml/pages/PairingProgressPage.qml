// WatchBridge - SPDX-License-Identifier: AGPL-3.0-or-later
import QtQuick 2.0
import Sailfish.Silica 1.0
import "../components"

Page {
    id: page

    property var daemon
    property string address
    property string name
    property bool started: false

    readonly property string st: daemon.watchState
    readonly property string detail: daemon.status.detail || ""
    // Ignore whatever state the daemon had before it acknowledged our Pair call
    property bool seenPairing: false
    readonly property bool done: seenPairing && st === "connected"
    readonly property bool failed: seenPairing && (st === "auth_failed" || (st === "disconnected" && stepIndex > 0))

    // 0 bluetooth, 1 connecting, 2 authenticating, 3 setting up, 4 done
    property int stepIndex: 0
    onStChanged: {
        if (st === "pairing") seenPairing = true
        if (!seenPairing) return
        var map = { "pairing": 0, "connecting": 1, "authenticating": 2, "initializing": 3, "connected": 4 }
        if (map[st] !== undefined && map[st] > stepIndex) stepIndex = map[st]
    }

    backNavigation: !started || done || failed

    onStatusChanged: {
        if (status === PageStatus.Active && !started) {
            started = true
            stepIndex = 0
            daemon.pair(address, name)
        }
    }

    SilicaFlickable {
        anchors.fill: parent
        contentHeight: column.height

        Column {
            id: column
            width: parent.width
            spacing: Theme.paddingLarge

            PageHeader {
                title: page.done ? qsTr("All set!") : page.failed ? qsTr("Pairing failed") : qsTr("Pairing")
                description: page.name
            }

            WatchFace {
                anchors.horizontalCenter: parent.horizontalCenter
                width: Math.min(page.width, page.height) * 0.45
                height: width
                watchState: page.done ? "connected" : page.failed ? "auth_failed" : "pairing"
                busy: !page.done && !page.failed
                battery: page.done ? daemon.status.battery : -1
            }

            Repeater {
                model: [
                    qsTr("Bluetooth pairing"),
                    qsTr("Opening the watch connection"),
                    qsTr("Secure handshake (HiChain)"),
                    qsTr("Setting up time, notifications and weather")
                ]
                Item {
                    x: Theme.horizontalPageMargin
                    width: parent.width - 2 * x
                    height: Theme.itemSizeExtraSmall
                    readonly property bool active: index === page.stepIndex && !page.done && !page.failed
                    readonly property bool complete: index < page.stepIndex || page.done

                    BusyIndicator {
                        id: spinner
                        anchors.verticalCenter: parent.verticalCenter
                        size: BusyIndicatorSize.ExtraSmall
                        running: parent.active
                        visible: running
                    }
                    Icon {
                        anchors.centerIn: spinner
                        visible: !spinner.running
                        source: parent.complete ? "image://theme/icon-s-installed"
                              : (page.failed && index === page.stepIndex) ? "image://theme/icon-s-high-importance"
                              : "image://theme/icon-s-checkmark"
                        opacity: parent.complete || (page.failed && index === page.stepIndex) ? 1.0 : 0.3
                    }
                    Label {
                        anchors { left: spinner.right; leftMargin: Theme.paddingLarge; right: parent.right
                                  verticalCenter: parent.verticalCenter }
                        text: modelData
                        truncationMode: TruncationMode.Fade
                        color: parent.active ? Theme.highlightColor
                             : parent.complete ? Theme.primaryColor : Theme.secondaryColor
                    }
                }
            }

            // Call to action while the watch wants a confirmation
            Rectangle {
                x: Theme.horizontalPageMargin
                width: parent.width - 2 * x
                height: confirmLabel.height + 2 * Theme.paddingLarge
                radius: Theme.paddingMedium
                color: Theme.rgba(Theme.highlightBackgroundColor, 0.25)
                visible: !page.done && !page.failed && (page.stepIndex <= 0 || detail === "confirm_on_watch")
                Label {
                    id: confirmLabel
                    anchors.centerIn: parent
                    width: parent.width - 2 * Theme.paddingLarge
                    wrapMode: Text.Wrap
                    horizontalAlignment: Text.AlignHCenter
                    color: Theme.highlightColor
                    text: page.stepIndex <= 0
                          ? qsTr("Accept the Bluetooth pairing request on the phone and on the watch.")
                          : qsTr("Look at your watch and tap ✓ to allow the connection.")
                }
            }

            Label {
                x: Theme.horizontalPageMargin
                width: parent.width - 2 * x
                visible: page.failed
                wrapMode: Text.Wrap
                color: "#ff6b5e"
                text: page.detail || qsTr("The watch did not accept the pairing.")
            }

            Label {
                x: Theme.horizontalPageMargin
                width: parent.width - 2 * x
                visible: page.done
                wrapMode: Text.Wrap
                horizontalAlignment: Text.AlignHCenter
                color: Theme.secondaryHighlightColor
                text: qsTr("Your watch is connected. Notifications and weather will be sent automatically.")
            }

            ButtonLayout {
                Button {
                    visible: page.failed
                    text: qsTr("Try again")
                    onClicked: {
                        page.stepIndex = 0
                        page.seenPairing = false
                        daemon.pair(page.address, page.name)
                    }
                }
                Button {
                    visible: page.done || page.failed
                    text: page.done ? qsTr("Done") : qsTr("Back")
                    onClicked: pageStack.pop(pageStack.find(function(p) { return p.hasOwnProperty("wx") }) || null)
                }
            }
        }
    }
}
