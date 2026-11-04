// WatchBridge - SPDX-License-Identifier: AGPL-3.0-or-later
import QtQuick 2.0
import Sailfish.Silica 1.0
import "../components"

Page {
    id: page

    property var daemon
    readonly property var status: daemon.status
    readonly property var info: status.info || {}
    readonly property var wx: daemon.weather

    function ago(ts) {
        if (!ts) return ""
        var mins = Math.round((Date.now() / 1000 - ts) / 60)
        if (mins < 1) return qsTr("just now")
        if (mins < 60) return qsTr("%n min ago", "", mins)
        return qsTr("%n h ago", "", Math.round(mins / 60))
    }

    function dayName(ts) {
        return Qt.formatDate(new Date(ts * 1000), "ddd")
    }

    SilicaFlickable {
        anchors.fill: parent
        contentHeight: column.height + Theme.paddingLarge

        PullDownMenu {
            busy: daemon.busy
            MenuItem {
                text: qsTr("About")
                onClicked: pageStack.push(Qt.resolvedUrl("AboutPage.qml"), { daemon: daemon })
            }
            MenuItem {
                text: qsTr("Settings")
                onClicked: pageStack.push(Qt.resolvedUrl("SettingsPage.qml"), { daemon: daemon })
            }
            MenuItem {
                text: daemon.paired ? qsTr("Pair another watch") : qsTr("Pair a watch")
                onClicked: pageStack.push(Qt.resolvedUrl("PairPage.qml"), { daemon: daemon })
            }
            MenuItem {
                visible: daemon.paired
                text: daemon.connected || daemon.busy ? qsTr("Disconnect") : qsTr("Connect")
                onClicked: daemon.connected || daemon.busy ? daemon.disconnectWatch() : daemon.connectWatch()
            }
        }

        Column {
            id: column
            width: parent.width
            spacing: Theme.paddingMedium

            PageHeader {
                title: status.name || "WatchBridge"
                description: daemon.stateText(daemon.watchState, status.detail)
            }

            WatchFace {
                anchors.horizontalCenter: parent.horizontalCenter
                width: Math.min(page.width, page.height) * 0.55
                height: width
                battery: status.battery !== undefined ? status.battery : -1
                watchState: daemon.watchState
                busy: daemon.busy
                opacity: daemon.paired ? 1.0 : 0.4
                Behavior on opacity { FadeAnimation {} }
            }

            Label {
                x: Theme.horizontalPageMargin
                width: parent.width - 2 * x
                visible: !!status.detail && status.detail !== "confirm_on_watch"
                text: status.detail || ""
                wrapMode: Text.Wrap
                horizontalAlignment: Text.AlignHCenter
                font.pixelSize: Theme.fontSizeSmall
                color: daemon.watchState === "auth_failed" ? "#ff6b5e" : Theme.secondaryHighlightColor
            }

            // ------------------------------------------------------- unpaired
            Column {
                width: parent.width
                visible: daemon.available && !daemon.paired
                spacing: Theme.paddingLarge

                Label {
                    x: Theme.horizontalPageMargin
                    width: parent.width - 2 * x
                    wrapMode: Text.Wrap
                    horizontalAlignment: Text.AlignHCenter
                    color: Theme.highlightColor
                    font.pixelSize: Theme.fontSizeLarge
                    text: qsTr("Let's connect your watch")
                }
                Label {
                    x: Theme.horizontalPageMargin
                    width: parent.width - 2 * x
                    wrapMode: Text.Wrap
                    horizontalAlignment: Text.AlignHCenter
                    color: Theme.secondaryHighlightColor
                    text: qsTr("WatchBridge forwards your notifications and the weather to a Huawei Watch GT 5.")
                }
                Button {
                    anchors.horizontalCenter: parent.horizontalCenter
                    text: qsTr("Pair a watch")
                    onClicked: pageStack.push(Qt.resolvedUrl("PairPage.qml"), { daemon: daemon })
                }
            }

            // -------------------------------------------------------- watch info
            SectionHeader { text: qsTr("Watch"); visible: daemon.paired }

            DetailItem {
                visible: daemon.paired && !!info.model
                label: qsTr("Model")
                value: info.model || ""
            }
            DetailItem {
                visible: daemon.paired && !!info.software_version
                label: qsTr("Firmware")
                value: info.software_version || ""
            }
            DetailItem {
                visible: daemon.paired
                label: qsTr("Battery")
                value: status.battery >= 0 ? status.battery + " %" : qsTr("unknown")
            }
            DetailItem {
                visible: daemon.paired
                label: qsTr("Bluetooth address")
                value: status.address || ""
            }

            ButtonLayout {
                visible: daemon.paired
                Button {
                    text: qsTr("Sync time")
                    enabled: daemon.connected
                    onClicked: daemon.syncTime()
                }
                Button {
                    text: daemon.connected ? qsTr("Reconnect") : qsTr("Connect")
                    enabled: !daemon.busy
                    onClicked: {
                        if (daemon.connected) daemon.disconnectWatch()
                        daemon.connectWatch()
                    }
                }
            }

            // ------------------------------------------------------ notifications
            SectionHeader { text: qsTr("Notifications"); visible: daemon.paired }

            TextSwitch {
                visible: daemon.paired
                text: qsTr("Forward notifications")
                readonly property var ns: daemon.settings.notifications || {}
                description: ns.mode === "selected" && (ns.allowed_apps || []).length === 0
                             ? qsTr("Only selected apps are forwarded, and none is selected yet. Choose them in Settings.")
                             : qsTr("%n notification(s) sent this session", "", status.notificationsForwarded || 0)
                checked: daemon.settings.notifications ? daemon.settings.notifications.enabled : true
                automaticCheck: false
                onClicked: daemon.updateSettings({ "notifications": { "enabled": !checked } })
            }

            BackgroundItem {
                visible: daemon.paired && !!status.lastNotification
                height: lastCol.height + 2 * Theme.paddingMedium
                Column {
                    id: lastCol
                    x: Theme.horizontalPageMargin
                    width: parent.width - 2 * x
                    anchors.verticalCenter: parent.verticalCenter
                    Label {
                        width: parent.width
                        truncationMode: TruncationMode.Fade
                        font.pixelSize: Theme.fontSizeExtraSmall
                        color: Theme.secondaryColor
                        text: status.lastNotification
                              ? qsTr("Last: %1 · %2").arg(status.lastNotification.app).arg(ago(status.lastNotification.time))
                              : ""
                    }
                    Label {
                        width: parent.width
                        truncationMode: TruncationMode.Fade
                        text: status.lastNotification ? status.lastNotification.title : ""
                    }
                    Label {
                        width: parent.width
                        maximumLineCount: 2
                        wrapMode: Text.Wrap
                        elide: Text.ElideRight
                        font.pixelSize: Theme.fontSizeSmall
                        color: Theme.secondaryColor
                        text: status.lastNotification ? status.lastNotification.body : ""
                    }
                }
            }

            Button {
                visible: daemon.paired
                anchors.horizontalCenter: parent.horizontalCenter
                text: qsTr("Send test notification")
                enabled: daemon.connected
                onClicked: daemon.sendTestNotification()
            }

            // ------------------------------------------------------------ weather
            SectionHeader { text: qsTr("Weather"); visible: daemon.paired }

            Item {
                visible: daemon.paired && !!wx
                width: parent.width
                height: Math.max(wxGlyph.height, wxText.height)

                WeatherGlyph {
                    id: wxGlyph
                    x: Theme.horizontalPageMargin
                    code: wx ? wx.code : null
                    font.pixelSize: Theme.fontSizeHuge
                }
                Column {
                    id: wxText
                    anchors { left: wxGlyph.right; leftMargin: Theme.paddingLarge; right: parent.right
                              rightMargin: Theme.horizontalPageMargin; verticalCenter: parent.verticalCenter }
                    Label {
                        width: parent.width
                        font.pixelSize: Theme.fontSizeExtraLarge
                        color: Theme.highlightColor
                        text: wx ? wx.temperature + "°" + wx.unit : ""
                    }
                    Label {
                        width: parent.width
                        truncationMode: TruncationMode.Fade
                        text: wx ? wx.description + (wx.location ? " · " + wx.location : "") : ""
                    }
                    Label {
                        width: parent.width
                        font.pixelSize: Theme.fontSizeExtraSmall
                        color: Theme.secondaryColor
                        text: wx ? qsTr("%1° / %2° · feels like %3° · updated %4")
                                   .arg(wx.max).arg(wx.min).arg(wx.feelsLike).arg(ago(status.weatherTime)) : ""
                    }
                }
            }

            // 7 day strip
            Row {
                visible: daemon.paired && !!wx && wx.daily.length > 1
                x: Theme.horizontalPageMargin
                width: parent.width - 2 * x
                Repeater {
                    model: wx ? Math.min(wx.daily.length, 7) : 0
                    Column {
                        width: parent.width / Math.min(wx.daily.length, 7)
                        Label {
                            width: parent.width
                            horizontalAlignment: Text.AlignHCenter
                            font.pixelSize: Theme.fontSizeExtraSmall
                            color: Theme.secondaryColor
                            text: index === 0 ? qsTr("Today") : dayName(wx.daily[index].time)
                        }
                        WeatherGlyph {
                            width: parent.width
                            code: wx.daily[index].code
                            font.pixelSize: Theme.fontSizeMedium
                        }
                        Label {
                            width: parent.width
                            horizontalAlignment: Text.AlignHCenter
                            font.pixelSize: Theme.fontSizeExtraSmall
                            text: wx.daily[index].max + "°"
                        }
                        Label {
                            width: parent.width
                            horizontalAlignment: Text.AlignHCenter
                            font.pixelSize: Theme.fontSizeExtraSmall
                            color: Theme.secondaryColor
                            text: wx.daily[index].min + "°"
                        }
                    }
                }
            }

            Label {
                x: Theme.horizontalPageMargin
                width: parent.width - 2 * x
                visible: daemon.paired && !!status.weatherError
                wrapMode: Text.Wrap
                font.pixelSize: Theme.fontSizeSmall
                color: Theme.secondaryHighlightColor
                text: status.weatherError || ""
            }

            ButtonLayout {
                visible: daemon.paired
                Button {
                    text: qsTr("Location")
                    onClicked: pageStack.push(Qt.resolvedUrl("LocationPage.qml"), { daemon: daemon })
                }
                Button {
                    text: qsTr("Push weather")
                    enabled: daemon.connected
                    onClicked: daemon.refreshWeather()
                }
            }
        }

        VerticalScrollDecorator {}
    }

    ViewPlaceholder {
        enabled: !daemon.available
        text: daemon.lastError ? qsTr("WatchBridge service is not responding") : qsTr("Starting WatchBridge service…")
        hintText: daemon.lastError
                  ? daemon.lastError + "\n\n" + qsTr("Check: journalctl --user -u harbour-watchbridge")
                  : ""
    }
}
