"""Taskbar tab: 5 panel layouts + a black & white look (a generated Plasma Style, see plasmastyle.py),
height, opacity, floating and auto-hide.

Layout properties go through plasmashell scripting; opacity is only read from plasmashellrc at startup,
so changing it restarts plasmashell (a one-second blink). The panel's widgets are left alone.
The original panel + Plasma Style are recorded on the first apply so "Restore" can put them back.
"""
import json
import subprocess
import time

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPainterPath
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QCheckBox, QComboBox, QGridLayout, QLabel, QPushButton

from grimoire.paths import ASSETS, DATA
from grimoire.spells.mural import plasmastyle
from grimoire.spells.mural.backdrop import wallpaper as _wallpaper
from grimoire.spells.mural.kde import kread, kwrite, plasma_script
from grimoire.spells.mural.screens import Design, ScreenTab
from grimoire.widgets import Slider

ORIGINAL = DATA / "mural" / "taskbar-original.json"
PROPS = ("location", "height", "floating", "hiding", "alignment", "lengthMode", "opacity")
OPACITY = {"Adaptive": 0, "Opaque": 1, "Translucent": 2}          # plasmashellrc panelOpacity values
OPACITY_NAMES = {"adaptive": 0, "opaque": 1, "translucent": 2}
LOOK_NAMES = {"Keep current": None, **{look.name: key for key, look in plasmastyle.LOOKS.items()}}
DEFAULTS = {"height": 46, "opacity": "Adaptive", "floating": True, "autohide": False, "look": "Onyx"}

#            id          location  lengthMode alignment
LAYOUTS = {
    "dock":    ("bottom", "fit", "center"),
}
DESIGNS = [
    Design("dock", "Dock", "Only as wide as its contents, centered at the bottom. The modern look."),
]


def _plasma(script: str) -> str:
    r = plasma_script(script)
    if r.returncode:
        raise RuntimeError(r.stderr.strip() or "plasmashell refused the script")
    return r.stdout.strip()


def read_panel() -> dict:
    out = _plasma("var p = panels()[0]; print(JSON.stringify({" +
                  ", ".join(f"{k}: p.{k}" for k in PROPS) + "}));")
    return json.loads(out)


def write_panel(props: dict):
    sets = "".join(f" p.{k} = {json.dumps(v)};" for k, v in props.items())
    _plasma(f"var p = panels()[0];{sets}")


def _panel_groups() -> list[str]:
    """The first panel's group in plasmashellrc."""
    return ["PlasmaViews", f"Panel {_plasma('print(panels()[0].id)')}"]


def set_opacity(value: int):
    """Opacity is only read at startup: write it and restart plasmashell, but only if it changed."""
    groups = _panel_groups()
    if kread("plasmashellrc", groups, "panelOpacity", default="0") == str(value):
        return
    kwrite("plasmashellrc", groups, "panelOpacity", value)
    subprocess.run(["systemctl", "--user", "restart", "plasma-plasmashell"], check=True)
    for _ in range(40):                        # wait until plasmashell answers again
        if subprocess.run(["qdbus6", "org.kde.plasmashell", "/PlasmaShell"], capture_output=True).returncode == 0:
            break
        time.sleep(0.25)


