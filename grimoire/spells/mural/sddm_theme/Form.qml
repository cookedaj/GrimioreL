// Username + password line. Enter logs in; a wrong password shakes the line.
import QtQuick

Column {
    id: form
    property int fieldWidth: 300
    property int align: Text.AlignHCenter
    property string user: userModel.lastUser !== "" ? userModel.lastUser : ""
    spacing: 14
    width: fieldWidth

    Text {
        width: parent.width
        horizontalAlignment: form.align
        text: form.user !== "" ? form.user.toUpperCase() : "LOG IN"
        color: "#9a9a9a"
        font.family: "IBM Plex Sans"; font.pixelSize: 12; font.letterSpacing: 5
    }

    Item {
        id: userBox
        visible: form.user === ""
        width: parent.width; height: visible ? 40 : 0
        TextInput {
            id: userInput
            anchors.fill: parent
            verticalAlignment: TextInput.AlignVCenter
            horizontalAlignment: form.align === Text.AlignHCenter ? TextInput.AlignHCenter : TextInput.AlignLeft
            color: "white"; font.family: "IBM Plex Sans"; font.pixelSize: 16
            KeyNavigation.tab: pw
        }
        Text {
            anchors.fill: parent; verticalAlignment: Text.AlignVCenter; horizontalAlignment: form.align
            visible: userInput.text === ""; text: "Username"; color: "#5a5a5a"
            font.family: "IBM Plex Sans"; font.pixelSize: 16
        }
        Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: "#5a5a5a" }
    }

    Item {
        id: line
        width: parent.width; height: 40
        TextInput {
            id: pw
            anchors.fill: parent
            verticalAlignment: TextInput.AlignVCenter
            horizontalAlignment: form.align === Text.AlignHCenter ? TextInput.AlignHCenter : TextInput.AlignLeft
            echoMode: TextInput.Password
            passwordCharacter: "•"
            color: "white"; font.family: "IBM Plex Sans"; font.pixelSize: 18; font.letterSpacing: 4
            focus: true
            onAccepted: form.submit()
        }
        Text {
            anchors.fill: parent; verticalAlignment: Text.AlignVCenter; horizontalAlignment: form.align
            visible: pw.text === ""
            text: keyboard.capsLock ? "Password  ·  Caps Lock is on" : "Password"
            color: "#5a5a5a"; font.family: "IBM Plex Sans"; font.pixelSize: 16
        }
        Rectangle {
            anchors.bottom: parent.bottom; width: parent.width; height: 1
            color: pw.activeFocus ? "white" : "#6a6a6a"
            Behavior on color { ColorAnimation { duration: 200 } }
        }
        SequentialAnimation {
            id: shake
            loops: 2
            NumberAnimation { target: line; property: "x"; to: -8; duration: 50 }
            NumberAnimation { target: line; property: "x"; to: 8; duration: 50 }
            NumberAnimation { target: line; property: "x"; to: 0; duration: 50 }
        }
    }

    Text {
        id: message
        width: parent.width
        horizontalAlignment: form.align
        color: "#9a9a9a"; font.family: "IBM Plex Sans"; font.pixelSize: 12
        text: ""
    }

    function submit() {
        const name = form.user !== "" ? form.user : userInput.text;
        message.text = "";
        sddm.login(name, pw.text, sessionModel.lastIndex);
    }

    Connections {
        target: sddm
        function onLoginFailed() {
            pw.text = "";
            message.text = "Wrong password";
            shake.start();
            pw.forceActiveFocus();
        }
    }
}
