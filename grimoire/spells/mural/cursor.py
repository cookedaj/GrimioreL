"""Cursor tab: black & white cursor themes on this system and from the store, at any size.
Previews are drawn from the real cursor files (a tiny Xcursor reader), on black and on white.
"""
import struct
from functools import lru_cache
from pathlib import Path

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter
from PySide6.QtWidgets import QComboBox, QGridLayout, QLabel

from grimoire.spells.mural import store as community
from grimoire.spells.mural.kde import kread, run_tool
from grimoire.spells.mural.screens import Design, ScreenTab

ICONS = Path("/usr/share/icons")
SEARCH = [Path.home() / ".local/share/icons", Path.home() / ".icons", ICONS]
DESIGNS = [
    Design("Oxygen_Black", "Oxygen Black", "Glossy black cursors with soft shading."),
]
SIZES = ["24", "32", "36", "48", "64"]
DEFAULTS = {"size": "24"}
SHAPES = [("left_ptr",), ("pointing_hand", "hand2"), ("xterm", "text", "ibeam"), ("wait", "watch")]


@lru_cache(maxsize=64)
def load_cursor(theme: str, names: tuple, size: int) -> QImage:
    """First frame of a cursor from an Xcursor file, at the nominal size closest to `size`."""
    path = next((base / theme / "cursors" / name for base in SEARCH for name in names
                 if (base / theme / "cursors" / name).exists()), None)
    if path is None:
        return QImage()
    data = path.read_bytes()
    if data[:4] != b"Xcur":
        return QImage()
    ntoc = struct.unpack_from("<I", data, 12)[0]
    images = []
    for i in range(ntoc):
        kind, subtype, pos = struct.unpack_from("<III", data, 16 + i * 12)
        if kind == 0xFFFD0002:                        # image chunk; subtype = nominal size
            images.append((abs(subtype - size), subtype, pos))
    if not images:
        return QImage()
    _, _, pos = min(images)
    w, h = struct.unpack_from("<II", data, pos + 16)
    pixels = data[pos + 36: pos + 36 + w * h * 4]
    return QImage(pixels, w, h, w * 4, QImage.Format.Format_ARGB32_Premultiplied).copy()


def render(theme: str, o: dict, w=1280, h=720) -> QImage:
    size = int({**DEFAULTS, **o}["size"])
    img = QImage(w, h, QImage.Format.Format_RGB32)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.fillRect(QRectF(0, 0, w / 2, h), QColor(10, 10, 10))
    p.fillRect(QRectF(w / 2, 0, w / 2, h), QColor(242, 242, 242))
    zoom = 2.0                                        # shown at 2x so the shapes are clear
    for half in range(2):
        for k, names in enumerate(SHAPES):
            cur = load_cursor(theme, names, size)
            if cur.isNull():
                continue
            cw, ch = cur.width() * zoom, cur.height() * zoom
            x = half * w / 2 + (w / 2) * (k + 1) / (len(SHAPES) + 1) - cw / 2
            y = h / 2 - ch / 2
            p.drawImage(QRectF(x, y, cw, ch), cur)
        p.setPen(QColor(120, 120, 120))
        p.setFont(QFont("IBM Plex Sans", 11))
        p.drawText(QRectF(half * w / 2, h - 70, w / 2, 24), Qt.AlignmentFlag.AlignCenter,
                   "on dark" if half == 0 else "on light")
    p.setPen(QColor(150, 150, 150))
    p.drawText(QRectF(0, 40, w, 24), Qt.AlignmentFlag.AlignCenter, f"{size} px  ·  shown at 2×")
    p.end()
    return img


def current() -> str:
    return kread("kcminputrc", "Mouse", "cursorTheme")


class CursorTab(ScreenTab):
    key = "cursor"
    subtitle = "Your mouse pointer. Previews come from the real cursor files, shown on dark and light."
    apply_label = "Apply cursor"
    store = ["cursor"]

    def designs(self):
        own = [d for d in DESIGNS if (ICONS / d.id / "cursors").exists()]
        return own + [Design(e["ident"], e["name"], f"Community · by {e['author'] or 'unknown'}")
                      for e in community.installed("cursor")]

    def build_options(self, lay):
        grid = QGridLayout()
        self.size = QComboBox()
        self.size.addItems(SIZES)
        self.size.currentTextChanged.connect(self.changed)
        grid.addWidget(QLabel("Size"), 0, 0)
        grid.addWidget(self.size, 0, 1)
        lay.addLayout(grid)

    def options(self):
        return {"size": self.size.currentText()}

    def set_options(self, o):
        self.size.setCurrentText({**DEFAULTS, **o}["size"])

    def preview(self, design, o):
        return render(design.id, o)

    def apply(self, design, o):
        run_tool(["plasma-apply-cursortheme", "--size", o["size"], design.id], ok_if_already=True)
        return "Applied ✓"
