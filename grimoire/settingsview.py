# SPDX-License-Identifier: GPL-3.0-or-later
"""The hub's Settings page (the gear at the foot of the rail): hotkeys, backup & restore, GitHub account, general.

The work lives in Qt-free modules (hotkeys.py, backup.py, github.py, keystore.py, prefs.py); this file only lays it
out and runs every slow or networked call off the UI thread.
"""
import threading
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QObject, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QGuiApplication, QImage, QKeySequence, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import (QCheckBox, QDialog, QFileDialog, QFrame, QHBoxLayout, QKeySequenceEdit, QLabel,
                               QPushButton, QScrollArea, QStackedWidget, QVBoxLayout, QWidget)

from grimoire import NAME, __version__
from grimoire.glyphs import clover, glyph
from grimoire.jobs import POOL, Job
from grimoire.widgets import Switch

SECTIONS = [("hotkeys", "Hotkeys", "keyboard"), ("backup", "Backup & restore", "archive"),
            ("account", "GitHub", "login"), ("general", "General", "sliders")]


def _label(text="", name="", wrap=True):
    lab = QLabel(text)
    lab.setTextFormat(Qt.TextFormat.PlainText)      # shows names from backups and GitHub, never as HTML
    if name:
        lab.setObjectName(name)
    lab.setWordWrap(wrap)
    return lab


def _button(text, slot, name="", tip=""):
    b = QPushButton(text)
    if name:
        b.setObjectName(name)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    b.clicked.connect(slot)
    if tip:
        b.setToolTip(tip)
    return b


def _rule():
    line = QFrame()
    line.setObjectName("Rule")
    line.setFixedHeight(1)
    return line


# ---------------------------------------------------------------- background work
class _Task(QObject):
    done = Signal(object)


_tasks: set = set()


def run(fn, then, errors=(Exception,)):
    """fn() on a pool thread, then(ok, value_or_message) on the UI thread. Exceptions come back as their message
    (our own error classes word them for the UI and never carry secrets); nothing is printed."""
    task = _Task()
    _tasks.add(task)

    def safe():
        try:
            return True, fn()
        except errors as e:
            return False, str(e) or type(e).__name__

    def finish(result):
        _tasks.discard(task)
        then(*result)
    task.done.connect(finish)
    POOL.start(Job(safe, task.done.emit))


class Row(QFrame):
    """A settings row: title and a muted line on the left, controls on the right."""

    def __init__(self, title, sub="", controls=()):
        super().__init__()
        self.setObjectName("Row")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(18, 14, 14, 14)
        lay.setSpacing(12)
        text = QVBoxLayout()
        text.setSpacing(2)
        self.title = _label(title, "RowTitle")
        text.addWidget(self.title)
        self.sub = _label(sub, "Muted")
        self.sub.setVisible(bool(sub))
        text.addWidget(self.sub)
        lay.addLayout(text, 1)
        for c in controls:
            lay.addWidget(c, 0, Qt.AlignmentFlag.AlignVCenter)


def _scroll(inner: QWidget) -> QScrollArea:
    s = QScrollArea()
    s.setWidgetResizable(True)
    s.setFrameShape(QFrame.Shape.NoFrame)
    inner.setObjectName("Page")
    s.setWidget(inner)
    return s


# ---------------------------------------------------------------- hotkeys
class KeyField(QKeySequenceEdit):
    """One key combination (no chords); edited(key) when the user finishes, 0 when cleared."""
    edited = Signal(int)

    def __init__(self):
        super().__init__()
        self.setObjectName("KeyField")
        self.setMaximumSequenceLength(1)
        self.setClearButtonEnabled(True)
        self.setFixedWidth(190)
        self.editingFinished.connect(self._done)

    def key(self) -> int:
        seq = self.keySequence()
        return seq[0].toCombined() if seq.count() else 0

    def set_key(self, key: int):
        self.blockSignals(True)
        self.setKeySequence(QKeySequence(key) if key else QKeySequence())
        self.blockSignals(False)

    def _done(self):
        self.edited.emit(self.key())


