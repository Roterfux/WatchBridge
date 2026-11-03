// WatchBridge - SPDX-License-Identifier: AGPL-3.0-or-later
// Choose the weather location: city search (Open-Meteo geocoding) or GPS.
import QtQuick 2.0
import QtPositioning 5.2
import Sailfish.Silica 1.0

Page {
    id: page

    property var daemon
    property var results: []
    property bool searching: false
    property string error: ""
    property bool locating: false

    function choose(name, lat, lon) {
        daemon.updateSettings({ "weather": { "location": name, "latitude": lat, "longitude": lon, "enabled": true } })
        pageStack.pop()
    }

    function search(query) {
        query = query.trim()
        if (query.length < 2) { results = []; return }
        searching = true
        error = ""
        var xhr = new XMLHttpRequest()
        var lang = Qt.locale().name.split("_")[0] || "en"
        xhr.open("GET", "https://geocoding-api.open-meteo.com/v1/search?count=15&format=json&language="
                 + lang + "&name=" + encodeURIComponent(query))
        xhr.onreadystatechange = function() {
            if (xhr.readyState !== XMLHttpRequest.DONE) return
            searching = false
            if (xhr.status !== 200) {
                error = qsTr("Search failed (%1)").arg(xhr.status || qsTr("no network"))
                return
            }
            try {
                results = JSON.parse(xhr.responseText).results || []
            } catch (e) {
                error = qsTr("Unexpected answer from the server")
            }
        }
        xhr.send()
    }

    Timer {
        id: debounce
        interval: 400
        onTriggered: page.search(listView.headerItem.searchText)
    }

    PositionSource {
        id: gps
        active: page.locating
        updateInterval: 1000
        onPositionChanged: {
            var c = position.coordinate
            if (page.locating && c.isValid) {
                page.locating = false
                page.choose(qsTr("Current location"), Math.round(c.latitude * 1e4) / 1e4,
                            Math.round(c.longitude * 1e4) / 1e4)
            }
        }
    }

    SilicaListView {
        id: listView
        anchors.fill: parent
        model: page.results

        header: Column {
            property alias searchText: field.text
            width: listView.width

            PageHeader {
                title: qsTr("Weather location")
                description: daemon.settings.weather && daemon.settings.weather.location
                             ? qsTr("Current: %1").arg(daemon.settings.weather.location) : ""
            }
            SearchField {
                id: field
                width: parent.width
                placeholderText: qsTr("Search for a city")
                inputMethodHints: Qt.ImhNoPredictiveText
                onTextChanged: debounce.restart()
                Component.onCompleted: forceActiveFocus()
            }
            BackgroundItem {
                height: Theme.itemSizeSmall
                enabled: gps.valid && !page.locating
                onClicked: page.locating = true
                Row {
                    x: Theme.horizontalPageMargin
                    anchors.verticalCenter: parent.verticalCenter
                    spacing: Theme.paddingMedium
                    Icon { source: "image://theme/icon-m-gps"; anchors.verticalCenter: parent.verticalCenter }
                    Label {
                        anchors.verticalCenter: parent.verticalCenter
                        text: page.locating ? qsTr("Locating…")
                              : gps.valid ? qsTr("Use my current position") : qsTr("Positioning is not available")
                        color: parent.parent.highlighted ? Theme.highlightColor : Theme.primaryColor
                    }
                    BusyIndicator {
                        size: BusyIndicatorSize.ExtraSmall
                        running: page.locating || page.searching
                        anchors.verticalCenter: parent.verticalCenter
                    }
                }
            }
            Label {
                x: Theme.horizontalPageMargin
                visible: page.error !== ""
                text: page.error
                color: "#ff6b5e"
            }
        }

        delegate: BackgroundItem {
            height: Theme.itemSizeMedium
            onClicked: page.choose(modelData.name, modelData.latitude, modelData.longitude)
            Column {
                x: Theme.horizontalPageMargin
                width: parent.width - 2 * x
                anchors.verticalCenter: parent.verticalCenter
                Label {
                    width: parent.width
                    truncationMode: TruncationMode.Fade
                    text: modelData.name
                    color: highlighted ? Theme.highlightColor : Theme.primaryColor
                }
                Label {
                    width: parent.width
                    truncationMode: TruncationMode.Fade
                    font.pixelSize: Theme.fontSizeExtraSmall
                    color: Theme.secondaryColor
                    text: [modelData.admin1, modelData.country].filter(function(x) { return !!x }).join(", ")
                          + "  ·  " + modelData.latitude.toFixed(2) + ", " + modelData.longitude.toFixed(2)
                }
            }
        }

        ViewPlaceholder {
            enabled: listView.count === 0 && !page.searching && listView.headerItem
                     && listView.headerItem.searchText.length >= 2
            text: qsTr("No places found")
        }

        VerticalScrollDecorator {}
    }

    Label {
        anchors { bottom: parent.bottom; bottomMargin: Theme.paddingLarge; horizontalCenter: parent.horizontalCenter }
        text: qsTr("Geocoding by Open-Meteo.com")
        font.pixelSize: Theme.fontSizeTiny
        color: Theme.secondaryColor
    }
}
