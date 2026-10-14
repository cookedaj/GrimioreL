// SPDX-License-Identifier: GPL-3.0-or-later
// One wallpaper layer: shows an image or a looping video. main.qml crossfades two of these.
import QtQuick
import QtMultimedia

Item {
    id: slot

    property url source
    property int fillMode: Image.PreserveAspectCrop   // same numeric values as VideoOutput
    property bool paused: false
    property bool muted: true
    readonly property bool isVideo: /\.(mp4|webm|mkv|mov|m4v|avi|gif)$/i.test(source.toString())
    // true once the content can be shown (so the fade never reveals a blank frame)
    readonly property bool ready: loader.item !== null && loader.item.ready === true

    opacity: 0

    Loader {
        id: loader
        anchors.fill: parent
        active: slot.source.toString() !== ""
        sourceComponent: slot.isVideo ? videoComponent : imageComponent
    }

    Component {
        id: imageComponent
        Image {
            readonly property bool ready: status === Image.Ready
            source: slot.source
            fillMode: slot.fillMode
            asynchronous: true
            cache: false
            smooth: true
            sourceSize: Qt.size(slot.width * Screen.devicePixelRatio, slot.height * Screen.devicePixelRatio)
        }
    }

    Component {
        id: videoComponent
        Video {
            id: video
            readonly property bool ready: playbackState === MediaPlayer.PlayingState || position > 0
            source: slot.source
            fillMode: slot.fillMode
            loops: MediaPlayer.Infinite
            muted: slot.muted
            autoPlay: !slot.paused
            onSourceChanged: if (!slot.paused) play()

            Connections {
                target: slot
                function onPausedChanged() { slot.paused ? video.pause() : video.play() }
            }
        }
    }
}
