// Grimoire MuraL: image/video wallpaper with crossfading playlists and fullscreen auto-pause.
// Configuration is written by the Grimoire app (see contents/config/main.xml for keys).
import QtQuick
import QtQml
import org.kde.plasma.plasmoid
import org.kde.taskmanager as TaskManager

WallpaperItem {
    id: root

    readonly property var items: {
        try {
            const list = JSON.parse(root.configuration.Items || "[]");
            return Array.isArray(list) ? list : [];
        } catch (e) {
            return [];
        }
    }
    readonly property int fadeMs: Math.max(0, root.configuration.FadeMs)
    readonly property int fillMode: root.configuration.FillMode
    readonly property bool paused: root.configuration.PauseOnFullscreen && fullscreenWatch.blocking

    property int index: -1
    property Layer front: layerA
    property Layer back: layerB

    Rectangle { anchors.fill: parent; color: "black" }

    Layer {
        id: layerA
        anchors.fill: parent
        fillMode: root.fillMode
        muted: root.configuration.Muted
        paused: root.paused
    }
    Layer {
        id: layerB
        anchors.fill: parent
        fillMode: root.fillMode
        muted: root.configuration.Muted
        paused: root.paused
    }

    // Load `url` into the back layer; once it's ready, fade it in on top of the front layer.
    function show(url) {
        if (url === undefined || url === "") return;
        if (front.source.toString() === url && front.opacity === 1) return;
        back.source = url;
        back.z = 1;
        front.z = 0;
        pending = true;
        if (back.ready) reveal();
    }

    property bool pending: false
    Connections {
        target: root.back
        function onReadyChanged() { if (root.pending && root.back.ready) root.reveal(); }
    }

    function reveal() {
        pending = false;
        root.loading = false;           // lets the splash screen finish once something is on screen
        fade.stop();
        fade.target = back;
        fade.start();
    }

    NumberAnimation {
        id: fade
        property: "opacity"
        from: 0
        to: 1
        duration: root.fadeMs
        easing.type: Easing.InOutQuad
        onFinished: {
            const old = root.front;
            root.front = root.back;
            root.back = old;
            old.opacity = 0;
            old.source = "";            // free memory / stop the old video
        }
    }

    function next() {
        if (items.length === 0) return;
        if (items.length === 1) {
            index = 0;
        } else if (root.configuration.Shuffle) {
            let n = index;
            while (n === index) n = Math.floor(Math.random() * items.length);
            index = n;
        } else {
            index = (index + 1) % items.length;
        }
        show(items[index]);
    }

    onItemsChanged: { index = -1; next(); }
    Component.onCompleted: {
        if (items.length > 0) root.loading = true;
        next();
    }

    Timer {
        interval: Math.max(5, root.configuration.Interval) * 1000
        repeat: true
        running: root.items.length > 1 && !root.paused
        onTriggered: root.next()
    }

    // ---- fullscreen / maximized detection (pauses videos + playlist while you game) ----
    TaskManager.VirtualDesktopInfo { id: desktopInfo }
    TaskManager.ActivityInfo { id: activityInfo }

    TaskManager.TasksModel {
        id: tasks
        filterByVirtualDesktop: true
        filterByActivity: true
        filterMinimized: true
        filterHidden: true
        virtualDesktop: desktopInfo.currentDesktop
        activity: activityInfo.currentActivity
    }

    QtObject {
        id: fullscreenWatch
        property int count: 0
        readonly property bool blocking: count > 0
    }

    Instantiator {
        model: tasks
        delegate: QtObject {
            readonly property bool covers: model.IsFullScreen === true || model.IsMaximized === true
            onCoversChanged: fullscreenWatch.count += covers ? 1 : -1
            Component.onCompleted: if (covers) fullscreenWatch.count += 1
            Component.onDestruction: if (covers) fullscreenWatch.count -= 1
        }
    }
}
