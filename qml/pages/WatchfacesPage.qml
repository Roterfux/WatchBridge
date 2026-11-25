// WatchBridge - SPDX-License-Identifier: AGPL-3.0-or-later
// The faces installed on the watch; install a new one from a .hwt file.
import QtQuick 2.0
import Sailfish.Silica 1.0
import "../components"

Page {
    id: page

    property var daemon
    readonly property var wf: daemon.status.watchfaces || {}
    readonly property var upload: wf.upload || {}
    readonly property bool uploading: upload.state === "uploading"
    readonly property var faces: wf.list || []

    // Set by the file picker; handled once this page is back on top of the stack
    property string pickedPath: ""

    // ------------------------------------------------------ day and night
    readonly property var fs: daemon.settings.face_schedule || {}

    // The watch names downloaded faces only; built-in ones are numbered in the watch's order
    function faceTitle(face) {
        if (face.name && face.name !== face.file) return face.name
        if (!face.factory) return face.file
        var n = 0
        for (var i = 0; i < faces.length; i++) {
            if (faces[i].factory) n++
            if (faces[i].file === face.file) break
        }
        return qsTr("Built-in face %1").arg(n)
    }
    function chosen(period, face) { return !!fs[period] && fs[period].file === face.file }
    function setSchedule(change) {
        var v = { "enabled": fs.enabled === true, "day": fs.day || null, "night": fs.night || null,
                  "day_start": fs.day_start || "07:00", "night_start": fs.night_start || "21:00" }
        for (var k in change) v[k] = change[k]
        daemon.updateSettings({ "face_schedule": v })
    }
    function choose(period, face) {
        var change = {}
        change[period] = chosen(period, face) ? null
                         : { "file": face.file, "version": face.version, "name": faceTitle(face) }
        // Choosing a face switches the schedule on
        if (change[period]) change.enabled = true
        setSchedule(change)
    }
    function pickTime(text, done) {
        var p = (text || "07:00").split(":")
        var d = pageStack.push("Sailfish.Silica.TimePickerDialog",
                               { "hour": parseInt(p[0], 10), "minute": parseInt(p[1], 10),
                                 "hourMode": DateTime.TwentyFourHours })
        d.accepted.connect(function() {
            done((d.hour < 10 ? "0" : "") + d.hour + ":" + (d.minute < 10 ? "0" : "") + d.minute)
        })
    }

    function openPicked() {
        var path = pickedPath
        pickedPath = ""
        daemon.inspectWatchface(path, function(info) {
            pageStack.push(Qt.resolvedUrl("InstallWatchfaceDialog.qml"), { daemon: daemon, path: path, info: info })
        })
    }

    onStatusChanged: {
        if (status === PageStatus.Active && pickedPath !== "")
            openPicked()
    }
    Component.onCompleted: if (daemon.connected) daemon.refreshWatchfaces()

    // Our own picker: it opens in the folder used last time and keeps the sort order
    function pickFile() {
        var picker = pageStack.push(Qt.resolvedUrl("FacePickerPage.qml"))
        picker.picked.connect(function(path) { page.pickedPath = path })
    }

    SilicaListView {
        id: list
        anchors.fill: parent
        model: page.faces

        PullDownMenu {
            busy: page.uploading || !!page.wf.loading
            MenuItem {
                text: qsTr("Refresh")
                enabled: daemon.connected && !page.uploading
                onClicked: daemon.refreshWatchfaces()
            }
            MenuItem {
                text: qsTr("Install from file")
                enabled: daemon.connected && !page.uploading
                onClicked: page.pickFile()
            }
        }

        header: Column {
            width: list.width

            PageHeader {
                title: qsTr("Watch faces")
                description: page.wf.resolution ? qsTr("Screen %1").arg(page.wf.resolution.replace("*", " × ")) : ""
            }

            // ------------------------------------------------------ upload state
            Column {
                width: parent.width
                visible: page.upload.state === "uploading" || page.upload.state === "failed"
                         || page.upload.state === "done"
                ProgressBar {
                    width: parent.width
                    visible: page.uploading
                    minimumValue: 0
                    maximumValue: 100
                    value: page.upload.progress || 0
                    valueText: value + " %"
                    label: qsTr("Sending %1 to the watch").arg(page.upload.title || qsTr("watch face"))
                }
                Label {
                    x: Theme.horizontalPageMargin
                    width: parent.width - 2 * x
                    visible: !page.uploading
                    wrapMode: Text.Wrap
                    font.pixelSize: Theme.fontSizeSmall
                    color: page.upload.state === "failed" ? "#ff6b5e" : Theme.highlightColor
                    text: page.upload.state === "failed"
                          ? qsTr("Installing %1 failed: %2").arg(page.upload.title || qsTr("the watch face")).arg(page.upload.error)
                          : qsTr("%1 is installed.").arg(page.upload.title || qsTr("The watch face"))
                }
                Item { width: 1; height: Theme.paddingLarge }
            }

            Label {
                x: Theme.horizontalPageMargin
                width: parent.width - 2 * x
                visible: !!page.wf.error
                wrapMode: Text.Wrap
                font.pixelSize: Theme.fontSizeSmall
                color: "#ff6b5e"
                text: page.wf.error || ""
            }

            // -------------------------------------------------- day and night
            SectionHeader { text: qsTr("Day and night") }
            TextSwitch {
                text: qsTr("Change the face by time of day")
                description: qsTr("Long-press a face below to choose it for the day or the night. It changes while the watch is connected; a face you pick on the watch stays until the next change.")
                checked: page.fs.enabled === true
                automaticCheck: false
                onClicked: page.setSchedule({ "enabled": !checked })
            }
            ValueButton {
                visible: page.fs.enabled === true
                label: qsTr("By day, from %1").arg(page.fs.day_start || "07:00")
                value: page.fs.day ? page.fs.day.name || page.fs.day.file : qsTr("not chosen")
                onClicked: page.pickTime(page.fs.day_start, function(t) { page.setSchedule({ "day_start": t }) })
            }
            ValueButton {
                visible: page.fs.enabled === true
                label: qsTr("At night, from %1").arg(page.fs.night_start || "21:00")
                value: page.fs.night ? page.fs.night.name || page.fs.night.file : qsTr("not chosen")
                onClicked: page.pickTime(page.fs.night_start, function(t) { page.setSchedule({ "night_start": t }) })
            }
            SectionHeader { text: qsTr("On the watch") }
        }

        delegate: ListItem {
            id: item
            contentHeight: Theme.itemSizeMedium
            menu: ContextMenu {
                MenuItem {
                    visible: !modelData.current
                    text: qsTr("Use on the watch")
                    onClicked: daemon.setWatchface(modelData.file, modelData.version)
                }
                MenuItem {
                    text: page.chosen("day", modelData) ? qsTr("Don't show by day") : qsTr("Show by day")
                    onClicked: page.choose("day", modelData)
                }
                MenuItem {
                    text: page.chosen("night", modelData) ? qsTr("Don't show at night") : qsTr("Show at night")
                    onClicked: page.choose("night", modelData)
                }
                MenuItem {
                    visible: item.deletable
                    text: qsTr("Delete from the watch")
                    onClicked: item.remorseDelete(function() { daemon.deleteWatchface(modelData.file, modelData.version) })
                }
            }
            enabled: daemon.connected && !page.uploading
            readonly property bool deletable: !modelData.factory && !modelData.current

            RoundImage {
                id: thumb
                x: Theme.horizontalPageMargin
                anchors.verticalCenter: parent.verticalCenter
                width: modelData.preview ? Theme.itemSizeSmall : 0
                height: width
                visible: !!modelData.preview
                source: modelData.preview ? "file://" + modelData.preview : ""
            }
            IconButton {
                id: deleteButton
                anchors { right: parent.right; rightMargin: Theme.horizontalPageMargin; verticalCenter: parent.verticalCenter }
                visible: item.deletable
                icon.source: "image://theme/icon-m-delete"
                onClicked: item.remorseDelete(function() { daemon.deleteWatchface(modelData.file, modelData.version) })
            }

            Column {
                anchors {
                    left: thumb.right; leftMargin: modelData.preview ? Theme.paddingMedium : 0
                    right: deleteButton.visible ? deleteButton.left : parent.right
                    rightMargin: deleteButton.visible ? Theme.paddingSmall : Theme.horizontalPageMargin
                    verticalCenter: parent.verticalCenter
                }
                Label {
                    width: parent.width
                    truncationMode: TruncationMode.Fade
                    text: page.faceTitle(modelData)
                    color: modelData.current ? Theme.highlightColor : Theme.primaryColor
                }
                Label {
                    width: parent.width
                    truncationMode: TruncationMode.Fade
                    font.pixelSize: Theme.fontSizeExtraSmall
                    color: Theme.secondaryColor
                    text: {
                        var parts = []
                        if (modelData.current) parts.push(qsTr("On the watch now"))
                        if (page.fs.enabled && page.chosen("day", modelData)) parts.push(qsTr("By day"))
                        if (page.fs.enabled && page.chosen("night", modelData)) parts.push(qsTr("At night"))
                        if (modelData.factory) parts.push(qsTr("Built in"))
                        if (modelData.trial) parts.push(qsTr("Trial"))
                        if (modelData.version) parts.push(qsTr("Version %1").arg(modelData.version))
                        return parts.join(" · ")
                    }
                }
            }
        }

        ViewPlaceholder {
            enabled: page.faces.length === 0 && !page.wf.loading
            text: !daemon.connected ? qsTr("Connect the watch to see its watch faces")
                  : page.wf.list === null || page.wf.list === undefined ? qsTr("Pull down to read the watch faces")
                  : qsTr("No watch faces")
        }
        BusyIndicator {
            anchors.centerIn: parent
            size: BusyIndicatorSize.Large
            running: !!page.wf.loading && page.faces.length === 0
        }
        VerticalScrollDecorator {}
    }
}