class HotkeyRow(QFrame):
    def __init__(self, panel, hk):
        from grimoire import hotkeys
        super().__init__()
        self.setObjectName("Row")
        self.panel, self.hk = panel, hk
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 12, 14, 12)
        lay.setSpacing(6)
        top = QHBoxLayout()
        top.setSpacing(10)
        text = QVBoxLayout()
        text.setSpacing(2)
        text.addWidget(_label(hk.name, "RowTitle"))
        default = f" · default {hotkeys.text(hk.default)}" if hk.default else ""
        text.addWidget(_label(("Command" if hk.kind == "command" else hk.component_name) + default, "Muted"))
        top.addLayout(text, 1)
        self.field = KeyField()
        self.field.set_key(hk.keys[0] if hk.keys else 0)
        self.field.edited.connect(self._edited)
        top.addWidget(self.field)
        self.reset = _button("Default" if hk.default else "Clear", self._reset,
                             tip="Back to Grimoire's default key" if hk.default else "Remove this shortcut")
        self.reset.setFixedWidth(84)
        top.addWidget(self.reset)
        lay.addLayout(top)
        self.note = _label("", "Muted")
        self.note.hide()
        lay.addWidget(self.note)
        self._sync()

    def _sync(self):
        cur = self.hk.keys[0] if self.hk.keys else 0
        self.reset.setEnabled(cur != self.hk.default)

    def say(self, text):
        self.note.setText(text)
        self.note.setVisible(bool(text))

    def _edited(self, key):
        from grimoire import hotkeys
        cur = self.hk.keys[0] if self.hk.keys else 0
        if key == cur:
            return
        taken = hotkeys.conflicts(key, self.hk, self.panel.everything)
        problem = hotkeys.check(key) or (f"{hotkeys.text(key)} is already used by {taken[0]}. Pick another key."
                                         if taken else "")
        if problem:
            self.say(problem)
            self.field.set_key(cur)
            return
        self._apply(key)

    def _reset(self):
        self._apply(self.hk.default)

    def _apply(self, key):
        from grimoire import hotkeys
        self.field.setEnabled(False)
        self.reset.setEnabled(False)
        self.say("Saving…")
        hk = self.hk
        run(lambda: hotkeys.apply(hk, key, hotkeys.all_shortcuts()), self._applied)

    def _applied(self, ok, value):
        self.field.setEnabled(True)
        if ok:
            self.hk.keys = value
            self.say("Saved." if value else "Removed.")
            QTimer.singleShot(2500, lambda: self.note.text() in ("Saved.", "Removed.") and self.say(""))
            self.panel.reload(quiet=True)
        else:
            self.say(value)
        self.field.set_key(self.hk.keys[0] if self.hk.keys else 0)
        self._sync()


class HotkeysPanel(QWidget):
    def __init__(self):
        super().__init__()
        self.everything = []
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 8, 0)
        lay.setSpacing(10)
        lay.addWidget(_label("Global shortcuts work anywhere in Plasma. Click a field and press the keys; changes go "
                             "straight to KDE (they also show in System Settings → Shortcuts). A key another "
                             "shortcut already uses is refused.", "Muted"))
        self.status = _label("Reading KDE's shortcuts…", "Muted")
        lay.addWidget(self.status)
        self.rows = QVBoxLayout()
        self.rows.setSpacing(8)
        lay.addLayout(self.rows)
        lay.addStretch(1)
        self._loaded = False

    def showEvent(self, e):
        super().showEvent(e)
        if not self._loaded:
            self._loaded = True
            self.reload()

    def reload(self, quiet=False):
        from grimoire import hotkeys
        run(hotkeys.load, lambda ok, v: self._show(ok, v, quiet))

    def _show(self, ok, value, quiet):
        if not ok:
            self.status.setText(f"Couldn't read KDE's shortcuts: {value}")
            self.status.show()
            return
        hks, self.everything = value
        if quiet:                                    # after a change: only refresh what we compare against
            return
        self.status.hide()
        while self.rows.count():
            w = self.rows.takeAt(0).widget()
            if w:
                w.deleteLater()
        actions = [h for h in hks if h.kind == "action"]
        commands = [h for h in hks if h.kind == "command"]
        if actions:
            self.rows.addWidget(_label("SPELLS", "Section"))
            for h in actions:
                self.rows.addWidget(HotkeyRow(self, h))
        if commands:
            self.rows.addSpacing(10)
            self.rows.addWidget(_label("COMMANDS YOU CAN BIND", "Section"))
            for h in commands:
                self.rows.addWidget(HotkeyRow(self, h))


