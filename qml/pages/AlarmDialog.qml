// WatchBridge - SPDX-License-Identifier: AGPL-3.0-or-later
// Time, name and repeat days of one watch alarm.
import QtQuick 2.0
import Sailfish.Silica 1.0

Dialog {
    id: dialog

    property int hour: 7
    property int minute: 0
    property int repeat: 0          // Monday = 1 ... Sunday = 64, 0 = once
    property string name: ""
    property bool isNew: true

    onAccepted: {
        hour = picker.hour
        minute = picker.minute
        name = nameField.text.trim()
    }

    SilicaFlickable {
        anchors.fill: parent
        contentHeight: column.height + Theme.paddingLarge

        Column {
            id: column
            width: parent.width
            spacing: Theme.paddingMedium

            DialogHeader {
                title: dialog.isNew ? qsTr("New alarm") : qsTr("Alarm")
                acceptText: qsTr("Save")
            }

            Label {
                anchors.horizontalCenter: parent.horizontalCenter
                text: (picker.hour < 10 ? "0" : "") + picker.hour + ":" + (picker.minute < 10 ? "0" : "") + picker.minute
                font.pixelSize: Theme.fontSizeHuge
                color: Theme.highlightColor
            }
            TimePicker {
                id: picker
                anchors.horizontalCenter: parent.horizontalCenter
                hour: dialog.hour
                minute: dialog.minute
                hourMode: DateTime.TwentyFourHours
            }

            TextField {
                id: nameField
                width: parent.width
                label: qsTr("Name")
                placeholderText: qsTr("Name (optional)")
                text: dialog.name
                maximumLength: 20
                EnterKey.iconSource: "image://theme/icon-m-enter-close"
                EnterKey.onClicked: focus = false
            }

            SectionHeader { text: qsTr("Repeat") }
            Row {
                x: Theme.horizontalPageMargin
                width: parent.width - 2 * x
                Repeater {
                    model: 7
                    BackgroundItem {
                        id: dayButton   // its children sit in contentItem, so not "parent"
                        readonly property bool isOn: (dialog.repeat & (1 << index)) !== 0
                        width: parent.width / 7
                        height: Theme.itemSizeSmall
                        highlighted: down || isOn
                        onClicked: dialog.repeat = dialog.repeat ^ (1 << index)
                        Label {
                            anchors.centerIn: parent
                            // Bit 0 is Monday; Qt counts days from Sunday
                            text: Qt.locale().dayName((index + 1) % 7, Locale.ShortFormat)
                            color: dayButton.isOn ? Theme.highlightColor : Theme.primaryColor
                            font.pixelSize: Theme.fontSizeSmall
                        }
                    }
                }
            }
            Label {
                x: Theme.horizontalPageMargin
                width: parent.width - 2 * x
                wrapMode: Text.Wrap
                font.pixelSize: Theme.fontSizeExtraSmall
                color: Theme.secondaryColor
                text: dialog.repeat === 0 ? qsTr("Rings once. Tap days to repeat it.") : ""
            }
        }
    }
}
