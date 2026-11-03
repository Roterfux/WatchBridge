// WatchBridge - SPDX-License-Identifier: AGPL-3.0-or-later
import QtQuick 2.0
import Sailfish.Silica 1.0

Page {
    SilicaFlickable {
        anchors.fill: parent
        contentHeight: column.height + Theme.paddingLarge

        Column {
            id: column
            width: parent.width
            spacing: Theme.paddingLarge

            PageHeader { title: qsTr("About") }

            Image {
                anchors.horizontalCenter: parent.horizontalCenter
                source: "/usr/share/icons/hicolor/172x172/apps/harbour-watchbridge.png"
                width: Theme.iconSizeExtraLarge; height: width
            }
            Label {
                anchors.horizontalCenter: parent.horizontalCenter
                text: "WatchBridge 0.1.0"
                font.pixelSize: Theme.fontSizeLarge
                color: Theme.highlightColor
            }
            Label {
                x: Theme.horizontalPageMargin
                width: parent.width - 2 * x
                wrapMode: Text.Wrap
                color: Theme.secondaryHighlightColor
                text: qsTr("A Sailfish OS companion for the Huawei Watch GT 5: pairing, notification forwarding and weather.")
            }
            Label {
                x: Theme.horizontalPageMargin
                width: parent.width - 2 * x
                wrapMode: Text.Wrap
                textFormat: Text.StyledText
                linkColor: Theme.highlightColor
                onLinkActivated: Qt.openUrlExternally(link)
                font.pixelSize: Theme.fontSizeSmall
                text: qsTr("The watch protocol implementation is a port of the Huawei support in " +
                           "<a href=\"https://gadgetbridge.org\">Gadgetbridge</a>, by Damien Gaignon, Martin.JM " +
                           "and the Gadgetbridge contributors. Weather data by " +
                           "<a href=\"https://open-meteo.com\">Open-Meteo.com</a> (CC BY 4.0).")
            }
            Label {
                x: Theme.horizontalPageMargin
                width: parent.width - 2 * x
                wrapMode: Text.Wrap
                font.pixelSize: Theme.fontSizeSmall
                color: Theme.secondaryColor
                text: qsTr("Licensed under the GNU Affero General Public License v3 or later. " +
                           "Huawei and Watch GT are trademarks of their owner; this project is not affiliated with them.")
            }
        }
    }
}
