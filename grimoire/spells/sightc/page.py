"""SightsL page: design the crosshair with a live preview; every change goes straight to the overlay."""
from dataclasses import asdict

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QCheckBox, QColorDialog, QComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel,
                               QPushButton, QScrollArea, QSpinBox, QVBoxLayout, QWidget)

from grimoire.paths import HOME
from grimoire.spells.mural import library as mural_library
from grimoire.spells.sightc import draw, overlay
from grimoire.spells.sightc.config import COLORS, STYLES, Crosshair
from grimoire.widgets import Slider

AUTOSTART = HOME / ".config/autostart/grimoire-sightc.desktop"
HOTKEY = "Ctrl+Alt+X"
ZOOM = 4


class Preview(QWidget):
    """Crosshair at real size over a backdrop, plus a zoomed inset in the corner."""

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
        elif self.backdrop == "Light":
            g = QLinearGradient(rect.topLeft(), rect.bottomLeft())
            g.setColorAt(0, QColor("#e9e9e9"))
            g.setColorAt(1, QColor("#bdbdbd"))
            p.fillRect(rect, g)
        else:
            g = QLinearGradient(rect.topLeft(), rect.bottomLeft())
            g.setColorAt(0, QColor("#2a2a2a"))
            g.setColorAt(1, QColor("#0d0d0d"))
            p.fillRect(rect, g)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect())
        p.setPen(Qt.PenStyle.NoPen)
        self._paint_backdrop(p, r)
        draw.paint(p, self.cfg, r.center().x(), r.center().y())

        # zoomed inset (bottom-right)
        box = QRectF(r.right() - 196, r.bottom() - 196, 180, 180)
        p.save()
        p.setClipRect(box)
        p.translate(box.center())
        p.scale(ZOOM, ZOOM)
        p.translate(-r.center())
        self._paint_backdrop(p, r)
        draw.paint(p, self.cfg, r.center().x(), r.center().y())
        p.restore()
        p.setPen(QPen(QColor("#ffffff"), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(box)
        p.setPen(QColor("#9a9a9a"))
        p.drawText(box.adjusted(8, 6, 0, 0), f"{ZOOM}×")


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

    # ------------------------------------------------------------------ layout
    def _build_main(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(36, 32, 24, 24)
        lay.setSpacing(18)

        head = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(2)
        t = QLabel("SightsL")
        t.setObjectName("Title")
        sub = QLabel(f"A crosshair drawn above every window and game. Click-through. Toggle in-game with {HOTKEY}.")
        sub.setObjectName("Subtitle")
        titles.addWidget(t)
        titles.addWidget(sub)
        head.addLayout(titles, 1)
        self.toggle = QPushButton()
        self.toggle.setObjectName("Primary")
        self.toggle.setMinimumSize(170, 40)
        self.toggle.clicked.connect(self._toggle_overlay)
        head.addWidget(self.toggle)
        lay.addLayout(head)

        self.preview = Preview(self.cfg)
        frame = QFrame()
        frame.setObjectName("Card")
        fl = QVBoxLayout(frame)
        fl.setContentsMargins(1, 1, 1, 1)
        fl.addWidget(self.preview)
        lay.addWidget(frame, 1)

        row = QHBoxLayout()
        lbl = QLabel("Preview backdrop")
        lbl.setObjectName("Muted")
        row.addWidget(lbl)
        for name in ("Dark", "Light", "Wallpaper"):
            b = QPushButton(name)
            b.clicked.connect(lambda _=False, n=name: self.preview.set_backdrop(n))
            row.addWidget(b)
        row.addStretch(1)
        self.state = QLabel()
        self.state.setObjectName("Muted")
        row.addWidget(self.state)
        lay.addLayout(row)
        return w

    def _section(self, lay, text):
        lab = QLabel(text)
        lab.setObjectName("Section")
        lay.addSpacing(6)
        lay.addWidget(lab)

    def _build_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("Panel")
        panel.setFixedWidth(330)
        outer = QVBoxLayout(panel)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        body = QWidget()
        body.setObjectName("Page")
        lay = QVBoxLayout(body)
        lay.setContentsMargins(24, 28, 24, 24)
        lay.setSpacing(8)
        ch = self._changed

        self._section(lay, "STYLE")
        self.style = QComboBox()
        self.style.addItems(STYLES)
        self.style.currentTextChanged.connect(ch)
        lay.addWidget(self.style)

        self._section(lay, "COLOR")
        swatches = QGridLayout()
        swatches.setSpacing(6)
        self.swatch_buttons = {}
        for i, (name, hexc) in enumerate(COLORS.items()):
            b = QPushButton()
            b.setToolTip(name)
            b.setFixedSize(30, 30)
            b.clicked.connect(lambda _=False, h=hexc: self._set_color(h))
            self.swatch_buttons[hexc] = b
            swatches.addWidget(b, 0, i)
        lay.addLayout(swatches)
        custom = QPushButton("Custom color…")
        custom.clicked.connect(self._pick_color)
        lay.addWidget(custom)

        self._section(lay, "SHAPE")
        grid = QGridLayout()
        grid.setVerticalSpacing(6)
        self.size = Slider(1, 60, " px", ch)
        self.thick = Slider(1, 10, " px", ch)
        self.gap = Slider(0, 30, " px", ch)
        self.dot = Slider(0, 10, " px", ch)
        self.opacity = Slider(10, 100, "%", ch)
        for r, (name, w) in enumerate((("Size", self.size), ("Thickness", self.thick), ("Gap", self.gap),
                                       ("Center dot", self.dot), ("Opacity", self.opacity))):
            grid.addWidget(QLabel(name), r, 0)
            grid.addWidget(w, r, 1)
        lay.addLayout(grid)

        self._section(lay, "OUTLINE")
        self.outline = QCheckBox("Outline for contrast")
        self.outline.toggled.connect(ch)
        lay.addWidget(self.outline)
        og = QGridLayout()
        self.outline_w = Slider(1, 4, " px", ch)
        self.outline_c = QComboBox()
        self.outline_c.addItems(["Black", "White"])
        self.outline_c.currentTextChanged.connect(ch)
        og.addWidget(QLabel("Width"), 0, 0)
        og.addWidget(self.outline_w, 0, 1)
        og.addWidget(QLabel("Color"), 1, 0)
        og.addWidget(self.outline_c, 1, 1)
        lay.addLayout(og)

        self._section(lay, "POSITION")
        pos = QGridLayout()
        self.off_x = QSpinBox()
        self.off_y = QSpinBox()
        for sp in (self.off_x, self.off_y):
            sp.setRange(-200, 200)
            sp.setSuffix(" px")
            sp.valueChanged.connect(ch)
        pos.addWidget(QLabel("Offset X"), 0, 0)
        pos.addWidget(self.off_x, 0, 1)
        pos.addWidget(QLabel("Offset Y"), 1, 0)
        pos.addWidget(self.off_y, 1, 1)
        lay.addLayout(pos)

        self._section(lay, "STARTUP")
        self.autostart = QCheckBox("Show crosshair at login")
        self.autostart.setChecked(AUTOSTART.exists())
        self.autostart.toggled.connect(self._set_autostart)
        lay.addWidget(self.autostart)

        lay.addStretch(1)
        reset = QPushButton("Reset to default")
        reset.clicked.connect(self._reset)
        lay.addWidget(reset)

        scroll.setWidget(body)
        outer.addWidget(scroll)
        return panel

    # ------------------------------------------------------------------ state
    def _load_into_controls(self):
        c = self.cfg
        self._loading = True
        self.style.setCurrentText(c.style)
        self.size.setValue(c.size)
        self.thick.setValue(c.thickness)
        self.gap.setValue(c.gap)
        self.dot.setValue(c.dot)
        self.opacity.setValue(round(c.opacity * 100))
        self.outline.setChecked(c.outline)
        self.outline_w.setValue(c.outline_width)
        self.outline_c.setCurrentText("White" if c.outline_color.lower() in ("#fff", "#ffffff") else "Black")
        self.off_x.setValue(c.offset_x)
        self.off_y.setValue(c.offset_y)
        self._loading = False
        self._paint_swatches()
        self.preview.update()

    def _changed(self, *_):
        if self._loading:
            return
        c = self.cfg
        c.style = self.style.currentText()
        c.size, c.thickness, c.gap, c.dot = self.size.value(), self.thick.value(), self.gap.value(), self.dot.value()
        c.opacity = self.opacity.value() / 100
        c.outline = self.outline.isChecked()
        c.outline_width = self.outline_w.value()
        c.outline_color = "#ffffff" if self.outline_c.currentText() == "White" else "#000000"
        c.offset_x, c.offset_y = self.off_x.value(), self.off_y.value()
        for w in (self.outline_w, self.outline_c):
            w.setEnabled(c.outline)
        self.preview.update()
        self._save_timer.start()

    def _save(self):
        self.cfg.save()

    def _set_color(self, hexc: str):
        self.cfg.color = hexc
        self._paint_swatches()
        self._changed()

    def _pick_color(self):
        col = QColorDialog.getColor(QColor(self.cfg.color), self, "Crosshair color")
        if col.isValid():
            self._set_color(col.name())

    def _paint_swatches(self):
        for hexc, b in self.swatch_buttons.items():
            ring = "#ffffff" if hexc.lower() == self.cfg.color.lower() else "#2e2e2e"
            b.setStyleSheet(f"background: {hexc}; border: 2px solid {ring}; border-radius: 15px; padding: 0;")

    def _reset(self):
        defaults = Crosshair()
        for k, v in asdict(defaults).items():
            setattr(self.cfg, k, v)
        self._load_into_controls()
        self._save()

    # ------------------------------------------------------------------ overlay process
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
        self.state.setText(f"Overlay running · {HOTKEY} hides it in-game" if on else "Overlay off")

    def _set_autostart(self, on: bool):
        if on:
            AUTOSTART.parent.mkdir(parents=True, exist_ok=True)
            AUTOSTART.write_text(
                "[Desktop Entry]\nType=Application\nName=Grimoire SightsL\nComment=Crosshair overlay\n"
                f"Exec={HOME}/.local/bin/grimoire-sightc on\nIcon=grimoire\nX-KDE-autostart-phase=2\n")
        else:
            AUTOSTART.unlink(missing_ok=True)