# ---------------------------------------------------------------- backup & restore
class Preview(QDialog):
    """What a backup would change, file by file, and the Restore button."""

    def __init__(self, plan, origin, parent=None):
        super().__init__(parent)
        self.setObjectName("WhatsNew")
        self.setWindowTitle("Restore settings")
        self.resize(620, 560)
        self.plan = plan
        lay = QVBoxLayout(self)
        lay.setContentsMargins(32, 28, 32, 24)
        lay.setSpacing(6)
        lay.addWidget(_label("Restore settings", "PageHeading"))
        made = f" · made {_when(plan.created)}" if _when(plan.created) else ""
        ver = f" by Grimoire v{plan.app_version}" if plan.app_version else ""
        lay.addWidget(_label(f"{origin}{made}{ver}", "Muted"))
        bits = [f"{plan.count('changed')} changed", f"{plan.count('new')} new", f"{plan.count('unchanged')} unchanged"]
        if plan.ignored:
            bits.append(f"{len(plan.ignored)} unknown, ignored")
        lay.addWidget(_label(" · ".join(bits), "Muted"))
        lay.addSpacing(8)
        body = QWidget()
        bl = QVBoxLayout(body)
        bl.setContentsMargins(0, 0, 8, 0)
        bl.setSpacing(0)
        for e in plan.entries:
            bl.addWidget(self._line(e.path, e.status.upper(), e.status != "unchanged", e.size))
        for name in plan.ignored:
            bl.addWidget(self._line(name, "IGNORED", False, None))
        bl.addStretch(1)
        lay.addWidget(_scroll(body), 1)
        todo = plan.count("changed") + plan.count("new")
        self.message = _label("A safety backup of your current settings is saved first. Restart Grimoire afterwards "
                              "to load everything." if todo else "Nothing to restore: it all matches already.", "Status")
        lay.addWidget(self.message)
        row = QHBoxLayout()
        row.addStretch(1)
        self.cancel = _button("Cancel", self.reject)
        row.addWidget(self.cancel)
        self.go = _button(f"Restore {todo} file{'s' * (todo != 1)}", self.accept, "Primary")
        self.go.setEnabled(bool(todo))
        row.addWidget(self.go)
        lay.addLayout(row)

    @staticmethod
    def _line(path, status, strong, size):
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 6, 0, 6)
        name = _label(path, "RowTitle" if strong else "Muted", wrap=False)
        h.addWidget(name, 1)
        if size is not None:
            h.addWidget(_label(_size(size), "Value", wrap=False))
        badge = _label(status, "BadgeSolid" if strong else "Badge", wrap=False)
        h.addWidget(badge)
        return w


def _when(iso: str) -> str:
    try:
        return datetime.fromisoformat(iso).astimezone().strftime("%b %-d, %Y at %H:%M")
    except (ValueError, TypeError):
        return ""


def _size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024