def render(design_id: str, o: dict, w=1280, h=720) -> QImage:
    o = {**DEFAULTS, **o}
    loc, length, _ = LAYOUTS[design_id]
    s = w / 2560                                       # preview scale vs your 2560x1440 screen
    img = _wallpaper(w, h).copy()
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.fillRect(img.rect(), QColor(0, 0, 0, 70))         # a touch darker so the panel reads

    thick = o["height"] * s * 1.0
    gap = 8 * s if o["floating"] else 0
    vertical = loc in ("left", "right")
    n_tasks = 6
    icon = thick * 0.56
    pad = thick * 0.28
    content = pad * 2 + icon * (n_tasks + 3) + pad * (n_tasks + 2) + (0 if vertical else 70 * s)
    if vertical:
        span = h - 2 * gap if length == "fill" else min(h - 2 * gap, content)
        rect = QRectF(gap, (h - span) / 2, thick, span)
    else:
        span = w - 2 * gap if length == "fill" else min(w - 2 * gap, content)
        y = gap if loc == "top" else h - thick - gap
        rect = QRectF((w - span) / 2, y, span, thick)

    look = plasmastyle.LOOKS.get(LOOK_NAMES.get(o["look"]) or "", None)
    fill = QColor(look.fill) if look else QColor(32, 35, 38)
    base_alpha = look.fill_opacity if look else 0.95
    alpha = {"Opaque": 1.0, "Translucent": 0.6, "Adaptive": 0.85}[o["opacity"]] * base_alpha
    if o["opacity"] == "Opaque":
        alpha = 1.0
    fill.setAlphaF(alpha)
    path = QPainterPath()
    radius = (look.radius if look else 8) * s * 2 if o["floating"] else 0   # Plasma squares a docked panel
    radius = min(radius, thick / 2)
    path.addRoundedRect(rect, radius, radius)
    if o["autohide"]:
        p.setOpacity(0.45)
    p.fillPath(path, fill)

    # contents: launcher clover, task icons, tray dots, clock
    def slot(k):                                        # top-left of the k-th icon slot
        if vertical:
            return QRectF(rect.x() + (thick - icon) / 2, rect.y() + pad + k * (icon + pad), icon, icon)
        return QRectF(rect.x() + pad + k * (icon + pad), rect.y() + (thick - icon) / 2, icon, icon)

    QSvgRenderer(str(ASSETS / "clover5.svg")).render(p, slot(0).adjusted(icon * .12, icon * .12, -icon * .12, -icon * .12))
    p.setPen(Qt.PenStyle.NoPen)
    for k in range(n_tasks):
        r = slot(k + 1.4)
        light = look is not None and look.light
        shade = (40 if k == 1 else 110) if light else (225 if k == 1 else 120)
        p.setBrush(QColor(shade, shade, shade, 230))
        p.drawRoundedRect(r, icon * 0.24, icon * 0.24)
    active = slot(2.4)                                  # running-indicator under the active task
    p.setBrush(QColor("white"))
    if vertical:
        p.drawRoundedRect(QRectF(rect.x() + 2 * s, active.center().y() - icon * .25, 3 * s, icon * .5), 1, 1)
    else:
        p.drawRoundedRect(QRectF(active.center().x() - icon * .25, rect.bottom() - 4 * s, icon * .5, 3 * s), 1, 1)
    p.setPen(QColor(20, 20, 20) if look is not None and look.light else QColor(230, 230, 230))
    p.setFont(QFont("IBM Plex Sans", max(6, int(thick * 0.26))))
    if vertical:
        clock = QRectF(rect.x(), rect.bottom() - thick, thick, thick)
        p.drawText(clock, Qt.AlignmentFlag.AlignCenter, "2:45")
    else:
        clock = QRectF(rect.right() - pad - 70 * s, rect.y(), 70 * s, thick)
        p.drawText(clock, Qt.AlignmentFlag.AlignCenter, "2:45")
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(170, 170, 170))
        for k in range(3):                              # tray
            c = QRectF(clock.x() - (k + 1) * icon * 0.75, rect.center().y() - icon * .16, icon * .32, icon * .32)
            p.drawEllipse(c)
    if o["autohide"]:
        p.setOpacity(1)
        p.setPen(QColor(255, 255, 255, 160))
        p.setFont(QFont("IBM Plex Sans", 10))
        note = QRectF(0, rect.y() - 30 if loc != "top" else rect.bottom() + 8, w, 22)
        if vertical:
            note = QRectF(rect.right() + 12, h / 2 - 11, 200, 22)
        p.drawText(note, Qt.AlignmentFlag.AlignHCenter if not vertical else Qt.AlignmentFlag.AlignLeft,
                   "hides until you touch the edge")
    p.end()
    return img


