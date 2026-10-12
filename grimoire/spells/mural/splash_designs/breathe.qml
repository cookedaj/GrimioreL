import QtQuick

Rectangle {
    id: root
    color: "black"
    property int stage
    readonly property real progress: Math.min(stage, 6) / 6
    readonly property real speed: @SPEED@

    Item {
        id: content
        anchors.fill: parent
        opacity: 0

        Image {
            id: clover
            anchors.centerIn: parent
            anchors.verticalCenterOffset: -40
            source: "images/clover5.svg"
            sourceSize: Qt.size(112, 112)
            SequentialAnimation on scale {
                loops: Animation.Infinite
                NumberAnimation { from: 1.0; to: 1.05; duration: 1400 / root.speed; easing.type: Easing.InOutSine }
                NumberAnimation { from: 1.05; to: 1.0; duration: 1400 / root.speed; easing.type: Easing.InOutSine }
            }
        }
        Rectangle {
            id: track
            width: 220; height: 1; color: "#2a2a2a"
            anchors.horizontalCenter: parent.horizontalCenter
            anchors.top: clover.bottom; anchors.topMargin: 56
            Rectangle {
                height: 1; color: "white"
                width: track.width * root.progress
                Behavior on width { NumberAnimation { duration: 600 / root.speed; easing.type: Easing.OutCubic } }
            }
        }
        Text {
            visible: @SHOW_TAGLINE@
            anchors.horizontalCenter: parent.horizontalCenter
            anchors.top: track.bottom; anchors.topMargin: 22
            text: @TAGLINE@
            color: "#8c8c8c"
            font.family: "IBM Plex Sans"; font.pixelSize: 12; font.letterSpacing: 6
        }
    }
    onStageChanged: if (stage >= 6) fadeOut.start()
    Component.onCompleted: fadeIn.start()
    OpacityAnimator { id: fadeIn; target: content; from: 0; to: 1; duration: 700 / root.speed }
    OpacityAnimator { id: fadeOut; target: content; from: 1; to: 0; duration: 500 / root.speed }
}
