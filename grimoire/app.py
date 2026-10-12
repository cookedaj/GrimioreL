"""Grimoire hub window: a slim icon rail on the left, a home page of spells, one page per spell."""
import sys
from datetime import datetime

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPalette
from PySide6.QtWidgets import (QApplication, QButtonGroup, QFrame, QGridLayout, QHBoxLayout, QLabel, QMainWindow,
                               QPushButton, QStackedWidget, QVBoxLayout, QWidget)

from grimoire import __version__
from grimoire.glyphs import clover, glyph
from grimoire.paths import ASSETS
from grimoire.spells import SPELLS
from grimoire.theme import FONT, QSS


def spaced(text: str, size: int, spacing: float, weight=QFont.Weight.DemiBold) -> QLabel:
    label = QLabel(text)
    font = QFont(FONT, size, weight)
    font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, spacing)
    label.setFont(font)
    return label


class SpellCard(QFrame):
    def __init__(self, spell, on_open):
        super().__init__()
        self.setObjectName("Card")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumSize(360, 190)
        self._on_open = on_open
        self.spell = spell
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 22, 24, 20)
        lay.setSpacing(6)
        top = QHBoxLayout()
        icon = QLabel()
        icon.setPixmap(glyph(spell.icon, 28).pixmap(28, 28, QIcon.Mode.Active))
        top.addWidget(icon)
        top.addSpacing(8)
        top.addWidget(spaced(spell.name.upper(), 14, 4))
        top.addStretch(1)
        lay.addLayout(top)
        tag = QLabel(spell.tagline)
        tag.setObjectName("Muted")
        tag.setWordWrap(True)
        lay.addWidget(tag)
        lay.addStretch(1)
        self.status = QLabel()
        self.status.setObjectName("Status")
        self.status.setWordWrap(True)
        lay.addWidget(self.status)
        self.refresh()

    def refresh(self):
        try:
            self.status.setText(self.spell.status())
        except Exception:          # a status line must never break the home page
            self.status.setText("")

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._on_open()


class Home(QWidget):
    def __init__(self, open_spell):
        super().__init__()
        self.setObjectName("Page")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(56, 52, 56, 44)
        lay.setSpacing(4)
        hour = datetime.now().hour
        greeting = "Good morning" if hour < 12 else "Good afternoon" if hour < 18 else "Good evening"
        hello = QLabel(greeting)
        hello.setObjectName("Hero")
        lay.addWidget(hello)
        sub = QLabel("Your spells. Personal tools for this machine, all in black and white.")
        sub.setObjectName("Muted")
        lay.addWidget(sub)
        lay.addSpacing(34)
        lay.addWidget(spaced("SPELLS", 10, 4))
        lay.addSpacing(10)

        grid = QGridLayout()
        grid.setSpacing(16)
        self.cards = [SpellCard(s, lambda s=s: open_spell(s.id)) for s in SPELLS]
        for i, card in enumerate(self.cards):
            grid.addWidget(card, i // 2, i % 2)
        soon = QFrame()
        soon.setObjectName("CardSoon")
        soon.setMinimumSize(360, 190)
        sl = QVBoxLayout(soon)
        sl.setContentsMargins(24, 22, 24, 20)
        t = QLabel("Next spell")
        t.setObjectName("Muted")
        sl.addWidget(t)
        sl.addStretch(1)
        n = len(self.cards)
        grid.addWidget(soon, n // 2, n % 2)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        lay.addLayout(grid)
        lay.addStretch(1)

    def showEvent(self, e):
        super().showEvent(e)
        for c in self.cards:
            c.refresh()


class Window(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Grimoire")
        self.resize(1440, 880)
        self.setMinimumSize(1100, 680)

        central = QWidget()
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.setCentralWidget(central)

        rail = QWidget()
        rail.setObjectName("Rail")
        rail.setFixedWidth(72)
        rl = QVBoxLayout(rail)
        rl.setContentsMargins(12, 22, 12, 16)
        rl.setSpacing(8)
        logo = QLabel()
        logo.setPixmap(clover(34))
        logo.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        logo.setToolTip("Grimoire")
        rl.addWidget(logo)
        rl.addSpacing(22)

        self.stack = QStackedWidget()
        self.nav = QButtonGroup(self)
        self.pages: dict[str, tuple] = {}
        self._add_page("home", "Home", "home", Home(self.open), rl)
        for spell in SPELLS:
            self._add_page(spell.id, spell.name, spell.icon, None, rl, spell)
        rl.addStretch(1)
        ver = QLabel(f"v{__version__}")
        ver.setObjectName("Tiny")
        ver.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        rl.addWidget(ver)

        root.addWidget(rail)
        root.addWidget(self.stack, 1)
        self.open("home")

    def _add_page(self, pid, label, icon, widget, rail_layout, spell=None):
        btn = QPushButton()
        btn.setObjectName("RailItem")
        btn.setIcon(glyph(icon, 22))
        btn.setIconSize(QSize(22, 22))
        btn.setFixedSize(48, 48)
        btn.setToolTip(label)
        btn.setCheckable(True)
        btn.clicked.connect(lambda: self.open(pid))
        self.nav.addButton(btn)
        rail_layout.addWidget(btn, 0, Qt.AlignmentFlag.AlignHCenter)
        self.pages[pid] = (btn, widget, spell)

    def open(self, pid: str):
        btn, widget, spell = self.pages[pid]
        if widget is None:                       # spells are built on first open
            widget = spell.page()
            self.pages[pid] = (btn, widget, spell)
        if self.stack.indexOf(widget) < 0:
            self.stack.addWidget(widget)
        self.stack.setCurrentWidget(widget)
        btn.setChecked(True)


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Grimoire")
    app.setDesktopFileName("grimoire")
    app.setWindowIcon(QIcon(str(ASSETS / "clover5.svg")))
    app.setStyle("Fusion")
    app.setFont(QFont(FONT, 10))
    pal = app.palette()                      # monochrome highlight (Qt's default is blue)
    for role, color in ((QPalette.ColorRole.Highlight, "#2a2a2a"), (QPalette.ColorRole.HighlightedText, "#ffffff"),
                        (QPalette.ColorRole.Window, "#0b0b0b"), (QPalette.ColorRole.Base, "#121212"),
                        (QPalette.ColorRole.Text, "#e8e8e8"), (QPalette.ColorRole.WindowText, "#e8e8e8"),
                        (QPalette.ColorRole.Button, "#121212"), (QPalette.ColorRole.ButtonText, "#e8e8e8")):
        pal.setColor(role, QColor(color))
    app.setPalette(pal)
    app.setStyleSheet(QSS)
    win = Window()
    start = sys.argv[1] if len(sys.argv) > 1 else "home"
    win.open(start if start in win.pages else "home")
    win.show()
    sys.exit(app.exec())
