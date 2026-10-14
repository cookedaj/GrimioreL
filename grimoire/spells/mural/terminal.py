# SPDX-License-Identifier: GPL-3.0-or-later
"""Terminal tab: Konsole in black & white. a grayscale palette (Ink) + font, size, transparency, padding,
cursor, and an optional shell prompt.

Writes ~/.local/share/konsole/Grimoire.profile + Grimoire-<palette>.colorscheme, makes Grimoire the default
profile, and (if a prompt style is chosen) a marked block in ~/.bashrc.
"""
import re
import subprocess

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QImage, QPainter, QPainterPath
from PySide6.QtWidgets import QCheckBox, QComboBox, QGridLayout, QLabel, QPushButton

from grimoire.paths import HOME
from grimoire.spells.mural.kde import kwrite
from grimoire.spells.mural.screens import Design, ScreenTab, community_designs, community_entry
from grimoire.spells.mural.backdrop import wallpaper as _wallpaper
from grimoire.widgets import Slider

KONSOLE = HOME / ".local/share/konsole"
BASHRC = HOME / ".bashrc"
FONTS = ["IBM Plex Mono", "DM Mono", "Hack", "DejaVu Sans Mono"]
CURSORS = {"Block": 0, "I-beam": 1, "Underline": 2}
PROMPTS = ["Keep mine", "Minimal", "Clover", "Two-line"]
DEFAULTS = {"font": "IBM Plex Mono", "size": 12, "transparency": 0, "blur": True, "padding": 14,
            "cursor": "Block", "prompt": "Keep mine"}
BLOCK_START, BLOCK_END = "# >>> grimoire prompt >>>", "# <<< grimoire prompt <<<"

# ANSI order: black red green yellow blue magenta cyan white -> distinct grays
#            bg     fg    ansi (normal)                                 dark?
PALETTES = {
    "ink":      (0x00, 0xe6, [0x2a, 0xb4, 0xd4, 0xec, 0x8c, 0xa6, 0xc6, 0xe6], True),
}
DESIGNS = [
    Design("ink", "Ink", "Pure black, soft white text. Every color becomes its own shade of gray."),
]
SAMPLE = [("prompt", "ls"), ("ls", ""), ("prompt", "git status"), ("out", "On branch main"),
          ("out", "Changes not staged for commit:"), ("mod", "	modified:   grimoire/spells/mural/terminal.py"),
          ("prompt", "python3 -c 'print(\"surpass your limits\")'"), ("out", "surpass your limits"),
          ("prompt", "")]


def _rgb(v):
    return f"{v},{v},{v}"


def colorscheme(pid: str, o: dict) -> str:
    bg, fg, ansi, dark = PALETTES[pid]
    lines = []

    def group(name, v):
        lines.append(f"[{name}]\nColor={_rgb(v)}\n")

    group("Background", bg)
    group("BackgroundIntense", bg)
    group("BackgroundFaint", bg)
    group("Foreground", fg)
    group("ForegroundIntense", 0xff if dark else 0x00)
    group("ForegroundFaint", int(fg * 0.6 + bg * 0.4))
    for i, v in enumerate(ansi):
        brighter = min(255, v + 24) if dark else max(0, v - 24)
        group(f"Color{i}", v)
        group(f"Color{i}Intense", brighter)
        group(f"Color{i}Faint", int(v * 0.6 + bg * 0.4))
    opacity = 1 - o["transparency"] / 100
    lines.append(f"[General]\nDescription=Grimoire {pid.title()}\nOpacity={opacity:.2f}\n"
                 f"Blur={'true' if o['blur'] and opacity < 1 else 'false'}\nWallpaper=\n")
    return "\n".join(lines)


def profile(pid: str, o: dict) -> str:
    return f"""[Appearance]
ColorScheme=Grimoire-{pid}
Font={o['font']},{o['size']},-1,5,400,0,0,0,0,0
LineSpacing=2

[Cursor Options]
CursorShape={CURSORS[o['cursor']]}

[General]
Name=Grimoire
Parent=FALLBACK/
TerminalMargin={o['padding']}
TerminalCenter=false

[Scrolling]
HistorySize=10000
ScrollBarPosition=2
"""


