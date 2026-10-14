"""LaunchL's page in Grimoire: install or update the widget, swap it in for Kickoff and back."""
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QMessageBox, QPushButton, QVBoxLayout, QWidget

from grimoire.jobs import POOL, Job
from grimoire.spells.launchl import panel

NAMES = {"org.kde.plasma.kickoff": "Kickoff", "org.kde.plasma.kicker": "Application Menu",
         "org.kde.plasma.kickerdash": "Application Dashboard"}


def _label(text="", name="", wrap=True) -> QLabel:
    lab = QLabel(text)
    if name:
        lab.setObjectName(name)
    lab.setWordWrap(wrap)
    return lab


def status() -> str:
    return panel.status()


class _Signals(QObject):
    done = Signal(object)          # (what, error text or "", result)


class LaunchLPage(QWidget):
    def __init__(self):
        super().__init__()
        self.setObjectName("Page")
        self.sig = _Signals()
        self.sig.done.connect(self._finished)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(56, 48, 56, 40)
        lay.setSpacing(6)
        lay.addWidget(_label("LaunchL", "PageHeading"))
        lay.addWidget(_label("Your app launcher in the panel, in black and white: favorites, every app by category, "
                             "places and recent files, search that also finds files, does sums and unit conversions "
                             "and runs Grimoire's spells, and the leave buttons. Meta opens it once it's in Kickoff's "
                             "place.", "Muted"))
        lay.addSpacing(24)

        lay.addWidget(_label("WIDGET", "Section"))
        self.state = _label("", "")
        lay.addWidget(self.state)
        row = QHBoxLayout()
        self.install_btn = QPushButton()
        self.install_btn.clicked.connect(self._install)
        row.addWidget(self.install_btn)
        row.addStretch(1)
        lay.addLayout(row)
        lay.addSpacing(24)

        lay.addWidget(_label("PANEL", "Section"))
        self.where = _label("", "Muted")
        lay.addWidget(self.where)
        row = QHBoxLayout()
        self.replace_btn = QPushButton("Replace launcher")
        self.replace_btn.setObjectName("Primary")
        self.replace_btn.clicked.connect(self._replace)
        self.restore_btn = QPushButton("Restore Kickoff")
        self.restore_btn.clicked.connect(self._restore)
        row.addWidget(self.replace_btn)
        row.addWidget(self.restore_btn)
        row.addStretch(1)
        lay.addLayout(row)
        self.note = _label("", "Muted")
        lay.addWidget(self.note)
        lay.addStretch(1)
        self.refresh()

    # ---- state ----------------------------------------------------------------------------------------------------

    def refresh(self):
        self.state.setText("Checking…")
        self._busy(True)
        POOL.start(Job(self._read, lambda r: self.sig.done.emit(("read", "", r))))

    @staticmethod
    def _read() -> dict:
        info = {"installed": panel.is_installed(), "update": panel.needs_update(), "record": panel.load_state()}
        try:
            info["panels"] = panel.scan()
        except (RuntimeError, ValueError) as err:
            info["panels"], info["error"] = [], str(err)
        return info

    def _show(self, info: dict):
        installed, panels = info["installed"], info["panels"]
        here = panel.in_panel(panels) if panels else False
        record = info["record"].get("replaced")
        self.state.setText("Not installed" if not installed else
                           ("In your panel" if here else "Installed, not in your panel")
                           + (" · an update is ready" if info["update"] else ""))
        self.install_btn.setText("Install widget" if not installed else
                                 "Update widget" if info["update"] else "Reinstall widget")
        found = panel.find_launcher(panels) if panels else None
        if "error" in info:
            self.where.setText(f"Plasma isn't answering ({info['error']}), so the panel can't be read right now.")
        elif record:
            self.where.setText(f"LaunchL took {NAMES.get(record['type'], record['type'])}'s place (panel "
                               f"{record['panel']}, position {record['position'] + 1}) on {record['recorded'][:10]}. "
                               "Restore puts it back exactly there, with its settings.")
        elif here:
            self.where.setText("LaunchL is in your panel (added by hand). Restore needs a recorded replacement, so "
                               "use Edit Mode to swap launchers.")
        elif found:
            p, w, pos = found
            self.where.setText(f"{NAMES.get(w['type'], w['type'])} is in panel {p['id']} at position {pos + 1}. "
                               "Replace puts LaunchL in that exact spot, with your favorites in their order and its "
                               "shortcut, and records everything so Restore can undo it.")
        else:
            self.where.setText("No Kickoff, Application Menu or Dashboard in your panels. Add LaunchL from the "
                               "panel's Add Widgets (search \"LaunchL\").")
        self.replace_btn.setEnabled(installed and bool(found) and not here)
        self.restore_btn.setEnabled(bool(record))
        self.restore_btn.setText(f"Restore {NAMES.get(record['type'], 'Kickoff')}" if record else "Restore Kickoff")
        self.install_btn.setEnabled(True)

    def _busy(self, on: bool):
        for b in (self.install_btn, self.replace_btn, self.restore_btn):
            b.setEnabled(not on)

    # ---- actions --------------------------------------------------------------------------------------------------

    def _start(self, what: str, fn):
        self._busy(True)
        self.note.setText("Working…")

        def guarded():
            try:
                return "", fn()
            except RuntimeError as err:
                return str(err), None
        POOL.start(Job(guarded, lambda r: self.sig.done.emit((what, r[0], r[1]))))

    def _install(self):
        self._start("install", panel.install)

    def _replace(self):
        if QMessageBox.question(
                self, "Replace launcher",
                "LaunchL takes Kickoff's place in your panel:\n\n"
                "1. Grimoire records where Kickoff is, its settings and its shortcut.\n"
                "2. LaunchL is added in the same spot, with your favorites in the same order.\n"
                "3. Kickoff is removed.\n\nRestore Kickoff puts it back exactly as it was.") \
                != QMessageBox.StandardButton.Yes:
            return
        self._start("replace", panel.replace)

    def _restore(self):
        if QMessageBox.question(self, "Restore Kickoff", "Put the old launcher back where LaunchL is, with its "
                                "settings, and remove LaunchL from the panel?") != QMessageBox.StandardButton.Yes:
            return
        self._start("restore", panel.restore)

    def _finished(self, payload):
        what, error, result = payload
        if what == "read":
            self._show(result)
            return
        if error:
            self.note.setText(f"Couldn't {what}: {error}")
        elif what == "install":
            self.note.setText("Widget installed. Plasma picks up a new version when it next restarts.")
        elif what == "replace":
            self.note.setText("LaunchL is in your panel. " + (result.get("check") or "Press Meta to open it."))
        elif what == "restore":
            self.note.setText(f"{NAMES.get(result['type'], 'Kickoff')} is back in your panel.")
        self.refresh()

    def showEvent(self, e):
        super().showEvent(e)
        self.refresh()