def restore_flow(widget, source, origin, report, after=lambda: None):
    """Shared by file and GitHub restores: inspect (off-thread) → preview → safety backup + restore (off-thread).
    report(text, done) shows progress and the outcome; after() runs once something was restored."""
    from grimoire import backup
    report("Checking the backup…", False)

    def inspected(ok, plan):
        if not ok:
            report(plan, True)
            return
        dlg = Preview(plan, origin, widget.window())
        if dlg.exec() != QDialog.DialogCode.Accepted:
            report("Restore cancelled; nothing changed.", True)
            return
        report("Saving a safety backup, then restoring…", False)
        run(lambda: backup.restore(plan), restored, (backup.BackupError, OSError))

    def restored(ok, value):
        if not ok:
            report(value, True)
            return
        safety, done = value
        after()
        report(f"Restored {len(done)} file{'s' * (len(done) != 1)}. Your previous settings are saved in "
               f"{safety.name if safety else 'nothing (no change)'}. Restart Grimoire to load them.", True)
    run(lambda: backup.inspect(source), inspected, (backup.BackupError, OSError))


class BackupPanel(QWidget):
    def __init__(self):
        from grimoire import backup
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 8, 0)
        lay.setSpacing(10)
        lay.addWidget(_label("One file with all of Grimoire's settings: every spell's options, crosshairs and "
                             "profiles, MuraL's screens and saved looks, tidy rules, alerts and the tray. Not caches, "
                             "logs or the installed app.", "Muted"))
        self.library = QCheckBox("Include MuraL's wallpaper library")
        self.library.setToolTip("Your imported wallpapers and videos; can be large")
        self.save = _button("Save backup…", self._export, "Primary")
        lay.addWidget(Row("Back up", "Saves a .grimoire-backup file wherever you choose.", [self.library, self.save]))
        self.load = _button("Restore from file…", self._import)
        lay.addWidget(Row("Restore", "Checks the file, shows what would change, keeps a safety backup of your "
                                     "current settings, then writes it. Only restore backups you made.", [self.load]))
        self.status = _label("", "Status")
        self.status.hide()
        lay.addWidget(self.status)
        folder = _button("Open safety backups folder", lambda: (backup.SAFETY.mkdir(parents=True, exist_ok=True),
                         QDesktopServices.openUrl(QUrl.fromLocalFile(str(backup.SAFETY)))), "Link")
        lay.addWidget(folder, 0, Qt.AlignmentFlag.AlignLeft)
        lay.addStretch(1)
        QTimer.singleShot(0, self._measure)

    def _measure(self):
        from grimoire import backup
        run(lambda: sum(p.stat().st_size for n, p in backup.collect(True) if backup.kind_of(n) == "library"),
            lambda ok, n: ok and self.library.setText(f"Include MuraL's wallpaper library ({_size(n)})"))

    def report(self, text, done=True):
        self.status.setText(text)
        self.status.setVisible(bool(text))
        for b in (self.save, self.load):
            b.setEnabled(done)

    def _export(self):
        from grimoire import backup
        start = str(Path.home() / backup.default_name())
        path, _ = QFileDialog.getSaveFileName(self, "Save Grimoire backup", start, "Grimoire backup (*.grimoire-backup)")
        if not path:
            return
        dest = Path(path)
        if dest.suffix != backup.SUFFIX:                 # the dialog only confirmed overwriting the name as typed
            from grimoire.fsutil import free_name
            dest = free_name(dest.with_name(dest.name + backup.SUFFIX))
        lib = self.library.isChecked()
        self.report("Saving…", False)
        run(lambda: backup.export(dest, lib),
            lambda ok, v: self.report(f"Saved {len(v['files'])} files to {dest}." if ok
                                      else f"Couldn't save the backup: {v}"), (OSError, ValueError))

    def _import(self):
        path, _ = QFileDialog.getOpenFileName(self, "Restore Grimoire backup", str(Path.home()),
                                              "Grimoire backup (*.grimoire-backup);;All files (*)")
        if path:
            restore_flow(self, Path(path), Path(path).name, self.report)


