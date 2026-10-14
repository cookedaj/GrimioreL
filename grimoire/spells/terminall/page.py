# SPDX-License-Identifier: GPL-3.0-or-later
"""TerminalL's window: tabs of terminals that split side by side or top and bottom, a search bar for the
scrollback, a profile picker and a command palette.

Shortcuts: Ctrl+Shift+T new tab, Ctrl+Shift+W close pane, Ctrl+Shift+E split side by side, Ctrl+Shift+O split top
and bottom, Ctrl+Shift+F search, Ctrl+Shift+P commands, Ctrl+Shift+C/V copy/paste, Ctrl+= / Ctrl+- / Ctrl+0 zoom,
Ctrl+PgUp/PgDn or Ctrl+(Shift+)Tab switch tabs, Shift+PgUp/PgDn scroll back.
"""
import subprocess
from pathlib import Path

from PySide6.QtCore import QEvent, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import (QApplication, QButtonGroup, QComboBox, QDialog, QFontComboBox, QFrame, QHBoxLayout,
                               QLabel, QLineEdit, QListWidget, QListWidgetItem, QMenu, QPushButton, QSpinBox,
                               QSplitter, QStackedWidget, QTabBar, QToolButton, QVBoxLayout, QWidget)

from grimoire.glyphs import glyph
from grimoire.paths import CACHE, HOME
from grimoire.spells.terminall import config

APT = "sudo apt install python3-pyte"
CTRL = Qt.KeyboardModifier.ControlModifier
SHIFT = Qt.KeyboardModifier.ShiftModifier
EDIT_PROFILES = "Edit profiles…"
LOCAL_QSS = """
QFrame#TermBar { background: #070707; border-bottom: 1px solid #161616; }
QTabBar { background: transparent; }
QTabBar::tab { background: transparent; color: #8c8c8c; border: none; border-bottom: 2px solid transparent;
               padding: 9px 6px 9px 14px; max-width: 260px; }
QTabBar::tab:hover { color: #ffffff; }
QTabBar::tab:selected { color: #ffffff; border-bottom: 2px solid #ffffff; }
QFrame#SearchBar { background: #070707; border-top: 1px solid #161616; }
QSplitter::handle { background: #262626; }
QFrame#Palette { background: #101010; border: 1px solid #2e2e2e; border-radius: 10px; }
QListWidget#Commands::item { padding: 7px 8px; }
QLabel#Hint { color: #555555; font-size: 11px; }
"""


def vaultl_folder() -> Path | None:
    """The folder VaultL shows: a VaultL page open in this Grimoire, else the last one VaultL remembered."""
    pages = [w for w in QApplication.allWidgets() if type(w).__name__ == "VaultLPage"]
    pages.sort(key=lambda w: not w.isVisible())
    if pages and isinstance(getattr(pages[0], "cwd", None), Path):
        return pages[0].cwd
    try:
        p = Path((CACHE / "vaultl-folder").read_text().strip())
    except OSError:
        return None
    return p if p.is_absolute() and p.is_dir() else None


def tool(icon: str, tip: str, slot) -> QToolButton:
    b = QToolButton()
    b.setObjectName("Tool")
    b.setIcon(glyph(icon, 18))
    b.setIconSize(QSize(18, 18))
    b.setToolTip(tip)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    b.clicked.connect(slot)
    return b


class Missing(QWidget):
    """Shown instead of the terminal when pyte isn't installed; the rest of Grimoire keeps working."""

    def __init__(self):
        super().__init__()
        self.setObjectName("Page")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(56, 52, 56, 44)
        lay.addStretch(1)
        for text, name in (("TerminalL needs one more package", "PageHeading"),
                           ("pyte, the terminal emulator library TerminalL is built on, isn't installed. "
                            "Install it from a terminal, then reopen TerminalL:", "Muted")):
            label = QLabel(text)
            label.setObjectName(name)
            label.setWordWrap(True)
            label.setAlignment(Qt.AlignmentFlag.AlignHCenter)
            lay.addWidget(label)
        lay.addSpacing(12)
        cmd = QLabel(APT)
        cmd.setObjectName("Mono")
        cmd.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        lay.addWidget(cmd, 0, Qt.AlignmentFlag.AlignHCenter)
        copy = QPushButton("Copy command")
        copy.clicked.connect(lambda: QApplication.clipboard().setText(APT))
        lay.addWidget(copy, 0, Qt.AlignmentFlag.AlignHCenter)
        lay.addStretch(2)


