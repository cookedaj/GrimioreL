"""Grimoire's tray icon: live CPU/RAM in the icon, and quick spells in its menu (crosshair, tidy Downloads,
performance mode, open any spell). Plasma shows it through StatusNotifierItem, so the menu uses the Plasma theme.

    grimoire-tray                        start it (one per session; a second start just says it's running)
    grimoire-tray autostart on|off       start it at login or not (also in its menu and on Grimoire's home page)
"""
import json
import os
import signal
import subprocess
import sys
from pathlib import Path

import psutil
from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtGui import QAction, QIcon
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from grimoire import standalone
from grimoire.glyphs import glyph, meter
from grimoire.paths import CACHE, CONFIG

SETTINGS = CONFIG / "tray.json"
EVERY_MS = 2000
TEMP_EVERY = 5               # sensors are read every 5th tick (10 s): they're the only costly reading


# ---------------------------------------------------------------- launching and autostart
def command(name: str) -> Path:
    """The ~/.local/bin link when installed (what autostart entries run), else the copy this runs from."""
    link = Path.home() / ".local/bin" / name
    return link if link.exists() else standalone.BIN / name


def launch(name: str, *args: str):
    subprocess.Popen([str(command(name)), *args], start_new_session=True, stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def autostart_file() -> Path:
    """Read late, so a sandbox XDG_CONFIG_HOME works in tests."""
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "autostart/grimoire-tray.desktop"


def autostart_on() -> bool:
    return autostart_file().exists()


def set_autostart(on: bool):
    f = autostart_file()
    if on:
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("[Desktop Entry]\nType=Application\nName=Grimoire tray\nComment=Live CPU/RAM and quick spells\n"
                     f"Exec={command('grimoire-tray')}\nIcon=grimoire\nX-KDE-autostart-phase=2\n")
    else:
        f.unlink(missing_ok=True)          # a file Grimoire wrote itself


# ---------------------------------------------------------------- single instance
def socket_path() -> str:
    run = os.environ.get("XDG_RUNTIME_DIR")
    return str(Path(run) / "grimoire-tray.sock") if run and Path(run).is_dir() else str(CACHE / "tray.sock")


def running() -> bool:
    s = QLocalSocket()
    s.connectToServer(socket_path())
    ok = s.waitForConnected(300)
    s.abort()
    return ok


# ---------------------------------------------------------------- settings and readings
def load_settings() -> dict:
    try:
        d = json.loads(SETTINGS.read_text())
        return {"meter": bool(d.get("meter", True))} if isinstance(d, dict) else {"meter": True}
    except (OSError, ValueError):
        return {"meter": True}


def save_settings(d: dict):
    SETTINGS.write_text(json.dumps(d, indent=1))


def cpu_temp() -> float | None:
    from grimoire.spells.systeml.probe import temps
    t = temps()
    return t.get("CPU", max(t.values()) if t else None)


def tooltip(cpu: float, used: int, total: int, temp: float | None) -> str:
    return f"CPU {cpu:.0f}%" + (f" · {temp:.0f} °C" if temp is not None else "") \
        + f"\nRAM {used / 2**30:.1f} of {total / 2**30:.0f} GB"


def _safely(fn) -> dict:
    """Any error comes back as a result, so a menu item never stays stuck on "Tidying…" / "Performance mode…"."""
    try:
        return fn()
    except Exception as e:
        return {"changed": [], "left": [], "problems": [str(e)],          # perfmode's shape
                "moved": 0, "cleaned": 0, "errors": [str(e)]}             # tidy.run's shape


# ---------------------------------------------------------------- the tray
class Tray(QObject):
    tidied = Signal(object)
    perf_done = Signal(object)

    def __init__(self):
        super().__init__()
        self.settings = load_settings()
        self.icon = QSystemTrayIcon()
        self.icon.setToolTip("Grimoire")
        self.icon.activated.connect(self._activated)
        self.menu = self._build_menu()
        self.icon.setContextMenu(self.menu)
        self.tidied.connect(self._on_tidied)
        self.perf_done.connect(self._on_perf)
        self._level = None               # last drawn bar levels, so the icon only changes when it would look different
        self._tip = ""
        self._ticks = 0
        self._temp = None
        psutil.cpu_percent(None)         # primes the counter; the first real reading is 2 s from now
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(EVERY_MS)
        self.tick()

    # -- menu
    def _action(self, menu: QMenu, text: str, slot, icon: str = "", checkable=False) -> QAction:
        a = QAction(text, menu)
        if icon:                         # checkable items go without one, so the menu shows their checkmark
            a.setIcon(glyph(icon, 16))
        a.setCheckable(checkable)
        a.triggered.connect(slot)
        menu.addAction(a)
        return a

    def _build_menu(self) -> QMenu:
        from grimoire.spells import SPELLS
        m = QMenu()
        m.addSection("Grimoire")
        self.a_cross = self._action(m, "Crosshair", self._toggle_crosshair, checkable=True)
        self._action(m, "Next crosshair profile", self._next_crosshair, "forward")
        self.a_tidy = self._action(m, "Tidy Downloads now", self._tidy, "tidy")
        self.a_perf = self._action(m, "Performance mode", self._toggle_perf, checkable=True)
        m.addSeparator()
        self._action(m, "Open Grimoire", lambda: launch("grimoire"), "home")
        for s in SPELLS:
            self._action(m, s.name, lambda _=False, sid=s.id: launch("grimoire", sid), s.icon)
        m.addSeparator()
        self.a_meter = self._action(m, "Live CPU/RAM in icon", self._toggle_meter, checkable=True)
        self.a_login = self._action(m, "Start tray at login", self._toggle_login, checkable=True)
        self._action(m, "Quit tray", QApplication.quit)
        m.aboutToShow.connect(self.refresh)
        self.refresh()
        return m

    def refresh(self):
        """Menu checkmarks from the real state (the crosshair may have been switched by its hotkey or SightsL)."""
        from grimoire.spells.optimizel import perfmode
        from grimoire.spells.sightc import overlay
        for action, on in ((self.a_cross, bool(overlay.running_pid())), (self.a_perf, perfmode.is_on()),
                           (self.a_meter, self.settings["meter"]), (self.a_login, autostart_on())):
            if action.isChecked() != on:
                action.setChecked(on)

    def _activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            launch("grimoire")
        elif reason == QSystemTrayIcon.ActivationReason.MiddleClick:
            self._toggle_crosshair()

    def notify(self, title: str, text: str, icon: str = ""):
        self.icon.showMessage(title, text, glyph(icon, 32) if icon else QIcon(), 6000)

    # -- live icon
    def tick(self):
        cpu = psutil.cpu_percent(None)
        mem = psutil.virtual_memory()
        used = mem.total - mem.available
        if self._ticks % TEMP_EVERY == 0:
            self._temp = cpu_temp()
        self._ticks += 1
        ram = 100 * used / mem.total if mem.total else 0
        level = (round(cpu / 100 * 16), round(ram / 100 * 16)) if self.settings["meter"] else None
        if level != self._level or self.icon.icon().isNull():
            self._level = level
            self.icon.setIcon(QIcon(meter(cpu, ram)) if level else glyph("system", 64))
        tip = tooltip(cpu, used, mem.total, self._temp)
        if tip != self._tip:
            self._tip = tip
            self.icon.setToolTip(tip)
        self.refresh()

    def _toggle_meter(self, on: bool):
        self.settings["meter"] = on
        save_settings(self.settings)
        self._level = -1
        self.tick()

    def _toggle_login(self, on: bool):
        try:
            set_autostart(on)
        except OSError as e:
            self.notify("Start at login", f"Couldn't change it: {e}")
        self.refresh()

    # -- crosshair
    def _toggle_crosshair(self):
        from grimoire.spells.sightc import overlay
        overlay.stop() if overlay.running_pid() else overlay.start()
        QTimer.singleShot(800, self.refresh)      # the overlay writes its pid once it's up

    def _next_crosshair(self):
        from grimoire.spells.sightc import overlay
        overlay.next_crosshair()

    # -- tidy
    def _tidy(self):
        from grimoire.jobs import POOL, Job
        from grimoire.spells.vaultl import tidy
        self.a_tidy.setEnabled(False)
        self.a_tidy.setText("Tidying Downloads…")
        POOL.start(Job(lambda: _safely(tidy.run), self.tidied.emit))

    def _on_tidied(self, r: dict):
        self.a_tidy.setEnabled(True)
        self.a_tidy.setText("Tidy Downloads now")
        text = (f"Sorted {r['moved']} file(s), {r['cleaned']} stale one(s) to the Trash" if r["moved"] or r["cleaned"]
                else "Nothing to sort") + (f"\n{len(r['errors'])} problem(s): {r['errors'][0]}" if r["errors"] else "")
        self.notify("Downloads tidied", text, "tidy")

    # -- performance mode
    def _toggle_perf(self, on: bool):
        from grimoire.jobs import POOL, Job
        from grimoire.spells.optimizel import perfmode
        self.a_perf.setEnabled(False)
        self.a_perf.setText("Performance mode…")
        POOL.start(Job(lambda: (on, _safely(perfmode.turn_on if on else perfmode.turn_off)), self.perf_done.emit))

    def _on_perf(self, result):
        from grimoire.spells.optimizel import perfmode
        on, r = result
        self.a_perf.setEnabled(True)
        self.a_perf.setText("Performance mode")
        self.refresh()
        if on:
            text = f"Turned on: {perfmode.describe(r['changed'])}" if r["changed"] else \
                "Everything it switches was already on (or doesn't apply here)"
        else:
            text = f"Turned back off: {perfmode.describe(r['changed'])}" if r["changed"] else "Nothing to turn back"
            if r["left"]:
                text += f"\nStill on: {perfmode.describe(r['left'])}"
        if r["problems"]:
            text += "\n" + "; ".join(r["problems"])
        self.notify(f"Performance mode {'on' if on else 'off'}", text, "optimize")


def run():
    app = QApplication(sys.argv[:1])
    app.setApplicationName("Grimoire tray")
    app.setDesktopFileName("grimoire-tray")
    app.setQuitOnLastWindowClosed(False)
    from grimoire.app import style_app
    style_app(app)
    if running():
        print("Grimoire's tray is already running.")
        s = QLocalSocket()                     # tells the running one, which says so in a notification
        s.connectToServer(socket_path())
        s.waitForConnected(300)
        s.waitForDisconnected(300)
        return 0
    QLocalServer.removeServer(socket_path())   # a stale socket from a crash
    server = QLocalServer()
    server.listen(socket_path())
    tray = Tray()
    server.newConnection.connect(lambda: (server.nextPendingConnection().disconnectFromServer(),
                                          tray.notify("Grimoire tray", "Already running, look in the system tray")))
    tray.icon.show()
    for sig in (signal.SIGTERM, signal.SIGINT):    # quit cleanly (the icon's 2 s timer lets Python see the signal)
        signal.signal(sig, lambda *_: app.quit())
    code = app.exec()
    server.close()                                 # removes the socket
    return code


def main(argv: list[str]):
    if argv[:1] == ["autostart"] and argv[1:] in (["on"], ["off"], ["status"], []):
        if argv[1:2] in (["on"], ["off"]):
            set_autostart(argv[1] == "on")
        print("tray at login " + ("on" if autostart_on() else "off"))
    elif not argv:
        sys.exit(run())
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
