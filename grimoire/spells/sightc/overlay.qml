// SightsL overlay window: transparent, click-through, centred, in KDE's overlay layer (above fullscreen games).
import QtQuick
import QtQuick.Window
import org.kde.layershell 1.0 as LayerShell
import Grimoire.SightsL 1.0

Window {
    id: win
    width: 512
    height: 512
    color: "transparent"
    flags: Qt.FramelessWindowHint | Qt.WindowTransparentForInput | Qt.WindowDoesNotAcceptFocus
    visible: false   // shown in onCompleted, after the layer-shell properties are set

    LayerShell.Window.layer: LayerShell.Window.LayerOverlay
    LayerShell.Window.anchors: LayerShell.Window.AnchorNone      // no anchors = centred on the screen
    LayerShell.Window.keyboardInteractivity: LayerShell.Window.KeyboardInteractivityNone
    LayerShell.Window.exclusionZone: -1
    LayerShell.Window.activateOnShow: false
    LayerShell.Window.scope: "grimoire-sightc"

    Crosshair {
        objectName: "crosshair"
        anchors.fill: parent
    }

    Component.onCompleted: win.visible = true
}
