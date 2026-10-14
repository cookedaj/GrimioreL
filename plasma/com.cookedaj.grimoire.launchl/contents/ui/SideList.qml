/*
    The left column: Favorites, All Applications and the app categories (or the Places groups). Text only, the
    picked one in white with a white bar, the rest gray.

    SPDX-FileCopyrightText: 2026 cookedaj
    SPDX-License-Identifier: GPL-3.0-or-later
*/
import QtQuick
import QtQuick.Controls as QQC2

ListView {
    id: side

    property bool focused: false             // the keyboard is on this column

    clip: true
    focus: false
    keyNavigationEnabled: false
    boundsBehavior: Flickable.StopAtBounds
    topMargin: 8
    bottomMargin: 8
    currentIndex: 0

    delegate: Item {
        id: cat
        required property int index
        required property var model
        readonly property bool separator: model.isSeparator === true
        readonly property bool picked: ListView.isCurrentItem
        width: ListView.view.width
        height: separator ? 11 : 34

        Rectangle {
            visible: cat.separator
            anchors.verticalCenter: parent.verticalCenter
            x: 18
            width: parent.width - 36
            height: 1
            color: launchl.ink.line
        }

        Rectangle {
            visible: !cat.separator
            anchors.fill: parent
            anchors.leftMargin: 8
            anchors.rightMargin: 8
            radius: 7
            color: cat.picked && side.focused ? launchl.ink.current : mouse.containsMouse ? launchl.ink.hover : "transparent"
            border.width: 1
            border.color: cat.picked && side.focused ? launchl.ink.edge : "transparent"
        }

        Rectangle {
            visible: cat.picked && !cat.separator
            x: 8
            anchors.verticalCenter: parent.verticalCenter
            width: 2
            height: 16
            radius: 1
            color: launchl.ink.white
        }

        Text {
            visible: !cat.separator
            anchors.verticalCenter: parent.verticalCenter
            x: 20
            width: parent.width - 34
            text: cat.model.display ?? ""
            elide: Text.ElideRight
            textFormat: Text.PlainText
            color: cat.picked ? launchl.ink.white : mouse.containsMouse ? launchl.ink.text : launchl.ink.muted
            font.family: launchl.ink.font
            font.pixelSize: 13
            font.weight: cat.picked ? Font.DemiBold : Font.Normal
        }

        Rectangle {                          // a newly installed app inside
            visible: cat.model.isNewlyInstalled === true
            anchors.verticalCenter: parent.verticalCenter
            anchors.right: parent.right
            anchors.rightMargin: 18
            width: 5
            height: 5
            radius: 2.5
            color: launchl.ink.muted
        }

        MouseArea {
            id: mouse
            anchors.fill: parent
            enabled: !cat.separator
            hoverEnabled: true
            onClicked: side.currentIndex = cat.index
        }
    }

    QQC2.ScrollBar.vertical: QQC2.ScrollBar {
        policy: side.contentHeight > side.height ? QQC2.ScrollBar.AsNeeded : QQC2.ScrollBar.AlwaysOff
        width: 6
        contentItem: Rectangle { implicitWidth: 2; radius: 1; color: launchl.ink.edge }
        background: null
    }

    function isSeparator(i: int): bool {
        const item = itemAtIndex(i)
        return item !== null && item.separator === true
    }

    function move(step: int) {
        let i = currentIndex + step
        while (i >= 0 && i < count && isSeparator(i)) {
            i += step
        }
        if (i >= 0 && i < count) {
            currentIndex = i
            positionViewAtIndex(i, ListView.Contain)
        }
    }
}
