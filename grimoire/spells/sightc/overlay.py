"""SightsL overlay process: draws the crosshair above everything and redraws when sightc.json changes.

    python3 -m grimoire.spells.sightc.overlay [run|on|off|toggle|status]

run     start the overlay in this process (used by `on`)
on/off  start / stop the background overlay
"""
import os
import signal
import subprocess
import sys
from pathlib import Path

from grimoire.paths import CACHE, CONFIG
from grimoire.spells.sightc.config import FILE, Crosshair

PID = CACHE / "sightc.pid"


# ---------------------------------------------------------------- process control
def running_pid() -> int | None:
    try:
        pid = int(PID.read_text())
        cmd = Path(f"/proc/{pid}/cmdline").read_bytes()
    except (OSError, ValueError):
        return None
    return pid if b"grimoire.spells.sightc.overlay" in cmd else None


def start():
    if running_pid():
        return
    repo = Path(__file__).resolve().parents[3]
    env = dict(os.environ, PYTHONPATH=f"{repo}:{os.environ.get('PYTHONPATH', '')}".rstrip(":"))
    with open(CACHE / "sightc.log", "w") as log:          # the child keeps its own copy of the handle
        subprocess.Popen([sys.executable, "-m", "grimoire.spells.sightc.overlay", "run"], env=env,
                         stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, start_new_session=True)


def stop():
    pid = running_pid()
    if pid:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:                         # it exited on its own just now
            pass
    PID.unlink(missing_ok=True)


# ---------------------------------------------------------------- global hotkey (KDE kglobalaccel)
COMPONENT, ACTION = "grimoire-sightc", "toggle-crosshair"
ACTION_ID = [COMPONENT, ACTION, "Grimoire SightsL", "Show/hide crosshair"]
DEFAULT_KEY = 0x04000000 | 0x08000000 | 0x58     # Qt: Ctrl + Alt + X


def register_hotkey(callback):
    """Register Ctrl+Alt+X with KDE (rebindable in System Settings → Shortcuts) and call
    `callback` when pressed. Returns the receiver object (keep a reference), or None."""
    from PySide6.QtCore import SLOT, QObject, Slot
    from PySide6.QtDBus import QDBusConnection

    base = ["busctl", "--user", "call", "org.kde.kglobalaccel", "/kglobalaccel", "org.kde.KGlobalAccel"]
    try:
        subprocess.run(base + ["doRegister", "as", "4", *ACTION_ID], check=True, capture_output=True)
        # flags 0x1 IsDefault | 0x2 SetPresent: default key, but a key you rebind in Settings wins
        subprocess.run(base + ["setShortcut", "asaiu", "4", *ACTION_ID, "1", str(DEFAULT_KEY), "3"],
                       check=True, capture_output=True)
    except (OSError, subprocess.CalledProcessError) as e:
        print("SightsL: couldn't register hotkey:", e, file=sys.stderr)
        return None

    class Receiver(QObject):
        @Slot(str, str, "qlonglong")
        def pressed(self, component, action, _timestamp):
            if component == COMPONENT and action == ACTION:
                callback()

    receiver = Receiver()
    path = "/component/" + "".join(ch if ch.isalnum() else "_" for ch in COMPONENT)
    ok = QDBusConnection.sessionBus().connect("org.kde.kglobalaccel", path, "org.kde.kglobalaccel.Component",
                                              "globalShortcutPressed", receiver,
                                              SLOT("pressed(QString,QString,qlonglong)"))
    if not ok:
        print("SightsL: couldn't listen for hotkey on", path, file=sys.stderr)
    return receiver


# ---------------------------------------------------------------- the overlay itself
def run():
    from PySide6.QtCore import QFileSystemWatcher, QTimer, QUrl
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtQml import QQmlApplicationEngine, qmlRegisterType
    from PySide6.QtQuick import QQuickPaintedItem

    from grimoire.spells.sightc import draw

    class CrosshairItem(QQuickPaintedItem):
        def __init__(self, parent=None):
            super().__init__(parent)
            self.cfg = Crosshair.load()
            self.setAntialiasing(True)

        def reload(self):
            self.cfg = Crosshair.load()
            self.update()

        def paint(self, painter):
            draw.paint(painter, self.cfg, self.width() / 2, self.height() / 2)

    app = QGuiApplication(sys.argv)
    app.setApplicationName("grimoire-sightc")
    app.setDesktopFileName("grimoire")
    qmlRegisterType(CrosshairItem, "Grimoire.SightsL", 1, 0, "Crosshair")
    engine = QQmlApplicationEngine()
    engine.load(QUrl.fromLocalFile(str(Path(__file__).with_name("overlay.qml"))))
    if not engine.rootObjects():
        sys.exit("SightsL: failed to load overlay.qml")
    item = engine.rootObjects()[0].findChild(CrosshairItem, "crosshair")

    # sightc.json is replaced atomically, so watch the folder rather than the file
    watcher = QFileSystemWatcher([str(CONFIG)])
    watcher.directoryChanged.connect(lambda _: item.reload())
    _hotkey = register_hotkey(lambda: item.setVisible(not item.isVisible()))   # keep a reference alive

    PID.write_text(str(os.getpid()))
    signal.signal(signal.SIGTERM, lambda *_: app.quit())
    signal.signal(signal.SIGINT, lambda *_: app.quit())
    keepalive = QTimer()            # lets Python handle signals while Qt's loop runs
    keepalive.start(250)
    keepalive.timeout.connect(lambda: None)
    code = app.exec()
    if running_pid() == os.getpid():
        PID.unlink(missing_ok=True)
    sys.exit(code)


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "toggle"
    if cmd == "run":
        if not FILE.exists():
            Crosshair().save()
        run()
    elif cmd == "on":
        start()
    elif cmd == "off":
        stop()
    elif cmd == "toggle":
        stop() if running_pid() else start()
    elif cmd == "status":
        print("on" if running_pid() else "off")
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