class TaskbarTab(ScreenTab):
    key = "taskbar"
    subtitle = ("Your Plasma taskbar. Changes apply instantly; the first apply records your original "
                "panel so you can restore it.")
    apply_label = "Apply to taskbar"

    def designs(self):
        return DESIGNS

    def build_options(self, lay):
        grid = QGridLayout()
        grid.setVerticalSpacing(8)
        self.height_ = Slider(28, 80, " px", self.changed)
        self.look = QComboBox()
        self.look.addItems(list(LOOK_NAMES))
        self.look.setToolTip("The panel's look (also popups and tooltips): a black & white Plasma Style")
        self.opacity = QComboBox()
        self.opacity.addItems(list(OPACITY))
        for c in (self.look, self.opacity):
            c.currentTextChanged.connect(self.changed)
        grid.addWidget(QLabel("Look"), 0, 0)
        grid.addWidget(self.look, 0, 1)
        grid.addWidget(QLabel("Height"), 1, 0)
        grid.addWidget(self.height_, 1, 1)
        grid.addWidget(QLabel("Opacity"), 2, 0)
        grid.addWidget(self.opacity, 2, 1)
        lay.addLayout(grid)
        self.floating = QCheckBox("Floating (gap + rounded corners)")
        self.autohide = QCheckBox("Auto-hide")
        for c in (self.floating, self.autohide):
            c.toggled.connect(self.changed)
            lay.addWidget(c)
        lay.addSpacing(6)
        restore = QPushButton("Restore original taskbar")
        restore.clicked.connect(self._restore)
        lay.addWidget(restore)

    def options(self):
        return {"look": self.look.currentText(), "height": self.height_.value(), "opacity": self.opacity.currentText(),
                "floating": self.floating.isChecked(), "autohide": self.autohide.isChecked()}

    def set_options(self, o):
        o = {**DEFAULTS, **o}
        self.look.setCurrentText(o["look"])
        self.height_.setValue(o["height"])
        self.opacity.setCurrentText(o["opacity"])
        self.floating.setChecked(o["floating"])
        self.autohide.setChecked(o["autohide"])

    def preview(self, design, o):
        return render(design.id, o)

    def thumbnail(self, design, o):
        """Cards zoom in on the panel's edge of the screen (it's thin at real scale)."""
        img = render(design.id, o, 2560, 1440)
        loc = LAYOUTS[design.id][0]
        x, y = {"bottom": (853, 960), "top": (853, 0), "left": (0, 480)}[loc]
        return img.copy(x, y, 853, 480)

    def apply(self, design, o):
        if not ORIGINAL.exists():
            ORIGINAL.parent.mkdir(parents=True, exist_ok=True)
            original = read_panel()
            original["opacity"] = OPACITY_NAMES.get(str(original.get("opacity")), 0)
            original["style"] = plasmastyle.current()
            ORIGINAL.write_text(json.dumps(original, indent=2))
        set_opacity(OPACITY[o["opacity"]])     # may restart plasmashell, so it goes first
        loc, length, align = LAYOUTS[design.id]
        write_panel({"location": loc, "lengthMode": length, "alignment": align, "height": o["height"],
                     "floating": o["floating"], "hiding": "autohide" if o["autohide"] else "none"})
        look = LOOK_NAMES.get(o["look"])
        if look:
            plasmastyle.apply(look)
        return "Applied ✓  (Floating panels go flat while a window is maximized; that's Plasma.)"

    def _restore(self):
        if not ORIGINAL.exists():
            self.status.setText("Nothing to restore — the taskbar hasn't been changed by MuraL.")
            return

        def work():                             # may restart plasmashell, so it runs off the UI thread
            original = json.loads(ORIGINAL.read_text())
            style = original.pop("style", None)
            opacity = original.pop("opacity", 0)
            set_opacity(opacity if isinstance(opacity, int) else OPACITY_NAMES.get(opacity, 0))
            write_panel(original)
            if style:
                subprocess.run(["plasma-apply-desktoptheme", style], capture_output=True)
            return "Original taskbar restored."
        self.background(work, "Restoring…")
