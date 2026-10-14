"""Grimoire hub window: a slim icon rail on the left, a home page of spells, one page per spell."""
import sys
from datetime import datetime
from types import SimpleNamespace

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPalette
from PySide6.QtWidgets import (QApplication, QButtonGroup, QCheckBox, QFrame, QGridLayout, QHBoxLayout, QLabel,
                               QMainWindow, QMessageBox, QPushButton, QScrollArea, QStackedWidget, QVBoxLayout,
                               QWidget)

from grimoire import NAME, standalone
from grimoire.glyphs import clover, glyph
from grimoire.paths import ASSETS
from grimoire.settingsview import SettingsPage
from grimoire.spells import SPELLS
from grimoire.theme import FONT, QSS
from grimoire.updateview import Banner, Updater, VersionButton, WhatsNew


def spaced(text: str, size: int, spacing: float, weight=QFont.Weight.DemiBold) -> QLabel:
    label = QLabel(text)
    font = QFont(FONT, size, weight)
    font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, spacing)
    label.setFont(font)
    return label


class InstallButton(QPushButton):
    """Top-right of a spell card: installs the spell as its own app in the menu; once installed it reads
    "Installed" and offers "Uninstall" on hover."""
    def __init__(self, spell):
        super().__init__()
        self.setObjectName("Pill")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.spell = spell
        self.clicked.connect(self._toggle)
        self._show(False)

    def _show(self, hover: bool):
        on = standalone.installed(self.spell.id)
        self.setProperty("on", on)
        self.setText(("Uninstall" if hover else "Installed") if on else "Install")
        self.setToolTip(f"{'Remove' if on else 'Add'} {self.spell.name} as its own app in the app menu")
        self.style().unpolish(self)
        self.style().polish(self)

    def enterEvent(self, e):
        self._show(True)
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._show(False)
        super().leaveEvent(e)

    def _toggle(self):
        sid = self.spell.id
        try:
            if not standalone.installed(sid):
                standalone.install(sid)
            elif sid != "vaultl" or QMessageBox.question(
                    self, "Uninstall VaultL", "Remove VaultL from the app menu? If it's your default file manager, "
                    "folders will open in another one until you install it again.") == QMessageBox.StandardButton.Yes:
                standalone.uninstall(sid)
        except (OSError, ValueError) as err:
            QMessageBox.warning(self, self.spell.name, f"Couldn't change the launcher: {err}")
        self._show(self.underMouse())


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
        if standalone.available(spell.id):
            top.addWidget(InstallButton(spell))
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


class TrayToggle(QCheckBox):
    """Opt-in: Grimoire's tray icon at login. Turning it on also starts the tray now."""
    def __init__(self):
        from grimoire import tray
        super().__init__("Tray icon at login")
        self.setToolTip("Live CPU and RAM in the system tray, plus crosshair, tidy Downloads, performance mode "
                        "and every spell in its menu")
        self.setChecked(tray.autostart_on())
        self.toggled.connect(self._set)

    def _set(self, on: bool):
        from grimoire import tray
        try:
            tray.set_autostart(on)
            if on and not tray.running():
                tray.launch("grimoire-tray")
        except OSError as err:
            QMessageBox.warning(self, "Tray icon", f"Couldn't change it: {err}")


class Home(QWidget):
    def __init__(self, open_spell, banner: QWidget):
        super().__init__()
        self.setObjectName("Page")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(56, 52, 56, 44)
        lay.setSpacing(4)
        lay.addWidget(banner)                    # hidden unless an update is waiting
        hour = datetime.now().hour
        greeting = "Good morning" if hour < 12 else "Good afternoon" if hour < 18 else "Good evening"
        hello = QLabel(greeting)
        hello.setObjectName("Hero")
        lay.addWidget(hello)
        sub = QLabel("Your spells. Personal tools for this machine, all in black and white.")
        sub.setObjectName("Muted")
        lay.addWidget(sub)
        lay.addSpacing(14)
        lay.addWidget(TrayToggle())
        lay.addSpacing(20)
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
        self.setWindowTitle(NAME)
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
        logo.setToolTip(NAME)
        rl.addWidget(logo)
        rl.addSpacing(22)

        self.updater = Updater(self)
        self._whatsnew = None
        self.stack = QStackedWidget()
        self.nav = QButtonGroup(self)
        self.pages: dict[str, tuple] = {}
        home = QScrollArea()                     # scrolls once there are more spell cards than fit
        home.setWidgetResizable(True)
        home.setWidget(Home(self.open, Banner(self.updater, self.whats_new)))
        self._add_page("home", "Home", "home", home, rl)
        for spell in SPELLS:
            self._add_page(spell.id, spell.name, spell.icon, None, rl, spell)
        rl.addStretch(1)
        self._add_page("settings", "Settings", "gear", None, rl,
                       SimpleNamespace(page=lambda: SettingsPage(self.updater, self.whats_new)))
        rl.addWidget(VersionButton(self.updater, self.whats_new), 0, Qt.AlignmentFlag.AlignHCenter)

        root.addWidget(rail)
        root.addWidget(self.stack, 1)
        self.open("home")
        self.updater.start()

    def whats_new(self):
        """The What's new panel (also 'Check for updates'); one per window, kept while it lives."""
        if self._whatsnew is None:
            self._whatsnew = WhatsNew(self.updater, self)
        self._whatsnew.show()
        self._whatsnew.raise_()
        self._whatsnew.activateWindow()

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


def style_app(app: QApplication):
    """Grimoire's black & white look (also used by standalone spells like VaultL)."""
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


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(NAME)
    app.setDesktopFileName("grimoire")
    style_app(app)
    win = Window()
    start = sys.argv[1] if len(sys.argv) > 1 else "home"
    start = {"filel": "vaultl", "tidyl": "vaultl"}.get(start, start)     # old menu actions from before the merge
    win.open(start if start in win.pages else "home")
    win.show()
    sys.exit(app.exec())