# ---------------------------------------------------------------- GitHub account
def _round_gray(data: bytes, size=56) -> QPixmap:
    """The avatar, in Grimoire's black & white, as a circle."""
    img = QImage.fromData(data)
    if img.isNull():
        return QPixmap()
    img = img.convertToFormat(QImage.Format.Format_Grayscale8).scaled(
        size * 2, size * 2, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
    out = QPixmap(size * 2, size * 2)
    out.fill(Qt.GlobalColor.transparent)
    p = QPainter(out)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    clip = QPainterPath()
    clip.addEllipse(0, 0, size * 2, size * 2)
    p.setClipPath(clip)
    p.drawImage(0, 0, img)
    p.end()
    out.setDevicePixelRatio(2)
    return out


class AccountPanel(QWidget):
    """Signed out → (code shown while signing in) → signed in, with GitHub backups."""

    def __init__(self):
        from grimoire import github
        super().__init__()
        self._attempt = 0
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 8, 0)
        lay.setSpacing(10)
        lay.addWidget(_label("Sign in with GitHub to keep a copy of your settings in a secret gist on your account and "
                             "restore it on any PC. No password is typed into Grimoire: you approve it on github.com, "
                             "and Grimoire only asks for access to gists. The sign-in is kept in the system keyring "
                             "(KWallet).", "Muted"))
        self.views = []                          # signed out, code shown, signed in: one visible at a time
        # signed out
        out = QWidget()
        ol = QVBoxLayout(out)
        ol.setContentsMargins(0, 0, 0, 0)
        self.signin = _button("Sign in with GitHub", self._start, "Primary")
        self.out_row = Row("Not signed in", "", [self.signin])
        ol.addWidget(self.out_row)
        self.views.append(out)
        # waiting for the code to be entered
        wait = QFrame()
        wait.setObjectName("Row")
        wl = QVBoxLayout(wait)
        wl.setContentsMargins(18, 16, 18, 16)
        wl.setSpacing(8)
        wl.addWidget(_label("Enter this code on GitHub", "RowTitle"))
        self.code = _label("", "UserCode", wrap=False)
        self.code.setStyleSheet('font-family: "IBM Plex Mono"; font-size: 30px; font-weight: 600; color: #ffffff;')
        self.code.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        wl.addWidget(self.code)
        self.where = _label("", "Muted")
        wl.addWidget(self.where)
        br = QHBoxLayout()
        br.addWidget(_button("Copy code", lambda: QGuiApplication.clipboard().setText(self.code.text())))
        self.open_page = _button("Open GitHub", self._open_device_page, "Primary")
        br.addWidget(self.open_page)
        br.addStretch(1)
        br.addWidget(_button("Cancel", self._cancel_signin))
        wl.addLayout(br)
        self.views.append(wait)
        # signed in
        inside = QWidget()
        il = QVBoxLayout(inside)
        il.setContentsMargins(0, 0, 0, 0)
        il.setSpacing(10)
        who = QFrame()
        who.setObjectName("Row")
        hl = QHBoxLayout(who)
        hl.setContentsMargins(16, 14, 14, 14)
        hl.setSpacing(14)
        self.avatar = QLabel()
        self.avatar.setFixedSize(56, 56)
        hl.addWidget(self.avatar)
        names = QVBoxLayout()
        names.setSpacing(2)
        self.login = _label("", "RowTitle")
        names.addWidget(self.login)
        self.fullname = _label("", "Muted")
        names.addWidget(self.fullname)
        hl.addLayout(names, 1)
        hl.addWidget(_button("Sign out", self._signout))
        il.addWidget(who)
        self.up = _button("Back up now", self._upload, "Primary")
        il.addWidget(Row("Back up settings to GitHub", "The same backup as a file, in a secret gist on your account "
                         "(anyone with its link could read it, so keep the link to yourself). Wallpapers stay out.",
                         [self.up]))
        self.down = _button("Restore…", self._download)
        self.gist = _button("Open gist", self._open_gist, "Link")
        il.addWidget(Row("Restore from GitHub", "Checked, previewed and safety-backed-up just like a file.",
                         [self.gist, self.down]))
        self.views.append(inside)
        for v in self.views:
            lay.addWidget(v)

        self.status = _label("", "Status")
        self.status.hide()
        lay.addWidget(self.status)
        self.revoke = _button("Revoke Grimoire's access on GitHub", lambda: QDesktopServices.openUrl(
            QUrl(github.REVOKE_PAGE)), "Link")
        self.revoke.hide()
        lay.addWidget(self.revoke, 0, Qt.AlignmentFlag.AlignLeft)
        lay.addStretch(1)
        self._dc = None
        self._loaded = False
        self._view(0)
        QCoreApplication.instance().aboutToQuit.connect(_quitting.set)   # a running sign-in poll stops with the app

    # ---- state
    def _view(self, i):
        for n, v in enumerate(self.views):
            v.setVisible(n == i)

    def showEvent(self, e):
        super().showEvent(e)
        if not self._loaded:
            self._loaded = True
            self.refresh()

    def say(self, text):
        self.status.setText(text)
        self.status.setVisible(bool(text))

    def refresh(self):
        from grimoire import github
        self._view(0)
        if not github.configured():
            self.out_row.sub.setText("Sign-in isn't set up yet in this copy of Grimoire (it needs Grimoire's GitHub "
                                     "app ID).")
            self.out_row.sub.show()
            self.signin.setEnabled(False)
            return
        self.out_row.sub.setText("Checking the keyring…")
        self.out_row.sub.show()
        self.signin.setEnabled(False)
        run(_who, self._who)

    def _who(self, ok, value):
        self.signin.setEnabled(True)
        if not ok:
            self.out_row.sub.setText(value)
            return
        if value is None:
            self.out_row.sub.setText("Sign in to back up your settings to GitHub.")
            self._view(0)
            return
        user, pic = value
        self.login.setText(user["login"])
        self.fullname.setText(user["name"] or "Signed in with GitHub")
        self.avatar.setPixmap(_round_gray(pic) if pic else glyph("login", 40).pixmap(40, 40))
        self._view(2)
        self._gist_buttons()

    def _gist_buttons(self):
        from grimoire import prefs
        self.gist.setVisible(bool(prefs.load()["gist_id"]))

    # ---- sign in
    def _start(self):
        from grimoire import github
        self._attempt += 1
        self.signin.setEnabled(False)
        self.say("Asking GitHub for a code…")
        self.revoke.hide()
        run(github.start, self._got_code, (github.GitHubError,))

    def _got_code(self, ok, dc):
        self.signin.setEnabled(True)
        if not ok:
            self.say(dc)
            return
        self._dc = dc
        self.code.setText(dc.user_code)
        self.where.setText(f"Open {dc.verification_uri}, type the code and approve Grimoire. "
                           f"The code works for {max(1, dc.expires_in // 60)} minutes.")
        self._view(1)
        self.say("Waiting for you to approve on GitHub…")
        self._open_device_page()
        n = self._attempt
        run(lambda: _finish_signin(dc, lambda: self._attempt != n or _quitting.is_set()),
            lambda ok, v: self._signed_in(n, ok, v))

    def _open_device_page(self):
        if self._dc:
            QDesktopServices.openUrl(QUrl(self._dc.verification_uri))

    def _cancel_signin(self):
        self._attempt += 1                       # the running poll sees it and stops
        self._view(0)
        self.say("Sign-in cancelled.")

    def _signed_in(self, attempt, ok, value):
        if attempt != self._attempt:             # cancelled, or an older try
            return
        self._dc = None
        if not ok:
            self._view(0)
            self.say(value)
            return
        self.say("Signed in. The sign-in is saved in your keyring.")
        self._who(True, value)

    def _signout(self):
        from grimoire import keystore
        run(keystore.delete, self._signed_out, (keystore.KeyringError,))

    def _signed_out(self, ok, value):
        if not ok:
            self.say(f"Couldn't remove the sign-in from the keyring: {value}")
            return
        self.refresh()
        self.say("Signed out on this PC. GitHub still lists Grimoire as allowed until you revoke it there:")
        self.revoke.show()

    # ---- gist backups
    def _upload(self):
        self.up.setEnabled(False)
        self.say("Backing up to GitHub…")
        run(_upload, self._uploaded)

    def _uploaded(self, ok, value):
        self.up.setEnabled(True)
        self.say(f"Backed up {value} files to your secret gist." if ok else value)
        self._gist_buttons()

    def _download(self):
        self.down.setEnabled(False)
        self.say("Fetching the backup from GitHub…")
        run(_download, self._downloaded)

    def _downloaded(self, ok, value):
        from grimoire import prefs
        if not ok:
            self.down.setEnabled(True)
            self.say(value)
            return
        self._gist_buttons()

        def report(text, done):
            self.say(text)
            self.down.setEnabled(done)
        gid = prefs.load()["gist_id"]             # the backup may predate the gist; keep pointing at it
        restore_flow(self, value, "From your GitHub gist", report, lambda: prefs.save(gist_id=gid))

    def _open_gist(self):
        from grimoire import prefs
        gid = prefs.load()["gist_id"]
        if gid:
            QDesktopServices.openUrl(QUrl(f"https://gist.github.com/{gid}"))


