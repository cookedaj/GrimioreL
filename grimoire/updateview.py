"""The hub's side of self-update: a checker that works off the UI thread, the home banner, the rail's version button
and the What's new panel. The work itself is in update.py."""
import sys
import time

from PySide6.QtCore import QObject, QProcess, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (QApplication, QDialog, QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea,
                               QToolButton, QVBoxLayout, QWidget)

from grimoire import __version__, update
from grimoire.glyphs import _pixmap
from grimoire.jobs import POOL, Job


def _safe(fn):
    """Job drops exceptions; the UI needs to show them, so hand back ("error", message) instead."""
    def run():
        try:
            return ("ok", fn())
        except update.UpdateError as e:
            return ("error", str(e))
        except Exception as e:                       # never leave the panel spinning
            return ("error", f"Something went wrong: {e}")
    return run


class Updater(QObject):
    """One per hub window. checked(Status | None, error) after every check; progress(text) and
    applied(info | None, error) while updating."""
    checked = Signal(object, str)
    progress = Signal(str)
    applied = Signal(object, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.status = None
        self.error = ""
        self.busy = False
        self.updated = False                          # installed this session; a restart is due
        self._timer = QTimer(self, interval=update.CHECK_EVERY * 1000)
        self._timer.timeout.connect(lambda: self.check())
        self.checked.connect(self._on_checked)       # connected first, so views see the updated state
        self.applied.connect(self._on_applied)

    def start(self):
        """Check on launch (from the cache when recent) and every few hours; only an installed copy updates.
        Settings → General (or GRIMOIRE_NO_UPDATE_CHECK=1) turns the automatic check off; 'Check for updates'
        still works."""
        from grimoire import prefs
        if update.is_installed() and prefs.auto_update():
            self.check()
            self._timer.start()

    def stop(self):
        self._timer.stop()

    def check(self, force=False):
        if self.busy:
            return
        self.busy = True
        POOL.start(Job(_safe(lambda: update.check(force)), self._checked))

    def _checked(self, result):
        kind, value = result
        self.checked.emit(value if kind == "ok" else None, "" if kind == "ok" else value)

    def apply(self):
        if self.busy or not self.status:
            return
        self.busy = True
        latest = self.status.latest
        POOL.start(Job(_safe(lambda: update.apply(latest["sha"], latest.get("date", ""), self.progress.emit)),
                       lambda r: self.applied.emit(r[1] if r[0] == "ok" else None, "" if r[0] == "ok" else r[1])))

    def _on_checked(self, status, error):
        self.busy = False
        self.error = error
        if status is not None:
            self.status = status

    def _on_applied(self, info, error):
        self.busy = False
        self.error = error
        if info is not None:
            self.updated = True
            self.status.installed = info
            self.status.available = False

    @property
    def available(self) -> bool:
        return bool(self.status and self.status.available and not self.updated)


def restart():
    """Start the installed copy afresh and quit this one (the new code can't load into a running Python)."""
    cmd = update.APP / "bin" / "grimoire"
    if cmd.is_file():
        QProcess.startDetached(str(cmd), [])
    else:
        QProcess.startDetached(sys.executable, ["-m", "grimoire"])
    QApplication.quit()


class VersionButton(QToolButton):
    """The version at the foot of the rail. Opens What's new; shows an arrow glyph when an update is waiting."""

    def __init__(self, updater: Updater, open_panel):
        super().__init__()
        self.setObjectName("RailVersion")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        self.setIconSize(QSize(18, 18))
        self.setFixedWidth(56)
        self.updater = updater
        self.clicked.connect(open_panel)
        updater.checked.connect(lambda *_: self.refresh())
        updater.applied.connect(lambda *_: self.refresh())
        self.refresh()

    def refresh(self):
        on = self.updater.available
        self.setText(f"v{__version__}")
        self.setIcon(QIcon(_pixmap("update", "#ffffff", 36)) if on else QIcon())
        self.setProperty("avail", on)
        inst = update.installed()
        built = f" · {update.short(inst['sha'])}" if inst.get("sha") != "unknown" else ""
        self.setToolTip(f"Grimoire v{__version__}{built}\n"
                        + ("Update available: see what's new" if on else "Check for updates"))
        self.style().unpolish(self)
        self.style().polish(self)


class Banner(QWidget):
    """A white strip on the home page while an update is waiting (until 'Later' for that version)."""

    def __init__(self, updater: Updater, open_panel):
        super().__init__()
        self.updater = updater
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 24)      # its gap to the greeting goes away with it
        strip = QFrame()
        strip.setObjectName("Pending")
        outer.addWidget(strip)
        lay = QHBoxLayout(strip)
        lay.setContentsMargins(18, 12, 12, 12)
        lay.setSpacing(10)
        self.text = QLabel()
        self.text.setObjectName("PendingText")
        lay.addWidget(self.text, 1)
        later = QPushButton("Later")
        later.setCursor(Qt.CursorShape.PointingHandCursor)
        later.clicked.connect(self._later)
        lay.addWidget(later)
        see = QPushButton("What's new")
        see.setObjectName("Primary")
        see.setCursor(Qt.CursorShape.PointingHandCursor)
        see.clicked.connect(open_panel)
        lay.addWidget(see)
        updater.checked.connect(lambda *_: self.refresh())
        updater.applied.connect(lambda *_: self.refresh())
        self.refresh()

    def refresh(self):
        st = self.updater.status
        show = self.updater.available and not update.snoozed(st.latest["sha"])
        if show:
            n = st.total
            self.text.setText("A new version of Grimoire is ready" + (f" · {n} change{'s' * (n != 1)}" if n else ""))
        self.setVisible(show)

    def _later(self):
        update.snooze(self.updater.status.latest["sha"])
        self.hide()


