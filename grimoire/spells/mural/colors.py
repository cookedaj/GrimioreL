"""Colors tab: 5 black & white KDE color schemes, applied to every window and app.

Generates ~/.local/share/color-schemes/Grimoire<Name>.colors and applies it with plasma-apply-colorscheme.
Every role (links, warnings, focus…) maps to a gray, so nothing on screen keeps a hue.
"""
import subprocess

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPainterPath
from PySide6.QtWidgets import QComboBox, QGridLayout, QLabel, QPushButton

from grimoire.paths import DATA, HOME
from grimoire.spells.mural.backdrop import wallpaper as _wallpaper
from grimoire.spells.mural.kde import kread, run_tool
from grimoire.spells.mural.screens import Design, ScreenTab, community_designs, community_entry

SCHEMES = HOME / ".local/share/color-schemes"
PREVIOUS = DATA / "mural" / "colors-previous.txt"
DEFAULTS = {"titlebar": "Match", "accent": "Design"}
ACCENTS = ["Design", "White", "Mid gray", "Black"]

#            window view  button header select sel-text text  muted dark
PALETTES = {
    "obsidian": (0x0e, 0x08, 0x18, 0x0a, 0xf0, 0x00, 0xe8, 0x80, True),
    "graphite": (0x1c, 0x14, 0x27, 0x17, 0x4c, 0xff, 0xe2, 0x8a, True),
    "slate":    (0x2b, 0x23, 0x36, 0x26, 0xd8, 0x10, 0xdc, 0x94, True),
    "silver":   (0xd4, 0xe4, 0xc6, 0xca, 0x2a, 0xff, 0x14, 0x60, False),
    "paper":    (0xf3, 0xff, 0xe8, 0xec, 0x1a, 0xff, 0x10, 0x70, False),
}
DESIGNS = [
    Design("obsidian", "Obsidian", "Near-black everywhere, pure white selection. The boldest monochrome."),
    Design("graphite", "Graphite", "Charcoal grays with a soft gray selection. Calm and balanced."),
    Design("slate", "Slate", "Lighter dark grays with a bright selection. Easy contrast for long sessions."),
    Design("silver", "Silver", "Light gray surfaces with near-black selection. A gentle light theme."),
    Design("paper", "Paper", "White paper and black ink. Crisp light theme."),
]
EFFECTS = """[ColorEffects:Disabled]
Color=56,56,56
ColorAmount=0
ColorEffect=0
ContrastAmount=0.65
ContrastEffect=1
IntensityAmount=0.1
IntensityEffect=2

[ColorEffects:Inactive]
ChangeSelectionColor=true
Color=112,111,110
ColorAmount=0.025
ColorEffect=2
ContrastAmount=0.1
ContrastEffect=2
Enable=false
IntensityAmount=0
IntensityEffect=0
"""


def _g(v: int) -> str:
    v = max(0, min(255, int(v)))
    return f"{v},{v},{v}"


def palette(pid: str, o: dict) -> dict:
    window, view, button, header, sel, sel_text, text, muted, dark = PALETTES[pid]
    accent = o.get("accent", "Design")
    if accent != "Design":
        sel = {"White": 0xf0, "Mid gray": 0x80, "Black": 0x10}[accent]
        sel_text = 0x00 if sel > 0x90 else 0xff
    if o.get("titlebar") == "Black":
        header = 0x05
    return dict(window=window, view=view, button=button, header=header, sel=sel, sel_text=sel_text,
                text=text, muted=muted, dark=dark)


