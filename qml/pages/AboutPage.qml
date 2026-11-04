// WatchBridge - SPDX-License-Identifier: AGPL-3.0-or-later
import QtQuick 2.0
import Sailfish.Silica 1.0

Page {
    id: page

    property var daemon
    // The RPM build replaces this with the exact package version, e.g. "0.1.0-7"
    readonly property string appVersion: "0.1.0-dev"
    readonly property bool serviceRunning: !!daemon && daemon.available
    // Services before 0.1.0-7 did not report a version
    readonly property string serviceVersion: !serviceRunning ? ""
                                             : daemon.status.daemonVersion || qsTr("older than 0.1.0-7")

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
                text: "WatchBridge " + page.appVersion
                font.pixelSize: Theme.fontSizeLarge
                color: Theme.highlightColor
            }
            Label {
                x: Theme.horizontalPageMargin
                width: parent.width - 2 * x
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.Wrap
                font.pixelSize: Theme.fontSizeSmall
                // A different service version means an old or hand-started daemon is answering
                color: page.serviceVersion && page.serviceVersion !== page.appVersion
                       ? "#ff6b5e" : Theme.secondaryColor
                text: !page.serviceRunning ? qsTr("Background service: not running")
                      : page.serviceVersion === page.appVersion ? qsTr("Background service: %1").arg(page.serviceVersion)
                      : qsTr("Background service: %1, does not match the app. Restart the phone or run " +
                             "\"systemctl --user restart harbour-watchbridge\".").arg(page.serviceVersion)
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
                           "<a href=\"https://gadgetbridge.org\">Gadgetbridge</a>, by Damien Gaignon, Martin.JM, " +
                           "José Rebelo, Vitalii Tomin and the Gadgetbridge contributors. Thank you! Weather data by " +
                           "<a href=\"https://open-meteo.com\">Open-Meteo.com</a> (CC BY 4.0).")
            }
            Label {
                x: Theme.horizontalPageMargin
                width: parent.width - 2 * x
                wrapMode: Text.Wrap
                font.pixelSize: Theme.fontSizeSmall
                color: Theme.secondaryColor
                text: qsTr("Licensed under the GNU Affero General Public License v3 or later. " +
                           "WatchBridge is an independent project, not affiliated with Gadgetbridge, Huawei or Jolla. " +
                           "Huawei and Watch GT are trademarks of Huawei Technologies.")
            }
        }
    }
}
