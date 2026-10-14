"""SightsL page: design the crosshair with a live preview; every change goes straight to the overlay."""
import subprocess

from PySide6.QtCore import QFileSystemWatcher, QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QGuiApplication, QImage, QLinearGradient, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QAbstractButton, QButtonGroup, QCheckBox, QColorDialog, QComboBox, QFrame,
                               QGridLayout, QHBoxLayout, QInputDialog, QLabel, QMenu, QMessageBox, QPushButton,
                               QScrollArea, QVBoxLayout, QWidget)

from grimoire.paths import CONFIG, HOME, command
from grimoire.spells.mural import library as mural_library
from grimoire.spells.sightc import draw, overlay
from grimoire.spells.sightc.config import (COLORS, LIMITS, PRESETS, STYLES, Crosshair, load_profiles, save_profiles)
from grimoire.widgets import Slider

AUTOSTART = HOME / ".config/autostart/grimoire-sightc.desktop"
ZOOM_BOX = 192        # px; the zoom picks the biggest whole factor (2..8) that still shows the whole crosshair
# styles where a setting does nothing, so its control is greyed out
USES_GAP = {"Cross", "Cross + dot", "T", "Circle + cross"}
USES_DOT = {"Dot", "Cross + dot", "Circle + dot"}


def _segments(names, on_click) -> tuple[QHBoxLayout, dict[str, QPushButton]]:
    """A joined row of checkable buttons (theme's #Segment), one checked at a time."""
    row, group, buttons = QHBoxLayout(), QButtonGroup(), {}
    row.setSpacing(0)
    for i, name in enumerate(names):
        b = QPushButton(name)
        b.setObjectName("Segment")
        b.setCheckable(True)
        b.setProperty("pos", "first" if i == 0 else "last" if i == len(names) - 1 else "mid")
        b.clicked.connect(lambda _=False, n=name: on_click(n))
        group.addButton(b)
        row.addWidget(b)
        buttons[name] = b
    row.group = group                     # keep the exclusive group alive with the layout
    return row, buttons


class Tile(QAbstractButton):
    """A square button showing a crosshair, with an optional name underneath."""

    def __init__(self, cfg: Crosshair, label: str = "", side: int = 64):
        super().__init__()
        self.cfg, self.label = cfg, label
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(side, side + (18 if label else 0))

    def sizeHint(self):
        return self.size()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        box = QRectF(0.5, 0.5, self.width() - 1, self.width() - 1)
        edge = "#f2f2f2" if self.isChecked() else "#5a5a5a" if self.underMouse() else "#232323"
        p.setPen(QPen(QColor(edge), 1))
        p.setBrush(QColor("#121212"))
        p.drawRoundedRect(box, 8, 8)
        c = self.cfg.copy(offset_x=0, offset_y=0)
        fit = (box.width() / 2 - 8) / max(8, draw.extent(c) - 4)       # shrink big crosshairs to fit the tile
        p.save()
        p.translate(box.center())
        if fit < 1:
            p.scale(fit, fit)
        draw.paint(p, c, 0, 0)
        p.restore()
        if self.label:
            p.setPen(QColor("#ffffff" if self.isChecked() else "#8c8c8c"))
            p.drawText(QRectF(0, box.bottom() + 2, self.width(), 16), Qt.AlignmentFlag.AlignCenter, self.label)

    def enterEvent(self, e):
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self.update()
        super().leaveEvent(e)


