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
    readonly property var calls: s.calls || {}
    readonly property var calendar: s.calendar || {}

    readonly property var intervals: [15, 30, 60, 120, 180]
    readonly property var healthIntervals: [1, 3, 6, 12, 24]
    readonly property var firstSyncDays: [1, 7, 14, 30]
    readonly property var spo2Alerts: [0, 80, 85, 90]
    readonly property var moveIntervals: [30, 45, 60, 90, 120, 180]
    readonly property var hrModes: [null, "smart", "realtime"]
    readonly property var hrEvery: [0, 5, 10, 15, 20, 30, 45, 60]
    readonly property var spo2Every: [0, 60, 120, 180, 240]
    readonly property var saveModes: ["phone", "always", "off"]
    readonly property var dnd: s.do_not_disturb || {}
    readonly property var phone: daemon.status.phone || {}
    readonly property var dayPresets: [0x1F, 0x7F, 0x60]     // weekdays, every day, weekends
    readonly property var genders: ["unknown", "female", "male"]
    readonly property var batteryWarnings: [0, 10, 15, 20, 30]
    readonly property var mr: watch.move_reminder || {}
    readonly property var profile: s.profile || {}

    // The whole reminder is sent each time, with "enabled" set once anything is chosen
    function setMoveReminder(change) {
        var v = { "enabled": mr.enabled === true, "interval": mr.interval || 60, "start": mr.start || "08:00",
                  "end": mr.end || "22:00", "days": mr.days === undefined ? 0x1F : mr.days }
        for (var k in change) v[k] = change[k]
        daemon.updateSettings({ "watch": { "move_reminder": v } })
    }
    function pickTime(text, done) {
        var p = (text || "08:00").split(":")
        var d = pageStack.push("Sailfish.Silica.TimePickerDialog",
                               { "hour": parseInt(p[0], 10), "minute": parseInt(p[1], 10),
                                 "hourMode": DateTime.TwentyFourHours })
        d.accepted.connect(function() {
            done((d.hour < 10 ? "0" : "") + d.hour + ":" + (d.minute < 10 ? "0" : "") + d.minute)
        })
    }
    function parseDate(text) {
        var p = text.split("-")
        return new Date(parseInt(p[0], 10), parseInt(p[1], 10) - 1, parseInt(p[2], 10), 12)
    }

    function ago(ts) {
        if (!ts) return ""
        var mins = Math.round((Date.now() / 1000 - ts) / 60)
        if (mins < 1) return qsTr("just now")
        if (mins < 60) return qsTr("%n min ago", "", mins)
        return qsTr("%n h ago", "", Math.round(mins / 60))
    }

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
            Item { width: 1; height: Theme.paddingMedium; visible: daemon.paired }
            Button {
                visible: daemon.paired
                anchors.horizontalCenter: parent.horizontalCenter
                text: qsTr("Sync time")
                enabled: daemon.connected
                onClicked: daemon.syncTime()
            }

            SectionHeader { text: qsTr("Notifications") }

            TextSwitch {
                text: qsTr("Forward notifications")
                description: n.mode === "selected" && (n.allowed_apps || []).length === 0
                             ? qsTr("Only selected apps are forwarded, and none is selected yet. Choose them below.")
                             : qsTr("%n notification(s) sent this session", "", daemon.status.notificationsForwarded || 0)
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
            TextSwitch {
                text: qsTr("Remove from the watch when cleared on the phone")
                description: qsTr("When you dismiss a notification on the phone, or read the message in its app, it also disappears from the watch.")
                checked: n.remove_dismissed !== false
                automaticCheck: false
                onClicked: daemon.updateSettings({ "notifications": { "remove_dismissed": !checked } })
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

            // The last forwarded notification (moved here from the main page)
            Item { width: 1; height: Theme.paddingMedium; visible: !!daemon.status.lastNotification }
            Column {
                readonly property var last: daemon.status.lastNotification || null
                visible: !!last
                x: Theme.horizontalPageMargin
                width: parent.width - 2 * x
                Label {
                    width: parent.width
                    truncationMode: TruncationMode.Fade
                    font.pixelSize: Theme.fontSizeExtraSmall
                    color: Theme.secondaryColor
                    text: parent.last ? qsTr("Last: %1 · %2").arg(parent.last.app).arg(page.ago(parent.last.time)) : ""
                }
                Label {
                    width: parent.width
                    truncationMode: TruncationMode.Fade
                    text: parent.last ? parent.last.title : ""
                }
                Label {
                    width: parent.width
                    maximumLineCount: 2
                    wrapMode: Text.Wrap
                    elide: Text.ElideRight
                    font.pixelSize: Theme.fontSizeSmall
                    color: Theme.secondaryColor
                    text: parent.last ? parent.last.body : ""
                }
            }
            Item { width: 1; height: Theme.paddingMedium }
            Button {
                visible: daemon.paired
                anchors.horizontalCenter: parent.horizontalCenter
                text: qsTr("Send test notification")
                enabled: daemon.connected
                onClicked: daemon.sendTestNotification()
            }

            // ------------------------------------------------------ do not disturb
            SectionHeader { text: qsTr("Do not disturb") }

            Label {
                x: Theme.horizontalPageMargin
                width: parent.width - 2 * x
                wrapMode: Text.Wrap
                font.pixelSize: Theme.fontSizeExtraSmall
                color: Theme.secondaryColor
                text: {
                    var base = qsTr("Notifications are not sent to the watch while do not disturb is on, so it stays quiet and dark.")
                    if (page.phone.quiet) base += "\n" + qsTr("On now.")
                    if (page.phone.held) base += " " + qsTr("%n notification(s) held back", "", page.phone.held)
                    return base
                }
            }
            TextSwitch {
                text: qsTr("Follow the phone")
                description: qsTr("When do not disturb is switched on in the phone's top menu.")
                checked: dnd.follow_phone !== false
                automaticCheck: false
                onClicked: daemon.updateSettings({ "do_not_disturb": { "follow_phone": !checked } })
            }
            TextSwitch {
                text: qsTr("Every day at set times")
                checked: !!dnd.scheduled
                automaticCheck: false
                onClicked: daemon.updateSettings({ "do_not_disturb": { "scheduled": !checked } })
            }
            ValueButton {
                label: qsTr("From")
                visible: !!dnd.scheduled
                value: dnd.start || "22:00"
                onClicked: page.pickTime(value, function(text) { daemon.updateSettings({ "do_not_disturb": { "start": text } }) })
            }
            ValueButton {
                label: qsTr("Until")
                visible: !!dnd.scheduled
                value: dnd.end || "07:00"
                onClicked: page.pickTime(value, function(text) { daemon.updateSettings({ "do_not_disturb": { "end": text } }) })
            }
            TextSwitch {
                text: qsTr("Let calls through")
                description: qsTr("Incoming calls still show on the watch.")
                checked: dnd.calls !== false
                automaticCheck: false
                onClicked: daemon.updateSettings({ "do_not_disturb": { "calls": !checked } })
            }

            SectionHeader { text: qsTr("Calls") }

            TextSwitch {
                text: qsTr("Show incoming calls on the watch")
                description: qsTr("Reject the call on the watch, or silence the ringtone.")
                checked: calls.enabled !== false
                automaticCheck: false
                onClicked: daemon.updateSettings({ "calls": { "enabled": !checked } })
            }
            TextSwitch {
                enabled: calls.enabled !== false
                text: qsTr("Show the caller's name")
                description: {
                    var st = daemon.status.calls || {}
                    var base = qsTr("Looks the number up in Contacts. Sailfish asks once for permission.")
                    if (calls.caller_names === false || calls.enabled === false) return base
                    if (st.names === "loading") return base + "\n" + qsTr("Reading contacts…")
                    if (st.names === "ready") return base + "\n" + qsTr("%n phone number(s) known", "", st.nameCount || 0)
                    if (st.names === "failed") return base + "\n" + qsTr("Not available: %1").arg(st.namesError || "")
                    return base
                }
                checked: calls.caller_names !== false
                automaticCheck: false
                onClicked: daemon.updateSettings({ "calls": { "caller_names": !checked } })
            }

            SectionHeader { text: qsTr("Calendar") }

            TextSwitch {
                text: qsTr("Show the calendar on the watch")
                description: {
                    var st = daemon.status.calendar || {}
                    var base = qsTr("Upcoming events appear in the calendar app on the watch. Changes reach it within half an hour.")
                    if (calendar.enabled === false) return base
                    if (st.syncing) return base + "\n" + qsTr("Syncing…")
                    if (st.error) return base + "\n" + qsTr("Not synced: %1").arg(st.error)
                    if (st.lastSync) return base + "\n" + qsTr("%n event(s) on the watch, synced %1", "", st.events || 0).arg(page.ago(st.lastSync))
                    return base
                }
                checked: calendar.enabled !== false
                automaticCheck: false
                onClicked: daemon.updateSettings({ "calendar": { "enabled": !checked } })
            }
            Button {
                visible: daemon.paired
                anchors.horizontalCenter: parent.horizontalCenter
                text: qsTr("Sync calendar now")
                enabled: daemon.connected && calendar.enabled !== false && !(daemon.status.calendar || {}).syncing
                onClicked: daemon.syncCalendar()
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
                label: qsTr("Heart rate mode")
                visible: hl.continuous_heart_rate === true
                description: qsTr("Smart measures less often while you rest and saves battery. Real-time measures about every second.")
                currentIndex: Math.max(0, page.hrModes.indexOf(hl.heart_rate_mode || null))
                menu: ContextMenu {
                    MenuItem { text: qsTr("Watch's own setting") }
                    MenuItem { text: qsTr("Smart, about every 10 min") }
                    MenuItem { text: qsTr("Real-time") }
                }
                onCurrentIndexChanged: {
                    if (!page.s.health) return
                    var v = page.hrModes[currentIndex]
                    if (v !== (hl.heart_rate_mode || null))
                        daemon.updateSettings({ "health": { "heart_rate_mode": v } })
                }
            }
            ComboBox {
                label: qsTr("Extra heart rate check")
                description: qsTr("Test: switches real-time measuring on for 2 min at this interval. Paused while saving power.")
                currentIndex: Math.max(0, page.hrEvery.indexOf(hl.heart_rate_every || 0))
                menu: ContextMenu {
                    Repeater {
                        model: page.hrEvery
                        MenuItem { text: modelData === 0 ? qsTr("Off") : qsTr("Every %1 min").arg(modelData) }
                    }
                }
                onCurrentIndexChanged: {
                    if (!page.s.health) return
                    var v = page.hrEvery[currentIndex]
                    if (v !== (hl.heart_rate_every || 0))
                        daemon.updateSettings({ "health": { "heart_rate_every": v } })
                }
            }
            ComboBox {
                label: qsTr("Extra blood oxygen check")
                description: qsTr("Test: switches automatic SpO₂ on for 10 min at this interval. Paused while saving power.")
                currentIndex: Math.max(0, page.spo2Every.indexOf(hl.spo2_every || 0))
                menu: ContextMenu {
                    Repeater {
                        model: page.spo2Every
                        MenuItem { text: modelData === 0 ? qsTr("Off") : qsTr("Every %1 h").arg(modelData / 60) }
                    }
                }
                onCurrentIndexChanged: {
                    if (!page.s.health) return
                    var v = page.spo2Every[currentIndex]
                    if (v !== (hl.spo2_every || 0))
                        daemon.updateSettings({ "health": { "spo2_every": v } })
                }
            }
            TextSwitch {
                text: qsTr("Measure blood oxygen automatically")
                description: hl.automatic_spo2 === null || hl.automatic_spo2 === undefined
                             ? qsTr("Currently left to the watch's own setting. When on, the watch measures SpO₂ through the day and night. Uses more battery.")
                             : qsTr("The watch measures SpO₂ through the day and night. Uses more battery.")
                checked: hl.automatic_spo2 === true
                automaticCheck: false
                onClicked: daemon.updateSettings({ "health": { "automatic_spo2": !checked } })
            }
            ComboBox {
                label: qsTr("Low blood oxygen warning")
                visible: hl.automatic_spo2 === true
                currentIndex: Math.max(0, page.spo2Alerts.indexOf(hl.low_spo2_alert || 0))
                menu: ContextMenu {
                    Repeater {
                        model: page.spo2Alerts
                        MenuItem { text: modelData === 0 ? qsTr("Off") : qsTr("Below %1 %").arg(modelData) }
                    }
                }
                onCurrentIndexChanged: {
                    if (!page.s.health) return
                    var v = page.spo2Alerts[currentIndex]
                    if (v !== (hl.low_spo2_alert || 0))
                        daemon.updateSettings({ "health": { "low_spo2_alert": v } })
                }
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
            // Daily goals for the rings on the health page; stored as steps, m, kcal and min
            Repeater {
                model: [
                    { "key": "steps", "label": qsTr("Step goal"), "min": 1000, "max": 30000, "step": 500, "scale": 1 },
                    { "key": "distance", "label": qsTr("Distance goal"), "min": 0.5, "max": 30, "step": 0.5, "scale": 1000 },
                    { "key": "calories", "label": qsTr("Calorie goal"), "min": 50, "max": 2000, "step": 50, "scale": 1 },
                    { "key": "sleep", "label": qsTr("Sleep goal"), "min": 4, "max": 12, "step": 0.5, "scale": 60 }
                ]
                Slider {
                    width: parent.width
                    label: modelData.label
                    minimumValue: modelData.min
                    maximumValue: modelData.max
                    stepSize: modelData.step
                    value: {
                        var defaults = { "steps": 8000, "distance": 5000, "calories": 350, "sleep": 420 }
                        var g = hl.goals || {}
                        return (g[modelData.key] || defaults[modelData.key]) / modelData.scale
                    }
                    valueText: modelData.key === "steps" ? Number(sliderValue).toLocaleString(Qt.locale(), "f", 0)
                             : modelData.key === "distance" ? qsTr("%1 km").arg(sliderValue.toFixed(1))
                             : modelData.key === "calories" ? qsTr("%1 kcal").arg(sliderValue)
                             : qsTr("%1 h").arg(sliderValue.toFixed(1))
                    onDownChanged: {
                        if (down) return
                        var change = {}
                        change[modelData.key] = Math.round(sliderValue * modelData.scale)
                        daemon.updateSettings({ "health": { "goals": change } })
                    }
                }
            }
            ComboBox {
                label: qsTr("Ring colours")
                description: qsTr("Colours of the goal rings and the week and month charts.")
                currentIndex: hl.ring_colors === "classic" ? 1 : 0
                menu: ContextMenu {
                    MenuItem { text: qsTr("From the ambience") }
                    MenuItem { text: qsTr("Classic") }
                }
                onCurrentIndexChanged: {
                    if (!page.s.health) return
                    var v = currentIndex === 1 ? "classic" : "ambience"
                    if (v !== (hl.ring_colors || "ambience"))
                        daemon.updateSettings({ "health": { "ring_colors": v } })
                }
            }
            // A preview of the four colours in the current ambience
            Row {
                x: Theme.horizontalPageMargin
                spacing: Theme.paddingMedium
                Repeater {
                    model: daemon.ringColors
                    Rectangle {
                        width: Theme.iconSizeSmall; height: width; radius: width / 2
                        color: modelData
                    }
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

            // ------------------------------------------------------ move reminder
            SectionHeader { text: qsTr("Move reminder") }

            TextSwitch {
                text: qsTr("Remind me to move")
                description: mr.enabled === null || mr.enabled === undefined
                             ? qsTr("Currently left to the watch's own setting. The watch vibrates after you have been sitting for a while.")
                             : qsTr("The watch vibrates after you have been sitting for a while.")
                checked: mr.enabled === true
                automaticCheck: false
                onClicked: page.setMoveReminder({ "enabled": !checked })
            }
            ComboBox {
                label: qsTr("After sitting for")
                visible: mr.enabled === true
                currentIndex: Math.max(0, page.moveIntervals.indexOf(mr.interval || 60))
                menu: ContextMenu {
                    Repeater {
                        model: page.moveIntervals
                        MenuItem { text: modelData < 120 ? qsTr("%n min", "", modelData) : qsTr("%n hour(s)", "", modelData / 60) }
                    }
                }
                onCurrentIndexChanged: {
                    var v = page.moveIntervals[currentIndex]
                    if (page.s.watch && v !== (mr.interval || 60)) page.setMoveReminder({ "interval": v })
                }
            }
            ValueButton {
                label: qsTr("From")
                visible: mr.enabled === true
                value: mr.start || "08:00"
                onClicked: page.pickTime(value, function(text) { page.setMoveReminder({ "start": text }) })
            }
            ValueButton {
                label: qsTr("Until")
                visible: mr.enabled === true
                value: mr.end || "22:00"
                onClicked: page.pickTime(value, function(text) { page.setMoveReminder({ "end": text }) })
            }
            ComboBox {
                label: qsTr("On")
                visible: mr.enabled === true
                currentIndex: { var i = page.dayPresets.indexOf(mr.days === undefined ? 0x1F : mr.days); return i < 0 ? 0 : i }
                menu: ContextMenu {
                    MenuItem { text: qsTr("Weekdays") }
                    MenuItem { text: qsTr("Every day") }
                    MenuItem { text: qsTr("Weekends") }
                }
                onCurrentIndexChanged: {
                    var v = page.dayPresets[currentIndex]
                    if (page.s.watch && v !== (mr.days === undefined ? 0x1F : mr.days)) page.setMoveReminder({ "days": v })
                }
            }

            // ------------------------------------------------------------ profile
            SectionHeader { text: qsTr("Profile") }

            Label {
                x: Theme.horizontalPageMargin
                width: parent.width - 2 * x
                wrapMode: Text.Wrap
                font.pixelSize: Theme.fontSizeExtraSmall
                color: Theme.secondaryColor
                text: qsTr("The watch estimates calories and distance from these. They are sent once height, weight and birthday are filled in, and stay on this phone otherwise.")
            }
            TextField {
                width: parent.width
                label: qsTr("Height (cm)")
                placeholderText: label
                text: profile.height ? String(profile.height) : ""
                inputMethodHints: Qt.ImhDigitsOnly
                validator: IntValidator { bottom: 100; top: 250 }
                EnterKey.iconSource: "image://theme/icon-m-enter-close"
                EnterKey.onClicked: focus = false
                onActiveFocusChanged: if (!activeFocus && acceptableInput && parseInt(text, 10) !== profile.height)
                                          daemon.updateSettings({ "profile": { "height": parseInt(text, 10) } })
            }
            TextField {
                width: parent.width
                label: qsTr("Weight (kg)")
                placeholderText: label
                text: profile.weight ? String(profile.weight) : ""
                inputMethodHints: Qt.ImhDigitsOnly
                validator: IntValidator { bottom: 30; top: 250 }
                EnterKey.iconSource: "image://theme/icon-m-enter-close"
                EnterKey.onClicked: focus = false
                onActiveFocusChanged: if (!activeFocus && acceptableInput && parseInt(text, 10) !== profile.weight)
                                          daemon.updateSettings({ "profile": { "weight": parseInt(text, 10) } })
            }
            ValueButton {
                label: qsTr("Birthday")
                value: profile.birthday ? Qt.formatDate(page.parseDate(profile.birthday), Qt.DefaultLocaleShortDate)
                                        : qsTr("Not set")
                onClicked: {
                    var d = pageStack.push("Sailfish.Silica.DatePickerDialog",
                                           { "date": profile.birthday ? page.parseDate(profile.birthday) : new Date(1990, 0, 1, 12) })
                    d.accepted.connect(function() {
                        daemon.updateSettings({ "profile": { "birthday": Qt.formatDate(d.date, "yyyy-MM-dd") } })
                    })
                }
            }
            ComboBox {
                label: qsTr("Sex")
                currentIndex: Math.max(0, page.genders.indexOf(profile.gender || "unknown"))
                menu: ContextMenu {
                    MenuItem { text: qsTr("Not set") }
                    MenuItem { text: qsTr("Female") }
                    MenuItem { text: qsTr("Male") }
                }
                onCurrentIndexChanged: {
                    var v = page.genders[currentIndex]
                    if (page.s.profile && v !== (profile.gender || "unknown"))
                        daemon.updateSettings({ "profile": { "gender": v } })
                }
            }

            // ------------------------------------------------------ watch battery
            SectionHeader { text: qsTr("Watch battery") }

            ComboBox {
                label: qsTr("Low battery warning")
                description: qsTr("A notification on the phone when the watch battery gets low.")
                currentIndex: { var i = page.batteryWarnings.indexOf(watch.low_battery_warning === undefined ? 20 : watch.low_battery_warning); return i < 0 ? 0 : i }
                menu: ContextMenu {
                    Repeater {
                        model: page.batteryWarnings
                        MenuItem { text: modelData === 0 ? qsTr("Off") : qsTr("At %1 %").arg(modelData) }
                    }
                }
                onCurrentIndexChanged: {
                    var v = page.batteryWarnings[currentIndex]
                    if (page.s.watch && v !== watch.low_battery_warning)
                        daemon.updateSettings({ "watch": { "low_battery_warning": v } })
                }
            }

            // ------------------------------------------------------- power saving
            SectionHeader { text: qsTr("Power saving") }

            ComboBox {
                label: qsTr("Save power")
                description: {
                    var base = qsTr("Fewer wake-ups for phone and watch: health sync at most every 12 h, watch battery every hour, weather every 3 h, calendar every 2 h, and a lost watch is tried every 30 min.")
                    return base + "\n" + (page.phone.saving ? qsTr("Saving now.") : qsTr("Not saving now."))
                                + " " + (page.phone.batterySaver ? qsTr("Phone battery saver is on.") : qsTr("Phone battery saver is off."))
                }
                currentIndex: Math.max(0, page.saveModes.indexOf((s.power_save || {}).mode || "phone"))
                menu: ContextMenu {
                    MenuItem { text: qsTr("With the phone's battery saver") }
                    MenuItem { text: qsTr("Always") }
                    MenuItem { text: qsTr("Never") }
                }
                onCurrentIndexChanged: {
                    if (!page.s.power_save) return
                    var v = page.saveModes[currentIndex]
                    if (v !== (s.power_save.mode || "phone"))
                        daemon.updateSettings({ "power_save": { "mode": v } })
                }
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
