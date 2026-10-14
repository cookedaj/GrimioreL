# SPDX-License-Identifier: GPL-3.0-or-later
"""The Community view inside a MuraL tab: browse the top 100 of a store category and install items."""
import webbrowser

from PySide6.QtCore import QObject, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QIcon, QImage, QPainter, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QFrame, QHBoxLayout, QLabel, QLineEdit,
                               QListWidget, QListWidgetItem, QPushButton, QVBoxLayout, QWidget)

from grimoire.spells.mural import store
from grimoire.jobs import POOL, Job

CARD = QSize(232, 146)
SORTS = {"Most downloaded": "down", "Best rated": "high", "Newest": "new"}


class _Signals(QObject):
    listed = Signal(int, object)          # generation, list[Item] or Exception
    thumb = Signal(int, int, QImage)      # generation, row, image
    installed = Signal(bool, str)


def fit(img: QImage, size: QSize) -> QPixmap:
    """Letterbox an image onto a dark card of `size`."""
    pm = QPixmap(size)
    pm.fill(QColor("#111111"))
    if not img.isNull():
        scaled = img.scaled(size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        p = QPainter(pm)
        p.drawImage((size.width() - scaled.width()) // 2, (size.height() - scaled.height()) // 2, scaled)
        p.end()
    return pm


def _label(it: store.Item, installed: bool) -> str:
    stats = f"{it.downloads:,} ↓" + (f"  ·  {it.score}%" if it.score else "")
    return f"{'✓ ' if installed else ''}{it.name}\n{stats}"


def _load_thumb(url: str) -> QImage:
    path = store.thumbnail(url)
    return QImage(str(path)) if path else QImage()


class StoreView(QWidget):
    """on_installed() is called after an install/uninstall so the tab can refresh its designs."""

    def __init__(self, category_keys: list[str], on_installed):
        super().__init__()
        self.cats = [store.CATEGORIES[k] for k in category_keys]
        self.on_installed = on_installed
        self.items: list[store.Item] = []
        self._gen = 0
        self._sig = _Signals()
        self._sig.listed.connect(self._on_listed)
        self._sig.thumb.connect(self._on_thumb)
        self._sig.installed.connect(self._on_installed)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)

        bar = QHBoxLayout()
        bar.setSpacing(8)
        self.category = QComboBox()
        self.category.addItems([c.title for c in self.cats])
        self.category.setVisible(len(self.cats) > 1)
        self.sort = QComboBox()
        self.sort.addItems(list(SORTS))
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search…")
        self.search.setClearButtonEnabled(True)
        self.bw = QCheckBox("Convert to black & white")
        self.bw.setChecked(True)
        for w in (self.category, self.sort, self.search):
            bar.addWidget(w)
        bar.addWidget(self.bw)
        bar.addStretch(1)
        self.count = QLabel()
        self.count.setObjectName("Muted")
        bar.addWidget(self.count)
        lay.addLayout(bar)
        self._search_timer = QTimer(self, singleShot=True, interval=450, timeout=self.refresh)
        self.category.currentIndexChanged.connect(self.refresh)
        self.sort.currentIndexChanged.connect(self.refresh)
        self.search.textChanged.connect(lambda _: self._search_timer.start())

        self.grid = QListWidget()
        self.grid.setViewMode(QListWidget.ViewMode.IconMode)
        self.grid.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.grid.setMovement(QListWidget.Movement.Static)
        self.grid.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.grid.setIconSize(CARD)
        self.grid.setGridSize(QSize(CARD.width() + 16, CARD.height() + 52))
        self.grid.setUniformItemSizes(True)
        self.grid.setWordWrap(True)
        self.grid.currentRowChanged.connect(self._select)
        self.grid.itemDoubleClicked.connect(lambda _: self._install())
        lay.addWidget(self.grid, 1)

        detail = QFrame()
        detail.setObjectName("Card")
        dl = QHBoxLayout(detail)
        dl.setContentsMargins(18, 12, 12, 12)
        info = QVBoxLayout()
        info.setSpacing(2)
        self.d_name = QLabel("Pick something to see details")
        self.d_name.setObjectName("Section")
        self.d_meta = QLabel()
        self.d_meta.setObjectName("Muted")
        self.d_meta.setWordWrap(True)
        info.addWidget(self.d_name)
        info.addWidget(self.d_meta)
        dl.addLayout(info, 1)
        self.page_btn = QPushButton("Store page")
        self.page_btn.clicked.connect(lambda: self._current() and webbrowser.open(self._current().page))
        self.install_btn = QPushButton("Install")
        self.install_btn.setObjectName("Primary")
        self.install_btn.setMinimumWidth(130)
        self.install_btn.clicked.connect(self._install)
        dl.addWidget(self.page_btn)
        dl.addWidget(self.install_btn)
        lay.addWidget(detail)
        self._select(-1)
        self._loaded = False

    def showEvent(self, e):
        super().showEvent(e)
        if not self._loaded:              # only hit the network once the user opens Community
            self._loaded = True
            self.refresh()

    def cat(self) -> store.Category:
        return self.cats[max(0, self.category.currentIndex())]

    # ---- listing
    def refresh(self):
        self._gen += 1
        gen, cat, sort, q, sig = self._gen, self.cat(), SORTS[self.sort.currentText()], self.search.text().strip(), self._sig
        self.bw.setVisible(cat.kind == "wallpaper")
        self.grid.clear()
        self.items = []
        self.count.setText("Loading…")

        def work():
            try:
                return store.top(cat, sort, q)
            except Exception as e:      # network errors are shown, not raised
                return e

        POOL.start(Job(work, lambda r: sig.listed.emit(gen, r)))

    def _on_listed(self, gen, result):
        if gen != self._gen:
            return
        if isinstance(result, Exception):
            self.count.setText(f"Couldn't reach the store: {result}")
            return
        self.items = result
        self.count.setText(f"Top {len(result)}")
        placeholder = QIcon(fit(QImage(), CARD))
        installed = {e["item"] for e in store.registry().values()}
        sig = self._sig
        for i, it in enumerate(result):
            row = QListWidgetItem(placeholder, _label(it, it.id in installed))
            row.setTextAlignment(Qt.AlignmentFlag.AlignHCenter)
            row.setToolTip(it.summary or it.name)
            self.grid.addItem(row)
            POOL.start(Job(lambda url=it.preview: _load_thumb(url),
                           lambda img, i=i: sig.thumb.emit(gen, i, img)))

    def _on_thumb(self, gen, row, img):
        if gen == self._gen and row < self.grid.count():
            self.grid.item(row).setIcon(QIcon(fit(img, CARD)))

    # ---- detail / install
    def _current(self) -> store.Item | None:
        r = self.grid.currentRow()
        return self.items[r] if 0 <= r < len(self.items) else None

    def _select(self, _row):
        it = self._current()
        self.install_btn.setEnabled(it is not None)
        self.page_btn.setEnabled(bool(it and it.page))
        if not it:
            return
        self.d_name.setText(it.name.upper())
        bits = [f"by {it.author}" if it.author else "", f"{it.downloads:,} downloads",
                f"rated {it.score}%" if it.score else "", it.summary]
        self.d_meta.setText("  ·  ".join(b for b in bits if b))
        self.install_btn.setText("Uninstall" if store.is_installed(it.id) else "Install")

    def _install(self):
        it, cat, bw, sig = self._current(), self.cat(), self.bw.isChecked(), self._sig
        if not it:
            return
        self.install_btn.setEnabled(False)
        removing = store.is_installed(it.id)
        self.install_btn.setText("Removing…" if removing else "Installing…")

        def work():
            try:
                if removing:
                    for key, e in list(store.registry().items()):
                        if e["item"] == it.id:
                            store.uninstall(key)
                    return True, f"Removed {it.name}"
                entries = store.install(cat, it, to_bw=bw)
                return True, f"Installed {', '.join(e['name'] for e in entries)} — it's now in Designs"
            except Exception as e:
                return False, f"Couldn't install {it.name}: {e}"

        POOL.start(Job(work, lambda r: sig.installed.emit(*r)))

    def _on_installed(self, ok, msg):
        self.d_meta.setText(msg)
        row = self.grid.currentRow()
        if ok and 0 <= row < len(self.items):
            it = self.items[row]
            self.grid.item(row).setText(_label(it, store.is_installed(it.id)))
        self.install_btn.setEnabled(True)
        it = self._current()
        if it:
            self.install_btn.setText("Uninstall" if store.is_installed(it.id) else "Install")
        if ok:
            self.on_installed()