def _label(text, name="", wrap=True, selectable=False):
    lab = QLabel(text)
    if name:
        lab.setObjectName(name)
    lab.setWordWrap(wrap)
    if selectable:
        lab.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return lab


class ChangeRow(QWidget):
    def __init__(self, change: update.Change):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 12, 0, 12)
        lay.setSpacing(4)
        top = QHBoxLayout()
        top.setSpacing(12)
        top.addWidget(_label(change.title, "ChangeTitle"), 1)
        meta = _label(" · ".join(x for x in (update.day(change.date), update.short(change.sha)) if x), "Value",
                      wrap=False)
        top.addWidget(meta, 0, Qt.AlignmentFlag.AlignTop)
        lay.addLayout(top)
        for b in change.bullets:
            lay.addWidget(_label(f"–  {b}", "Muted"))


class WhatsNew(QDialog):
    """Installed vs latest, the commits in between, and Update now / Later. Doubles as 'Check for updates'."""

    def __init__(self, updater: Updater, parent=None):
        super().__init__(parent)
        self.setObjectName("WhatsNew")
        self.setWindowTitle("What's new in Grimoire")
        self.resize(620, 640)
        self.updater = updater
        lay = QVBoxLayout(self)
        lay.setContentsMargins(32, 28, 32, 24)
        lay.setSpacing(6)
        lay.addWidget(_label("What's new", "PageHeading"))
        self.versions = _label("", "Muted", selectable=True)
        lay.addWidget(self.versions)
        self.note = _label("", "Muted")
        lay.addWidget(self.note)
        lay.addSpacing(10)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        lay.addWidget(self.scroll, 1)

        self.message = _label("", "Status")
        lay.addWidget(self.message)
        row = QHBoxLayout()
        row.setSpacing(10)
        self.again = QPushButton("Check for updates")
        self.again.setObjectName("Link")
        self.again.setCursor(Qt.CursorShape.PointingHandCursor)
        self.again.clicked.connect(lambda: self._check(force=True))
        row.addWidget(self.again)
        row.addStretch(1)
        self.later = QPushButton("Later")
        self.later.clicked.connect(self.close)
        row.addWidget(self.later)
        self.go = QPushButton("Update now")
        self.go.setObjectName("Primary")
        self.go.setCursor(Qt.CursorShape.PointingHandCursor)
        self.go.clicked.connect(self._go)
        row.addWidget(self.go)
        lay.addLayout(row)

        updater.checked.connect(self._checked)
        updater.progress.connect(self._progress)
        updater.applied.connect(self._applied)
        self._render()
        if updater.busy:                                  # the launch check is still out
            self.message.setText("Checking GitHub…")
        elif updater.status is None:                      # first open with nothing known yet
            self._check(force=False)

    # ---- actions
    def _check(self, force):
        if self.updater.busy:
            return
        self.message.setText("Checking GitHub…")
        self._buttons(busy=True)
        self.updater.check(force)

    def _go(self):
        if self.updater.updated:
            restart()
            return
        self.message.setText("Starting…")
        self._buttons(busy=True)
        self.updater.apply()

    # ---- signals
    def _checked(self, status, error):
        self._render()
        self.message.setText(error)

    def _progress(self, text):
        self.message.setText(text)

    def _applied(self, info, error):
        self._render()
        if info is not None:
            self.message.setText("Updated. Restart Grimoire (and any open spell windows) to use the new version.")
        else:
            self.message.setText(error)

    # ---- view
    def _buttons(self, busy=False):
        u = self.updater
        self.again.setEnabled(not busy and not u.updated)
        self.again.setVisible(not u.updated)
        self.go.setEnabled(not busy and (u.available or u.updated))
        self.go.setText("Restart now" if u.updated else "Update now")
        self.go.setVisible(u.updated or u.available or busy)
        self.later.setText("Later" if (u.available or u.updated) else "Close")

    def _render(self):
        u, st = self.updater, self.updater.status
        self._buttons(busy=u.busy)
        body = QWidget()
        body.setObjectName("Page")
        bl = QVBoxLayout(body)
        bl.setContentsMargins(0, 0, 8, 0)
        bl.setSpacing(0)
        if st is None:
            sha = update.installed()["sha"]
            built = f" · {update.short(sha)}" if sha != "unknown" else ""
            self.versions.setText(f"Grimoire v{__version__}" + (built if update.is_installed() else
                                  " · not installed (run ./install.sh; a git checkout updates with git pull)"))
            self.note.setText("")
        else:
            inst, latest = st.installed, st.latest

            def ver(d):
                return " ".join(x for x in (update.short(d.get("sha", "unknown")), f"({update.day(d.get('date', ''))})"
                                            if update.day(d.get("date", "")) else "") if x)
            if u.updated:
                self.versions.setText(f"Now on {ver(inst)}")
            elif not st.available and not st.note:
                when = f" · checked at {time.strftime('%H:%M', time.localtime(st.checked))}" if st.checked else ""
                self.versions.setText(f"Grimoire is up to date · {ver(inst)}{when}")
            else:
                self.versions.setText(f"You have {ver(inst)} · latest is {ver(latest)}")
            note = st.note
            if inst.get("dirty") and not u.updated:
                note = (note + " " if note else "") + "This copy was installed with local changes."
            if st.total > len(st.changes) and not u.updated:
                note = (note + " " if note else "") + f"Showing the newest {len(st.changes)} of {st.total} changes."
            self.note.setText(note)
            self.note.setVisible(bool(note))
            changes = st.changes if (st.available or u.updated) else []
            for i, c in enumerate(changes):
                if i:
                    line = QFrame()
                    line.setObjectName("Rule")
                    line.setFixedHeight(1)
                    bl.addWidget(line)
                bl.addWidget(ChangeRow(c))
            if not changes:
                bl.addWidget(_label("Nothing new on GitHub since your version." if not st.available else "", "Muted"))
        bl.addStretch(1)
        self.scroll.setWidget(body)
