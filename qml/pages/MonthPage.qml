// WatchBridge - SPDX-License-Identifier: AGPL-3.0-or-later
// Week or month overview: steps, sleep, heart rate and stress per day, with averages. Tap a day to open it.
import QtQuick 2.0
import Sailfish.Silica 1.0
import "../components"

Page {
    id: page

    property var daemon
    property var healthPage: null       // the day page a tapped day is shown on
    property string mode: "month"       // "week" (Monday to Sunday) or "month"
    property string day: dateKey(new Date())   // any day in the week or month shown
    property var m: ({})
    property bool loading: true

    readonly property bool isWeek: mode === "week"
    // First day shown, at noon so that adding days never trips over a DST change
    readonly property var start: {
        var d = parseDay(day)
        if (isWeek) d.setDate(d.getDate() - (d.getDay() + 6) % 7)    // back to Monday
        else d.setDate(1)
        return d
    }
    readonly property int nDays: isWeek ? 7 : new Date(start.getFullYear(), start.getMonth() + 1, 0).getDate()
    readonly property int today: indexOf(dateKey(new Date()))
    readonly property bool isCurrent: today >= 0
    readonly property var s: m.summary || {}
    readonly property bool hasData: (m.days || []).length > 0

    // Same colours as the activity rings (ambience or classic, see Daemon.qml)
    readonly property color stepsColor: daemon.ringColors[0]
    readonly property color sleepColor: daemon.ringColors[3]
    readonly property color alertColor: "#ff6b5e"

    readonly property var goals: rings.goalsFrom(daemon.settings.health && daemon.settings.health.goals)
    ActivityRings { id: rings; visible: false; width: 0; height: 0 }

    // Axis: weekday names for a week; 1, 8, 15, 22, 29 for a month
    readonly property var dayTicks: {
        var out = []
        if (isWeek) {
            for (var i = 0; i < 7; i++)
                out.push({ "pos": (i + 0.5) / 7, "text": Qt.locale().dayName((i + 1) % 7, Locale.ShortFormat) })
        } else {
            for (var d = 1; d <= nDays; d += 7) out.push({ "pos": (d - 0.5) / nDays, "text": String(d) })
        }
        return out
    }

    function dateKey(d) { return Qt.formatDate(d, "yyyy-MM-dd") }
    function parseDay(key) {
        var p = key.split("-")
        return new Date(parseInt(p[0], 10), parseInt(p[1], 10) - 1, parseInt(p[2], 10), 12)
    }
    function dayAt(index) { return new Date(start.getFullYear(), start.getMonth(), start.getDate() + index, 12) }
    // Position of a date in the period shown, -1 outside it
    function indexOf(key) {
        var i = Math.round((parseDay(key).getTime() - start.getTime()) / 86400000)
        return i >= 0 && i < nDays ? i : -1
    }
    // One value per day shown (index 0 = the first day), null where there is none
    function series(key) {
        var out = []
        for (var i = 0; i < nDays; i++) out.push(null)
        var days = m.days || []
        for (var j = 0; j < days.length; j++) {
            var idx = indexOf(days[j].day)
            if (idx >= 0) out[idx] = days[j][key]
        }
        return out
    }
    function count(list, test) {
        var n = 0
        for (var i = 0; i < list.length; i++) if (list[i] !== null && test(list[i])) n++
        return n
    }
    function any(list) { return count(list, function() { return true }) > 0 }
    function stressColor(v) {
        // Huawei's bands, as on the day page
        return v < 30 ? "#4fb3ff" : v < 60 ? "#7fd36b" : v < 80 ? "#ffb347" : "#ff6b5e"
    }
    function duration(minutes) {
        minutes = Math.round(minutes || 0)
        var hh = Math.floor(minutes / 60), mm = minutes % 60
        return hh > 0 ? qsTr("%1 h %2 min").arg(hh).arg(mm) : qsTr("%1 min").arg(mm)
    }
    function shortDuration(minutes) {
        minutes = Math.round(minutes || 0)
        var mm = minutes % 60
        return Math.floor(minutes / 60) + ":" + (mm < 10 ? "0" : "") + mm
    }
    function num(v) { return Number(v || 0).toLocaleString(Qt.locale(), "f", 0) }
    function shift(n) {
        var d = parseDay(day)
        if (isWeek) d.setDate(d.getDate() + 7 * n)
        else d = new Date(d.getFullYear(), d.getMonth() + n, 1, 12)
        day = dateKey(d)
    }
    function title() {
        if (!isWeek) return Qt.formatDate(start, "MMMM yyyy")
        var end = dayAt(6)
        return Qt.formatDate(start, start.getMonth() === end.getMonth() ? "d." : "d. MMM") + " – "
               + Qt.formatDate(end, "d. MMM yyyy")
    }
    function openDay(index) {
        var key = dateKey(dayAt(index))
        if (healthPage) {
            healthPage.day = key
            pageStack.pop()
        } else {
            pageStack.push(Qt.resolvedUrl("HealthPage.qml"), { daemon: daemon, day: key })
        }
    }
    property string loadedKey: ""
    property bool created: false
    function load() {
        // While the page is being created, Qt sets day, mode and daemon in no fixed order: a load
        // started then had no daemon yet, failed, and the week opened from the day page stayed empty
        if (!created || !daemon) return
        // Mode and start can change together; ask once
        var key = mode + " " + dateKey(start)
        if (key === loadedKey) return
        loadedKey = key
        loading = true
        // Only the answer to the latest request counts, should two cross
        var done = function(r) {
            if (key !== page.loadedKey) return
            page.m = r
            page.loading = false
        }
        if (isWeek) daemon.getHealthWeek(dateKey(start), done)
        else daemon.getHealthMonth(Qt.formatDate(start, "yyyy-MM"), done)
    }

    onStartChanged: load()
    onModeChanged: load()
    Component.onCompleted: {
        created = true
        load()
    }

    readonly property var steps: series("steps")
    readonly property var sleep: series("sleep")
    readonly property var hrMax: series("hrMax")
    readonly property var stress: series("stress")
    readonly property var stressColors: {
        var out = []
        for (var i = 0; i < stress.length; i++) out.push(stress[i] === null ? null : stressColor(stress[i]))
        return out
    }

    SilicaFlickable {
        anchors.fill: parent
        contentHeight: column.height + Theme.paddingLarge

        PullDownMenu {
            MenuItem {
                text: page.isWeek ? qsTr("Show the month") : qsTr("Show the week")
                onClicked: page.mode = page.isWeek ? "month" : "week"
            }
        }

        Column {
            id: column
            width: parent.width
            spacing: Theme.paddingMedium

            PageHeader {
                title: page.isWeek ? qsTr("Week") : qsTr("Month")
                description: page.hasData ? qsTr("Tap a day to open it") : ""
            }

            // ---------------------------------------------- period navigation
            Item {
                width: parent.width
                height: Theme.itemSizeSmall
                IconButton {
                    id: prevButton
                    anchors { left: parent.left; leftMargin: Theme.horizontalPageMargin; verticalCenter: parent.verticalCenter }
                    icon.source: "image://theme/icon-m-left"
                    onClicked: page.shift(-1)
                }
                Label {
                    anchors { left: prevButton.right; right: nextButton.left; verticalCenter: parent.verticalCenter }
                    horizontalAlignment: Text.AlignHCenter
                    fontSizeMode: Text.HorizontalFit
                    minimumPixelSize: Theme.fontSizeSmall
                    text: page.title()
                    color: Theme.highlightColor
                    font.pixelSize: Theme.fontSizeLarge
                }
                IconButton {
                    id: nextButton
                    anchors { right: parent.right; rightMargin: Theme.horizontalPageMargin; verticalCenter: parent.verticalCenter }
                    icon.source: "image://theme/icon-m-right"
                    enabled: !page.isCurrent
                    onClicked: page.shift(1)
                }
            }

            Label {
                x: Theme.horizontalPageMargin
                width: parent.width - 2 * x
                visible: !!m.error
                wrapMode: Text.Wrap
                color: page.alertColor
                text: m.error || ""
            }

            // ---------------------------------------------------------- steps
            SectionHeader { text: qsTr("Steps"); visible: page.any(page.steps) }
            MonthBars {
                x: Theme.horizontalPageMargin
                width: parent.width - 2 * x
                visible: page.any(page.steps)
                days: page.nDays
                today: page.today
                values: page.steps
                color: page.stepsColor
                goal: page.goals.steps
                onDayClicked: page.openDay(index)
            }
            TimeAxis {
                x: Theme.horizontalPageMargin
                width: parent.width - 2 * x
                visible: page.any(page.steps)
                ticks: page.dayTicks
            }
            // A week has room for each day's number
            DayValues {
                visible: page.isWeek && page.any(page.steps)
                values: page.steps.map(function(v) { return v === null ? "" : page.num(v) })
            }
            DetailItem {
                visible: s.steps !== null && s.steps !== undefined
                label: qsTr("Average")
                value: qsTr("%1 steps a day").arg(page.num(s.steps))
            }
            DetailItem {
                visible: page.any(page.steps)
                label: qsTr("Goal reached")
                value: qsTr("%n day(s)", "", page.count(page.steps, function(v) { return v >= page.goals.steps }))
            }
            DetailItem {
                visible: page.any(page.steps)
                label: qsTr("Distance")
                value: qsTr("%1 km in total").arg(((s.distanceTotal || 0) / 1000).toFixed(1))
            }
            DetailItem {
                visible: s.calories !== null && s.calories !== undefined
                label: qsTr("Calories")
                value: qsTr("%1 kcal a day").arg(page.num(s.calories))
            }

            // ---------------------------------------------------------- sleep
            SectionHeader { text: qsTr("Sleep"); visible: page.any(page.sleep) }
            MonthBars {
                x: Theme.horizontalPageMargin
                width: parent.width - 2 * x
                visible: page.any(page.sleep)
                days: page.nDays
                today: page.today
                values: page.sleep
                inner: page.series("deep")
                color: page.sleepColor
                goal: page.goals.sleep
                onDayClicked: page.openDay(index)
            }
            TimeAxis {
                x: Theme.horizontalPageMargin
                width: parent.width - 2 * x
                visible: page.any(page.sleep)
                ticks: page.dayTicks
            }
            DayValues {
                visible: page.isWeek && page.any(page.sleep)
                values: page.sleep.map(function(v) { return v === null ? "" : page.shortDuration(v) })
            }
            DayValues {
                visible: page.isWeek && page.any(page.series("score"))
                values: page.series("score").map(function(v) { return v === null ? "" : qsTr("score %1").arg(v) })
                secondary: true
            }
            Label {
                x: Theme.horizontalPageMargin
                width: parent.width - 2 * x
                visible: page.any(page.sleep)
                wrapMode: Text.Wrap
                font.pixelSize: Theme.fontSizeExtraSmall
                color: Theme.secondaryColor
                text: qsTr("Darker part: deep sleep. Line: your sleep goal.")
            }
            DetailItem {
                visible: !!s.sleep
                label: qsTr("Average")
                value: page.duration(s.sleep)
            }
            DetailItem {
                visible: !!s.deep
                label: qsTr("Deep sleep")
                value: page.duration(s.deep)
            }
            DetailItem {
                visible: s.score !== null && s.score !== undefined
                label: qsTr("Sleep score")
                value: String(s.score)
            }
            DetailItem {
                visible: page.any(page.sleep)
                label: qsTr("Goal reached")
                value: qsTr("%n night(s)", "", page.count(page.sleep, function(v) { return v >= page.goals.sleep }))
            }

            // ----------------------------------------------------- heart rate
            SectionHeader { text: qsTr("Heart rate"); visible: page.any(page.hrMax) }
            MonthBars {
                x: Theme.horizontalPageMargin
                width: parent.width - 2 * x
                height: Theme.itemSizeExtraLarge
                visible: page.any(page.hrMax)
                days: page.nDays
                today: page.today
                values: page.hrMax
                lows: page.series("hrMin")
                marks: page.series("resting")
                color: page.alertColor
                markColor: page.alertColor
                fade: 0.35
                minValue: 40
                onDayClicked: page.openDay(index)
            }
            TimeAxis {
                x: Theme.horizontalPageMargin
                width: parent.width - 2 * x
                visible: page.any(page.hrMax)
                ticks: page.dayTicks
            }
            Label {
                x: Theme.horizontalPageMargin
                width: parent.width - 2 * x
                visible: page.any(page.hrMax)
                wrapMode: Text.Wrap
                font.pixelSize: Theme.fontSizeExtraSmall
                color: Theme.secondaryColor
                text: qsTr("Bars: lowest to highest. Dots: resting heart rate.")
            }
            DetailItem {
                visible: !!s.resting
                label: qsTr("Resting")
                value: qsTr("%1 bpm on average, lowest %2").arg(s.resting).arg(s.restingMin)
            }
            DetailItem {
                visible: !!s.hrAvg
                label: qsTr("Average")
                value: qsTr("%1 bpm").arg(s.hrAvg)
            }

            // --------------------------------------------------------- stress
            SectionHeader { text: qsTr("Stress"); visible: page.any(page.stress) }
            MonthBars {
                x: Theme.horizontalPageMargin
                width: parent.width - 2 * x
                height: Theme.itemSizeMedium
                visible: page.any(page.stress)
                days: page.nDays
                today: page.today
                values: page.stress
                colors: page.stressColors
                maxValue: 100
                onDayClicked: page.openDay(index)
            }
            TimeAxis {
                x: Theme.horizontalPageMargin
                width: parent.width - 2 * x
                visible: page.any(page.stress)
                ticks: page.dayTicks
            }
            DetailItem {
                visible: !!s.stress
                label: qsTr("Average")
                value: String(s.stress)
            }
        }

        ViewPlaceholder {
            enabled: !page.loading && !page.hasData && m.available !== false && !m.error
            text: qsTr("No health data for this month")
        }
        ViewPlaceholder {
            enabled: !page.loading && m.available === false
            text: qsTr("Health data is not available")
            hintText: m.error || ""
        }

        VerticalScrollDecorator {}
    }
}
