// SPDX-License-Identifier: GPL-3.0-or-later
import QtQuick

Row {
    spacing: 28
    Repeater {
        model: [
            { label: "Sleep", ok: sddm.canSuspend, act: function () { sddm.suspend() } },
            { label: "Restart", ok: sddm.canReboot, act: function () { sddm.reboot() } },
            { label: "Shut down", ok: sddm.canPowerOff, act: function () { sddm.powerOff() } }
        ]
        Text {
            required property var modelData
            visible: modelData.ok
            text: modelData.label.toUpperCase()
            color: hover.hovered ? "white" : "#7a7a7a"
            font.family: "IBM Plex Sans"; font.pixelSize: 11; font.letterSpacing: 3
            HoverHandler { id: hover }
            TapHandler { onTapped: modelData.act() }
        }
    }
}