class Tab(QWidget):
    """One tab: a terminal, or a tree of splitters holding several."""

    def __init__(self, first):
        super().__init__()
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(0, 0, 0, 0)
        self.lay.addWidget(first)
        self.active = first

    def views(self) -> list:
        from grimoire.spells.terminall.view import TerminalView
        return [w for w in self.findChildren(TerminalView) if w.session.fd >= 0]

    def split(self, view, new, orientation: Qt.Orientation):
        parent = view.parentWidget()
        if isinstance(parent, QSplitter) and parent.orientation() == orientation:
            sizes = parent.sizes()
            i = parent.indexOf(view)
            parent.insertWidget(i + 1, new)
            half = sizes[i] // 2
            sizes[i:i + 1] = [half, sizes[i] - half]
            parent.setSizes(sizes)
            return
        splitter = QSplitter(orientation, self)          # parented now: PySide would collect an orphan
        splitter.setHandleWidth(1)
        splitter.setChildrenCollapsible(False)
        if isinstance(parent, QSplitter):
            i, sizes = parent.indexOf(view), parent.sizes()
            parent.replaceWidget(i, splitter)
            parent.setSizes(sizes)
        else:
            self.lay.replaceWidget(view, splitter)
        splitter.addWidget(view)
        splitter.addWidget(new)
        total = splitter.width() if orientation == Qt.Orientation.Horizontal else splitter.height()
        splitter.setSizes([max(1, total // 2)] * 2)

    def remove(self, view):
        """Take a pane out; a splitter left with one child is replaced by that child."""
        parent = view.parentWidget()
        view.hide()
        view.setParent(None)
        view.deleteLater()
        if isinstance(parent, QSplitter) and parent.count() == 1:
            only = parent.widget(0)
            grand = parent.parentWidget()
            if isinstance(grand, QSplitter):
                i, sizes = grand.indexOf(parent), grand.sizes()
                grand.replaceWidget(i, only)
                grand.setSizes(sizes)
            else:
                self.lay.replaceWidget(parent, only)
            parent.deleteLater()


class SearchBar(QFrame):
    def __init__(self, page):
        super().__init__()
        self.setObjectName("SearchBar")
        self.page = page
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 6, 12, 6)
        lay.setSpacing(6)
        icon = QLabel()
        icon.setPixmap(glyph("search", 16).pixmap(16, 16))
        lay.addWidget(icon)
        self.edit = QLineEdit()
        self.edit.setPlaceholderText("Search the scrollback   (Enter older, Shift+Enter newer)")
        self.edit.textChanged.connect(lambda: self.go(True))
        self.edit.returnPressed.connect(lambda: self.go(not QApplication.keyboardModifiers() & SHIFT))
        lay.addWidget(self.edit, 1)
        self.count = QLabel("")
        self.count.setObjectName("Muted")
        self.count.setMinimumWidth(70)
        lay.addWidget(self.count)
        for icon, back, tip in (("up", True, "Older match (Enter)"), ("down", False, "Newer match (Shift+Enter)")):
            lay.addWidget(tool(icon, tip, lambda _=False, back=back: self.go(back)))
        lay.addWidget(tool("close", "Close search (Esc)", self.close_bar))

    def go(self, backwards: bool):
        view = self.page.active_view()
        if not view:
            return
        n, total = view.find(self.edit.text(), backwards)
        self.count.setText(f"{n} of {total}" if total else ("No matches" if self.edit.text() else ""))

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Escape:
            return self.close_bar()
        super().keyPressEvent(e)

    def open_bar(self):
        self.show()
        view = self.page.active_view()
        if view and view.selected_text() and "\n" not in view.selected_text():
            self.edit.setText(view.selected_text())
        self.edit.setFocus()
        self.edit.selectAll()

    def close_bar(self):
        self.hide()
        self.count.setText("")
        for view in self.page.all_views():
            view.end_search()
        view = self.page.active_view()
        if view:
            view.sel = None
            view.setFocus()


class Palette(QFrame):
    """Saved commands: type to filter, Enter runs one in the active terminal, Shift+Enter only types it."""

    def __init__(self, page):
        super().__init__(page)
        self.setObjectName("Palette")
        self.page = page
        self.hide()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(8)
        self.filter = QLineEdit()
        self.filter.setPlaceholderText("Run a saved command…")
        self.filter.textChanged.connect(self._fill)
        self.filter.installEventFilter(self)
        lay.addWidget(self.filter)
        self.list = QListWidget()
        self.list.setObjectName("Commands")
        self.list.itemActivated.connect(lambda _: self.run(False))
        lay.addWidget(self.list, 1)
        add = QHBoxLayout()
        self.name = QLineEdit()
        self.name.setPlaceholderText("Name")
        self.cmd = QLineEdit()
        self.cmd.setPlaceholderText("Command")
        save = QPushButton("Save")
        save.clicked.connect(self._add)
        self.cmd.returnPressed.connect(self._add)
        remove = QPushButton("Remove")
        remove.setToolTip("Remove the selected command from the list")
        remove.clicked.connect(self._remove)
        add.addWidget(self.name, 1)
        add.addWidget(self.cmd, 2)
        add.addWidget(save)
        add.addWidget(remove)
        lay.addLayout(add)
        hint = QLabel("Enter runs it in the active tab · Shift+Enter types it without running · Esc closes")
        hint.setObjectName("Hint")
        lay.addWidget(hint)

    def open(self):
        w = min(720, self.page.width() - 40)
        self.setGeometry((self.page.width() - w) // 2, 56, w, min(440, self.page.height() - 80))
        self.filter.clear()
        self._fill()
        self.show()
        self.raise_()
        self.filter.setFocus()

    def _commands(self) -> list:
        return self.page.cfg["commands"]

    def _fill(self):
        q = self.filter.text().lower()
        self.list.clear()
        for c in self._commands():
            if q in c["name"].lower() or q in c["command"].lower():
                item = QListWidgetItem(f"{c['name']}\n{c['command']}")
                item.setData(Qt.ItemDataRole.UserRole, c)
                item.setToolTip(c["command"])
                self.list.addItem(item)
        if self.list.count():
            self.list.setCurrentRow(0)

    def run(self, type_only: bool):
        item = self.list.currentItem()
        view = self.page.active_view()
        self.close_palette()
        if item and view:
            cmd = item.data(Qt.ItemDataRole.UserRole)["command"]
            view.send_text(cmd if type_only else cmd + "\r")

    def _add(self):
        name, cmd = self.name.text().strip(), self.cmd.text().strip()
        if not cmd:
            return
        self._commands().append({"name": name or cmd[:40], "command": cmd})
        self.page.save_cfg()
        self.name.clear()
        self.cmd.clear()
        self._fill()

    def _remove(self):
        item = self.list.currentItem()
        if item:
            self._commands().remove(item.data(Qt.ItemDataRole.UserRole))
            self.page.save_cfg()
            self._fill()

    def close_palette(self):
        self.hide()
        view = self.page.active_view()
        if view:
            view.setFocus()

    def eventFilter(self, obj, e):
        if e.type() == QEvent.Type.KeyPress:
            if e.key() == Qt.Key.Key_Escape:
                self.close_palette()
                return True
            if e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self.run(bool(e.modifiers() & SHIFT))
                return True
            if e.key() in (Qt.Key.Key_Up, Qt.Key.Key_Down):
                row = self.list.currentRow() + (1 if e.key() == Qt.Key.Key_Down else -1)
                self.list.setCurrentRow(max(0, min(self.list.count() - 1, row)))
                return True
        return super().eventFilter(obj, e)

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Escape:
            return self.close_palette()
        super().keyPressEvent(e)


class ProfileDialog(QDialog):
    """Profiles: font, size, cursor shape and scrollback. Changes apply to open terminals right away."""

    def __init__(self, page):
        super().__init__(page)
        self.setWindowTitle("TerminalL profiles")
        self.page = page
        self.cfg = page.cfg
        self.resize(640, 380)
        root = QHBoxLayout(self)
        left = QVBoxLayout()
        self.names = QListWidget()
        self.names.setObjectName("Plain")
        self.names.currentTextChanged.connect(self._show)
        self.names.itemChanged.connect(self._renamed)
        left.addWidget(self.names, 1)
        row = QHBoxLayout()
        for text, slot in (("New", self._new), ("Remove", self._remove)):
            b = QPushButton(text)
            b.clicked.connect(slot)
            row.addWidget(b)
        left.addLayout(row)
        root.addLayout(left, 1)
        form = QVBoxLayout()
        form.setSpacing(6)

        def field(label, w):
            t = QLabel(label)
            t.setObjectName("Section")
            form.addWidget(t)
            form.addWidget(w)
            form.addSpacing(6)
            return w
        self.font_box = field("FONT", QFontComboBox())
        self.font_box.setFontFilters(QFontComboBox.FontFilter.MonospacedFonts)
        self.size_box = field("SIZE", QSpinBox())
        self.size_box.setRange(*config.LIMITS["size"])
        self.size_box.setSuffix(" pt")
        seg = QWidget()
        sl = QHBoxLayout(seg)
        sl.setContentsMargins(0, 0, 0, 0)
        sl.setSpacing(0)
        self.cursor_group = QButtonGroup(self)
        for i, shape in enumerate(config.CURSORS):
            b = QPushButton(shape.title())
            b.setObjectName("Segment")
            b.setCheckable(True)
            b.setProperty("pos", "first" if i == 0 else "last" if i == len(config.CURSORS) - 1 else "mid")
            self.cursor_group.addButton(b, i)
            sl.addWidget(b)
        sl.addStretch(1)
        field("CURSOR", seg)
        self.scrollback = field("SCROLLBACK LINES", QSpinBox())
        self.scrollback.setRange(*config.LIMITS["scrollback"])
        self.scrollback.setSingleStep(1000)
        form.addStretch(1)
        done = QPushButton("Done")
        done.setObjectName("Primary")
        done.clicked.connect(self.accept)
        form.addWidget(done, 0, Qt.AlignmentFlag.AlignRight)
        root.addLayout(form, 2)
        self.font_box.currentFontChanged.connect(lambda f: self._set("font", f.family()))
        self.size_box.valueChanged.connect(lambda v: self._set("size", v))
        self.cursor_group.idClicked.connect(lambda i: self._set("cursor", config.CURSORS[i]))
        self.scrollback.valueChanged.connect(lambda v: self._set("scrollback", v))
        self._loading = False
        self._list(self.cfg["profile"])

    def _list(self, select: str):
        self.names.blockSignals(True)
        self.names.clear()
        for name in self.cfg["profiles"]:
            item = QListWidgetItem(name)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
            self.names.addItem(item)
        self.names.blockSignals(False)
        found = self.names.findItems(select, Qt.MatchFlag.MatchExactly)
        self.names.setCurrentItem(found[0] if found else self.names.item(0))

    def _show(self, name: str):
        prof = self.cfg["profiles"].get(name)
        if not prof:
            return
        self._loading = True
        self.font_box.setCurrentFont(prof["font"])
        self.size_box.setValue(prof["size"])
        self.cursor_group.button(config.CURSORS.index(prof["cursor"])).setChecked(True)
        self.scrollback.setValue(prof["scrollback"])
        self._loading = False
        self.page.use_profile(name)

    def _set(self, key, value):
        item = self.names.currentItem()
        if self._loading or not item:
            return
        self.cfg["profiles"][item.text()][key] = value
        self.page.use_profile(item.text())

    def _renamed(self, item):
        old = self.cfg["profile"]
        new = item.text().strip()[:40]
        if not new or new in self.cfg["profiles"]:
            item.setText(old)
            return
        self.cfg["profiles"] = {(new if k == old else k): v for k, v in self.cfg["profiles"].items()}
        self.page.use_profile(new)

    def _new(self):
        n = 2
        while f"Profile {n}" in self.cfg["profiles"]:
            n += 1
        name = f"Profile {n}"
        self.cfg["profiles"][name] = dict(self.cfg["profiles"][self.cfg["profile"]])
        self._list(name)

    def _remove(self):
        item = self.names.currentItem()
        if item and len(self.cfg["profiles"]) > 1:
            del self.cfg["profiles"][item.text()]
            self._list(next(iter(self.cfg["profiles"])))


class TerminalLPage(QWidget):
    titleChanged = Signal(str)

    def __init__(self, start: Path | None = None, standalone: bool = False):
        super().__init__()
        self.setObjectName("Page")
        self.standalone = standalone
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        try:
            from grimoire.spells.terminall import session, view   # needs pyte
        except ImportError:
            self.ok = False
            lay.addWidget(Missing())
            return
        self.ok = True
        self._session, self._view = session, view
        self.setStyleSheet(LOCAL_QSS)
        self.cfg = config.load()
        self._active = None

        bar = QFrame()
        bar.setObjectName("TermBar")
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(8, 0, 10, 0)
        bl.setSpacing(2)
        self.tabs = QTabBar()
        self.tabs.setDrawBase(False)
        self.tabs.setMovable(True)
        self.tabs.setExpanding(False)
        self.tabs.setElideMode(Qt.TextElideMode.ElideMiddle)
        self.tabs.setUsesScrollButtons(True)
        self.tabs.currentChanged.connect(self._tab_changed)
        self.tabs.tabMoved.connect(self._tab_moved)
        bl.addWidget(self.tabs, 0)
        bl.addWidget(tool("plus", "New tab (Ctrl+Shift+T)", lambda: self.new_tab()))
        bl.addStretch(1)
        bl.addWidget(tool("splith", "Split side by side (Ctrl+Shift+E)", lambda: self.split(Qt.Orientation.Horizontal)))
        bl.addWidget(tool("splitv", "Split top and bottom (Ctrl+Shift+O)", lambda: self.split(Qt.Orientation.Vertical)))
        bl.addWidget(tool("search", "Search the scrollback (Ctrl+Shift+F)", lambda: self.search.open_bar()))
        bl.addWidget(tool("palette", "Saved commands (Ctrl+Shift+P)", lambda: self.palette.open()))
        bl.addWidget(tool("vault", "New tab in VaultL's folder", self.tab_at_vaultl))
        bl.addSpacing(8)
        self.profiles = QComboBox()
        self.profiles.setToolTip("Profile: font, size, cursor and scrollback")
        self.profiles.activated.connect(self._profile_picked)
        bl.addWidget(self.profiles)
        lay.addWidget(bar)

        self.stack = QStackedWidget()
        self.empty = self._empty_state()
        self.stack.addWidget(self.empty)
        lay.addWidget(self.stack, 1)
        self.search = SearchBar(self)
        self.search.hide()
        lay.addWidget(self.search)
        self.palette = Palette(self)
        self._fill_profiles()
        self.titles = QTimer(self, interval=1000)            # foreground program names change without output
        self.titles.timeout.connect(self._retitle)
        self.titles.start()
        QApplication.instance().aboutToQuit.connect(self.close_all)
        self.new_tab(start)

    def _empty_state(self) -> QWidget:
        w = QWidget()
        w.setObjectName("Page")
        lay = QVBoxLayout(w)
        lay.addStretch(1)
        t = QLabel("No terminals open")
        t.setObjectName("Muted")
        t.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        lay.addWidget(t)
        b = QPushButton("New tab")
        b.setObjectName("Primary")
        b.clicked.connect(lambda: self.new_tab())
        lay.addWidget(b, 0, Qt.AlignmentFlag.AlignHCenter)
        lay.addStretch(1)
        return w

    # -- profiles ----------------------------------------------------------------------------------------------
    def profile(self) -> dict:
        return self.cfg["profiles"][self.cfg["profile"]]

    def save_cfg(self):
        try:
            config.save(self.cfg)
        except OSError:
            pass

    def _fill_profiles(self):
        self.profiles.blockSignals(True)
        self.profiles.clear()
        self.profiles.addItems(list(self.cfg["profiles"]))
        self.profiles.insertSeparator(self.profiles.count())
        self.profiles.addItem(EDIT_PROFILES)
        self.profiles.setCurrentText(self.cfg["profile"])
        self.profiles.blockSignals(False)

    def _profile_picked(self, i: int):
        text = self.profiles.itemText(i)
        if text == EDIT_PROFILES:
            self.profiles.setCurrentText(self.cfg["profile"])
            ProfileDialog(self).exec()
            self._fill_profiles()
            self.save_cfg()
        elif text in self.cfg["profiles"]:
            self.use_profile(text)
            self.save_cfg()

    def use_profile(self, name: str):
        """Pick a profile: it becomes the default and every open terminal takes it on."""
        self.cfg["profile"] = name
        for v in self.all_views():
            v.set_profile(self.profile())

    # -- tabs and panes ----------------------------------------------------------------------------------------
    def _make_view(self, cwd: Path | None):
        cwd = cwd if cwd and cwd.is_dir() else (self._active.session.cwd() if self._active else None) or HOME
        prof = self.profile()
        s = self._session.Session(cwd, 80, 24, prof["scrollback"], self)
        v = self._view.TerminalView(s, prof)
        v.activated.connect(self._activate)
        v.titleChanged.connect(self._retitle)
        v.shortcut.connect(lambda e, v=v: self._shortcut(v, e))
        s.finished.connect(lambda v=v: self.close_view(v))
        return v

    def new_tab(self, cwd: Path | None = None):
        v = self._make_view(cwd)
        tab = Tab(v)
        self.stack.addWidget(tab)
        i = self.tabs.addTab("Shell")
        self.tabs.setTabData(i, tab)
        close = tool("close", "Close tab", lambda _=False, tab=tab: self.close_tab(tab))
        close.setIconSize(QSize(12, 12))
        close.setIcon(glyph("close", 12))
        self.tabs.setTabButton(i, QTabBar.ButtonPosition.RightSide, close)
        self.tabs.setCurrentIndex(i)
        self.stack.setCurrentWidget(tab)
        self._activate(v)
        v.setFocus()
        return v

    def split(self, orientation: Qt.Orientation):
        view = self.active_view()
        if not view:
            return self.new_tab()
        tab = self._tab_of(view)
        new = self._make_view(view.session.cwd())
        tab.split(view, new, orientation)
        self._mark_focus(tab)
        new.setFocus()

    def close_view(self, view):
        tab = self._tab_of(view)
        view.session.close()
        if tab is None:
            return
        rest = [v for v in tab.views() if v is not view]
        if not rest:
            return self._drop_tab(tab)
        tab.remove(view)
        tab.active = rest[0]
        self._mark_focus(tab)
        if self._active is view:
            self._active = None
            rest[0].setFocus()
            self._activate(rest[0])

    def close_tab(self, tab):
        for v in tab.views():
            v.session.close()
        self._drop_tab(tab)

    def _drop_tab(self, tab):
        i = self._tab_index(tab)
        if i >= 0:
            self.tabs.removeTab(i)
        self.stack.removeWidget(tab)
        tab.deleteLater()
        if self._active and self._tab_of(self._active) in (tab, None):
            self._active = None
        if self.tabs.count() == 0:
            if self.standalone:
                QTimer.singleShot(0, self.window().close)
            self.stack.setCurrentWidget(self.empty)
            self.titleChanged.emit("TerminalL")
        else:
            self._tab_changed(self.tabs.currentIndex())

    def close_all(self):
        for v in self.all_views():
            v.session.close()

    def _tab_index(self, tab) -> int:
        return next((i for i in range(self.tabs.count()) if self.tabs.tabData(i) is tab), -1)

    def _tab_of(self, view):
        w = view.parentWidget()
        while w is not None and not isinstance(w, Tab):
            w = w.parentWidget()
        return w

    def _tab_changed(self, i: int):
        tab = self.tabs.tabData(i) if i >= 0 else None
        if tab is None:
            return
        self.stack.setCurrentWidget(tab)
        views = tab.views()
        if views:
            target = tab.active if tab.active in views else views[0]
            target.setFocus()
            self._activate(target)

    def _tab_moved(self, *_):
        pass                                    # tab data travels with the tab; the stack order doesn't matter

    def _activate(self, view):
        self._active = view
        tab = self._tab_of(view)
        if tab:
            tab.active = view
        if self.search.isVisible() and self.search.edit.text():
            self.search.count.setText("")
        self._retitle()

    def _mark_focus(self, tab):
        views = tab.views()
        for v in views:
            v.show_focus = len(views) > 1
            v.update()

    def active_view(self):
        return self._active if self._active is not None and self._active.session.fd >= 0 else None

    def all_views(self) -> list:
        return [v for i in range(self.tabs.count()) for v in self.tabs.tabData(i).views()] \
            if self.ok and hasattr(self, "tabs") else []

    def busy(self) -> list[str]:
        """Programs still running in the foreground of some tab (worth a question before closing)."""
        return [name for v in self.all_views() if (name := v.session.foreground())]

    def _retitle(self):
        for i in range(self.tabs.count()):
            tab = self.tabs.tabData(i)
            views = tab.views()
            if not views:
                continue
            v = tab.active if tab.active in views else views[0]
            title = v.title()
            short = title if len(title) <= 32 else "…" + title[-31:]
            if self.tabs.tabText(i) != short:
                self.tabs.setTabText(i, short)
                self.tabs.setTabToolTip(i, title)
        v = self.active_view()
        self.titleChanged.emit(f"{v.title()} — TerminalL" if v else "TerminalL")

    def tab_at_vaultl(self):
        folder = vaultl_folder()
        self.new_tab(folder or HOME)

    # -- keys and menu -----------------------------------------------------------------------------------------
    def _shortcut(self, view, e):
        if not isinstance(e, QKeyEvent):
            return self._menu(view, e)
        mods, key = e.modifiers() & (CTRL | SHIFT | Qt.KeyboardModifier.AltModifier), e.key()
        actions = {}
        if mods == CTRL | SHIFT:
            actions = {Qt.Key.Key_T: lambda: self.new_tab(view.session.cwd()), Qt.Key.Key_W: lambda: self.close_view(view),
                       Qt.Key.Key_E: lambda: self.split(Qt.Orientation.Horizontal),
                       Qt.Key.Key_O: lambda: self.split(Qt.Orientation.Vertical),
                       Qt.Key.Key_F: self.search.open_bar, Qt.Key.Key_P: self.palette.open,
                       Qt.Key.Key_Backtab: lambda: self._cycle(-1), Qt.Key.Key_Tab: lambda: self._cycle(-1)}
        elif mods == CTRL:
            actions = {Qt.Key.Key_PageUp: lambda: self._cycle(-1), Qt.Key.Key_PageDown: lambda: self._cycle(1),
                       Qt.Key.Key_Tab: lambda: self._cycle(1)}
        act = actions.get(key)
        if act:
            e.accept()
            act()

    def _cycle(self, step: int):
        if self.tabs.count():
            self.tabs.setCurrentIndex((self.tabs.currentIndex() + step) % self.tabs.count())

    def _menu(self, view, e):
        m = QMenu(self)
        has_sel = bool(view.selected_text())
        m.addAction(glyph("copies", 16), "Copy\tCtrl+Shift+C", view.copy).setEnabled(has_sel)
        m.addAction("Paste\tCtrl+Shift+V", view.paste)
        m.addAction("Select all\tCtrl+Shift+A", view.select_all)
        m.addSeparator()
        m.addAction(glyph("splith", 16), "Split side by side\tCtrl+Shift+E", lambda: self.split(Qt.Orientation.Horizontal))
        m.addAction(glyph("splitv", 16), "Split top and bottom\tCtrl+Shift+O", lambda: self.split(Qt.Orientation.Vertical))
        m.addAction(glyph("plus", 16), "New tab\tCtrl+Shift+T", lambda: self.new_tab(view.session.cwd()))
        m.addSeparator()
        m.addAction(glyph("search", 16), "Search…\tCtrl+Shift+F", self.search.open_bar)
        m.addAction(glyph("palette", 16), "Saved commands…\tCtrl+Shift+P", self.palette.open)
        m.addAction(glyph("vault", 16), "Open this folder in VaultL", lambda: self.open_in_vaultl(view))
        m.addAction("Clear scrollback", view.clear_scrollback)
        m.addSeparator()
        m.addAction(glyph("close", 16), "Close pane\tCtrl+Shift+W", lambda: self.close_view(view))
        m.exec(e.globalPosition().toPoint())

    def open_in_vaultl(self, view):
        from grimoire.standalone import BIN
        cwd = view.session.cwd() or HOME
        cmd = BIN / "grimoire-vaultl"
        if cmd.is_file():
            subprocess.Popen([str(cmd), str(cwd)], start_new_session=True)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self.ok and self.palette.isVisible():
            self.palette.open()


def status() -> str:
    try:
        from grimoire.spells.terminall import session
    except ImportError:
        return f"Needs pyte: {APT}"
    n = sum(1 for s in session.LIVE if s.alive)
    return f"{n} session{'s' if n != 1 else ''} open" if n else "Ready · your shell, in black and white"
