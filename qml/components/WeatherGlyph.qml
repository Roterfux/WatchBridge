// WatchBridge - SPDX-License-Identifier: AGPL-3.0-or-later
// Weather symbol for a WMO weather code.
import QtQuick 2.0
import Sailfish.Silica 1.0

Label {
    property var code: null

    function glyph(c) {
        if (c === null || c === undefined) return "–"
        if (c === 0 || c === 1) return "☀"            // sun
        if (c === 2) return "⛅"                       // sun behind cloud
        if (c === 3) return "☁"                       // cloud
        if (c === 45 || c === 48) return "\uD83C\uDF2B"       // fog
        if (c >= 51 && c <= 67) return "\uD83C\uDF27"         // rain
        if (c >= 71 && c <= 77) return "❄"            // snow
        if (c >= 80 && c <= 82) return "\uD83C\uDF26"         // showers
        if (c === 85 || c === 86) return "\uD83C\uDF28"       // snow showers
        if (c >= 95) return "⛈"                       // thunder
        return "☁"
    }

    text: glyph(code)
    font.pixelSize: Theme.fontSizeLarge
    horizontalAlignment: Text.AlignHCenter
}
