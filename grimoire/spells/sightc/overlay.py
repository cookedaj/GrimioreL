"""SightsL overlay process: draws the crosshair above everything and redraws when sightc.json changes.

    python3 -m grimoire.spells.sightc.overlay [run|on|off|toggle|status]

run     start the overlay in this process (used by `on`)
on/off  start / stop the background overlay
next    switch to the next saved crosshair (also Ctrl+Alt+Shift+X)
"""
import fcntl
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


def _write_pid(pid: int):
    tmp = PID.with_suffix(".tmp")
    tmp.write_text(str(pid))
    tmp.replace(PID)                                       # atomic: running_pid() never reads half a number


def start():
    """Start the background overlay unless one is running. The pid is written here, straight from Popen, not
    once the overlay has loaded: a quick second click (or the tray, or `on`) then sees it and doesn't start a
    second overlay that `off` couldn't reach. The lock makes check-and-start atomic across processes."""
    with open(CACHE / "sightc.lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if running_pid():
            return
        repo = Path(__file__).resolve().parents[3]
        env = dict(os.environ, PYTHONPATH=f"{repo}:{os.environ.get('PYTHONPATH', '')}".rstrip(":"))
        with open(CACHE / "sightc.log", "w") as log:      # the child keeps its own copy of the handle
            proc = subprocess.Popen([sys.executable, "-m", "grimoire.spells.sightc.overlay", "run"], env=env,
                                    stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                    start_new_session=True)
        _write_pid(proc.pid)


def stop():
    pid = running_pid()
    if pid:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:                         # it exited on its own just now
            pass
    PID.unlink(missing_ok=True)


# ---------------------------------------------------------------- global hotkeys (KDE kglobalaccel)
COMPONENT, ACTION, NEXT_ACTION = "grimoire-sightc", "toggle-crosshair", "next-crosshair"
CTRL, ALT, SHIFT = 0x04000000, 0x08000000, 0x02000000
HOTKEYS = {   # action -> (friendly name, default key as a Qt key code)
    ACTION: ("Show/hide crosshair", CTRL | ALT | 0x58),                 # Ctrl+Alt+X
    NEXT_ACTION: ("Next crosshair", CTRL | ALT | SHIFT | 0x58),         # Ctrl+Alt+Shift+X
}
KGA = ["busctl", "--user", "call", "org.kde.kglobalaccel", "/kglobalaccel", "org.kde.KGlobalAccel"]


def _action_id(action: str) -> list[str]:
    return [COMPONENT, action, "Grimoire SightsL", HOTKEYS[action][0]]


def hotkey_text(action: str = ACTION) -> str:
    """The key currently bound in KDE (it may have been rebound in System Settings), e.g. "Ctrl+Alt+X"."""
    from PySide6.QtGui import QKeySequence
    key = HOTKEYS[action][1]
    try:
        out = subprocess.run(KGA + ["shortcut", "as", "4", *_action_id(action)], capture_output=True, text=True,
                             timeout=2).stdout.split()        # "ai 1 201326680" (or "ai 0" when unbound)
        if len(out) >= 2 and out[0] == "ai":
            if out[1] != "0":           # 0 keys: not registered yet (overlay never ran), so the default applies
                key = int(out[2])
    except (OSError, ValueError, IndexError, subprocess.SubprocessError):
        pass
    return QKeySequence(key).toString(QKeySequence.SequenceFormat.NativeText)


def register_hotkeys(callbacks: dict):
    """Register the SightsL shortcuts with KDE (rebindable in System Settings → Shortcuts) and call
    callbacks[action] when one is pressed. Returns the receiver object (keep a reference), or None."""
    from PySide6.QtCore import SLOT, QObject, Slot
    from PySide6.QtDBus import QDBusConnection

    try:
        for action in callbacks:
            subprocess.run(KGA + ["doRegister", "as", "4", *_action_id(action)], check=True, capture_output=True)
            # flags 0x1 IsDefault | 0x2 SetPresent: default key, but a key you rebind in Settings wins
            subprocess.run(KGA + ["setShortcut", "asaiu", "4", *_action_id(action), "1", str(HOTKEYS[action][1]),
                                  "3"], check=True, capture_output=True)
    except (OSError, subprocess.CalledProcessError) as e:
        print("SightsL: couldn't register hotkeys:", e, file=sys.stderr)
        return None

    class Receiver(QObject):
        @Slot(str, str, "qlonglong")
        def pressed(self, component, action, _timestamp):
            if component == COMPONENT and action in callbacks:
                callbacks[action]()

    receiver = Receiver()
    path = "/component/" + "".join(ch if ch.isalnum() else "_" for ch in COMPONENT)
    ok = QDBusConnection.sessionBus().connect("org.kde.kglobalaccel", path, "org.kde.kglobalaccel.Component",
                                              "globalShortcutPressed", receiver,
                                              SLOT("pressed(QString,QString,qlonglong)"))
    if not ok:
        print("SightsL: couldn't listen for hotkeys on", path, file=sys.stderr)
    return receiver


def next_crosshair():
    """Switch to the next saved profile (or preset), keeping the screen choice. Used by the hotkey."""
    from grimoire.spells.sightc.config import cycle_order
    cur = Crosshair.load()
    order = cycle_order()
    looks = [c.look() for c in order]
    i = looks.index(cur.look()) + 1 if cur.look() in looks else 0
    order[i % len(order)].copy(screen=cur.screen).save()


# ---------------------------------------------------------------- the overlay itself
def run():
    other = running_pid()
    if other and other != os.getpid():
        sys.exit(f"SightsL: an overlay is already running (pid {other})")
    _write_pid(os.getpid())         # start() wrote it already; this covers `run` by hand (or any re-exec)

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

        def paint(self, painter):
            # whole-pixel center: the window size is even, so this is exactly the screen's middle
            draw.paint(painter, self.cfg, int(self.width()) // 2, int(self.height()) // 2)

    app = QGuiApplication(sys.argv)
    app.setApplicationName("grimoire-sightc")
    app.setDesktopFileName("grimoire")
    qmlRegisterType(CrosshairItem, "Grimoire.SightsL", 1, 0, "Crosshair")
    engine = QQmlApplicationEngine()
    engine.load(QUrl.fromLocalFile(str(Path(__file__).with_name("overlay.qml"))))
    if not engine.rootObjects():
        sys.exit("SightsL: failed to load overlay.qml")
    win = engine.rootObjects()[0]
    item = win.findChild(CrosshairItem, "crosshair")

    def pick_screen(name: str):
        screens = {s.name(): s for s in app.screens()}
        return screens.get(name) or app.primaryScreen()

    def apply():
        cfg = item.cfg
        side = 2 * max(64, draw.extent(cfg) + 2)            # even, so the centre lands on a pixel edge
        if (win.width(), win.height()) != (side, side):
            win.setWidth(side)
            win.setHeight(side)
        screen = pick_screen(cfg.screen)
        if win.property("targetScreen") != screen:
            win.setProperty("targetScreen", screen)          # overlay.qml re-maps the layer surface on change
        item.update()

    def reload():
        item.cfg = Crosshair.load()
        apply()

    # sightc.json is replaced atomically, so watch the folder rather than the file
    watcher = QFileSystemWatcher([str(CONFIG)])
    watcher.directoryChanged.connect(lambda _: reload())
    app.screenAdded.connect(lambda _: apply())
    app.screenRemoved.connect(lambda _: QTimer.singleShot(0, apply))
    apply()
    win.setProperty("ready", True)

    _hotkeys = register_hotkeys({                          # keep a reference alive
        ACTION: lambda: win.setProperty("shown", not win.property("shown")),
        NEXT_ACTION: next_crosshair,
    })

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
    elif cmd == "next":
        next_crosshair()
    elif cmd == "status":
        print("on" if running_pid() else "off")
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
