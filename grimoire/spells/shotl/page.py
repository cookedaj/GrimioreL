# SPDX-License-Identifier: GPL-3.0-or-later
"""ShotL page: capture buttons and options on top, then either the gallery of past shots and recordings or the
editor. Grimoire's window hides while a capture is taken, so it's never in the picture."""
import hashlib
import subprocess
import time
from pathlib import Path

from PySide6.QtCore import QObject, QPoint, QPointF, QRect, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import (QColor, QDesktopServices, QIcon, QImage, QImageReader, QPainter, QPen, QPixmap,
                           QPolygonF)
from PySide6.QtWidgets import (QAbstractItemView, QButtonGroup, QCheckBox, QComboBox, QFileDialog,
                               QHBoxLayout, QLabel, QListView, QListWidget, QListWidgetItem, QMenu, QPushButton,
                               QSizePolicy, QStackedWidget, QToolButton, QVBoxLayout, QWidget)

from grimoire.fsutil import human, tilde, trash
from grimoire.jobs import POOL, Job
from grimoire.spells.shotl import capture, record, region, shots
from grimoire.spells.shotl.editor import Editor
from grimoire.spells.shotl.icons import icon

THUMB = QSize(232, 140)
DELAYS = [0, 3, 5, 10]
LOCAL_QSS = """
QToolButton#Capture { background: #101010; border: 1px solid #1f1f1f; border-radius: 10px; padding: 12px 6px 10px 6px;
                      color: #d0d0d0; font-size: 12px; }
QToolButton#Capture:hover { border-color: #5a5a5a; color: #ffffff; }
QToolButton#Capture:pressed { background: #151515; }
QToolButton#Capture[on="true"] { background: #f2f2f2; color: #000000; border-color: #f2f2f2; font-weight: 600; }
QToolButton#Capture::menu-indicator { image: none; width: 0; }
QListWidget#Gallery::item { color: #a8a8a8; padding: 8px; }
"""


class _Signals(QObject):
    thumb = Signal(str, object)


def _label(text="", name="", wrap=False) -> QLabel:
    lab = QLabel(text)
    if name:
        lab.setObjectName(name)
    lab.setWordWrap(wrap)
    return lab


def _repolish(w: QWidget):
    w.style().unpolish(w)
    w.style().polish(w)


def _video_frame(path: Path) -> QImage | None:
    """One frame from a recording via ffmpeg, cached by file name + mtime."""
    st = path.stat()
    key = hashlib.sha1(f"{path}:{st.st_mtime_ns}".encode()).hexdigest()[:20]
    out = shots.TEMP / "thumbs" / f"{key}.jpg"
    if not out.is_file():
        out.parent.mkdir(parents=True, exist_ok=True)
        try:
            subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-ss", "0.5", "-i", str(path),
                            "-frames:v", "1", "-vf", f"scale={THUMB.width() * 2}:-2", str(out)],
                           capture_output=True, timeout=20)
        except (OSError, subprocess.TimeoutExpired):
            return None
    img = QImage(str(out))
    return None if img.isNull() else img