_quitting = threading.Event()      # set when the app quits: Python waits for pool threads, so a poll must end


def _token():
    from grimoire import github, keystore
    value = keystore.load()
    if not value:
        raise github.GitHubError("Not signed in any more; sign in again.")
    return github.Token(value)


def _who():
    """(user, avatar bytes) if a sign-in is saved, else None. Runs off the UI thread."""
    from grimoire import github, keystore
    value = keystore.load()
    if not value:
        return None
    token = github.Token(value)
    user = github.user(token)
    try:
        pic = github.avatar(user["avatar_url"])
    except github.GitHubError:
        pic = b""
    return user, pic


def _finish_signin(dc, cancelled):
    from grimoire import github, keystore
    token = github.poll(dc, cancelled)
    user = github.user(token)                   # proves the token works before it's saved
    keystore.store(token.reveal())
    try:
        pic = github.avatar(user["avatar_url"])
    except github.GitHubError:
        pic = b""
    return user, pic


def _upload():
    from grimoire import backup, github, prefs
    token = _token()
    data = backup.export_bytes(include_library=False)
    gid = prefs.load()["gist_id"] or github.find_backup(token)
    gid = github.upload(token, data, gid)
    prefs.save(gist_id=gid)
    return len(backup.inspect(data).entries)


def _download():
    from grimoire import github, prefs
    token = _token()
    gid = prefs.load()["gist_id"] or github.find_backup(token)
    if not gid:
        raise github.GitHubError("There's no Grimoire backup on your GitHub yet.")
    data = github.download(token, gid)
    prefs.save(gist_id=gid)
    return data


