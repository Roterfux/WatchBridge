// WatchBridge - SPDX-License-Identifier: AGPL-3.0-or-later
// Choose a watch-face file. Unlike Sailfish's own file picker, it opens in the folder used last time
// and keeps the sort order (stored with Nemo.Configuration).
import QtQuick 2.0
import Sailfish.Silica 1.0
import Nemo.FileManager 1.0
import Nemo.Configuration 1.0

Page {
    id: page

    // The chosen file; the page pops itself afterwards, like FilePickerPage
    signal picked(string path)

    ConfigurationValue {
        id: lastFolder
        key: "/apps/harbour-watchbridge/facePicker/folder"
        defaultValue: StandardPaths.download
    }
    ConfigurationValue {
        id: sortKey
        key: "/apps/harbour-watchbridge/facePicker/sortBy"
        defaultValue: FileModel.SortByName
    }
    ConfigurationValue {
        id: sortDescending
        key: "/apps/harbour-watchbridge/facePicker/descending"
        defaultValue: false
    }

    function open(folder) {
        files.path = folder
        lastFolder.value = folder
    }
    function sortName(key) {
        return key === FileModel.SortByModified ? qsTr("date")
             : key === FileModel.SortBySize ? qsTr("size")
             : qsTr("name")
    }

    FileModel {
        id: files
        path: lastFolder.value
        active: page.status === PageStatus.Active
        includeDirectories: true
        directorySort: FileModel.SortDirectoriesBeforeFiles
        nameFilters: ["*.hwt", "*.hwf", "*.zip"]
        caseSensitivity: Qt.CaseInsensitive
        sortBy: sortKey.value
        sortOrder: sortDescending.value ? Qt.DescendingOrder : Qt.AscendingOrder
        // The folder used last time may be gone (deleted, SD card removed): start at home instead
        onPopulatedChanged: if (populated && errorType !== FileModel.NoError) page.open(StandardPaths.home)
    }

    SilicaListView {
        id: list
        anchors.fill: parent
        model: files

        header: PageHeader {
            title: files.directoryName || "/"
            description: files.absolutePath
        }

        PullDownMenu {
            MenuItem {
                text: qsTr("Home folder")
                onClicked: page.open(StandardPaths.home)
            }
            MenuItem {
                text: qsTr("Up to %1").arg(files.parentDirectoryName || "/")
                visible: files.absolutePath !== "/" && files.absolutePath !== ""
                onClicked: page.open(files.parentPath())
            }
            // The sort keys not in use, then turning the order around
            Repeater {
                model: [FileModel.SortByName, FileModel.SortByModified, FileModel.SortBySize]
                MenuItem {
                    visible: modelData !== sortKey.value
                    text: qsTr("Sort by %1").arg(page.sortName(modelData))
                    onClicked: {
                        sortKey.value = modelData
                        // Newest first is what one usually wants by date
                        sortDescending.value = modelData === FileModel.SortByModified
                    }
                }
            }
            MenuItem {
                text: sortDescending.value ? qsTr("Sort ascending") : qsTr("Sort descending")
                onClicked: sortDescending.value = !sortDescending.value
            }
        }

        delegate: ListItem {
            id: item
            contentHeight: Theme.itemSizeMedium
            onClicked: {
                if (model.isDir) {
                    page.open(model.absolutePath)
                } else {
                    page.picked(model.absolutePath)
                    pageStack.pop()
                }
            }

            Icon {
                id: icon
                x: Theme.horizontalPageMargin
                anchors.verticalCenter: parent.verticalCenter
                source: model.isDir ? "image://theme/icon-m-file-folder" : "image://theme/icon-m-file-other"
            }
            Column {
                anchors { left: icon.right; leftMargin: Theme.paddingMedium; right: parent.right
                          rightMargin: Theme.horizontalPageMargin; verticalCenter: parent.verticalCenter }
                Label {
                    width: parent.width
                    truncationMode: TruncationMode.Fade
                    text: model.fileName
                    color: item.highlighted ? Theme.highlightColor : Theme.primaryColor
                }
                Label {
                    width: parent.width
                    truncationMode: TruncationMode.Fade
                    font.pixelSize: Theme.fontSizeExtraSmall
                    color: Theme.secondaryColor
                    text: model.isDir ? Format.formatDate(model.modified, Formatter.DateMedium)
                                      : Format.formatFileSize(model.size) + " · "
                                        + Format.formatDate(model.modified, Formatter.DateMedium)
                }
            }
        }

        ViewPlaceholder {
            enabled: files.populated && files.count === 0
            text: qsTr("No watch faces here")
            hintText: qsTr("Watch faces are .hwt files. Pull down to go to another folder.")
        }
        VerticalScrollDecorator {}
    }
}