class Preview(QWidget):
    """Crosshair at real size over a backdrop, plus a pixel-exact zoom of the centre in the corner."""

    def __init__(self, cfg: Crosshair):
        super().__init__()
        self.cfg = cfg
        self.backdrop = "Dark"
        self._image: QPixmap | None = None
        self.setMinimumSize(520, 360)

    def set_backdrop(self, name: str):
        self.backdrop = name
        self._image = None
        if name == "Wallpaper":
            pics = [p for p in mural_library.items() if not mural_library.is_video(p)]
            if pics:
                self._image = QPixmap(str(pics[0]))
        self.update()

    def _paint_backdrop(self, p: QPainter, rect: QRectF):
        if self.backdrop == "Wallpaper" and self._image and not self._image.isNull():
            img = self._image.scaled(rect.size().toSize(), Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                     Qt.TransformationMode.SmoothTransformation)
            p.drawPixmap(rect.topLeft(), img, QRectF((img.width() - rect.width()) / 2,
                                                     (img.height() - rect.height()) / 2, rect.width(), rect.height()))
        else:
            top, bottom = ("#e9e9e9", "#bdbdbd") if self.backdrop == "Light" else ("#2a2a2a", "#0d0d0d")
            g = QLinearGradient(rect.topLeft(), rect.bottomLeft())
            g.setColorAt(0, QColor(top))
            g.setColorAt(1, QColor(bottom))
            p.fillRect(rect, g)

    def paintEvent(self, _):
        p = QPainter(self)
        r = QRectF(self.rect())
        cx, cy = self.width() // 2, self.height() // 2            # whole pixels, like the overlay
        self._paint_backdrop(p, r)
        draw.paint(p, self.cfg, cx, cy)

        # zoom: grab the real pixels around the centre and blow them up without smoothing
        side = ZOOM_BOX
        b = draw.shape(self.cfg.copy(offset_x=0, offset_y=0), 0, 0).boundingRect()
        reach = 2 * (max(abs(b.left()), abs(b.right()), abs(b.top()), abs(b.bottom())) + self.cfg.outline_width + 2)
        zoom = max(2, min(8, int(side // max(1, reach))))
        n = side // zoom
        src = QImage(n, n, QImage.Format.Format_ARGB32_Premultiplied)
        sp = QPainter(src)
        sp.translate(n // 2 - cx - self.cfg.offset_x, n // 2 - cy - self.cfg.offset_y)
        self._paint_backdrop(sp, r)
        draw.paint(sp, self.cfg, cx, cy)
        sp.end()
        side = n * zoom
        box = QRectF(r.right() - side - 16, r.bottom() - side - 16, side, side)
        p.drawImage(box, src)
        p.setPen(QPen(QColor(128, 128, 128, 40), 1))                # faint pixel grid
        for i in range(1, n):
            p.drawLine(QPointF(box.left() + i * zoom, box.top()), QPointF(box.left() + i * zoom, box.bottom()))
            p.drawLine(QPointF(box.left(), box.top() + i * zoom), QPointF(box.right(), box.top() + i * zoom))
        p.setPen(QPen(QColor("#f2f2f2"), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(box)
        p.fillRect(QRectF(box.left() + 1, box.top() + 1, 34, 18), QColor(0, 0, 0, 170))
        p.setPen(QColor("#d0d0d0"))
        p.drawText(QRectF(box.left() + 1, box.top() + 1, 34, 18), Qt.AlignmentFlag.AlignCenter, f"{zoom}×")


class SightCPage(QWidget):
    def __init__(self):
        super().__init__()
        self.setObjectName("Page")
        self.cfg = Crosshair.load()
        self._loading = True
        self._save_timer = QTimer(self, singleShot=True, interval=40, timeout=self._save)

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._build_main(), 1)
        root.addWidget(self._build_panel())
        self._load_into_controls()
        self._loading = False
        self._refresh_running()
        QTimer(self, interval=1500, timeout=self._refresh_running).start()
        # the next-crosshair hotkey (or another Grimoire window) can change the file under us
        self._watcher = QFileSystemWatcher([str(CONFIG)], self)
        self._watcher.directoryChanged.connect(self._file_changed)

    # ------------------------------------------------------------------ layout
    def _build_main(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(36, 32, 24, 24)
        lay.setSpacing(16)

        head = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(4)
        t = QLabel("SightsL")
        t.setObjectName("Title")
        sub = QLabel("A crosshair drawn above every window and game. Click-through, pixel-sharp.")
        sub.setObjectName("Subtitle")
        titles.addWidget(t)
        titles.addWidget(sub)
        keys = QHBoxLayout()
        keys.setSpacing(6)
        keys.setContentsMargins(0, 6, 0, 0)
        self.key_toggle, self.key_next = QLabel(), QLabel()
        for key, what in ((self.key_toggle, "show / hide"), (self.key_next, "next crosshair")):
            key.setObjectName("Key")
            lbl = QLabel(what)
            lbl.setObjectName("Muted")
            keys.addWidget(key)
            keys.addWidget(lbl)
            keys.addSpacing(10)
        change = QPushButton("Change keys")
        change.setObjectName("Link")
        change.setCursor(Qt.CursorShape.PointingHandCursor)
        change.clicked.connect(lambda: subprocess.Popen(["systemsettings", "kcm_keys"], start_new_session=True,
                                                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
        keys.addWidget(change)
        keys.addStretch(1)
        titles.addLayout(keys)
        head.addLayout(titles, 1)

        side = QVBoxLayout()
        side.setSpacing(6)
        self.toggle = QPushButton()
        self.toggle.setObjectName("Primary")
        self.toggle.setMinimumSize(170, 40)
        self.toggle.clicked.connect(self._toggle_overlay)
        self.state = QLabel()
        self.state.setObjectName("Muted")
        self.state.setAlignment(Qt.AlignmentFlag.AlignCenter)
        side.addWidget(self.toggle)
        side.addWidget(self.state)
        side.addStretch(1)
        head.addLayout(side)
        lay.addLayout(head)

        self.preview = Preview(self.cfg)
        frame = QFrame()
        frame.setObjectName("Card")
        fl = QVBoxLayout(frame)
        fl.setContentsMargins(1, 1, 1, 1)
        fl.addWidget(self.preview)
        lay.addWidget(frame, 1)

        row = QHBoxLayout()
        lbl = QLabel("Backdrop")
        lbl.setObjectName("Muted")
        row.addWidget(lbl)
        row.addSpacing(6)
        seg, self.backdrops = _segments(("Dark", "Light", "Wallpaper"), self.preview.set_backdrop)
        self.backdrops["Dark"].setChecked(True)
        row.addLayout(seg)
        row.addStretch(1)
        hint = QLabel("Corner: real pixels, magnified")
        hint.setObjectName("Muted")
        row.addWidget(hint)
        lay.addLayout(row)
        return w

    def _section(self, lay, text, right: QWidget | None = None):
        lab = QLabel(text)
        lab.setObjectName("Section")
        lay.addSpacing(10)
        if right is None:
            lay.addWidget(lab)
            return
        row = QHBoxLayout()
        row.addWidget(lab)
        row.addStretch(1)
        row.addWidget(right)
        lay.addLayout(row)

    def _small(self, text, slot) -> QPushButton:
        b = QPushButton(text)
        b.setObjectName("Link")
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.clicked.connect(slot)
        return b

    def _build_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("Panel")
        panel.setFixedWidth(360)
        outer = QVBoxLayout(panel)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body = QWidget()
        body.setObjectName("Page")
        lay = QVBoxLayout(body)
        lay.setContentsMargins(24, 22, 24, 24)
        lay.setSpacing(8)
        ch = self._changed

        # presets + your saved crosshairs
        self._section(lay, "PRESETS")
        grid = QGridLayout()
        grid.setSpacing(8)
        self.preset_tiles: dict[str, Tile] = {}
        for i, (name, c) in enumerate(PRESETS.items()):
            tile = Tile(c, name, 64)
            tile.clicked.connect(lambda _=False, c=c: self._apply_look(c))
            grid.addWidget(tile, i // 4, i % 4)
            self.preset_tiles[name] = tile
        lay.addLayout(grid)

        self._section(lay, "SAVED", self._small("Save current…", self._save_profile))
        self.saved_grid = QGridLayout()
        self.saved_grid.setSpacing(8)
        self.saved_grid.setColumnStretch(4, 1)          # keep tiles left-aligned like the presets
        lay.addLayout(self.saved_grid)
        self.saved_empty = QLabel("Save crosshairs you like, then flip through them in-game with the next key.")
        self.saved_empty.setObjectName("Muted")
        self.saved_empty.setWordWrap(True)
        lay.addWidget(self.saved_empty)
        self.saved_tiles: dict[str, Tile] = {}
        codes = QHBoxLayout()
        codes.addWidget(self._small("Copy share code", self._copy_code))
        codes.addWidget(self._small("Paste code", self._paste_code))
        codes.addStretch(1)
        lay.addLayout(codes)

        self._section(lay, "STYLE")
        sg = QGridLayout()
        sg.setSpacing(6)
        self.style_group = QButtonGroup(self)
        self.style_tiles: dict[str, Tile] = {}
        for i, name in enumerate(STYLES):
            demo = Crosshair(style=name, size=9, thickness=2, gap=3, dot=2, outline=False,
                             rotation=0, round_caps=name == "Chevron")
            tile = Tile(demo, "", 56)
            tile.setToolTip(name)
            tile.clicked.connect(lambda _=False, n=name: self._set_style(n))
            self.style_group.addButton(tile)
            sg.addWidget(tile, i // 5, i % 5)
            self.style_tiles[name] = tile
        lay.addLayout(sg)
        self.style_name = QLabel()
        self.style_name.setObjectName("Muted")
        lay.addWidget(self.style_name)

        self._section(lay, "COLOR")
        swatches = QHBoxLayout()
        swatches.setSpacing(6)
        self.swatch_buttons = {}
        for name, hexc in COLORS.items():
            b = QPushButton()
            b.setToolTip(name)
            b.setFixedSize(30, 30)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _=False, h=hexc: self._set_color(h))
            self.swatch_buttons[hexc] = b
            swatches.addWidget(b)
        self.custom = QPushButton("+")
        self.custom.setToolTip("Custom color…")
        self.custom.setFixedSize(30, 30)
        self.custom.setCursor(Qt.CursorShape.PointingHandCursor)
        self.custom.clicked.connect(self._pick_color)
        swatches.addWidget(self.custom)
        swatches.addStretch(1)
        lay.addLayout(swatches)

        self._section(lay, "SHAPE")
        grid = QGridLayout()
        grid.setVerticalSpacing(6)
        grid.setHorizontalSpacing(12)
        self.size = Slider(1, 60, " px", ch)
        self.thick = Slider(1, 10, " px", ch)
        self.gap = Slider(0, 30, " px", ch)
        self.dot = Slider(0, 10, " px", ch)
        self.rotation = Slider(0, 90, "°", ch)
        self.opacity = Slider(10, 100, "%", ch)
        self.shape_labels = {}
        for r, (name, w) in enumerate((("Size", self.size), ("Thickness", self.thick), ("Gap", self.gap),
                                       ("Center dot", self.dot), ("Rotation", self.rotation),
                                       ("Opacity", self.opacity))):
            self.shape_labels[w] = QLabel(name)
            grid.addWidget(self.shape_labels[w], r, 0)
            grid.addWidget(w, r, 1)
        lay.addLayout(grid)
        self.round_caps = QCheckBox("Rounded ends")
        self.round_caps.toggled.connect(ch)
        lay.addWidget(self.round_caps)

        self._section(lay, "OUTLINE")
        self.outline = QCheckBox("Outline for contrast")
        self.outline.toggled.connect(ch)
        lay.addWidget(self.outline)
        og = QGridLayout()
        og.setHorizontalSpacing(12)
        self.outline_w = Slider(1, 4, " px", ch)
        seg, self.outline_c = _segments(("Black", "White"), lambda _: ch())
        self.outline_label_w, self.outline_label_c = QLabel("Width"), QLabel("Color")
        og.addWidget(self.outline_label_w, 0, 0)
        og.addWidget(self.outline_w, 0, 1)
        og.addWidget(self.outline_label_c, 1, 0)
        og.addLayout(seg, 1, 1)
        lay.addLayout(og)

        self._section(lay, "POSITION", self._small("Center", self._center))
        pos = QGridLayout()
        pos.setHorizontalSpacing(12)
        self.off_x = Slider(*LIMITS["offset_x"], " px", ch)
        self.off_y = Slider(*LIMITS["offset_y"], " px", ch)
        for s in (self.off_x, self.off_y):
            s.v.setFixedWidth(58)
        pos.addWidget(QLabel("Offset X"), 0, 0)
        pos.addWidget(self.off_x, 0, 1)
        pos.addWidget(QLabel("Offset Y"), 1, 0)
        pos.addWidget(self.off_y, 1, 1)
        self.screen = QComboBox()
        self.screen.addItem("Primary screen", "")
        for s in QGuiApplication.screens():
            self.screen.addItem(f"{s.name()}  ·  {s.size().width()}×{s.size().height()}", s.name())
        self.screen.currentIndexChanged.connect(ch)
        self.screen_label = QLabel("Screen")
        pos.addWidget(self.screen_label, 2, 0)
        pos.addWidget(self.screen, 2, 1)
        multi = len(QGuiApplication.screens()) > 1
        self.screen.setVisible(multi)                  # one monitor: nothing to choose
        self.screen_label.setVisible(multi)
        lay.addLayout(pos)

        self._section(lay, "STARTUP")
        self.autostart = QCheckBox("Show crosshair at login")
        self.autostart.setChecked(AUTOSTART.exists())
        self.autostart.toggled.connect(self._set_autostart)
        lay.addWidget(self.autostart)

        lay.addSpacing(16)
        lay.addStretch(1)
        reset = QPushButton("Reset to default")
        reset.clicked.connect(lambda: self._apply_look(Crosshair()))
        lay.addWidget(reset)

        scroll.setWidget(body)
        outer.addWidget(scroll)
        self._fill_saved()
        return panel

    # ------------------------------------------------------------------ state
    def _load_into_controls(self):
        c = self.cfg
        self._loading = True
        self.size.setValue(c.size)
        self.thick.setValue(c.thickness)
        self.gap.setValue(c.gap)
        self.dot.setValue(c.dot)
        self.rotation.setValue(c.rotation)
        self.opacity.setValue(round(c.opacity * 100))
        self.round_caps.setChecked(c.round_caps)
        self.outline.setChecked(c.outline)
        self.outline_w.setValue(max(1, c.outline_width))
        self.outline_c["White" if c.outline_color.lower() in ("#fff", "#ffffff") else "Black"].setChecked(True)
        self.off_x.setValue(c.offset_x)
        self.off_y.setValue(c.offset_y)
        i = self.screen.findData(c.screen)
        self.screen.setCurrentIndex(max(0, i))
        self._loading = False
        self._sync_view()

    def _changed(self, *_):
        if self._loading:
            return
        c = self.cfg
        c.size, c.thickness, c.gap, c.dot = self.size.value(), self.thick.value(), self.gap.value(), self.dot.value()
        c.rotation = self.rotation.value()
        c.opacity = self.opacity.value() / 100
        c.round_caps = self.round_caps.isChecked()
        c.outline = self.outline.isChecked()
        c.outline_width = self.outline_w.value()
        c.outline_color = "#ffffff" if self.outline_c["White"].isChecked() else "#000000"
        c.offset_x, c.offset_y = self.off_x.value(), self.off_y.value()
        c.screen = self.screen.currentData() or ""
        self._sync_view()
        self._save_timer.start()

    def _sync_view(self):
        """Everything that only reflects the current settings: tiles, swatches, greyed-out controls, preview."""
        c = self.cfg
        for name, tile in self.style_tiles.items():
            tile.setChecked(name == c.style)
        self.style_name.setText(c.style)
        look = c.look()
        for tiles, profiles in ((self.preset_tiles, PRESETS), (self.saved_tiles, self._profiles)):
            for name, tile in tiles.items():
                tile.setChecked(name in profiles and profiles[name].look() == look)
        for hexc, b in self.swatch_buttons.items():
            ring = "#ffffff" if hexc.lower() == c.color.lower() else "#2e2e2e"
            b.setStyleSheet(f"background: {hexc}; border: 2px solid {ring}; border-radius: 15px; padding: 0;")
        custom = c.color.lower() not in (h.lower() for h in self.swatch_buttons)
        self.custom.setText("" if custom else "+")
        self.custom.setStyleSheet(
            f"background: {c.color if custom else 'transparent'}; color: #8c8c8c; padding: 0; border-radius: 15px;"
            f"border: {'2px solid #ffffff' if custom else '1px dashed #4a4a4a'};")
        for w, on in ((self.size, c.style != "Dot"), (self.gap, c.style in USES_GAP),
                      (self.dot, c.style in USES_DOT), (self.rotation, c.style != "Dot")):
            w.setEnabled(on)
            self.shape_labels[w].setEnabled(on)
        for w in (self.outline_w, self.outline_label_w, self.outline_label_c, *self.outline_c.values()):
            w.setEnabled(c.outline)
        self.preview.update()

    def _file_changed(self, *_):
        if self._save_timer.isActive():               # our own newer edit is about to be written
            return
        disk = Crosshair.load()
        if disk != self.cfg:
            for k, v in vars(disk).items():
                setattr(self.cfg, k, v)
            self._load_into_controls()

    def _save(self):
        self.cfg.save()

    def _apply_look(self, c: Crosshair):
        """Take a preset/profile/code, keeping which screen the crosshair is on."""
        for k, v in c.look().items():
            setattr(self.cfg, k, v)
        self._load_into_controls()
        self._save()

    def _set_style(self, name: str):
        self.cfg.style = name
        self._changed()

    def _set_color(self, hexc: str):
        self.cfg.color = hexc
        self._changed()

    def _pick_color(self):
        col = QColorDialog.getColor(QColor(self.cfg.color), self, "Crosshair color")
        if col.isValid():
            self._set_color(col.name())

    def _center(self):
        self.cfg.offset_x = self.cfg.offset_y = 0
        self._load_into_controls()
        self._save()

    # ------------------------------------------------------------------ saved profiles and share codes
    def _fill_saved(self):
        self._profiles = load_profiles()
        for tile in self.saved_tiles.values():
            tile.deleteLater()
        self.saved_tiles = {}
        for i, (name, c) in enumerate(self._profiles.items()):
            tile = Tile(c, name if len(name) <= 9 else name[:8] + "…", 64)
            tile.setToolTip(f"{name}\nRight-click to rename or delete")
            tile.clicked.connect(lambda _=False, c=c: self._apply_look(c))
            tile.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            tile.customContextMenuRequested.connect(lambda _pos, n=name, t=tile: self._profile_menu(n, t))
            self.saved_grid.addWidget(tile, i // 4, i % 4)
            self.saved_tiles[name] = tile
        self.saved_empty.setVisible(not self._profiles)

    def _ask_name(self, title: str, text: str = "") -> str:
        name, ok = QInputDialog.getText(self, title, "Name", text=text)
        return name.strip()[:40] if ok else ""

    def _save_profile(self):
        name = self._ask_name("Save crosshair", f"Crosshair {len(self._profiles) + 1}")
        if not name:
            return
        if name in self._profiles and QMessageBox.question(
                self, "Save crosshair", f"Replace the saved crosshair “{name}”?") != QMessageBox.StandardButton.Yes:
            return
        self._profiles[name] = self.cfg.copy()
        save_profiles(self._profiles)
        self._fill_saved()
        self._sync_view()

    def _profile_menu(self, name: str, tile: Tile):
        menu = QMenu(self)
        rename = menu.addAction("Rename…")
        delete = menu.addAction("Delete")
        chosen = menu.exec(tile.mapToGlobal(tile.rect().center()))
        if chosen is rename:
            new = self._ask_name("Rename crosshair", name)
            if new and new != name and new not in self._profiles:
                self._profiles = {new if k == name else k: v for k, v in self._profiles.items()}
        elif chosen is delete:
            if QMessageBox.question(self, "Delete crosshair",
                                    f"Delete the saved crosshair “{name}”?") != QMessageBox.StandardButton.Yes:
                return
            self._profiles.pop(name, None)
        else:
            return
        save_profiles(self._profiles)
        self._fill_saved()
        self._sync_view()

    def _copy_code(self):
        QGuiApplication.clipboard().setText(self.cfg.code())
        self.state.setText("Share code copied")
        QTimer.singleShot(2000, self._refresh_running)

    def _paste_code(self):
        c = Crosshair.from_code(QGuiApplication.clipboard().text())
        if c is None:
            QMessageBox.information(self, "Paste code", "The clipboard doesn't hold a SightsL code (they start "
                                                        "with “SL1-”).")
            return
        self._apply_look(c)

    # ------------------------------------------------------------------ overlay process
    def showEvent(self, e):
        super().showEvent(e)
        self.key_toggle.setText(overlay.hotkey_text(overlay.ACTION))       # may have been rebound in Settings
        self.key_next.setText(overlay.hotkey_text(overlay.NEXT_ACTION))

    def _toggle_overlay(self):
        was_on = overlay.running_pid() is not None
        if was_on:
            overlay.stop()
        else:
            self.cfg.save()
            overlay.start()
        self._refresh_running(on=not was_on)        # the new process takes a moment to write its pid
        QTimer.singleShot(600, self._refresh_running)

    def _refresh_running(self, on: bool | None = None):
        if on is None:
            on = overlay.running_pid() is not None
        self.toggle.setText("Hide crosshair" if on else "Show crosshair")
        self.state.setText("●  On screen" if on else "○  Off")

    def _set_autostart(self, on: bool):
        if on:
            AUTOSTART.parent.mkdir(parents=True, exist_ok=True)
            AUTOSTART.write_text(
                "[Desktop Entry]\nType=Application\nName=Grimoire SightsL\nComment=Crosshair overlay\n"
                f"Exec={command('grimoire-sightc')} on\nIcon=grimoire\nX-KDE-autostart-phase=2\n")
        else:
            AUTOSTART.unlink(missing_ok=True)
