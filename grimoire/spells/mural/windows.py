"""Windows tab: title bar button layouts + Breeze decoration options (button size, title alignment,
border, outline, hide title bar when maximized). Applies live through KWin.
"""
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QCheckBox, QComboBox, QGridLayout, QLabel

from grimoire.spells.mural.backdrop import wallpaper
from grimoire.spells.mural.kde import kread, kwin_reconfigure, kwrite
from grimoire.spells.mural.screens import Design, ScreenTab, community_designs, community_entry

#            left  right   (KWin codes: M menu, S on-all-desktops, H help, I minimize, A maximize, X close)
LAYOUTS = {
    "classic": ("M", "IAX"),
    "mac":     ("XIA", ""),
    "minimal": ("", "X"),
    "left":    ("X", "M"),
    "full":    ("MS", "HIAX"),
}
DESIGNS = [
    Design("classic", "Classic", "Menu on the left; minimize, maximize and close on the right."),
    Design("mac", "Mac", "Close, minimize and maximize on the left, nothing on the right."),
    Design("minimal", "Minimal", "Just a close button. Use the keyboard or double-click the title for the rest."),
    Design("left", "Left-hand", "Close on the left, window menu on the right."),
    Design("full", "Everything", "Menu + all-desktops on the left; help, minimize, maximize, close on the right."),
]
SIZES = {"Tiny": "ButtonTiny", "Small": "ButtonSmall", "Default": "ButtonDefault", "Large": "ButtonLarge"}
ALIGN = {"Left": "AlignLeft", "Center": "AlignCenterFullWidth", "Right": "AlignRight"}
BORDERS = {"None": "None", "No sides": "NoSides", "Tiny": "Tiny", "Normal": "Normal", "Large": "Large"}
OUTLINE = {"Off": "OutlineOff", "Low": "OutlineLow", "Medium": "OutlineMedium", "High": "OutlineHigh"}
DEFAULTS = {"size": "Default", "align": "Center", "border": "No sides", "outline": "Low", "borderless_max": False}


def _header_colors() -> tuple[QColor, QColor]:
    """Active title bar background/foreground from the current color scheme ([WM] in kdeglobals)."""
    def read(key, default):
        r = kread("kdeglobals", "WM", key)
        try:
            return QColor(*map(int, r.split(",")[:3]))
        except ValueError:
            return QColor(default)
    return read("activeBackground", "#1a1a1a"), read("activeForeground", "#e8e8e8")


def render(design_id: str, o: dict, w=1280, h=720) -> QImage:
    o = {**DEFAULTS, **o}
    left, right = LAYOUTS[design_id]
    bg, fg = _header_colors()
    img = wallpaper(w, h).copy()
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.fillRect(img.rect(), QColor(0, 0, 0, 120))
    btn = {"Tiny": 14, "Small": 17, "Default": 20, "Large": 25}[o["size"]]
    title_h = btn + 16
    border = {"None": 0, "No sides": 0, "Tiny": 2, "Normal": 4, "Large": 7}[o["border"]]
    bottom_border = 0 if o["border"] in ("None",) else max(border, 2 if o["border"] == "No sides" else border)

    for x, y, ww, hh, active in ((150, 170, 760, 420, False), (330, 110, 800, 470, True)):
        win = QRectF(x, y, ww, hh)
        path = QPainterPath()
        path.addRoundedRect(win, 6, 6)
        p.save()
        p.setClipPath(path)
        p.fillRect(win, QColor(bg).darker(115) if active else QColor(bg).darker(140))
        p.fillRect(QRectF(win.x() + border, win.y() + title_h, ww - 2 * border, hh - title_h - bottom_border),
                   QColor(20, 20, 20))
        for line in range(6):                           # fake content
            p.fillRect(QRectF(win.x() + 30, win.y() + title_h + 30 + line * 34, (ww - 60) * (0.9 - line * 0.1), 10),
                       QColor(60, 60, 60))
        p.restore()
        tint = fg if active else QColor(fg.red(), fg.green(), fg.blue(), 120)
        # buttons
        def glyph(code, cx, cy):
            r = btn / 2
            p.setPen(Qt.PenStyle.NoPen)
            if code == "X":
                p.setBrush(QColor(tint.red(), tint.green(), tint.blue(), 230 if active else 110))
                p.drawEllipse(QRectF(cx - r, cy - r, btn, btn))
                pen = QPen(bg.darker(115), 1.6)
                p.setPen(pen)
                d = r * 0.42
                p.drawLine(int(cx - d), int(cy - d), int(cx + d), int(cy + d))
                p.drawLine(int(cx - d), int(cy + d), int(cx + d), int(cy - d))
                return
            pen = QPen(tint, 1.6)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            d = r * 0.45
            if code == "I":
                p.drawLine(int(cx - d), int(cy + d * 0.3), int(cx + d), int(cy + d * 0.3))
            elif code == "A":
                p.drawRect(QRectF(cx - d, cy - d, 2 * d, 2 * d))
            elif code == "M":
                p.drawEllipse(QRectF(cx - d, cy - d, 2 * d, 2 * d))
            elif code == "S":
                p.drawEllipse(QRectF(cx - d * 0.4, cy - d * 0.4, d * 0.8, d * 0.8))
            elif code == "H":
                p.drawText(QRectF(cx - r, cy - r, btn, btn), Qt.AlignmentFlag.AlignCenter, "?")

        cy = win.y() + title_h / 2
        gap = btn + 8
        for i, code in enumerate(left):
            glyph(code, win.x() + 14 + btn / 2 + i * gap, cy)
        for i, code in enumerate(reversed(right)):
            glyph(code, win.right() - 14 - btn / 2 - i * gap, cy)
        p.setPen(tint)
        p.setFont(QFont("IBM Plex Sans", 10, QFont.Weight.DemiBold if active else QFont.Weight.Normal))
        inner = QRectF(win.x() + 20 + len(left) * gap, win.y(), ww - 40 - (len(left) + len(right)) * gap, title_h)
        align = {"Left": Qt.AlignmentFlag.AlignLeft, "Center": Qt.AlignmentFlag.AlignHCenter,
                 "Right": Qt.AlignmentFlag.AlignRight}[o["align"]]
        p.drawText(inner, align | Qt.AlignmentFlag.AlignVCenter, "Konsole — ~/Desktop/Repo" if active else "Dolphin")
        if o["outline"] != "Off":
            alpha = {"Low": 40, "Medium": 80, "High": 130}[o["outline"]]
            p.setPen(QColor(255, 255, 255, alpha))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(path)
    if o["borderless_max"]:
        p.setPen(QColor(255, 255, 255, 170))
        p.setFont(QFont("IBM Plex Sans", 10))
        p.drawText(QRectF(0, h - 44, w, 24), Qt.AlignmentFlag.AlignCenter, "maximized windows hide their title bar")
    p.end()
    return img