def prompt_block(style: str) -> str:
    ps1 = {
        "Minimal": r"PS1='\[\e[2m\]\W\[\e[0m\] ❯ '",
        "Clover": r"PS1='\[\e[1m\]♣\[\e[0m\] \W › '",
        "Two-line": r"PS1='\n\[\e[2m\]\w\[\e[0m\]\n❯ '",
    }[style]
    return f"{BLOCK_START}\n# Written by Grimoire → MuraL → Terminal. Delete this block to undo.\n{ps1}\n{BLOCK_END}\n"


def write_prompt(style: str):
    text = BASHRC.read_text() if BASHRC.exists() else ""
    if style == "Keep mine" and BLOCK_START not in text:
        return                                          # nothing of ours in there: don't touch the file
    text = re.sub(rf"\n?{re.escape(BLOCK_START)}.*?{re.escape(BLOCK_END)}\n?", "\n", text, flags=re.S).rstrip() + "\n"
    if style != "Keep mine":
        text += "\n" + prompt_block(style)
    BASHRC.write_text(text)


def _prompt_text(style: str) -> list[tuple[str, int]]:
    """(text, ansi color index or -1 for fg) runs for the preview prompt."""
    if style == "Minimal":
        return [("Repo", 8), (" ❯ ", -1)]
    if style == "Clover":
        return [("♣", -2), (" Repo › ", -1)]
    if style == "Two-line":
        return [("~/Projects", 8), ("\n❯ ", -1)]
    return [("you@grimoire", 2), (":", -1), ("~/Projects", 4), ("$ ", -1)]


def render(pid: str, o: dict, w=1280, h=720) -> QImage:
    o = {**DEFAULTS, **o}
    bg, fg, ansi, dark = PALETTES[pid]
    img = _wallpaper(w, h).copy()
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    p.fillRect(img.rect(), QColor(0, 0, 0, 120))

    win = QRectF(w * 0.12, h * 0.12, w * 0.76, h * 0.76)
    shape = QPainterPath()
    shape.addRoundedRect(win, 10, 10)
    p.setClipPath(shape)
    title_h = 34
    p.fillRect(QRectF(win.x(), win.y(), win.width(), title_h), QColor(18, 18, 18) if dark else QColor(228, 228, 228))
    alpha = int(255 * (1 - o["transparency"] / 100))
    body = QRectF(win.x(), win.y() + title_h, win.width(), win.height() - title_h)
    p.fillRect(body, QColor(bg, bg, bg, alpha))
    p.setClipping(False)
    p.setPen(QColor(255, 255, 255, 30) if dark else QColor(0, 0, 0, 40))
    p.drawPath(shape)
    p.setPen(QColor(150, 150, 150))
    p.setFont(QFont("IBM Plex Sans", 10))
    p.drawText(QRectF(win.x(), win.y(), win.width(), title_h), Qt.AlignmentFlag.AlignCenter, "Repo : bash — Konsole")

    def col(i):
        if i == -1:
            return QColor(fg, fg, fg)
        if i == -2:
            return QColor(0xff, 0xff, 0xff) if dark else QColor(0, 0, 0)
        if i == 8:                                      # "faint" text
            v = int(fg * 0.6 + bg * 0.4)
            return QColor(v, v, v)
        v = ansi[i]
        return QColor(v, v, v)

    font = QFont(o["font"], 1)
    font.setPixelSize(int(o["size"] * 1.25))
    p.setFont(font)
    fm = QFontMetricsF(font)
    line_h = fm.height() + 3
    x0 = body.x() + o["padding"] * 0.9
    x, y = x0, body.y() + o["padding"] * 0.9 + fm.ascent()

    def run(text, color):
        nonlocal x, y
        for k, part in enumerate(text.split("\n")):
            if k:
                x, y = x0, y + line_h
            p.setPen(col(color))
            p.drawText(QRectF(x, y - fm.ascent(), 2000, line_h), part)
            x += fm.horizontalAdvance(part)

    for kind, text in SAMPLE:
        if kind == "prompt":
            for t, c in _prompt_text(o["prompt"]):
                run(t, c)
            run(text, -1)
            if not text:                                # cursor on the last prompt
                cw = fm.horizontalAdvance("M")
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(col(-1))
                shape_c = o["cursor"]
                if shape_c == "Block":
                    p.drawRect(QRectF(x, y - fm.ascent(), cw, fm.height()))
                elif shape_c == "I-beam":
                    p.drawRect(QRectF(x, y - fm.ascent(), 2, fm.height()))
                else:
                    p.drawRect(QRectF(x, y + fm.descent() - 2, cw, 2))
        elif kind == "ls":
            for name, c in (("Desktop", 4), ("Documents", 4), ("Downloads", 4), ("Repo", 4),
                            ("clover.png", 5), ("notes.txt", -1)):
                run(name + "  ", c)
        elif kind == "mod":
            run(text, 1)
        else:
            run(text, -1)
        x, y = x0, y + line_h
    p.end()
    return img


