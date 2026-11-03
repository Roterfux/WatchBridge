// WatchBridge - SPDX-License-Identifier: AGPL-3.0-or-later
import QtQuick 2.0
import Sailfish.Silica 1.0

Page {
    id: page

    property var daemon
    readonly property var s: daemon.settings
    readonly property var n: s.notifications || {}
    readonly property var w: s.weather || {}
    readonly property var watch: s.watch || {}

    readonly property var intervals: [15, 30, 60, 120, 180]

    SilicaFlickable {
        anchors.fill: parent
        contentHeight: column.height + Theme.paddingLarge

        Column {
            id: column
            width: parent.width

            PageHeader { title: qsTr("Settings") }

            SectionHeader { text: qsTr("Connection") }

            TextSwitch {
                text: qsTr("Reconnect automatically")
                description: qsTr("Keep the watch connected in the background and reconnect when it comes back into range.")
                checked: s.auto_reconnect !== false
                automaticCheck: false
                onClicked: daemon.updateSettings({ "auto_reconnect": !checked })
            }

            SectionHeader { text: qsTr("Notifications") }

            TextSwitch {
                text: qsTr("Forward notifications")
                checked: n.enabled !== false
                automaticCheck: false
                onClicked: daemon.updateSettings({ "notifications": { "enabled": !checked } })
            }
            TextSwitch {
                text: qsTr("Include system notifications")
                description: qsTr("Battery, transfers, connectivity and other device status messages.")
                checked: !!n.include_system
                automaticCheck: false
                onClicked: daemon.updateSettings({ "notifications": { "include_system": !checked } })
            }
            ValueButton {
                label: qsTr("Muted apps")
                value: (n.blocked_apps || []).length === 0 ? qsTr("None") : (n.blocked_apps || []).join(", ")
                onClicked: pageStack.push(blockedDialog)
            }

            SectionHeader { text: qsTr("Weather") }

            TextSwitch {
                text: qsTr("Send weather to the watch")
                description: qsTr("Forecasts from Open-Meteo.com")
                checked: w.enabled !== false
                automaticCheck: false
                onClicked: daemon.updateSettings({ "weather": { "enabled": !checked } })
            }
            ValueButton {
                label: qsTr("Location")
                value: w.location || qsTr("Not set")
                onClicked: pageStack.push(Qt.resolvedUrl("LocationPage.qml"), { daemon: daemon })
            }
            ComboBox {
                label: qsTr("Units")
                currentIndex: w.fahrenheit ? 1 : 0
                menu: ContextMenu {
                    MenuItem { text: qsTr("Celsius, km/h") }
                    MenuItem { text: qsTr("Fahrenheit, mph") }
                }
                onCurrentIndexChanged: {
                    if (!page.s.weather) return
                    if ((currentIndex === 1) !== !!w.fahrenheit)
                        daemon.updateSettings({ "weather": { "fahrenheit": currentIndex === 1 } })
                }
            }
            ComboBox {
                label: qsTr("Update every")
                currentIndex: Math.max(0, page.intervals.indexOf(w.interval_minutes || 60))
                menu: ContextMenu {
                    Repeater {
                        model: page.intervals
                        MenuItem { text: modelData < 60 ? qsTr("%n minute(s)", "", modelData) : qsTr("%n hour(s)", "", modelData / 60) }
                    }
                }
                onCurrentIndexChanged: {
                    if (!page.s.weather) return
                    var v = page.intervals[currentIndex]
                    if (v !== w.interval_minutes)
                        daemon.updateSettings({ "weather": { "interval_minutes": v } })
                }
            }

            SectionHeader { text: qsTr("Watch display") }

            TextSwitch {
                text: qsTr("24-hour clock")
                checked: watch.time_24h !== false
                automaticCheck: false
                onClicked: daemon.updateSettings({ "watch": { "time_24h": !checked } })
            }
            ComboBox {
                label: qsTr("Date format")
                currentIndex: Math.max(0, [3, 2, 1].indexOf(watch.date_format || 3))
                menu: ContextMenu {
                    MenuItem { text: qsTr("Day / month / year") }
                    MenuItem { text: qsTr("Month / day / year") }
                    MenuItem { text: qsTr("Year / month / day") }
                }
                onCurrentIndexChanged: {
                    if (!page.s.watch) return
                    var v = [3, 2, 1][currentIndex]
                    if (v !== watch.date_format)
                        daemon.updateSettings({ "watch": { "date_format": v } })
                }
            }
            Label {
                x: Theme.horizontalPageMargin
                width: parent.width - 2 * x
                wrapMode: Text.Wrap
                font.pixelSize: Theme.fontSizeExtraSmall
                color: Theme.secondaryColor
                text: qsTr("Display settings are applied the next time the watch connects.")
            }

            SectionHeader { text: qsTr("Paired watch"); visible: daemon.paired }

            ButtonLayout {
                visible: daemon.paired
                Button {
                    text: qsTr("Forget watch")
                    color: "#ff6b5e"
                    onClicked: remorse.execute(qsTr("Forgetting watch"), function() {
                        daemon.forget(true)
                        pageStack.pop()
                    })
                }
            }
            Label {
                x: Theme.horizontalPageMargin
                width: parent.width - 2 * x
                visible: daemon.paired
                wrapMode: Text.Wrap
                font.pixelSize: Theme.fontSizeExtraSmall
                color: Theme.secondaryColor
                text: qsTr("Removes the pairing keys and the Bluetooth bond. Reset the watch before pairing it again.")
            }
        }
        VerticalScrollDecorator {}
    }

    RemorsePopup { id: remorse }

    Component {
        id: blockedDialog
        Dialog {
            id: dlg
            property var apps: (page.n.blocked_apps || []).slice(0)

            onAccepted: daemon.updateSettings({ "notifications": { "blocked_apps": apps } })

            SilicaListView {
                id: blockedList
                anchors.fill: parent
                model: dlg.apps
                header: Column {
                    width: blockedList.width
                    DialogHeader { acceptText: qsTr("Save") }
                    Label {
                        x: Theme.horizontalPageMargin
                        width: parent.width - 2 * x
                        wrapMode: Text.Wrap
                        font.pixelSize: Theme.fontSizeSmall
                        color: Theme.secondaryHighlightColor
                        text: qsTr("Notifications from these apps are not sent to the watch. Use the app name shown in the notification, or an Android package name.")
                    }
                    TextField {
                        id: entry
                        width: parent.width
                        label: qsTr("App name")
                        placeholderText: qsTr("Add app, e.g. Email")
                        EnterKey.iconSource: "image://theme/icon-m-add"
                        EnterKey.onClicked: {
                            var v = text.trim()
                            if (v && dlg.apps.indexOf(v) < 0) {
                                var copy = dlg.apps.slice(0)
                                copy.push(v)
                                dlg.apps = copy
                            }
                            text = ""
                        }
                    }
                    Item {
                        width: parent.width
                        height: Theme.paddingMedium
                    }
                }
                delegate: ListItem {
                    menu: ContextMenu {
                        MenuItem {
                            text: qsTr("Remove")
                            onClicked: {
                                var copy = dlg.apps.slice(0)
                                copy.splice(index, 1)
                                dlg.apps = copy
                            }
                        }
                    }
                    Label {
                        x: Theme.horizontalPageMargin
                        anchors.verticalCenter: parent.verticalCenter
                        text: modelData
                    }
                }
                VerticalScrollDecorator {}
            }
        }
    }
}
