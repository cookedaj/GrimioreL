// SPDX-License-Identifier: GPL-3.0-or-later
// SightsL overlay window: transparent, click-through, centred, in KDE's overlay layer (above fullscreen games).
// overlay.py sizes it to fit the crosshair, picks the screen (targetScreen) and flips `shown` on the hotkey.
import QtQuick
import QtQuick.Window
import org.kde.layershell 1.0 as LayerShell
import Grimoire.SightsL 1.0

Window {
    id: win
    width: 128
    height: 128
    color: "transparent"
    flags: Qt.FramelessWindowHint | Qt.WindowTransparentForInput | Qt.WindowDoesNotAcceptFocus
    visible: false   // shown once overlay.py set size and screen, after the layer-shell properties are set

    property bool ready: false
    property bool shown: true
    property var targetScreen: null

    LayerShell.Window.layer: LayerShell.Window.LayerOverlay
    LayerShell.Window.anchors: LayerShell.Window.AnchorNone      // no anchors = centred on the screen
    LayerShell.Window.keyboardInteractivity: LayerShell.Window.KeyboardInteractivityNone
    LayerShell.Window.exclusionZone: -1
    LayerShell.Window.activateOnShow: false
    LayerShell.Window.scope: "grimoire-sightc"

    function place() {
        if (!ready || !targetScreen)
            return
        // a layer surface is bound to its output when mapped, so moving screens means re-mapping it
        win.visible = false
        win.screen = targetScreen
        LayerShell.Window.screen = targetScreen
        win.visible = true
    }
    onReadyChanged: place()
    onTargetScreenChanged: place()

    Crosshair {
        objectName: "crosshair"
        anchors.fill: parent
        opacity: win.shown ? 1 : 0
        Behavior on opacity { NumberAnimation { duration: 110; easing.type: Easing.OutQuad } }
    }
}
