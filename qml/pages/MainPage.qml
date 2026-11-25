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
    readonly property var hs: status.health || {}
    readonly property int healthLastSync: hs.lastSync || 0
    property int todaySteps: -1
    property var today: null    // today's GetHealth result, for the goal rings

    function loadTodaySteps() {
        if (!daemon.available) return
        daemon.getHealth(Qt.formatDate(new Date(), "yyyy-MM-dd"), function(r) {
            var has = r.available && (r.minutes > 0 || r.totalsUpdated)
            page.todaySteps = has ? r.steps : -1
            page.today = has ? r : null
        })
    }
    onHealthLastSyncChanged: loadTodaySteps()
    Component.onCompleted: loadTodaySteps()
    Connections {
        target: daemon
        onAvailableChanged: page.loadTodaySteps()
    }
    // The face may have been changed on the watch itself; ask again when the app comes forward
    Connections {
        target: Qt.application
        onActiveChanged: if (Qt.application.active && daemon.connected) daemon.refreshWatchfaces()
    }

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

            Item {
                anchors.horizontalCenter: parent.horizontalCenter
                width: Math.min(page.width, page.height) * 0.55
                height: width

                // The face on the watch, if WatchBridge installed it and so has its picture;
                // otherwise (built-in and store faces, or while loading) the drawn watch
                readonly property string facePreview: daemon.paired
                    ? ((status.watchfaces || {}).currentPreview || "") : ""

                RoundImage {
                    id: currentFace
                    anchors.fill: parent
                    anchors.margins: Theme.paddingMedium
                    source: parent.facePreview ? "file://" + parent.facePreview : ""
                    opacity: daemon.connected ? 1.0 : 0.5
                    Behavior on opacity { FadeAnimation {} }
                }
                WatchFace {
                    anchors.fill: parent
                    visible: !currentFace.ready
                    battery: status.battery !== undefined ? status.battery : -1
                    watchState: daemon.watchState
                    busy: daemon.busy
                    opacity: daemon.paired ? 1.0 : 0.4
                    Behavior on opacity { FadeAnimation {} }
                }
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

            // ----------------------------------------------------------- health
            SectionHeader { text: qsTr("Health"); visible: daemon.paired }

            BackgroundItem {
                visible: daemon.paired
                height: Math.max(healthCol.height, miniRings.visible ? miniRings.height : 0) + 2 * Theme.paddingMedium
                onClicked: pageStack.push(Qt.resolvedUrl("HealthPage.qml"), { daemon: daemon })
                ActivityRings {
                    id: miniRings
                    visible: !!page.today
                    x: Theme.horizontalPageMargin
                    width: Theme.itemSizeMedium
                    height: width
                    anchors.verticalCenter: parent.verticalCenter
                    thickness: 0.18
                    gap: 0.06
                    values: dayValues(page.today, daemon.settings.health && daemon.settings.health.goals)
                    colors: daemon.ringColors
                }
                Column {
                    id: healthCol
                    x: miniRings.visible ? miniRings.x + miniRings.width + Theme.paddingLarge : Theme.horizontalPageMargin
                    width: parent.width - x - Theme.horizontalPageMargin - healthArrow.width
                    anchors.verticalCenter: parent.verticalCenter
                    Label {
                        width: parent.width
                        truncationMode: TruncationMode.Fade
                        text: page.todaySteps >= 0 ? qsTr("%1 steps today").arg(page.todaySteps)
                                                   : qsTr("Steps, heart rate and sleep")
                    }
                    Label {
                        width: parent.width
                        truncationMode: TruncationMode.Fade
                        font.pixelSize: Theme.fontSizeExtraSmall
                        color: page.hs.error ? "#ff6b5e" : Theme.secondaryColor
                        text: page.hs.syncing ? qsTr("Syncing with the watch…")
                              : page.hs.error ? page.hs.error
                              : page.hs.lastSync ? qsTr("Last sync %1").arg(ago(page.hs.lastSync))
                              : qsTr("Not synced yet")
                    }
                }
                Icon {
                    id: healthArrow
                    anchors { right: parent.right; rightMargin: Theme.horizontalPageMargin; verticalCenter: parent.verticalCenter }
                    source: "image://theme/icon-m-right"
                }
            }

            // ------------------------------------------------------ watch faces
            SectionHeader { text: qsTr("Watch"); visible: daemon.paired }

            BackgroundItem {
                visible: daemon.paired
                height: Theme.itemSizeSmall
                onClicked: pageStack.push(Qt.resolvedUrl("WatchfacesPage.qml"), { daemon: daemon })
                Label {
                    x: Theme.horizontalPageMargin
                    anchors.verticalCenter: parent.verticalCenter
                    width: parent.width - 2 * x - facesArrow.width
                    truncationMode: TruncationMode.Fade
                    readonly property var up: (status.watchfaces || {}).upload || {}
                    text: up.state === "uploading" ? qsTr("Watch faces · sending %1 %").arg(up.progress || 0)
                                                   : qsTr("Watch faces")
                }
                Icon {
                    id: facesArrow
                    anchors { right: parent.right; rightMargin: Theme.horizontalPageMargin; verticalCenter: parent.verticalCenter }
                    source: "image://theme/icon-m-right"
                }
            }

            BackgroundItem {
                // Children of a BackgroundItem live in its contentItem, so they refer to it by id
                id: alarmsRow
                readonly property var al: status.alarms || {}
                readonly property var active: (al.list || []).filter(function(a) { return a.enabled })
                visible: daemon.paired && (!!al.supported || al.list !== null && al.list !== undefined)
                height: Theme.itemSizeSmall
                onClicked: pageStack.push(Qt.resolvedUrl("AlarmsPage.qml"), { daemon: daemon })
                Label {
                    x: Theme.horizontalPageMargin
                    anchors.verticalCenter: parent.verticalCenter
                    width: parent.width - 2 * x - alarmsArrow.width
                    truncationMode: TruncationMode.Fade
                    text: alarmsRow.active.length === 0 ? qsTr("Alarms")
                          : qsTr("Alarms · %1").arg(alarmsRow.active.map(function(a) {
                                return (a.hour < 10 ? "0" : "") + a.hour + ":" + (a.minute < 10 ? "0" : "") + a.minute
                            }).join(", "))
                }
                Icon {
                    id: alarmsArrow
                    anchors { right: parent.right; rightMargin: Theme.horizontalPageMargin; verticalCenter: parent.verticalCenter }
                    source: "image://theme/icon-m-right"
                }
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

            // ------------------------------------------------- watch details
            SectionHeader { text: qsTr("Watch details"); visible: daemon.paired }

            DetailItem {
                visible: daemon.paired && !!info.model
                label: qsTr("Model")
                value: info.model || ""
            }
            DetailItem {
                visible: daemon.paired && !!info.software_version
                label: qsTr("Firmware")
                // "6.0.0.23(SP10C00M06)" -> "6.0.0.23"
                value: (info.software_version || "").replace(/\s*\(.*\)\s*$/, "")
            }
            BackgroundItem {
                visible: daemon.paired
                height: batteryItem.height
                onClicked: pageStack.push(Qt.resolvedUrl("BatteryPage.qml"), { daemon: daemon })
                DetailItem {
                    id: batteryItem
                    label: qsTr("Battery")
                    value: status.battery >= 0 ? (status.batteryCharging ? qsTr("%1 % · charging").arg(status.battery)
                                                                         : qsTr("%1 % · history").arg(status.battery))
                                               : qsTr("unknown")
                }
            }
            DetailItem {
                visible: daemon.paired
                label: qsTr("Bluetooth address")
                value: status.address || ""
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
