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
    readonly property var hl: s.health || {}

    readonly property var intervals: [15, 30, 60, 120, 180]
    readonly property var healthIntervals: [1, 3, 6, 12, 24]
    readonly property var firstSyncDays: [1, 7, 14, 30]

    // Fetch the latest seen-apps list before showing the picker
    function openAppList(key, title, description) {
        daemon.reloadSettings(function() {
            pageStack.push(Qt.resolvedUrl("AppListDialog.qml"),
                           { daemon: daemon, settingsKey: key, title: title, description: description })
        })
    }

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
            ComboBox {
                label: qsTr("Forward from")
                currentIndex: n.mode === "selected" ? 1 : 0
                menu: ContextMenu {
                    MenuItem { text: qsTr("All apps") }
                    MenuItem { text: qsTr("Selected apps only") }
                }
                onCurrentIndexChanged: {
                    if (!page.s.notifications) return
                    var mode = currentIndex === 1 ? "selected" : "all"
                    if (mode !== (n.mode || "all"))
                        daemon.updateSettings({ "notifications": { "mode": mode } })
                }
            }
            ValueButton {
                visible: n.mode !== "selected"
                label: qsTr("Muted apps")
                value: (n.blocked_apps || []).length === 0 ? qsTr("None") : (n.blocked_apps || []).join(", ")
                onClicked: page.openAppList("blocked_apps", qsTr("Muted apps"),
                    qsTr("Notifications from these apps are not sent to the watch."))
            }
            ValueButton {
                visible: n.mode === "selected"
                label: qsTr("Allowed apps")
                value: (n.allowed_apps || []).length === 0 ? qsTr("None, nothing is forwarded")
                                                           : (n.allowed_apps || []).join(", ")
                onClicked: page.openAppList("allowed_apps", qsTr("Allowed apps"),
                    qsTr("Only notifications from these apps are sent to the watch."))
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

            SectionHeader { text: qsTr("Health") }

            TextSwitch {
                text: qsTr("Sync automatically")
                description: qsTr("Fetch steps, heart rate and sleep from the watch while it is connected.")
                checked: hl.enabled !== false
                automaticCheck: false
                onClicked: daemon.updateSettings({ "health": { "enabled": !checked } })
            }
            ComboBox {
                label: qsTr("Sync every")
                enabled: hl.enabled !== false
                currentIndex: Math.max(0, page.healthIntervals.indexOf(hl.interval_hours || 6))
                menu: ContextMenu {
                    Repeater {
                        model: page.healthIntervals
                        MenuItem { text: qsTr("%n hour(s)", "", modelData) }
                    }
                }
                onCurrentIndexChanged: {
                    if (!page.s.health) return
                    var v = page.healthIntervals[currentIndex]
                    if (v !== hl.interval_hours)
                        daemon.updateSettings({ "health": { "interval_hours": v } })
                }
            }
            TextSwitch {
                text: qsTr("Measure heart rate continuously")
                description: hl.continuous_heart_rate === null || hl.continuous_heart_rate === undefined
                             ? qsTr("Currently left to the watch's own setting. Without it, the watch records no heart rate between workouts. Uses more battery.")
                             : qsTr("Sets the watch's continuous heart-rate measurement. Uses more battery.")
                checked: hl.continuous_heart_rate === true
                automaticCheck: false
                onClicked: daemon.updateSettings({ "health": { "continuous_heart_rate": !checked } })
            }
            ComboBox {
                label: qsTr("First sync reaches back")
                description: qsTr("Only used while no data has been synced yet.")
                currentIndex: Math.max(0, page.firstSyncDays.indexOf(hl.first_sync_days || 7))
                menu: ContextMenu {
                    Repeater {
                        model: page.firstSyncDays
                        MenuItem { text: qsTr("%n day(s)", "", modelData) }
                    }
                }
                onCurrentIndexChanged: {
                    if (!page.s.health) return
                    var v = page.firstSyncDays[currentIndex]
                    if (v !== hl.first_sync_days)
                        daemon.updateSettings({ "health": { "first_sync_days": v } })
                }
            }
            Label {
                x: Theme.horizontalPageMargin
                width: parent.width - 2 * x
                wrapMode: Text.Wrap
                font.pixelSize: Theme.fontSizeExtraSmall
                color: Theme.secondaryColor
                text: qsTr("Data is stored in %1 as a database and CSV files you can open in any spreadsheet.")
                      .arg((daemon.status.health && daemon.status.health.folder) || "Documents/WatchBridge")
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
}
