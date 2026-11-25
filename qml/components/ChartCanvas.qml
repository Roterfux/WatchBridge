// WatchBridge - SPDX-License-Identifier: AGPL-3.0-or-later
// A Canvas that draws itself again when the app comes back to the foreground. Sailfish frees the
// window's graphics while the app is in the background, and a Canvas does not repaint on its own,
// so the charts were empty after switching back to the app.
import QtQuick 2.0

Canvas {
    id: canvas

    Connections {
        target: Qt.application
        onActiveChanged: if (Qt.application.active) canvas.requestPaint()
    }
    onVisibleChanged: if (visible) requestPaint()
}
