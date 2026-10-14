/*
    The leave buttons, bottom right: a power button that slides open into Lock, Log out, Sleep, Restart and
    Shut down while hovered (like Kickoff's Leave). They run through Plasma's session model, so the usual
    confirmations and availability (no Sleep where it can't) apply.

    SPDX-FileCopyrightText: 2026 cookedaj
    SPDX-License-Identifier: GPL-2.0-or-later
*/
import QtQuick
import QtQuick.Layouts
import org.kde.kirigami as Kirigami
import org.kde.kitemmodels as KItemModels
import org.kde.plasma.private.kicker as Kicker

Item {
    id: leave

    readonly property var buttons: [
        { id: "lock-screen", label: i18n("Lock"), icon: "system-lock-screen-symbolic" },
        { id: "logout", label: i18n("Log out"), icon: "system-log-out-symbolic" },
        { id: "suspend", label: i18n("Sleep"), icon: "system-suspend-symbolic" },
        { id: "reboot", label: i18n("Restart"), icon: "system-reboot-symbolic" },
        { id: "shutdown", label: i18n("Shut down"), icon: "system-shutdown-symbolic" },
    ]
    property bool stuck: false               // clicked open (touch, or to keep it open)
    readonly property bool open: hover.hovered || closing.running || stuck
    signal done()

    implicitHeight: 34

    // Lives in the popup, created after rootModel.refresh() (as Kickoff does): made earlier, in main.qml, it
    // crashed in the kicker plugin when the session-management state arrived before the favorites model existed
    Kicker.SystemModel {
        id: systemModel
        favoritesModel: launchl.rootModel.systemFavoritesModel
        // what's available (Sleep, Restart, ...) arrives asynchronously from the session manager
        onModelReset: leave.revision++
        onRowsInserted: leave.revision++
        onRowsRemoved: leave.revision++
        onDataChanged: leave.revision++
    }
    property int revision: 0
    implicitWidth: open ? row.implicitWidth : power.width

    Behavior on implicitWidth {
        NumberAnimation { duration: Kirigami.Units.longDuration; easing.type: Easing.OutCubic }
    }

    HoverHandler { id: hover }
    Timer {                                  // let the pointer wander off for a moment before it folds away
        id: closing
        interval: 450
    }
    Connections {
        target: hover
        function onHoveredChanged() {
            if (!hover.hovered) {
                closing.restart()
            }
        }
    }

    // row of the session model whose favoriteId is id, -1 if this system doesn't offer it
    function rowFor(id: string): int {
        const m = systemModel
        const role = m.KItemModels.KRoleNames.role("favoriteId")
        for (let i = 0; i < m.count; i++) {
            if (m.data(m.index(i, 0), role) === id) {
                return i
            }
        }
        return -1
    }

    function run(id: string) {
        const r = rowFor(id)
        if (r >= 0) {
            systemModel.trigger(r, "", null)
            done()
        }
    }

    clip: true

    RowLayout {
        id: row
        anchors.right: parent.right
        anchors.verticalCenter: parent.verticalCenter
        spacing: 2

        Repeater {
            model: leave.buttons
            delegate: Rectangle {
                id: b
                required property var modelData
                readonly property bool available: leave.revision >= 0 && leave.rowFor(modelData.id) >= 0
                visible: available
                Layout.preferredHeight: 34
                Layout.preferredWidth: label.implicitWidth + 44
                radius: 7
                opacity: leave.open ? 1 : 0
                color: m.pressed ? launchl.ink.white : m.containsMouse ? launchl.ink.current : "transparent"
                Behavior on opacity { NumberAnimation { duration: Kirigami.Units.shortDuration } }
                Kirigami.Icon {
                    anchors.verticalCenter: parent.verticalCenter
                    x: 10
                    width: 16
                    height: 16
                    source: b.modelData.icon
                    isMask: true
                    color: m.pressed ? launchl.ink.bg : launchl.ink.text
                }
                Text {
                    id: label
                    anchors.verticalCenter: parent.verticalCenter
                    x: 32
                    text: b.modelData.label
                    color: m.pressed ? launchl.ink.bg : launchl.ink.text
                    font.family: launchl.ink.font
                    font.pixelSize: 13
                }
                MouseArea {
                    id: m
                    anchors.fill: parent
                    hoverEnabled: true
                    onClicked: leave.run(b.modelData.id)
                }
            }
        }

        Rectangle {
            id: power
            Layout.preferredWidth: 34
            Layout.preferredHeight: 34
            radius: 17
            color: leave.open ? launchl.ink.current : "transparent"
            border.width: 1
            border.color: leave.open ? launchl.ink.edge : launchl.ink.line
            Kirigami.Icon {
                anchors.centerIn: parent
                width: 16
                height: 16
                source: "system-shutdown-symbolic"
                isMask: true
                color: launchl.ink.text
            }
            Accessible.name: i18n("Leave")
            Accessible.role: Accessible.Button
            MouseArea {
                anchors.fill: parent
                onClicked: leave.stuck = !leave.stuck
            }
        }
    }
}
