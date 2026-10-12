"""FileL: Grimoire's file manager. Same system underneath (the local filesystem via QFileSystemModel,
the freedesktop Trash via gio, KDE-compatible clipboard), new black & white interface.

Shortcuts follow Dolphin: Alt+Left/Right/Up, Backspace, F2, Del, Ctrl+C/X/V, Ctrl+A, Ctrl+H, Ctrl+L, Ctrl+F,
Ctrl+Shift+N, F5, F4 (terminal here), Enter to open.
"""
import subprocess
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import (QDir, QItemSelectionModel, QMimeData, QMimeDatabase, QModelIndex, QObject, QRect, QRectF, QSize,
                            QStorageInfo, Qt, QThreadPool, QTimer, QUrl, Signal)
from PySide6.QtGui import (QColor, QDesktopServices, QFont, QFontMetrics, QGuiApplication, QIcon, QImage,
                           QImageReader, QKeySequence, QPainter, QPainterPath, QPixmap, QShortcut)
from PySide6.QtWidgets import (QAbstractItemView, QFileSystemModel, QFrame, QHBoxLayout, QHeaderView,
                               QLabel, QLineEdit, QListView, QListWidget, QListWidgetItem, QMenu, QMessageBox,
                               QPushButton, QSplitter, QStackedWidget, QStyle, QStyledItemDelegate, QToolButton,
                               QTreeView, QVBoxLayout, QWidget)

from grimoire.fsutil import human, tilde
from grimoire.glyphs import glyph
from grimoire.jobs import Job
from grimoire.paths import HOME
from grimoire.spells.filel import ops

IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".avif", ".tif", ".tiff", ".svg"}
TEXT_EXT = {".txt", ".md", ".py", ".lua", ".luau", ".json", ".toml", ".yaml", ".yml", ".sh", ".ini", ".cfg",
            ".conf", ".log", ".csv", ".qml", ".js", ".ts", ".rs", ".c", ".h", ".cpp", ".html", ".css", ".xml"}
PLACES = [("Home", "home", "~"), ("Desktop", "desktop", "~/Desktop"), ("Repo", "terminal", "~/Desktop/Repo"),
          ("Documents", "document", "~/Documents"), ("Downloads", "store", "~/Downloads"),
          ("Pictures", "mural", "~/Pictures"), ("Videos", "video", "~/Videos"), ("Music", "music", "~/Music"),
          ("Trash", "trash", str(ops.TRASH_FILES))]
THUMBS = QThreadPool()
THUMBS.setMaxThreadCount(3)
GRID = QSize(128, 132)
ICON = 72


class _Signals(QObject):
    thumb = Signal(str, QImage)
    transferred = Signal(int, list, str)
    sized = Signal(str, object, object)     # sizes can exceed 32-bit ints