def scheme_text(pid: str, o: dict, name: str, ident: str) -> str:
    c = palette(pid, o)
    dark = c["dark"]
    alt = 10 if dark else -10                          # alternating-row offset
    focus = c["sel"]
    hover = (c["sel"] + c["text"]) / 2

    def group(title, bg, fg, muted=c["muted"], fg_active=None):
        header_text = fg if not (title.startswith("Colors:Header") and c["header"] < 0x40) else 0xe8
        return f"""[{title}]
BackgroundAlternate={_g(bg + alt)}
BackgroundNormal={_g(bg)}
DecorationFocus={_g(focus)}
DecorationHover={_g(hover)}
ForegroundActive={_g(fg_active if fg_active is not None else header_text)}
ForegroundInactive={_g(muted)}
ForegroundLink={_g(header_text)}
ForegroundNegative={_g(0xc8 if dark else 0x30)}
ForegroundNeutral={_g(0xb0 if dark else 0x48)}
ForegroundNormal={_g(header_text)}
ForegroundPositive={_g(0xd8 if dark else 0x24)}
ForegroundVisited={_g(muted)}
"""

    header_fg = 0xe8 if c["header"] < 0x40 else c["text"]
    parts = [
        EFFECTS,
        group("Colors:Button", c["button"], c["text"]),
        group("Colors:Complementary", 0x0b, 0xe8, 0x80),
        group("Colors:Header", c["header"], c["text"]),
        group("Colors:Header][Inactive", c["header"], c["text"]),
        group("Colors:Selection", c["sel"], c["sel_text"], muted=c["sel_text"], fg_active=c["sel_text"]),
        group("Colors:Tooltip", c["window"], c["text"]),
        group("Colors:View", c["view"], c["text"]),
        group("Colors:Window", c["window"], c["text"]),
        f"[General]\nColorScheme={ident}\nName={name}\nshadeSortColumn=true\n",
        "[KDE]\ncontrast=4\n",
        f"""[WM]
activeBackground={_g(c['header'])}
activeBlend={_g(header_fg)}
activeForeground={_g(header_fg)}
inactiveBackground={_g(c['header'])}
inactiveBlend={_g(c['muted'])}
inactiveForeground={_g(c['muted'])}
""",
    ]
    return "\n".join(parts)


def render(pid: str, o: dict, w=1280, h=720) -> QImage:
    """A mock app window painted with the scheme."""
    c = palette(pid, {**DEFAULTS, **o})

    def q(v, a=255):
        return QColor(v, v, v, a)

    img = _wallpaper(w, h).copy()
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    p.fillRect(img.rect(), QColor(0, 0, 0, 110))
    win = QRectF(w * 0.1, h * 0.1, w * 0.8, h * 0.8)
    clip = QPainterPath()
    clip.addRoundedRect(win, 10, 10)
    p.setClipPath(clip)
    p.fillRect(win, q(c["window"]))
    title = QRectF(win.x(), win.y(), win.width(), 38)
    p.fillRect(title, q(c["header"]))
    header_fg = 0xe8 if c["header"] < 0x40 else c["text"]
    p.setFont(QFont("IBM Plex Sans", 10))
    p.setPen(q(header_fg))
    p.drawText(title, Qt.AlignmentFlag.AlignCenter, "Dolphin — Repo")
    for k in range(3):                                  # window buttons
        p.setBrush(q(header_fg, 140))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QRectF(win.right() - 26 - k * 24, title.center().y() - 6, 12, 12))

    tool = QRectF(win.x(), title.bottom(), win.width(), 46)
    p.fillRect(tool, q(c["window"]))
    p.setFont(QFont("IBM Plex Sans", 9))
    x = tool.x() + 14
    for label in ("Back", "Forward", "New Folder", "Share"):
        r = QRectF(x, tool.y() + 9, 24 + len(label) * 7, 28)
        p.setBrush(q(c["button"]))
        p.setPen(q(c["text"], 40))
        p.drawRoundedRect(r, 5, 5)
        p.setPen(q(c["text"]))
        p.drawText(r, Qt.AlignmentFlag.AlignCenter, label)
        x = r.right() + 8
    search = QRectF(tool.right() - 230, tool.y() + 9, 210, 28)
    p.setBrush(q(c["view"]))
    p.setPen(q(c["sel"] if c["dark"] else c["text"], 160))
    p.drawRoundedRect(search, 5, 5)
    p.setPen(q(c["muted"]))
    p.drawText(search.adjusted(10, 0, 0, 0), Qt.AlignmentFlag.AlignVCenter, "Search…")

    side = QRectF(win.x(), tool.bottom(), 190, win.bottom() - tool.bottom())
    p.fillRect(side, q(c["window"]))
    p.setFont(QFont("IBM Plex Sans", 10))
    for k, place in enumerate(("Home", "Desktop", "Documents", "Downloads", "Repo", "Trash")):
        r = QRectF(side.x() + 8, side.y() + 10 + k * 32, side.width() - 16, 28)
        if place == "Repo":
            p.setBrush(q(c["sel"]))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawRoundedRect(r, 5, 5)
            p.setPen(q(c["sel_text"]))
        else:
            p.setPen(q(c["text"]))
        p.drawText(r.adjusted(12, 0, 0, 0), Qt.AlignmentFlag.AlignVCenter, place)

    view = QRectF(side.right(), tool.bottom(), win.right() - side.right(), side.height())
    p.fillRect(view, q(c["view"]))
    alt = 10 if c["dark"] else -10
    rows = ("Grimoire", "Linux Setup", "assets", "design", "clover5.svg", "notes.md", "wallpaper.png")
    for k, name in enumerate(rows):
        r = QRectF(view.x(), view.y() + k * 34, view.width(), 34)
        if k % 2:
            p.fillRect(r, q(c["view"] + alt))
        if k == 1:
            p.fillRect(r.adjusted(6, 2, -6, -2), q(c["sel"], 90 if c["dark"] else 60))
        p.setPen(q(c["text"]))
        p.drawText(r.adjusted(20, 0, 0, 0), Qt.AlignmentFlag.AlignVCenter, name)
        p.setPen(q(c["muted"]))
        p.drawText(r.adjusted(0, 0, -20, 0), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                   "folder" if "." not in name else "file")
    btn = QRectF(view.right() - 150, view.bottom() - 52, 130, 34)
    p.setBrush(q(c["sel"]))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawRoundedRect(btn, 6, 6)
    p.setPen(q(c["sel_text"]))
    p.drawText(btn, Qt.AlignmentFlag.AlignCenter, "Open")
    p.setClipping(False)
    p.setPen(q(255 if c["dark"] else 0, 40))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPath(clip)
    p.end()
    return img