# ---------------------------------------------------------------- general
class GeneralPanel(QWidget):
    def __init__(self, updater, whats_new):
        import os

        from grimoire import prefs, tray, update
        super().__init__()
        self.updater = updater
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 8, 0)
        lay.setSpacing(10)
        self.auto = Switch()
        self.auto.setChecked(prefs.load()["auto_update"])
        env = bool(os.environ.get("GRIMOIRE_NO_UPDATE_CHECK"))
        sub = ("Off while GRIMOIRE_NO_UPDATE_CHECK is set in the environment." if env else
               "Looks at GitHub every few hours (no account needed) and says when a new version is ready.")
        self.auto.setEnabled(not env)
        self.auto.toggled.connect(self._auto)
        lay.addWidget(Row("Check for updates automatically", sub, [self.auto]))
        self.tray = Switch()
        self.tray.setChecked(tray.autostart_on())
        self.tray.toggled.connect(self._tray)
        lay.addWidget(Row("Start the tray icon at login", "Live CPU and RAM in the system tray, with the crosshair, "
                          "tidy Downloads, performance mode and every spell in its menu.", [self.tray]))
        self.login = Switch()
        self.login.setChecked(prefs.open_at_login())
        self.login.toggled.connect(self._login)
        lay.addWidget(Row("Open Grimoire Linux at login", "Opens the hub when Plasma starts.", [self.login]))
        self.status = _label("", "Status")
        self.status.hide()
        lay.addWidget(self.status)

        lay.addSpacing(16)
        lay.addWidget(_label("ABOUT", "Section"))
        about = QFrame()
        about.setObjectName("Row")
        al = QHBoxLayout(about)
        al.setContentsMargins(18, 16, 14, 16)
        al.setSpacing(16)
        logo = QLabel()
        logo.setPixmap(clover(44))
        al.addWidget(logo)
        col = QVBoxLayout()
        col.setSpacing(2)
        col.addWidget(_label(NAME, "RowTitle"))
        sha = update.installed().get("sha", "unknown")
        built = f" · {update.short(sha)}" if sha != "unknown" else ""
        col.addWidget(_label(f"Version {__version__}{built} · black & white tools for KDE Plasma", "Muted"))
        al.addLayout(col, 1)
        al.addWidget(_button("Source on GitHub", lambda: QDesktopServices.openUrl(
            QUrl(f"https://github.com/{update.REPO}")), "Link"))
        al.addWidget(_button("What's new", whats_new))
        lay.addWidget(about)
        lay.addStretch(1)

    def _say(self, text):
        self.status.setText(text)
        self.status.setVisible(bool(text))

    def _auto(self, on):
        from grimoire import prefs
        prefs.save(auto_update=on)
        if on:
            self.updater.start()
        else:
            self.updater.stop()

    def _tray(self, on):
        from grimoire import tray
        try:
            tray.set_autostart(on)
            if on and not tray.running():
                tray.launch("grimoire-tray")
        except OSError as e:
            self._say(f"Couldn't change it: {e}")

    def _login(self, on):
        from grimoire import prefs
        try:
            prefs.set_open_at_login(on)
        except OSError as e:
            self._say(f"Couldn't change it: {e}")


