import QtQuick

Column {
    id: clock
    property real size: 72
    property int align: Text.AlignHCenter
    property bool use24: false
    property date now: new Date()
    spacing: size * 0.06

    Timer { interval: 1000; running: true; repeat: true; onTriggered: clock.now = new Date() }

    Text {
        width: parent.width
        horizontalAlignment: clock.align
        text: Qt.formatTime(clock.now, clock.use24 ? "HH:mm" : "h:mm")
        color: "white"
        font.family: "IBM Plex Sans"; font.weight: Font.Light; font.pixelSize: clock.size
    }
    Text {
        width: parent.width
        horizontalAlignment: clock.align
        text: Qt.formatDate(clock.now, "dddd, MMMM d")
        color: "#b0b0b0"
        font.family: "IBM Plex Sans"; font.pixelSize: Math.max(13, clock.size * 0.2)
    }
}