def current_scheme() -> str:
    return kread("kdeglobals", "General", "ColorScheme")


class ColorsTab(ScreenTab):
    key = "colors"
    subtitle = ("System colors for every window and app. Links, warnings and focus all become grays. "
                "Grimoire itself keeps its own look.")
    apply_label = "Apply colors"
    store = ["colors"]

    def designs(self):
        return DESIGNS + community_designs("colors")

    def build_options(self, lay):
        grid = QGridLayout()
        grid.setVerticalSpacing(8)
        self.titlebar = QComboBox()
        self.titlebar.addItems(["Match", "Black"])
        self.accent = QComboBox()
        self.accent.addItems(ACCENTS)
        for c in (self.titlebar, self.accent):
            c.currentTextChanged.connect(self.changed)
        grid.addWidget(QLabel("Title bars"), 0, 0)
        grid.addWidget(self.titlebar, 0, 1)
        grid.addWidget(QLabel("Selection"), 1, 0)
        grid.addWidget(self.accent, 1, 1)
        lay.addLayout(grid)
        lay.addSpacing(6)
        restore = QPushButton("Restore previous colors")
        restore.clicked.connect(self._restore)
        lay.addWidget(restore)

    def options(self):
        return {"titlebar": self.titlebar.currentText(), "accent": self.accent.currentText()}

    def set_options(self, o):
        o = {**DEFAULTS, **o}
        self.titlebar.setCurrentText(o["titlebar"])
        self.accent.setCurrentText(o["accent"])

    def preview(self, design, o):
        return render(design.id, o)

    def apply(self, design, o):
        SCHEMES.mkdir(parents=True, exist_ok=True)
        cur = current_scheme()
        if not cur.startswith("Grimoire"):
            PREVIOUS.parent.mkdir(parents=True, exist_ok=True)
            PREVIOUS.write_text(cur or "BreezeDark")
        if design.id.startswith("store:"):
            ident = community_entry(design.id)["ident"]
            run_tool(["plasma-apply-colorscheme", ident], ok_if_already=True)
            return "Applied ✓"
        # plasma-apply-colorscheme ignores re-applying the current name, so alternate between two names
        base = f"Grimoire{design.name}"
        ident = base + "B" if cur == base else base
        (SCHEMES / f"{ident}.colors").write_text(scheme_text(design.id, o, f"Grimoire {design.name}", ident))
        run_tool(["plasma-apply-colorscheme", ident])
        for old in SCHEMES.glob("Grimoire*.colors"):    # keep only the active one
            if old.stem != ident:
                old.unlink()
        return "Applied ✓  Open apps update right away."

    def _restore(self):
        prev = PREVIOUS.read_text().strip() if PREVIOUS.exists() else "BreezeDark"
        r = subprocess.run(["plasma-apply-colorscheme", prev], capture_output=True, text=True)
        self.status.setText(f"Restored {prev}." if r.returncode == 0 else f"Couldn't restore: {r.stderr.strip()}")