# ---------------------------------------------------------------- the page
class SettingsPage(QWidget):
    def __init__(self, updater, whats_new):
        super().__init__()
        self.setObjectName("Page")
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        nav = QFrame()
        nav.setObjectName("SubNav")
        nav.setFixedWidth(210)
        nl = QVBoxLayout(nav)
        nl.setContentsMargins(12, 26, 12, 16)
        nl.setSpacing(2)
        nl.addWidget(_label("Settings", "Title"))
        nl.addSpacing(12)
        self.nav = {}
        for sid, name, icon in SECTIONS:
            b = QPushButton(glyph(icon, 18), "  " + name.replace("&", "&&"))
            b.setIconSize(QSize(18, 18))
            b.setObjectName("SubNavItem")
            b.setCheckable(True)
            b.setAutoExclusive(True)
            b.clicked.connect(lambda _=False, s=sid: self.show_section(s))
            nl.addWidget(b)
            self.nav[sid] = b
        nl.addStretch(1)
        root.addWidget(nav)

        right = QVBoxLayout()
        right.setContentsMargins(32, 26, 32, 18)
        right.setSpacing(14)
        self.heading = _label("", "PageHeading")
        right.addWidget(self.heading)
        self.stack = QStackedWidget()
        self.panels = {"hotkeys": HotkeysPanel(), "backup": BackupPanel(), "account": AccountPanel(),
                       "general": GeneralPanel(updater, whats_new)}
        self.scrolls = {k: _scroll(p) for k, p in self.panels.items()}
        for s in self.scrolls.values():
            self.stack.addWidget(s)
        right.addWidget(self.stack, 1)
        root.addLayout(right, 1)
        self.show_section("hotkeys")

    def show_section(self, sid):
        self.nav[sid].setChecked(True)
        self.heading.setText(dict((s, n) for s, n, _ in SECTIONS)[sid])
        self.stack.setCurrentWidget(self.scrolls[sid])