def _thumb(path: Path, video: bool) -> QImage:
    """A tile-sized image (on a pool thread): the picture fitted on black, a play mark on recordings."""
    if video:
        src = _video_frame(path)
    else:
        reader = QImageReader(str(path))
        size = reader.size()
        if size.isValid():
            reader.setScaledSize(size.scaled(THUMB * 2, Qt.AspectRatioMode.KeepAspectRatio))
        src = reader.read()
    tile = QImage(THUMB * 2, QImage.Format.Format_ARGB32_Premultiplied)
    tile.fill(QColor("#060606"))
    p = QPainter(tile)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    if src is not None and not src.isNull():
        s = src.size().scaled(tile.size(), Qt.AspectRatioMode.KeepAspectRatio)
        p.drawImage(QRect(QPoint((tile.width() - s.width()) // 2, (tile.height() - s.height()) // 2), s), src)
    if video:
        c = tile.rect().center()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 170))
        p.drawEllipse(c, 34, 34)
        p.setPen(QPen(QColor("#ffffff"), 3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                      Qt.PenJoinStyle.RoundJoin))        # drawn, not a QPixmap: this runs on a pool thread
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPolygon(QPolygonF([QPointF(c.x() - 9, c.y() - 15), QPointF(c.x() + 15, c.y()),
                                 QPointF(c.x() - 9, c.y() + 15)]))
    p.end()
    tile.setDevicePixelRatio(2)
    return tile


class ShotLPage(QWidget):
    def __init__(self):
        super().__init__()
        self.setObjectName("Page")
        self.setStyleSheet(LOCAL_QSS)
        self.settings = shots.load()
        self._sig = _Signals()
        self._sig.thumb.connect(self._thumb_ready)
        self._thumbs: dict[str, QPixmap] = {}
        self._pending: set[str] = set()
        self.filter = "all"

        root = QVBoxLayout(self)
        root.setContentsMargins(40, 30, 40, 22)
        root.setSpacing(16)

        head = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(2)
        titles.addWidget(_label("ShotL", "Title"))
        titles.addWidget(_label("Screenshots and screen recordings, an editor to mark them up, and every one you've "
                                "taken.", "Subtitle", wrap=True))
        head.addLayout(titles, 1)
        root.addLayout(head)

        # capture buttons
        row = QHBoxLayout()
        row.setSpacing(10)
        self.region_btn = self._capture_btn("region", "Region", "Drag out part of the screen")
        self.region_btn.clicked.connect(lambda: self.capture("region"))
        self.window_btn = self._capture_btn("window", "Window", "The active window (the one you used before "
                                            "ShotL; use the delay to pick another)")
        self.window_btn.clicked.connect(lambda: self.capture("window"))
        self.screen_btn = self._capture_btn("desktop", "Screen", "All screens, or one of them")
        self.screen_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.screen_menu = QMenu(self)
        self.screen_menu.aboutToShow.connect(self._fill_screens)
        self.screen_btn.setMenu(self.screen_menu)
        self.record_btn = self._capture_btn("record", "Record", "Record a screen or a window")
        self.record_btn.clicked.connect(self.toggle_record)
        for b in (self.region_btn, self.window_btn, self.screen_btn, self.record_btn):
            row.addWidget(b, 1)
        root.addLayout(row)

        # options
        self.opts_w = QWidget()
        opts = QHBoxLayout(self.opts_w)
        opts.setContentsMargins(0, 0, 0, 0)
        opts.setSpacing(10)
        opts.addWidget(_label("DELAY", "Section"))
        self.delays = QButtonGroup(self)
        for i, d in enumerate(DELAYS):
            b = QPushButton(f"{d} s" if d else "Off")
            b.setObjectName("Segment")
            b.setProperty("pos", "first" if i == 0 else "last" if i == len(DELAYS) - 1 else "mid")
            b.setCheckable(True)
            b.setChecked(d == self.settings["delay"])
            b.clicked.connect(lambda _=False, v=d: self._set(delay=v))
            self.delays.addButton(b)
            opts.addWidget(b)
        opts.addSpacing(14)
        opts.addWidget(_label("AFTER", "Section"))
        self.after = QComboBox()
        for k, v in shots.AFTER.items():
            self.after.addItem(v, k)
        self.after.setCurrentIndex(list(shots.AFTER).index(self.settings["after"]))
        self.after.currentIndexChanged.connect(lambda _: self._set(after=self.after.currentData()))
        opts.addWidget(self.after)
        opts.addSpacing(14)
        self.pointer = QCheckBox("Pointer in shots")
        self.pointer.setChecked(self.settings["pointer"])
        self.pointer.toggled.connect(lambda on: self._set(pointer=on))
        self.sound = QCheckBox("Sound in recordings")
        self.sound.setToolTip("Records what's playing (your default output), not the microphone")
        self.sound.setChecked(self.settings["sound"])
        self.sound.toggled.connect(lambda on: self._set(sound=on))
        opts.addWidget(self.pointer)
        opts.addWidget(self.sound)
        opts.addStretch(1)
        self.folder_btn = QPushButton()
        self.folder_btn.setObjectName("Link")
        self.folder_btn.setIcon(icon("folder", 16))
        self.folder_btn.setToolTip("Where shots and recordings are saved. Click to change")
        self.folder_btn.clicked.connect(self._pick_folder)
        opts.addWidget(self.folder_btn)
        root.addWidget(self.opts_w)

        # body: gallery or editor
        self.stack = QStackedWidget()
        self.stack.addWidget(self._gallery())
        self.editor = Editor()
        self.editor.closed.connect(self._editor_closed)
        self.editor.saved.connect(lambda _: self.refresh())
        self.editor.toast.connect(self.say)
        self.stack.addWidget(self.editor)
        root.addWidget(self.stack, 1)
        self.stack.currentChanged.connect(self._mode_changed)

        foot = QHBoxLayout()
        self.hint = _label("", "Muted", wrap=True)
        self.hint.setTextFormat(Qt.TextFormat.RichText)
        foot.addWidget(self.hint, 1)
        self.toast = _label("", "Toast", wrap=True)
        self.toast.hide()
        foot.addWidget(self.toast, 0, Qt.AlignmentFlag.AlignRight)
        root.addLayout(foot)
        self._toast_timer = QTimer(self, singleShot=True, interval=6000, timeout=self.toast.hide)
        self._rec_timer = QTimer(self, interval=1000, timeout=self._show_record)

        self._update_folder()
        self._update_hint()
        self._show_record()
        self.refresh()

    # ================================================================== layout
    def _capture_btn(self, glyph_name, text, tip) -> QToolButton:
        b = QToolButton()
        b.setObjectName("Capture")
        b.setIcon(icon(glyph_name, 26))
        b.setIconSize(QSize(26, 26))
        b.setText(text)
        b.setToolTip(tip)
        b.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        b.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        b.setMinimumHeight(78)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        return b

    def _gallery(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        bar = QHBoxLayout()
        bar.setSpacing(0)
        self.tabs = QButtonGroup(self)
        for key, text in (("all", "All"), ("shots", "Screenshots"), ("videos", "Recordings")):
            b = QPushButton(text)
            b.setObjectName("Tab")
            b.setCheckable(True)
            b.setChecked(key == self.filter)
            b.clicked.connect(lambda _=False, k=key: self._set_filter(k))
            self.tabs.addButton(b)
            bar.addWidget(b)
        bar.addSpacing(12)
        self.count = _label("", "Muted")
        bar.addWidget(self.count)
        bar.addStretch(1)
        self.actions = {}
        for key, glyph_name, tip, slot in (
                ("open", "play", "Open in its app", self.open_selected),
                ("edit", "edit", "Edit a copy in ShotL", self.edit_selected),
                ("copy", "copies", "Copy (paste the file or the picture)", self.copy_selected),
                ("folder", "folder", "Show in VaultL", self.show_in_vault),
                ("trash", "trash", "Move to the Trash", self.trash_selected)):
            t = QToolButton()
            t.setObjectName("Tool")
            t.setIcon(icon(glyph_name, 18))
            t.setIconSize(QSize(18, 18))
            t.setToolTip(tip)
            t.setAutoRaise(True)
            t.clicked.connect(slot)
            self.actions[key] = t
            bar.addWidget(t)
        lay.addLayout(bar)

        self.list = QListWidget()
        self.list.setObjectName("Gallery")
        self.list.setViewMode(QListView.ViewMode.IconMode)
        self.list.setIconSize(THUMB)
        self.list.setGridSize(THUMB + QSize(24, 50))
        self.list.setResizeMode(QListView.ResizeMode.Adjust)
        self.list.setMovement(QListView.Movement.Static)
        self.list.setUniformItemSizes(True)
        self.list.setWordWrap(True)
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._menu)
        self.list.itemDoubleClicked.connect(lambda it: self.edit_selected() if not it.data(Qt.ItemDataRole.UserRole + 1)
                                            else self.open_selected())
        self.list.itemSelectionChanged.connect(self._update_actions)
        self.empty = _label("Nothing captured yet. Pick Region, Window or Screen above, or bind a key to "
                            "grimoire-shotl (see below).", "Muted", wrap=True)
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.views = QStackedWidget()
        self.views.addWidget(self.list)
        self.views.addWidget(self.empty)
        lay.addWidget(self.views, 1)
        return w

    # ================================================================== settings
    def _set(self, **changes):
        self.settings.update(changes)
        shots.update(**changes)

    def _update_folder(self):
        self.folder_btn.setText(tilde(shots.folder(self.settings)))

    def _pick_folder(self):
        d = QFileDialog.getExistingDirectory(self, "Save shots in", str(shots.folder(self.settings)))
        if d:
            default = shots.pictures() / "Screenshots"
            self._set(folder="" if Path(d) == default else d)
            self._update_folder()

    def _update_hint(self):
        def key(t):
            return f"<span style='font-family: IBM Plex Mono; color: #d0d0d0'>{t}</span>"
        how = capture.backend()
        stills = {"spectacle": "Shots via Spectacle", "portal": "Shots via the desktop portal (whole screen only)",
                  "": "No screenshot tool found: install Spectacle"}[how]
        self.hint.setText(f"{stills} · Recordings: {record.describe()}<br>Hotkeys: System Settings → Keyboard → "
                          f"Shortcuts → Add New → Command, then {key('grimoire-shotl region')}, "
                          f"{key('grimoire-shotl window')}, {key('grimoire-shotl full')} or "
                          f"{key('grimoire-shotl record')} (press again to stop)")

    def say(self, text: str):
        self.toast.setText(text)
        self.toast.show()
        self._toast_timer.start()

    # ================================================================== capturing
    def _fill_screens(self):
        from PySide6.QtGui import QGuiApplication
        m = self.screen_menu
        m.clear()
        m.addAction("All screens", lambda: self.capture("full"))
        m.addAction("Screen under the pointer", lambda: self.capture("screen"))
        screens = QGuiApplication.screens()
        if len(screens) > 1:
            m.addSeparator()
            for s in screens:
                g = s.geometry()
                m.addAction(f"{s.name()}  ·  {g.width()}×{g.height()}", lambda s=s: self.capture("monitor", s))

    def capture(self, mode: str, screen=None):
        """Hide our window, wait for it (and the delay) to clear the screen, then grab."""
        if not capture.backend():
            self.say("No screenshot tool found: install Spectacle (sudo apt install kde-spectacle)")
            return
        if self.stack.currentIndex() == 1 and not self.editor.request_close():
            return
        win = self.window()
        win.hide()
        QTimer.singleShot(450 + int(self.settings["delay"]) * 1000, lambda: self._grab(mode, screen))

    def _grab(self, mode, screen):
        win = self.window()
        try:
            raw = capture.take(capture.grab("full" if mode in ("region", "monitor") else mode,
                                            pointer=self.settings["pointer"] and mode != "region"))
            if mode == "region":
                rect = region.pick(raw)
                raw = raw.copy(rect) if rect else None
            elif mode == "monitor":
                raw = raw.copy(capture.screen_rect(raw, screen))
        except capture.CaptureError as e:
            raw = None
            self.say(str(e))
        win.show()
        win.raise_()
        win.activateWindow()
        if raw is not None and not raw.isNull():
            self.handle(raw)

    def handle(self, img: QImage):
        """What happens after a capture, per the "After" setting."""
        after = self.settings["after"]
        if after == "edit":
            self.editor.load(img)
            self.stack.setCurrentIndex(1)
            self.editor.canvas.setFocus()
            return
        dest = shots.new_path()
        if not img.save(str(dest), "PNG"):
            shots.release(dest)
            self.say(f"Couldn't write {tilde(dest)}")
            return
        shots.add(dest)
        if after == "copy":
            capture.copy_image(img)
        self.say(("Copied and saved " if after == "copy" else "Saved ") + tilde(dest))
        self.refresh()

    def _mode_changed(self, i: int):
        """The editor gets the room the options and hotkey hint take in the gallery."""
        self.opts_w.setVisible(i == 0)
        self.hint.setVisible(i == 0)

    def _editor_closed(self):
        self.stack.setCurrentIndex(0)
        self.refresh()

    # ================================================================== recording
    def toggle_record(self):
        if record.stop():
            self.say("Finishing the recording…")
            QTimer.singleShot(1500, self.refresh)
        else:
            msg = record.start(sound=self.settings["sound"])
            self.say(msg or "Pick a screen or window if KDE asks; press Stop (or grimoire-shotl record) to finish")
        self._show_record()
        self._rec_timer.start()

    def _show_record(self):
        st = record.state()
        b = self.record_btn
        if st:
            secs = int(time.time() - st["started"])
            b.setText(f"Stop  {secs // 60}:{secs % 60:02d}")
            b.setIcon(icon("stop", 26))
        else:
            b.setText("Record")
            b.setIcon(icon("record", 26))
            if self._rec_timer.isActive() and not self.isVisible():
                self._rec_timer.stop()
        b.setProperty("on", bool(st))
        _repolish(b)
        if st and not self._rec_timer.isActive():
            self._rec_timer.start()
        if not st and getattr(self, "_was_recording", False):
            self.refresh()                                  # the new recording just landed
        self._was_recording = bool(st)

    def showEvent(self, e):
        super().showEvent(e)
        self.refresh()
        self._show_record()
        self._rec_timer.start()

    def hideEvent(self, e):
        super().hideEvent(e)
        if not record.state():
            self._rec_timer.stop()

    # ================================================================== gallery
    def _set_filter(self, key):
        self.filter = key
        self.refresh()

    def refresh(self):
        items = shots.entries()
        if self.filter == "shots":
            items = [e for e in items if not e["video"]]
        elif self.filter == "videos":
            items = [e for e in items if e["video"]]
        keep = {it.data(Qt.ItemDataRole.UserRole) for it in self.list.selectedItems()}
        self.list.clear()
        placeholder = QPixmap(THUMB)
        placeholder.fill(QColor("#060606"))
        for e in items:
            path = Path(e["path"])
            try:
                size = human(path.stat().st_size)
            except OSError:
                continue
            it = QListWidgetItem(f"{path.name}\n{shots.ago(e['time'])} · {size}")
            it.setData(Qt.ItemDataRole.UserRole, e["path"])
            it.setData(Qt.ItemDataRole.UserRole + 1, e["video"])
            it.setToolTip(tilde(path))
            it.setTextAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
            key = self._key(path)
            it.setIcon(QIcon(self._thumbs.get(key, placeholder)))
            self.list.addItem(it)
            if e["path"] in keep:
                it.setSelected(True)
            if key not in self._thumbs and key not in self._pending:
                self._pending.add(key)
                POOL.start(Job(lambda p=path, v=e["video"]: (str(p), _thumb(p, v)),
                               lambda r, k=key: self._sig.thumb.emit(k, r[1])))
        total = len(items)
        self.count.setText(f"{total} item{'s' if total != 1 else ''}")
        self.views.setCurrentIndex(0 if total else 1)
        self._update_actions()

    @staticmethod
    def _key(path: Path) -> str:
        try:
            return f"{path}:{path.stat().st_mtime_ns}"
        except OSError:
            return str(path)

    def _thumb_ready(self, key: str, img: QImage):
        self._pending.discard(key)
        self._thumbs[key] = QPixmap.fromImage(img)
        path = key.rsplit(":", 1)[0]
        for i in range(self.list.count()):
            it = self.list.item(i)
            if it.data(Qt.ItemDataRole.UserRole) == path:
                it.setIcon(QIcon(self._thumbs[key]))

    def selected(self) -> list[Path]:
        return [Path(it.data(Qt.ItemDataRole.UserRole)) for it in self.list.selectedItems()]

    def _update_actions(self):
        sel = self.list.selectedItems()
        one = len(sel) == 1
        is_video = one and bool(sel[0].data(Qt.ItemDataRole.UserRole + 1))
        self.actions["open"].setEnabled(one)
        self.actions["edit"].setEnabled(one and not is_video)
        self.actions["copy"].setEnabled(one)
        self.actions["folder"].setEnabled(one)
        self.actions["trash"].setEnabled(bool(sel))

    def _menu(self, pos):
        if not self.list.itemAt(pos):
            return
        self._update_actions()
        m = QMenu(self)
        for key, text in (("open", "Open"), ("edit", "Edit"), ("copy", "Copy"), ("folder", "Show in VaultL"),
                          ("trash", "Move to Trash")):
            a = m.addAction(text, self.actions[key].click)
            a.setEnabled(self.actions[key].isEnabled())
        m.exec(self.list.viewport().mapToGlobal(pos))

    def open_selected(self):
        for p in self.selected()[:1]:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(p)))

    def edit_selected(self):
        for p in self.selected()[:1]:
            img = QImage(str(p))
            if img.isNull():
                self.say(f"Couldn't open {p.name}")
                return
            self.editor.load(img, source=p)
            self.stack.setCurrentIndex(1)
            self.editor.canvas.setFocus()

    def copy_selected(self):
        for p in self.selected()[:1]:
            capture.copy_file(p)
            self.say(f"Copied {p.name}")

    def show_in_vault(self):
        from grimoire import tray
        for p in self.selected()[:1]:
            try:
                tray.launch("grimoire-vaultl", str(p))
            except OSError as e:
                self.say(f"Couldn't open VaultL: {e}")

    def trash_selected(self):
        done, errors = 0, []
        for p in self.selected():
            try:
                trash(p)
                done += 1
            except OSError as e:
                errors.append(str(e))
        self.say(f"Moved {done} to the Trash" + (f" · {errors[0]}" if errors else ""))
        self.refresh()
