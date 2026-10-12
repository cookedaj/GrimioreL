"""MuraL: everything you look at, in one place. A side menu of sections, each opening a tab.

SCREENS  desktop, lock screen, splash, login, boot
SHELL    taskbar, style, windows, motion
LOOK     colors, icons, fonts, cursor, terminal
Tabs are built the first time they're opened.
"""
from importlib import import_module

from PySide6.QtCore import QSize
from PySide6.QtWidgets import (QButtonGroup, QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea, QStackedWidget,
                               QVBoxLayout, QWidget)

from grimoire.glyphs import glyph

SECTIONS = [
    ("SCREENS", [
        ("Desktop", "desktop", "desktop", "DesktopTab"),
        ("Lock screen", "lock", "lock", "LockTab"),
        ("Splash", "splash", "splash", "SplashTab"),
        ("Login", "login", "login", "LoginTab"),
        ("Boot", "boot", "boot", "BootTab"),
    ]),
    ("SHELL", [
        ("Taskbar", "taskbar", "taskbar", "TaskbarTab"),
        ("Style", "style", "style", "StyleTab"),
        ("Windows", "windows", "windows", "WindowsTab"),
        ("Motion", "motion", "motion", "MotionTab"),
    ]),
    ("LOOK", [
        ("Colors", "colors", "colors", "ColorsTab"),
        ("Icons", "icons", "icons", "IconsTab"),
        ("Fonts", "fonts", "fonts", "FontsTab"),
        ("Cursor", "cursor", "cursor", "CursorTab"),
        ("Terminal", "terminal", "terminal", "TerminalTab"),
    ]),
]
TABS = [tab for _, tabs in SECTIONS for tab in tabs]


class MuralPage(QWidget):
    def __init__(self):
        super().__init__()
        self.setObjectName("Page")
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        nav = QFrame()
        nav.setObjectName("SubNav")
        nav.setFixedWidth(208)
        nl = QVBoxLayout(nav)
        nl.setContentsMargins(14, 30, 14, 20)
        nl.setSpacing(2)
        title = QLabel("MuraL")
        title.setObjectName("Title")
        nl.addWidget(title)
        hint = QLabel("Everything you look at")
        hint.setObjectName("Muted")
        nl.addWidget(hint)
        nl.addSpacing(18)

        self.group = QButtonGroup(self)
        self.stack = QStackedWidget()
        self.built: dict[int, QWidget] = {}
        i = 0
        for section, tabs in SECTIONS:
            label = QLabel(section)
            label.setObjectName("NavSection")
            nl.addWidget(label)
            for name, icon, _, _ in tabs:
                b = QPushButton(name)
                b.setObjectName("SubNavItem")
                b.setIcon(glyph(icon))
                b.setIconSize(QSize(18, 18))
                b.setCheckable(True)
                b.clicked.connect(lambda _=False, i=i: self.open_tab(i))
                self.group.addButton(b, i)
                nl.addWidget(b)
                i += 1
            nl.addSpacing(12)
        nl.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setFixedWidth(208)
        scroll.setWidget(nav)
        root.addWidget(scroll)

        body = QWidget()
        bl = QVBoxLayout(body)
        bl.setContentsMargins(0, 22, 0, 0)
        bl.setSpacing(0)
        self.heading = QLabel()
        self.heading.setObjectName("PageHeading")
        self.heading.setContentsMargins(36, 0, 0, 0)
        bl.addWidget(self.heading)
        bl.addWidget(self.stack, 1)
        root.addWidget(body, 1)
        self.open_tab(0)

    def open_tab(self, i: int):
        name, _, module, cls = TABS[i]
        if i not in self.built:
            self.built[i] = getattr(import_module(f"grimoire.spells.mural.{module}"), cls)()
            self.stack.addWidget(self.built[i])
        self.stack.setCurrentWidget(self.built[i])
        self.group.button(i).setChecked(True)
        self.heading.setText(name)
