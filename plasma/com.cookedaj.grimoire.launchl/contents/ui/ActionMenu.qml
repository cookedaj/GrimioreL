/*
    Right-click menu for an entry: add/remove favorite plus the model's own actions (add to panel/desktop, pin to
    task manager, edit application, jump-list actions, ...). Text only, black & white.

    SPDX-FileCopyrightText: 2026 cookedaj
    SPDX-License-Identifier: GPL-3.0-or-later
*/
import QtQuick
import QtQuick.Controls as QQC2

QQC2.Popup {
    id: menu

    property var actions: []                 // [{text, actionId, actionArgument, type}]
    property int current: -1
    signal picked(var action)

    padding: 5
    modal: false
    focus: true
    closePolicy: QQC2.Popup.CloseOnEscape | QQC2.Popup.CloseOnPressOutside

    background: Rectangle {
        color: "#101010"
        radius: 8
        border.width: 1
        border.color: launchl.ink.edge
    }

    TextMetrics {
        id: metrics
        font.family: launchl.ink.font
        font.pixelSize: 13
    }
    // the widest label decides the width (the rows themselves stretch to the column, so they can't)
    property real widest: 0
    onActionsChanged: {
        let w = 0
        for (const a of actions) {
            metrics.text = (a.text ?? "").replace(/&(?!&)/g, "")
            w = Math.max(w, metrics.advanceWidth)
        }
        widest = w
    }

    contentItem: FocusScope {
        implicitWidth: Math.max(200, Math.min(420, menu.widest + 32))
        implicitHeight: column.implicitHeight
        focus: true

        Keys.onPressed: event => {
            if (event.key === Qt.Key_Down || event.key === Qt.Key_Up) {
                menu.step(event.key === Qt.Key_Down ? 1 : -1)
                event.accepted = true
            } else if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter || event.key === Qt.Key_Space) {
                if (menu.current >= 0) {
                    menu.choose(menu.actions[menu.current])
                }
                event.accepted = true
            }
        }

        Column {
            id: column
            width: parent.width
            Repeater {
                model: menu.actions
                delegate: Item {
                    id: item
                    required property int index
                    required property var modelData
                    readonly property bool line: modelData.type === "separator"
                    readonly property bool title: modelData.type === "title"
                    width: column.width
                    height: line ? 9 : 30

                    Rectangle {
                        visible: item.line
                        anchors.verticalCenter: parent.verticalCenter
                        x: 8
                        width: parent.width - 16
                        height: 1
                        color: launchl.ink.line
                    }
                    Rectangle {
                        visible: !item.line && !item.title
                        anchors.fill: parent
                        radius: 5
                        color: mouse.pressed ? launchl.ink.white : menu.current === item.index ? launchl.ink.current : "transparent"
                    }
                    Text {
                        id: label
                        visible: !item.line
                        anchors.verticalCenter: parent.verticalCenter
                        x: 12
                        width: parent.width - 24
                        text: (item.modelData.text ?? "").replace(/&(?!&)/g, "")
                        elide: Text.ElideRight
                        textFormat: Text.PlainText
                        color: mouse.pressed ? launchl.ink.bg : item.title ? launchl.ink.faint : launchl.ink.text
                        font.family: launchl.ink.font
                        font.pixelSize: item.title ? 11 : 13
                        font.weight: item.title ? Font.DemiBold : Font.Normal
                    }
                    MouseArea {
                        id: mouse
                        anchors.fill: parent
                        enabled: !item.line && !item.title
                        hoverEnabled: true
                        onEntered: menu.current = item.index
                        onClicked: menu.choose(item.modelData)
                    }
                }
            }
        }
    }

    function selectable(i: int): bool {
        const a = actions[i]
        return a && a.type !== "separator" && a.type !== "title"
    }

    function step(dir: int) {
        let i = current
        for (let n = 0; n < actions.length; n++) {
            i = (i + dir + actions.length) % actions.length
            if (selectable(i)) {
                current = i
                return
            }
        }
    }

    function choose(action) {
        close()
        picked(action)
    }

    onOpened: {
        current = -1
        step(1)
    }
}