class WindowsTab(ScreenTab):
    key = "windows"
    subtitle = "Title bars and window frames (KWin + Breeze). Applies instantly to every window."
    apply_label = "Apply to windows"
    store = ["aurorae"]

    def designs(self):
        return DESIGNS + community_designs("aurorae")

    def build_options(self, lay):
        grid = QGridLayout()
        grid.setVerticalSpacing(8)
        self.size = QComboBox()
        self.size.addItems(list(SIZES))
        self.align = QComboBox()
        self.align.addItems(list(ALIGN))
        self.border = QComboBox()
        self.border.addItems(list(BORDERS))
        self.outline = QComboBox()
        self.outline.addItems(list(OUTLINE))
        for r, (name, c) in enumerate((("Buttons", self.size), ("Title", self.align), ("Border", self.border),
                                       ("Outline", self.outline))):
            c.currentTextChanged.connect(self.changed)
            grid.addWidget(QLabel(name), r, 0)
            grid.addWidget(c, r, 1)
        lay.addLayout(grid)
        self.borderless_max = QCheckBox("Hide title bar when maximized")
        self.borderless_max.toggled.connect(self.changed)
        lay.addWidget(self.borderless_max)

    def options(self):
        return {"size": self.size.currentText(), "align": self.align.currentText(),
                "border": self.border.currentText(), "outline": self.outline.currentText(),
                "borderless_max": self.borderless_max.isChecked()}

    def set_options(self, o):
        o = {**DEFAULTS, **o}
        self.size.setCurrentText(o["size"])
        self.align.setCurrentText(o["align"])
        self.border.setCurrentText(o["border"])
        self.outline.setCurrentText(o["outline"])
        self.borderless_max.setChecked(o["borderless_max"])

    def preview(self, design, o):
        return render(design.id, o)

    def apply(self, design, o):
        deco = ["org.kde.kdecoration2"]
        if design.id.startswith("store:"):           # community Aurorae decoration; keeps your button layout
            kwrite("kwinrc", deco, "library", "org.kde.kwin.aurorae")
            kwrite("kwinrc", deco, "theme", "__aurorae__svg__" + community_entry(design.id)["ident"])
        else:
            left, right = LAYOUTS[design.id]
            kwrite("kwinrc", deco, "library", "org.kde.breeze")
            kwrite("kwinrc", deco, "theme", "Breeze")
            kwrite("kwinrc", deco, "ButtonsOnLeft", left)
            kwrite("kwinrc", deco, "ButtonsOnRight", right)
        kwrite("kwinrc", deco, "BorderSize", BORDERS[o["border"]])
        kwrite("kwinrc", deco, "BorderSizeAuto", "false", "bool")
        kwrite("kwinrc", ["Windows"], "BorderlessMaximizedWindows", str(o["borderless_max"]).lower(), "bool")
        kwrite("breezerc", ["Windeco"], "ButtonSize", SIZES[o["size"]])
        kwrite("breezerc", ["Windeco"], "TitleAlignment", ALIGN[o["align"]])
        kwrite("breezerc", ["Common"], "OutlineIntensity", OUTLINE[o["outline"]])
        kwin_reconfigure()
        return "Applied ✓"
