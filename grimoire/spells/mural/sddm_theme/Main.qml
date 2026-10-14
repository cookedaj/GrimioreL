// SPDX-License-Identifier: GPL-3.0-or-later
// Grimoire login (SDDM). Layout and look come from theme.conf, written by Grimoire → MuraL → Login.
import QtQuick

Rectangle {
    id: root
    width: 1920; height: 1080
    color: "black"

    readonly property real dim: Number(config.dim || 55) / 100
    readonly property bool use24: String(config.clock24) === "true"
    readonly property bool showPower: String(config.showPower) !== "false"
    readonly property real u: Math.min(width / 1920, height / 1080)     // scale unit

    Image {
        id: bg
        anchors.fill: parent
        source: config.background ? Qt.resolvedUrl(config.background) : ""
        fillMode: Image.PreserveAspectCrop
        asynchronous: false
    }
    Rectangle { anchors.fill: parent; color: "black"; opacity: root.dim }

    // card layout: small clock top-left, a dark floating card with the clover and login, power row below
    Clock { x: 72 * root.u; y: 56 * root.u; width: 400 * root.u; size: 44 * root.u
            align: Text.AlignLeft; use24: root.use24 }
    Rectangle {
        anchors.centerIn: parent
        width: 420 * root.u; height: 380 * root.u
        radius: 18 * root.u
        color: Qt.rgba(0.03, 0.03, 0.03, 0.82)
        border.color: "#2e2e2e"; border.width: 1
        Column {
            anchors.centerIn: parent
            spacing: 40 * root.u
            Image { anchors.horizontalCenter: parent.horizontalCenter; source: "clover5.svg"
                    sourceSize: Qt.size(64 * root.u, 64 * root.u) }
            Form { fieldWidth: 300 * root.u }
        }
    }
    Power { visible: root.showPower; anchors.horizontalCenter: parent.horizontalCenter
            anchors.bottom: parent.bottom; anchors.bottomMargin: 48 * root.u }
}
