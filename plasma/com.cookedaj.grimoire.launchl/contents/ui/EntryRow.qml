/*
    One row in LaunchL's lists: icon, name, an optional muted second line. Gray when it's the current row,
    white with black text while pressed.

    SPDX-FileCopyrightText: 2026 cookedaj
    SPDX-License-Identifier: GPL-2.0-or-later
*/
import QtQuick
import QtQuick.Layouts
import org.kde.kirigami as Kirigami

Item {
    id: row

    property var icon
    property bool maskIcon: false            // Grimoire's own entries: line glyphs drawn in white
    property string title
    property string subtitle
    property bool isCurrent: false
    property bool outlined: false            // keyboard focus: an edge around the current row
    property bool badge: false               // newly installed app
    readonly property alias hovered: mouse.containsMouse

    signal clicked()
    signal rightClicked(real x, real y)
    signal entered()

    implicitHeight: subtitle !== "" ? 50 : 40

    Rectangle {
        anchors.fill: parent
        anchors.leftMargin: 6
        anchors.rightMargin: 6
        anchors.topMargin: 1
        anchors.bottomMargin: 1
        radius: 7
        color: mouse.pressed && mouse.pressedButtons & Qt.LeftButton ? launchl.ink.white
             : row.isCurrent ? launchl.ink.current
             : mouse.containsMouse ? launchl.ink.hover : "transparent"
        border.width: 1
        border.color: row.isCurrent && row.outlined ? launchl.ink.edge : "transparent"
    }

    RowLayout {
        anchors.fill: parent
        anchors.leftMargin: 16
        anchors.rightMargin: 16
        spacing: 12

        Kirigami.Icon {
            Layout.preferredWidth: row.subtitle !== "" ? 32 : 26
            Layout.preferredHeight: Layout.preferredWidth
            source: row.icon
            isMask: row.maskIcon
            color: mouse.pressed ? launchl.ink.bg : launchl.ink.text
            animated: false
        }

        ColumnLayout {
            Layout.fillWidth: true
            spacing: 1
            Text {
                Layout.fillWidth: true
                text: row.title
                elide: Text.ElideRight
                textFormat: Text.PlainText
                color: mouse.pressed ? launchl.ink.bg : launchl.ink.text
                font.family: launchl.ink.font
                font.pixelSize: 14
            }
            Text {
                Layout.fillWidth: true
                visible: row.subtitle !== ""
                text: row.subtitle
                elide: Text.ElideMiddle
                textFormat: Text.PlainText
                color: mouse.pressed ? "#333333" : launchl.ink.muted
                font.family: launchl.ink.font
                font.pixelSize: 12
            }
        }

        Rectangle {
            visible: row.badge
            Layout.preferredWidth: 6
            Layout.preferredHeight: 6
            radius: 3
            color: launchl.ink.white
        }
    }

    MouseArea {
        id: mouse
        anchors.fill: parent
        hoverEnabled: true
        acceptedButtons: Qt.LeftButton | Qt.RightButton
        onEntered: row.entered()
        onPositionChanged: row.entered()
        onClicked: m => {
            if (m.button === Qt.RightButton) {
                row.rightClicked(m.x, m.y)
            } else {
                row.clicked()
            }
        }
    }
}
