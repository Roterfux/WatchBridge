// WatchBridge - SPDX-License-Identifier: AGPL-3.0-or-later
import QtQuick 2.0
import Sailfish.Silica 1.0
import "../components"

CoverBackground {
    id: cover
    property var daemon
    readonly property var st: daemon.status
    readonly property var wx: daemon.weather

    Column {
        anchors { top: parent.top; topMargin: Theme.paddingLarge; left: parent.left; right: parent.right }
        spacing: Theme.paddingSmall

        WatchFace {
            anchors.horizontalCenter: parent.horizontalCenter
            width: cover.width * 0.55
            height: width
            battery: st.battery !== undefined ? st.battery : -1
            watchState: daemon.watchState
            busy: daemon.busy
        }
        Label {
            width: parent.width
            horizontalAlignment: Text.AlignHCenter
            truncationMode: TruncationMode.Fade
            font.pixelSize: Theme.fontSizeSmall
            color: Theme.highlightColor
            text: daemon.paired ? daemon.stateText(daemon.watchState, "") : qsTr("No watch")
        }
        Row {
            anchors.horizontalCenter: parent.horizontalCenter
            spacing: Theme.paddingSmall
            visible: !!wx
            WeatherGlyph { code: wx ? wx.code : null; font.pixelSize: Theme.fontSizeMedium }
            Label {
                anchors.verticalCenter: parent.verticalCenter
                text: wx ? wx.temperature + "°" : ""
                font.pixelSize: Theme.fontSizeMedium
            }
        }
    }

    CoverActionList {
        enabled: daemon.paired && daemon.connected
        CoverAction {
            iconSource: "image://theme/icon-cover-refresh"
            onTriggered: daemon.refreshWeather()
        }
    }
    CoverActionList {
        enabled: daemon.paired && !daemon.connected && !daemon.busy
        CoverAction {
            iconSource: "image://theme/icon-cover-sync"
            onTriggered: daemon.connectWatch()
        }
    }
}
