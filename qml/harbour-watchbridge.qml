// WatchBridge - Huawei Watch GT 5 companion for Sailfish OS
// SPDX-License-Identifier: AGPL-3.0-or-later
import QtQuick 2.0
import Sailfish.Silica 1.0
import Nemo.Notifications 1.0
import "components"
import "pages"
import "cover"

ApplicationWindow {
    id: app

    Daemon {
        id: watchDaemon
        onMessage: {
            if (level === "findphone") {
                pageStack.push(Qt.resolvedUrl("pages/FindPhonePage.qml"), { daemon: watchDaemon })
                app.activate()
                return
            }
            banner.body = text
            banner.previewBody = text
            banner.publish()
        }
    }

    Notification {
        id: banner
        isTransient: true
        appName: "WatchBridge"
        previewSummary: "WatchBridge"
    }

    initialPage: Component { MainPage { daemon: watchDaemon } }
    cover: Component { CoverPage { daemon: watchDaemon } }
    allowedOrientations: defaultAllowedOrientations
}