class TerminalTab(ScreenTab):
    key = "terminal"
    subtitle = ("Konsole, your terminal. Every color becomes its own shade of gray so output stays readable. "
                "Applies to new Konsole windows.")
    apply_label = "Apply to Konsole"
    store = ["konsole"]

    def designs(self):
        return DESIGNS + community_designs("konsole")

    def build_options(self, lay):
        grid = QGridLayout()
        grid.setVerticalSpacing(8)
        self.font = QComboBox()
        self.font.addItems(FONTS)
        self.size = Slider(8, 20, " pt", self.changed)
        self.transparency = Slider(0, 60, "%", self.changed)
        self.padding = Slider(0, 40, " px", self.changed)
        self.cursor = QComboBox()
        self.cursor.addItems(list(CURSORS))
        self.prompt = QComboBox()
        self.prompt.addItems(PROMPTS)
        for c in (self.font, self.cursor, self.prompt):
            c.currentTextChanged.connect(self.changed)
        rows = (("Font", self.font), ("Size", self.size), ("Transparency", self.transparency),
                ("Padding", self.padding), ("Cursor", self.cursor), ("Prompt", self.prompt))
        for r, (name, wdg) in enumerate(rows):
            grid.addWidget(QLabel(name), r, 0)
            grid.addWidget(wdg, r, 1)
        lay.addLayout(grid)
        self.blur = QCheckBox("Blur behind when transparent")
        self.blur.toggled.connect(self.changed)
        lay.addWidget(self.blur)
        lay.addSpacing(6)
        test = QPushButton("Open a Konsole window")
        test.clicked.connect(lambda: subprocess.Popen(["konsole", "--profile", "Grimoire"],
                                                      start_new_session=True))
        lay.addWidget(test)

    def options(self):
        return {"font": self.font.currentText(), "size": self.size.value(),
                "transparency": self.transparency.value(), "blur": self.blur.isChecked(),
                "padding": self.padding.value(), "cursor": self.cursor.currentText(),
                "prompt": self.prompt.currentText()}

    def set_options(self, o):
        o = {**DEFAULTS, **o}
        self.font.setCurrentText(o["font"])
        self.size.setValue(o["size"])
        self.transparency.setValue(o["transparency"])
        self.blur.setChecked(o["blur"])
        self.padding.setValue(o["padding"])
        self.cursor.setCurrentText(o["cursor"])
        self.prompt.setCurrentText(o["prompt"])

    def preview(self, design, o):
        return render(design.id, o)

    def thumbnail(self, design, o):
        """Cards zoom in on the top-left of the terminal so the text is legible."""
        return render(design.id, o).copy(150, 85, 560, 315)

    def apply(self, design, o):
        KONSOLE.mkdir(parents=True, exist_ok=True)
        if design.id.startswith("store:"):           # community scheme + your font/padding/cursor options
            scheme = community_entry(design.id)["ident"]
        else:
            (KONSOLE / f"Grimoire-{design.id}.colorscheme").write_text(colorscheme(design.id, o))
            scheme = f"Grimoire-{design.id}"
        (KONSOLE / "Grimoire.profile").write_text(profile(design.id, o).replace(
            f"ColorScheme=Grimoire-{design.id}", f"ColorScheme={scheme}"))
        kwrite("konsolerc", "Desktop Entry", "DefaultProfile", "Grimoire.profile")
        write_prompt(o["prompt"])
        extra = "" if o["prompt"] == "Keep mine" else " Prompt takes effect in new terminals."
        return f"Applied ✓  New Konsole windows use it.{extra}"
