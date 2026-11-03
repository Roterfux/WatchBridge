// WatchBridge - SPDX-License-Identifier: AGPL-3.0-or-later
// Pick apps for the muted or allowed list: recently seen apps as switches,
// plus manual entry for apps that have not sent a notification yet.
import QtQuick 2.0
import Sailfish.Silica 1.0

Dialog {
    id: dlg

    property var daemon
    property string settingsKey         // "blocked_apps" or "allowed_apps"
    property string title
    property string description
    property var selected: []
    // Listed apps that have not sent a notification yet (typed in, or saved earlier).
    // Kept apart from `selected` so toggling a switch does not rebuild the list.
    property var extra: []

    readonly property var notif: daemon.settings.notifications || {}
    // Snapshot: the periodic settings refresh must not rebuild the list under the user's finger
    property var seen: ({})

    // Seen apps (most recent first), then the extra ones
    readonly property var apps: {
        var names = Object.keys(seen)
        names.sort(function(a, b) { return (seen[b].last || 0) - (seen[a].last || 0) })
        var out = []
        for (var i = 0; i < names.length; i++)
            out.push({ "name": names[i], "package": seen[names[i]].package || "", "last": seen[names[i]].last || 0 })
        for (var j = 0; j < extra.length; j++)
            if (!seen.hasOwnProperty(extra[j]))
                out.push({ "name": extra[j], "package": "", "last": 0 })
        return out
    }

    Component.onCompleted: {
        seen = notif.seen_apps || {}
        selected = (notif[settingsKey] || []).slice(0)
        extra = selected.slice(0)
    }
    onAccepted: {
        var change = { "notifications": {} }
        change.notifications[settingsKey] = selected
        daemon.updateSettings(change)
    }

    function toggle(name) {
        var copy = selected.slice(0)
        var i = copy.indexOf(name)
        if (i >= 0) copy.splice(i, 1)
        else copy.push(name)
        selected = copy
    }

    function ago(ts) {
        if (!ts) return qsTr("not seen yet")
        var days = Math.floor((Date.now() / 1000 - ts) / 86400)
        if (days < 1) return qsTr("seen today")
        return qsTr("seen %n day(s) ago", "", days)
    }

    SilicaListView {
        id: list
        anchors.fill: parent
        model: dlg.apps

        header: Column {
            width: list.width
            DialogHeader { acceptText: qsTr("Save"); title: dlg.title }
            Label {
                x: Theme.horizontalPageMargin
                width: parent.width - 2 * x
                wrapMode: Text.Wrap
                font.pixelSize: Theme.fontSizeSmall
                color: Theme.secondaryHighlightColor
                text: dlg.description
            }
            TextField {
                width: parent.width
                label: qsTr("Add an app by name")
                placeholderText: qsTr("App not listed? Type its name")
                EnterKey.iconSource: "image://theme/icon-m-add"
                EnterKey.onClicked: {
                    var v = text.trim()
                    if (v && dlg.selected.indexOf(v) < 0) {
                        dlg.toggle(v)
                        if (dlg.extra.indexOf(v) < 0) dlg.extra = dlg.extra.concat([v])
                    }
                    text = ""
                }
            }
            Label {
                x: Theme.horizontalPageMargin
                width: parent.width - 2 * x
                visible: dlg.apps.length === 0
                wrapMode: Text.Wrap
                font.pixelSize: Theme.fontSizeSmall
                color: Theme.secondaryColor
                text: qsTr("No apps have sent a notification yet. Apps appear here after their first notification.")
            }
        }

        delegate: TextSwitch {
            text: modelData.name
            description: (modelData.package && modelData.package.indexOf("sailfish.") !== 0
                          ? modelData.package + " · " : "") + dlg.ago(modelData.last)
            checked: dlg.selected.indexOf(modelData.name) >= 0
            automaticCheck: false
            onClicked: dlg.toggle(modelData.name)
        }

        VerticalScrollDecorator {}
    }
}
