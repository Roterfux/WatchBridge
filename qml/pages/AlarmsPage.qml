// WatchBridge - SPDX-License-Identifier: AGPL-3.0-or-later
// The watch's alarms. Every change sends the whole list; the watch replaces its own with it.
import QtQuick 2.0
import Sailfish.Silica 1.0

Page {
    id: page

    property var daemon
    readonly property var al: daemon.status.alarms || {}
    readonly property var alarms: al.list || []
    readonly property int maxAlarms: al.max || 5
    readonly property bool canChange: daemon.connected && !!al.supported && !al.loading

    // The list as the daemon takes it (without the watch's index)
    function plain() {
        var out = []
        for (var i = 0; i < alarms.length; i++) {
            var a = alarms[i]
            out.push({ "enabled": a.enabled, "hour": a.hour, "minute": a.minute, "repeat": a.repeat, "name": a.name })
        }
        return out
    }
    function clock(a) { return (a.hour < 10 ? "0" : "") + a.hour + ":" + (a.minute < 10 ? "0" : "") + a.minute }
    // Repeat bits: Monday = 1 ... Sunday = 64
    function repeatText(r) {
        if (!r) return qsTr("Once")
        if (r === 0x7F) return qsTr("Every day")
        if (r === 0x1F) return qsTr("Weekdays")
        if (r === 0x60) return qsTr("Weekends")
        var names = []
        for (var i = 0; i < 7; i++)
            if (r & (1 << i)) names.push(Qt.locale().dayName((i + 1) % 7, Locale.ShortFormat))
        return names.join(", ")
    }
    function edit(index) {
        var a = index >= 0 ? alarms[index] : { "enabled": true, "hour": 7, "minute": 0, "repeat": 0, "name": "" }
        var d = pageStack.push(Qt.resolvedUrl("AlarmDialog.qml"),
                               { "hour": a.hour, "minute": a.minute, "repeat": a.repeat,
                                 "name": a.name === "Alarm" ? "" : a.name, "isNew": index < 0 })
        d.accepted.connect(function() {
            var list = page.plain()
            var changed = { "enabled": true, "hour": d.hour, "minute": d.minute, "repeat": d.repeat,
                            "name": d.name || "Alarm" }
            if (index >= 0) list[index] = changed
            else list.push(changed)
            daemon.setAlarms(list)
        })
    }
    function toggle(index) {
        var list = plain()
        list[index].enabled = !list[index].enabled
        daemon.setAlarms(list)
    }
    function remove(index) {
        var list = plain()
        list.splice(index, 1)
        daemon.setAlarms(list)
    }

    Component.onCompleted: daemon.refreshAlarms()

    SilicaListView {
        id: view
        anchors.fill: parent
        model: page.alarms

        header: PageHeader {
            title: qsTr("Alarms")
            description: page.al.loading ? qsTr("Talking to the watch…")
                         : !daemon.connected ? qsTr("Connect the watch to change its alarms")
                         : page.al.error ? page.al.error
                         : qsTr("On the watch")
        }

        PullDownMenu {
            busy: !!page.al.loading
            MenuItem {
                text: qsTr("Refresh")
                enabled: page.canChange
                onClicked: daemon.refreshAlarms()
            }
            MenuItem {
                text: page.alarms.length >= page.maxAlarms ? qsTr("The watch holds %1 alarms").arg(page.maxAlarms)
                                                           : qsTr("Add alarm")
                enabled: page.canChange && page.alarms.length < page.maxAlarms
                onClicked: page.edit(-1)
            }
        }

        delegate: ListItem {
            id: item
            contentHeight: Theme.itemSizeLarge
            enabled: page.canChange
            onClicked: page.edit(index)
            menu: ContextMenu {
                MenuItem {
                    text: qsTr("Delete")
                    onClicked: item.remorseAction(qsTr("Deleting"), function() { page.remove(index) })
                }
            }

            Column {
                anchors { left: parent.left; leftMargin: Theme.horizontalPageMargin
                          right: toggleSwitch.left; verticalCenter: parent.verticalCenter }
                Label {
                    text: page.clock(modelData)
                    font.pixelSize: Theme.fontSizeExtraLarge
                    color: modelData.enabled ? Theme.highlightColor : Theme.secondaryColor
                }
                Label {
                    width: parent.width
                    truncationMode: TruncationMode.Fade
                    font.pixelSize: Theme.fontSizeSmall
                    color: Theme.secondaryColor
                    text: (modelData.name && modelData.name !== "Alarm" ? modelData.name + " · " : "")
                          + page.repeatText(modelData.repeat)
                }
            }
            Switch {
                id: toggleSwitch
                anchors { right: parent.right; rightMargin: Theme.horizontalPageMargin; verticalCenter: parent.verticalCenter }
                checked: modelData.enabled
                automaticCheck: false
                enabled: page.canChange
                onClicked: page.toggle(index)
            }
        }

        ViewPlaceholder {
            enabled: page.alarms.length === 0 && !page.al.loading
            text: page.al.list === null || page.al.list === undefined ? qsTr("Alarms not read yet")
                                                                     : qsTr("No alarms on the watch")
            hintText: page.canChange ? qsTr("Pull down to add one.")
                                     : qsTr("Connect the watch to see its alarms.")
        }

        VerticalScrollDecorator {}
    }
}