class GridDelegate(QStyledItemDelegate):
    """Icon-grid cells: rounded selection, real thumbnails for images (generated off the UI thread)."""

    def __init__(self, page):
        super().__init__(page)
        self.page = page
        self.cache: dict[str, QPixmap] = {}
        self.pending: set[str] = set()

    def sizeHint(self, option, index):
        return GRID

    def paint(self, p: QPainter, option, index):
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = option.rect.adjusted(4, 4, -4, -4)
        selected = option.state & QStyle.StateFlag.State_Selected
        hover = option.state & QStyle.StateFlag.State_MouseOver
        if selected or hover:
            path = QPainterPath()
            path.addRoundedRect(QRectF(r), 10, 10)
            p.fillPath(path, QColor("#232323" if selected else "#141414"))
        model: QFileSystemModel = index.model()
        fpath = model.filePath(index)
        icon_rect = QRect(r.center().x() - ICON // 2, r.y() + 8, ICON, ICON)
        pm = self._thumb(fpath) if Path(fpath).suffix.lower() in IMAGE_EXT else None
        if pm is not None:
            scaled = pm.scaled(icon_rect.size(), Qt.AspectRatioMode.KeepAspectRatio,
                               Qt.TransformationMode.SmoothTransformation)
            p.drawPixmap(icon_rect.x() + (ICON - scaled.width()) // 2,
                         icon_rect.y() + (ICON - scaled.height()) // 2, scaled)
        elif model.isDir(index):
            glyph("folder", ICON).paint(p, icon_rect, mode=QIcon.Mode.Active if selected else QIcon.Mode.Normal)
        else:
            icon = model.fileIcon(index)
            (icon if not icon.isNull() and icon.availableSizes() else glyph("document", ICON)).paint(p, icon_rect)
        p.setPen(QColor("#ffffff" if selected else "#d6d6d6"))
        f = QFont(option.font)
        p.setFont(f)
        fm = QFontMetrics(f)
        text_rect = QRect(r.x() + 4, icon_rect.bottom() + 6, r.width() - 8, fm.height() * 2 + 2)
        name = model.fileName(index)
        lines = fm.elidedText(name, Qt.TextElideMode.ElideMiddle, text_rect.width() * 2 - 12)
        p.drawText(text_rect, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWrapAnywhere,
                   lines)
        p.restore()

    def _thumb(self, fpath: str) -> QPixmap | None:
        if fpath in self.cache:
            return self.cache[fpath]
        if fpath not in self.pending:
            self.pending.add(fpath)
            sig = self.page._sig

            def work():
                reader = QImageReader(fpath)
                reader.setAutoTransform(True)
                size = reader.size()
                if size.isValid():
                    reader.setScaledSize(size.scaled(QSize(ICON * 2, ICON * 2), Qt.AspectRatioMode.KeepAspectRatio))
                return reader.read()

            THUMBS.start(Job(work, lambda img: sig.thumb.emit(fpath, img)))
        return None

    def ready(self, fpath: str, img: QImage):
        self.pending.discard(fpath)
        if not img.isNull():
            self.cache[fpath] = QPixmap.fromImage(img)
            self.page.grid.viewport().update()


class FileLPage(QWidget):
    def __init__(self, start: str | Path | None = None, standalone: bool = False):
        super().__init__()
        self.setObjectName("Page")
        self._sig = _Signals()
        self.history: list[Path] = []
        self.hist_i = -1
        self.show_hidden = False
        self.standalone = standalone                      # own window: the title follows the folder
        self.cwd = HOME

        self.model = QFileSystemModel(self)
        self.model.setRootPath("/")
        self.model.setReadOnly(False)                     # rename + drag & drop moves
        self.model.setNameFilterDisables(False)
        self._apply_filter()

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._sidebar())

        main = QWidget()
        ml = QVBoxLayout(main)
        ml.setContentsMargins(18, 14, 18, 10)
        ml.setSpacing(10)
        ml.addLayout(self._toolbar())
        self.trash_bar = self._trash_bar()
        ml.addWidget(self.trash_bar)

        split = QSplitter(Qt.Orientation.Horizontal)
        split.setHandleWidth(1)
        self.views = QStackedWidget()
        self.grid = self._make_grid()
        self.details = self._make_details()
        self.views.addWidget(self.grid)
        self.views.addWidget(self.details)
        split.addWidget(self.views)
        self.preview = self._preview_pane()
        split.addWidget(self.preview)
        split.setStretchFactor(0, 1)
        split.setSizes([900, 280])
        ml.addWidget(split, 1)
        self.status = QLabel()
        self.status.setObjectName("Muted")
        ml.addWidget(self.status)
        root.addWidget(main, 1)

        self._sig.thumb.connect(self.grid_delegate.ready)
        self._sig.transferred.connect(self._transfer_done)
        self._sig.sized.connect(self._folder_sized)
        self.model.directoryLoaded.connect(lambda _: self._update_status())
        self._shortcuts()
        self.navigate(Path(start).expanduser() if start else HOME)

    # ================================================================== layout
    def _sidebar(self) -> QWidget:
        side = QFrame()
        side.setObjectName("SubNav")
        side.setFixedWidth(200)
        v = QVBoxLayout(side)
        v.setContentsMargins(12, 18, 12, 14)
        v.setSpacing(4)
        title = QLabel("FileL")
        title.setObjectName("Title")
        v.addWidget(title)
        v.addSpacing(10)
        label = QLabel("PLACES")
        label.setObjectName("NavSection")
        v.addWidget(label)
        self.places = QListWidget()
        self.places.setObjectName("Places")
        self.places.setIconSize(QSize(18, 18))
        for name, icon, path in PLACES:
            p = Path(path).expanduser()
            if p.exists() or name == "Trash":
                it = QListWidgetItem(glyph(icon, 18), name)
                it.setData(Qt.ItemDataRole.UserRole, str(p))
                self.places.addItem(it)
        self.places.itemClicked.connect(lambda it: self.navigate(Path(it.data(Qt.ItemDataRole.UserRole))))
        v.addWidget(self.places, 3)
        dl = QLabel("DRIVES")
        dl.setObjectName("NavSection")
        v.addWidget(dl)
        self.drives = QListWidget()
        self.drives.setObjectName("Places")
        self.drives.setIconSize(QSize(18, 18))
        self.drives.itemClicked.connect(lambda it: self.navigate(Path(it.data(Qt.ItemDataRole.UserRole))))
        v.addWidget(self.drives, 2)
        self._fill_drives()
        return side

    def _fill_drives(self):
        self.drives.clear()
        seen = set()
        for vol in sorted(QStorageInfo.mountedVolumes(), key=lambda v: len(v.rootPath())):
            dev = bytes(vol.device()).decode(errors="ignore")
            root = vol.rootPath()
            if not vol.isValid() or not vol.isReady() or not dev.startswith("/dev/") or "/snap" in root \
                    or root.startswith("/boot"):
                continue
            if dev in seen:                                  # same disk mounted twice (e.g. / and a subvolume)
                continue
            seen.add(dev)
            name = "System" if root == "/" else (vol.displayName() or Path(root).name)
            it = QListWidgetItem(glyph("drive", 18), f"{name}\n{human(vol.bytesAvailable())} free")
            it.setData(Qt.ItemDataRole.UserRole, root)
            it.setToolTip(f"{root}  ·  {human(vol.bytesAvailable())} free of {human(vol.bytesTotal())}")
            self.drives.addItem(it)

    def _tool(self, icon, tip, slot, checkable=False) -> QToolButton:
        b = QToolButton()
        b.setObjectName("Tool")
        b.setIcon(glyph(icon, 18))
        b.setIconSize(QSize(18, 18))
        b.setToolTip(tip)
        b.setCheckable(checkable)
        b.setAutoRaise(True)
        b.clicked.connect(slot)
        return b

    def _toolbar(self):
        bar = QHBoxLayout()
        bar.setSpacing(4)
        self.back_btn = self._tool("back", "Back (Alt+Left)", self.back)
        self.fwd_btn = self._tool("forward", "Forward (Alt+Right)", self.forward)
        self.up_btn = self._tool("up", "Up (Alt+Up)", self.up)
        for b in (self.back_btn, self.fwd_btn, self.up_btn):
            bar.addWidget(b)
        bar.addSpacing(6)
        self.path_stack = QStackedWidget()
        self.path_stack.setFixedHeight(34)
        self.crumbs = QFrame()
        self.crumbs.setObjectName("Crumbs")
        self.crumb_lay = QHBoxLayout(self.crumbs)
        self.crumb_lay.setContentsMargins(6, 0, 6, 0)
        self.crumb_lay.setSpacing(0)
        self.path_edit = QLineEdit()
        self.path_edit.returnPressed.connect(self._path_entered)
        self.path_edit.editingFinished.connect(lambda: self.path_stack.setCurrentIndex(0))
        self.path_stack.addWidget(self.crumbs)
        self.path_stack.addWidget(self.path_edit)
        self.crumbs.mouseDoubleClickEvent = lambda e: self.edit_path()
        bar.addWidget(self.path_stack, 1)
        bar.addSpacing(6)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search this folder")
        self.search.setClearButtonEnabled(True)
        self.search.addAction(glyph("search", 16), QLineEdit.ActionPosition.LeadingPosition)
        self.search.setFixedWidth(220)
        self.search.textChanged.connect(self._filter_names)
        bar.addWidget(self.search)
        bar.addSpacing(6)
        self.new_btn = self._tool("newfolder", "New folder (Ctrl+Shift+N)", self.new_folder)
        self.grid_btn = self._tool("grid", "Grid", lambda: self.set_view(0), True)
        self.list_btn = self._tool("list", "Details", lambda: self.set_view(1), True)
        self.hidden_btn = self._tool("hidden", "Show hidden files (Ctrl+H)", self.toggle_hidden, True)
        self.prev_btn = self._tool("preview", "Preview panel (F11)", self.toggle_preview, True)
        self.prev_btn.setChecked(True)
        for b in (self.new_btn, self.grid_btn, self.list_btn, self.hidden_btn, self.prev_btn):
            bar.addWidget(b)
        self.grid_btn.setChecked(True)
        return bar

    def _trash_bar(self) -> QWidget:
        w = QFrame()
        w.setObjectName("Card")
        h = QHBoxLayout(w)
        h.setContentsMargins(14, 8, 8, 8)
        t = QLabel("Trash · items here can be restored to where they came from")
        t.setObjectName("Muted")
        h.addWidget(t, 1)
        restore = QPushButton("Restore selected")
        restore.clicked.connect(self.restore_selected)
        empty = QPushButton("Empty Trash…")
        empty.clicked.connect(self.empty_trash)
        h.addWidget(restore)
        h.addWidget(empty)
        w.hide()
        return w

    def _common_view(self, view: QAbstractItemView):
        view.setModel(self.model)
        view.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        view.setDragEnabled(True)
        view.setAcceptDrops(True)
        view.setDropIndicatorShown(True)
        view.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        view.setDefaultDropAction(Qt.DropAction.MoveAction)
        view.setEditTriggers(QAbstractItemView.EditTrigger.EditKeyPressed | QAbstractItemView.EditTrigger.SelectedClicked)
        view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        view.customContextMenuRequested.connect(lambda pos, v=view: self._menu(v, pos))
        view.activated.connect(self.open_index)
        view.setFrameShape(QFrame.Shape.NoFrame)

    def _make_grid(self) -> QListView:
        g = QListView()
        g.setObjectName("FileGrid")
        g.setViewMode(QListView.ViewMode.IconMode)
        g.setResizeMode(QListView.ResizeMode.Adjust)
        g.setMovement(QListView.Movement.Snap)
        g.setGridSize(GRID)
        g.setUniformItemSizes(True)
        g.setWordWrap(True)
        g.setMouseTracking(True)
        g.setSpacing(4)
        self.grid_delegate = GridDelegate(self)
        g.setItemDelegate(self.grid_delegate)
        self._common_view(g)
        g.setMovement(QListView.Movement.Static)
        return g

    def _make_details(self) -> QTreeView:
        t = QTreeView()
        t.setObjectName("FileDetails")
        self._common_view(t)
        t.setRootIsDecorated(False)
        t.setItemsExpandable(False)
        t.setUniformRowHeights(True)
        t.setSortingEnabled(True)
        t.sortByColumn(0, Qt.SortOrder.AscendingOrder)
        t.setIconSize(QSize(20, 20))
        t.setAlternatingRowColors(False)
        h = t.header()
        h.setStretchLastSection(False)
        h.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for c, w in ((1, 100), (2, 150), (3, 170)):
            t.setColumnWidth(c, w)
        return t

    def _preview_pane(self) -> QWidget:
        w = QFrame()
        w.setObjectName("Panel")
        w.setMinimumWidth(240)
        v = QVBoxLayout(w)
        v.setContentsMargins(18, 18, 18, 18)
        v.setSpacing(10)
        self.pv_image = QLabel()
        self.pv_image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.pv_image.setMinimumHeight(180)
        self.pv_text = QLabel()
        self.pv_text.setObjectName("Mono")
        self.pv_text.setWordWrap(True)
        self.pv_text.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.pv_name = QLabel()
        self.pv_name.setObjectName("Section")
        self.pv_name.setWordWrap(True)
        self.pv_info = QLabel()
        self.pv_info.setObjectName("Muted")
        self.pv_info.setWordWrap(True)
        self.pv_info.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        for x in (self.pv_image, self.pv_text, self.pv_name, self.pv_info):
            v.addWidget(x)
        self.pv_text.hide()
        v.addStretch(1)
        self.pv_open = QPushButton("Open")
        self.pv_open.setObjectName("Primary")
        self.pv_open.clicked.connect(lambda: [self.open_path(p) for p in self.selected()[:1]])
        v.addWidget(self.pv_open)
        return w

    # ================================================================== navigation
    def view(self) -> QAbstractItemView:
        return self.views.currentWidget()

    def navigate(self, path: Path, record=True):
        path = Path(path)
        if not path.is_dir():
            self.status.setText(f"Can't open {tilde(path)}")
            return
        self.cwd = path
        if record:
            del self.history[self.hist_i + 1:]
            self.history.append(path)
            self.hist_i = len(self.history) - 1
        if self.search.text():
            self.search.blockSignals(True)
            self.search.clear()
            self.search.blockSignals(False)
            self.model.setNameFilters([])
        idx = self.model.index(str(path))
        for v in (self.grid, self.details):
            v.setRootIndex(idx)
            v.clearSelection()
        self._crumbs()
        self.back_btn.setEnabled(self.hist_i > 0)
        self.fwd_btn.setEnabled(self.hist_i < len(self.history) - 1)
        self.up_btn.setEnabled(path != path.parent)
        self.trash_bar.setVisible(ops.in_trash(path))
        for i in range(self.places.count()):
            it = self.places.item(i)
            it.setSelected(Path(it.data(Qt.ItemDataRole.UserRole)) == path)
        self._update_preview()
        self._update_status()
        self._update_title()

    def _update_title(self):
        if self.standalone and self.window() is not self:
            self.window().setWindowTitle(f"{self.cwd.name or self.cwd} — FileL")

    def back(self):
        if self.hist_i > 0:
            self.hist_i -= 1
            self.navigate(self.history[self.hist_i], record=False)

    def forward(self):
        if self.hist_i < len(self.history) - 1:
            self.hist_i += 1
            self.navigate(self.history[self.hist_i], record=False)

    def up(self):
        if self.cwd != self.cwd.parent:
            self.navigate(self.cwd.parent)

    def _crumbs(self):
        while self.crumb_lay.count():
            w = self.crumb_lay.takeAt(0).widget()
            if w:
                w.deleteLater()
        parts = []
        p = self.cwd
        while True:
            parts.append(p)
            if p == HOME or p == p.parent:
                break
            p = p.parent
        for i, part in enumerate(reversed(parts)):
            label = "Home" if part == HOME else ("/" if part == part.parent else part.name)
            if part == ops.TRASH_FILES:
                label = "Trash"
            b = QPushButton(label)
            b.setObjectName("Crumb")
            b.setFlat(True)
            b.clicked.connect(lambda _=False, part=part: self.navigate(part))
            if i:
                sep = QLabel("›")
                sep.setObjectName("Muted")
                self.crumb_lay.addWidget(sep)
            self.crumb_lay.addWidget(b)
        self.crumb_lay.addStretch(1)

    def edit_path(self):
        self.path_edit.setText(str(self.cwd))
        self.path_stack.setCurrentIndex(1)
        self.path_edit.setFocus()
        self.path_edit.selectAll()

    def _path_entered(self):
        p = Path(self.path_edit.text().strip()).expanduser()
        self.path_stack.setCurrentIndex(0)
        if p.is_dir():
            self.navigate(p)
        elif p.exists():
            self.navigate(p.parent)
            self.open_path(p)
        else:
            self.status.setText(f"No such folder: {tilde(p)}")

    # ================================================================== view options
    def set_view(self, i: int):
        self.views.setCurrentIndex(i)
        self.grid_btn.setChecked(i == 0)
        self.list_btn.setChecked(i == 1)
        self.view().setRootIndex(self.model.index(str(self.cwd)))

    def _apply_filter(self):
        f = QDir.Filter.AllEntries | QDir.Filter.NoDotAndDotDot | QDir.Filter.AllDirs
        if self.show_hidden:
            f |= QDir.Filter.Hidden
        self.model.setFilter(f)

    def toggle_hidden(self):
        self.show_hidden = not self.show_hidden
        self.hidden_btn.setChecked(self.show_hidden)
        self._apply_filter()

    def toggle_preview(self):
        self.preview.setVisible(not self.preview.isVisible())
        self.prev_btn.setChecked(self.preview.isVisible())

    def _filter_names(self, text: str):
        self.model.setNameFilters([f"*{text}*"] if text else [])

    # ================================================================== selection / preview / status
    def selected(self) -> list[Path]:
        sm = self.view().selectionModel()
        rows = sm.selectedRows(0) if isinstance(self.view(), QTreeView) else sm.selectedIndexes()
        return [Path(self.model.filePath(i)) for i in rows]

    def _connect_selection(self):
        for v in (self.grid, self.details):
            v.selectionModel().selectionChanged.connect(lambda *_: (self._update_preview(), self._update_status()))

    def showEvent(self, e):
        super().showEvent(e)
        if not getattr(self, "_sel_hooked", False):
            self._sel_hooked = True
            self._connect_selection()
        QTimer.singleShot(0, self._update_preview)      # the panel was hidden until now
        self._update_title()                            # the first folder opened before we had a window

    def _update_preview(self):
        if not self.preview.isVisible():
            return
        sel = self.selected()
        p = sel[0] if len(sel) == 1 else self.cwd
        self.pv_image.clear()
        self.pv_text.clear()
        self.pv_text.hide()
        self.pv_open.setVisible(len(sel) == 1)
        try:
            st = p.stat()
        except OSError:
            return
        self.pv_name.setText(p.name or str(p))
        lines = []
        if p.is_dir():
            try:
                n = sum(1 for _ in p.iterdir())
                lines.append(f"Folder · {n} item{'s' if n != 1 else ''}")
            except OSError:                               # e.g. a folder you can't read
                lines.append("Folder · can't read its contents")
            self.pv_image.setPixmap(glyph("folder", 96).pixmap(96, 96, QIcon.Mode.Active))
            sig = self._sig
            THUMBS.start(Job(lambda p=p: ops.folder_size(p), lambda r, p=p: sig.sized.emit(str(p), *r)))
        else:
            lines.append(f"{human(st.st_size)} · {self.model.type(self.model.index(str(p)))}")
            ext = p.suffix.lower()
            if ext in IMAGE_EXT:
                reader = QImageReader(str(p))
                reader.setAutoTransform(True)
                if reader.size().isValid():
                    lines.append(f"{reader.size().width()} × {reader.size().height()}")
                    reader.setScaledSize(reader.size().scaled(QSize(240, 240), Qt.AspectRatioMode.KeepAspectRatio))
                img = reader.read()
                if not img.isNull():
                    self.pv_image.setPixmap(QPixmap.fromImage(img))
            elif ext in TEXT_EXT and st.st_size < 2_000_000:
                try:
                    head = p.read_text(errors="replace")[:1500]
                except OSError:
                    head = ""
                self.pv_text.setText(head)
                self.pv_text.show()
                self.pv_image.setPixmap(self.model.fileIcon(self.model.index(str(p))).pixmap(56, 56))
            else:
                self.pv_image.setPixmap(self.model.fileIcon(self.model.index(str(p))).pixmap(96, 96))
        if ops.in_trash(p) and p != ops.TRASH_FILES:
            orig = ops.original_location(p)
            if orig:
                lines.append(f"Was in {tilde(Path(orig).parent)}")
        lines.append(f"Modified {datetime.fromtimestamp(st.st_mtime).strftime('%b %-d %Y, %-I:%M %p')}")
        lines.append(tilde(p))
        self._pv_lines = lines
        self.pv_info.setText("\n".join(lines))
        self._pv_path = str(p)

    def _folder_sized(self, path: str, size: int, files: int):
        """Folder sizes are counted off the UI thread; fill them into the preview when ready."""
        if getattr(self, "_pv_path", None) == path and self._pv_lines:
            lines = list(self._pv_lines)
            lines[0] += f" · {human(size)}"
            self.pv_info.setText("\n".join(lines))

    def _update_status(self):
        root = self.view().rootIndex()
        n = self.model.rowCount(root)
        sel = self.selected()
        free = QStorageInfo(str(self.cwd)).bytesAvailable()
        text = f"{n} item{'s' if n != 1 else ''}"
        if sel:
            size = 0
            for p in sel:
                try:
                    size += p.stat().st_size if p.is_file() else 0
                except OSError:                           # deleted since it was selected
                    pass
            text += f"   ·   {len(sel)} selected" + (f" ({human(size)})" if size else "")
        text += f"   ·   {human(free)} free"
        self.status.setText(text)

    # ================================================================== actions
    def open_index(self, index: QModelIndex):
        self.open_path(Path(self.model.filePath(index)))

    def open_path(self, p: Path):
        if p.is_dir():
            self.navigate(p)
        else:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(p)))

    def new_folder(self):
        try:
            made = ops.new_folder(self.cwd)
        except OSError as e:
            self.status.setText(f"Couldn't create a folder: {e.strerror or e}")
            return
        QTimer.singleShot(150, lambda: self._edit_new(made))

    def _edit_new(self, made: Path):
        idx = self.model.index(str(made))
        if idx.isValid():
            self.view().setCurrentIndex(idx)
            self.view().edit(idx)

    def rename(self):
        sel = self.selected()
        if len(sel) == 1:
            self.view().edit(self.model.index(str(sel[0])))
        elif len(sel) > 1:
            self.status.setText("Pick a single item to rename.")

    def copy(self, cut=False):
        sel = self.selected()
        if not sel:
            return
        data = QMimeData()
        data.setUrls([QUrl.fromLocalFile(str(p)) for p in sel])
        data.setData("application/x-kde-cutselection", b"1" if cut else b"0")   # understood by Dolphin too
        QGuiApplication.clipboard().setMimeData(data)
        self.status.setText(f"{'Cut' if cut else 'Copied'} {len(sel)} item{'s' if len(sel) != 1 else ''}")

    def paste(self):
        data = QGuiApplication.clipboard().mimeData()
        if not data or not data.hasUrls():
            return
        if ops.in_trash(self.cwd):
            self.status.setText("Can't paste into the Trash. Use Move to Trash instead.")
            return
        sources = [Path(u.toLocalFile()) for u in data.urls() if u.isLocalFile()]
        move = bytes(data.data("application/x-kde-cutselection")) == b"1"
        dest, sig = self.cwd, self._sig
        self.status.setText(f"{'Moving' if move else 'Copying'} {len(sources)} item(s)…")
        THUMBS.start(Job(lambda: ops.transfer(sources, dest, move),
                          lambda r: sig.transferred.emit(r[0], r[1], "moved" if move else "copied")))
        if move:
            QGuiApplication.clipboard().clear()

    def _transfer_done(self, done: int, errors: list, verb: str):
        msg = f"{verb.capitalize()} {done} item{'s' if done != 1 else ''}."
        if errors:
            msg += "  Problems: " + "; ".join(errors[:3])
        self.status.setText(msg)

    def trash_selected(self):
        sel = self.selected()
        if not sel:
            return
        if ops.in_trash(self.cwd):
            self.status.setText("These are already in the Trash. Use Restore, or Empty Trash.")
            return
        errors = ops.trash(sel)
        self.status.setText(f"Moved {len(sel) - len(errors)} item(s) to the Trash."
                            + (f"  Problems: {'; '.join(errors[:2])}" if errors else ""))

    def restore_selected(self):
        sel = self.selected()
        if not sel:
            return
        errors = ops.restore(sel)
        self.status.setText(f"Restored {len(sel) - len(errors)} item(s)."
                            + (f"  Problems: {'; '.join(errors[:2])}" if errors else ""))

    def empty_trash(self):
        n = len(list(ops.TRASH_FILES.iterdir())) if ops.TRASH_FILES.exists() else 0
        if not n:
            self.status.setText("The Trash is already empty.")
            return
        if QMessageBox.warning(self, "Empty Trash?",
                               f"Permanently delete the {n} item{'s' if n != 1 else ''} in the Trash?\n\n"
                               "This can't be undone.",
                               QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Yes,
                               QMessageBox.StandardButton.Cancel) != QMessageBox.StandardButton.Yes:
            return
        err = ops.empty_trash()
        self.status.setText(err or "Trash emptied.")

    def terminal_here(self):
        subprocess.Popen(["konsole", "--workdir", str(self.cwd)], start_new_session=True)

    def copy_path(self):
        sel = self.selected() or [self.cwd]
        QGuiApplication.clipboard().setText("\n".join(str(p) for p in sel))
        self.status.setText("Path copied.")

    def _menu(self, view, pos):
        idx = view.indexAt(pos)
        if idx.isValid() and not view.selectionModel().isSelected(idx):
            view.selectionModel().select(idx, QItemSelectionModel.SelectionFlag.ClearAndSelect
                                         | QItemSelectionModel.SelectionFlag.Rows)
        sel = self.selected() if idx.isValid() else []
        m = QMenu(self)
        trash_mode = ops.in_trash(self.cwd)
        if sel:
            m.addAction("Open", lambda: [self.open_path(p) for p in sel])
            if len(sel) == 1 and sel[0].is_file():
                self._open_with_menu(m.addMenu("Open with"), sel[0])
            m.addSeparator()
            if trash_mode:
                m.addAction("Restore", self.restore_selected)
            else:
                m.addAction("Cut\tCtrl+X", lambda: self.copy(cut=True))
                m.addAction("Copy\tCtrl+C", self.copy)
                if len(sel) == 1:
                    m.addAction("Rename\tF2", self.rename)
                m.addAction("Copy path", self.copy_path)
                m.addSeparator()
                m.addAction(glyph("trash", 16), "Move to Trash\tDel", self.trash_selected)
        else:
            m.addAction(glyph("newfolder", 16), "New folder\tCtrl+Shift+N", self.new_folder)
            paste = m.addAction("Paste\tCtrl+V", self.paste)
            data = QGuiApplication.clipboard().mimeData()
            paste.setEnabled(bool(data and data.hasUrls()) and not trash_mode)
            m.addSeparator()
            m.addAction(glyph("terminal", 16), "Open terminal here\tF4", self.terminal_here)
            m.addAction("Copy path", self.copy_path)
            hidden = m.addAction("Show hidden files\tCtrl+H", self.toggle_hidden)
            hidden.setCheckable(True)
            hidden.setChecked(self.show_hidden)
            if trash_mode:
                m.addSeparator()
                m.addAction("Empty Trash…", self.empty_trash)
        m.addSeparator()
        m.addAction("Properties\tAlt+Return", self.properties)
        target = sel[0] if len(sel) == 1 else self.cwd
        m.addAction("Show in Dolphin", lambda: subprocess.Popen(["dolphin", "--select", str(target)],
                                                                start_new_session=True))
        m.exec(view.viewport().mapToGlobal(pos))

    def _open_with_menu(self, menu: QMenu, p: Path):
        """Apps the system registers for this file type (gio mime), launched with gio."""
        mime = QMimeDatabase().mimeTypeForFile(str(p)).name()
        out = subprocess.run(["gio", "mime", mime], capture_output=True, text=True).stdout
        apps = []
        for line in out.splitlines():
            line = line.strip()
            if line.endswith(".desktop") and line not in apps and ":" not in line:
                apps.append(line)
        for desktop_id in apps[:12]:
            info = next((Path(d) / desktop_id for d in ("/usr/share/applications",
                                                        str(HOME / ".local/share/applications"),
                                                        "/var/lib/flatpak/exports/share/applications",
                                                        str(HOME / ".local/share/flatpak/exports/share/applications"))
                         if (Path(d) / desktop_id).is_file()), None)
            if not info:
                continue
            name = next((l[5:] for l in info.read_text(errors="ignore").splitlines() if l.startswith("Name=")),
                        desktop_id)
            menu.addAction(name, lambda info=info: subprocess.Popen(["gio", "launch", str(info), str(p)],
                                                                    start_new_session=True))
        if not apps:
            menu.addAction("No apps registered for this type").setEnabled(False)

    def properties(self):
        target = (self.selected() or [self.cwd])[0]
        subprocess.Popen(["kioclient", "openProperties", QUrl.fromLocalFile(str(target)).toString()],
                         start_new_session=True)

    def _shortcuts(self):
        def sc(keys, fn):
            s = QShortcut(QKeySequence(keys), self)
            s.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            s.activated.connect(fn)

        sc("Alt+Left", self.back)
        sc("Alt+Right", self.forward)
        sc("Alt+Up", self.up)
        sc("Backspace", lambda: None if self.focusWidget() in (self.search, self.path_edit) else self.back())
        sc("F2", self.rename)
        sc("Delete", self.trash_selected)
        sc("Ctrl+C", lambda: None if self.focusWidget() in (self.search, self.path_edit) else self.copy())
        sc("Ctrl+X", lambda: None if self.focusWidget() in (self.search, self.path_edit) else self.copy(cut=True))
        sc("Ctrl+V", lambda: None if self.focusWidget() in (self.search, self.path_edit) else self.paste())
        sc("Ctrl+A", lambda: self.view().selectAll())
        sc("Ctrl+H", self.toggle_hidden)
        sc("Ctrl+L", self.edit_path)
        sc("Ctrl+F", lambda: (self.search.setFocus(), self.search.selectAll()))
        sc("Ctrl+Shift+N", self.new_folder)
        sc("F4", self.terminal_here)
        sc("F5", lambda: (self._fill_drives(), self.navigate(self.cwd, record=False)))
        sc("F11", self.toggle_preview)
        sc("Alt+Return", self.properties)
        sc("Escape", lambda: (self.path_stack.setCurrentIndex(0), self.view().clearSelection()))
