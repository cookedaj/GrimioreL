"""MuraL → Looks tab: saved snapshots of the whole desktop look, restored in one click.
The work is in looks.py; this is the list on the left and the details + buttons on the right.
"""
from datetime import datetime

from PySide6.QtCore import QObject, QSize, Qt, Signal
from PySide6.QtGui import QIcon, QImage, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QFrame, QHBoxLayout, QInputDialog, QLabel, QListWidget,
                               QListWidgetItem, QMessageBox, QPushButton, QVBoxLayout, QWidget)

from grimoire.jobs import POOL, Job
from grimoire.spells.mural import looks
from grimoire.spells.mural.screens import THUMB, placeholder

ID_ROLE = Qt.ItemDataRole.UserRole


class _Signals(QObject):
    saved = Signal(object)        # the new look, or an error message
    progress = Signal(str)        # part being applied
    restored = Signal(object)     # [(key, ok, message)] or an error message


def when(iso: str) -> str:
    try:
        return datetime.fromisoformat(iso).strftime("%-d %b %Y, %H:%M")
    except ValueError:
        return ""


class LooksTab(QWidget):
    restored = Signal()           # the page rebuilds the other tabs so they show what's in use now

    def __init__(self):
        super().__init__()
        self.setObjectName("Page")
        self._sig = _Signals()
        self._sig.saved.connect(self._on_saved)
        self._sig.progress.connect(lambda key: self.status.setText(f"Applying {looks.LABELS[key].lower()}…"))
        self._sig.restored.connect(self._on_restored)

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(36, 8, 24, 24)
        lv.setSpacing(14)
        head = QHBoxLayout()
        sub = QLabel("Save everything MuraL has applied (wallpaper, taskbar, colors, icons, fonts…) as a look, "
                     "and put it all back in one click.")
        sub.setObjectName("Subtitle")
        sub.setWordWrap(True)
        head.addWidget(sub, 1)
        self.save_btn = QPushButton("Save current look")
        self.save_btn.clicked.connect(self._save)
        head.addWidget(self.save_btn)
        lv.addLayout(head)

        self.list = QListWidget()
        self.list.setViewMode(QListWidget.ViewMode.IconMode)
        self.list.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.list.setMovement(QListWidget.Movement.Static)
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.list.setIconSize(THUMB)
        self.list.setGridSize(QSize(THUMB.width() + 24, THUMB.height() + 58))
        self.list.setSpacing(8)
        self.list.currentItemChanged.connect(lambda *_: self._show_details())
        self.list.itemDoubleClicked.connect(lambda _: self._rename())
        lv.addWidget(self.list, 1)
        self.empty = QLabel("No looks saved yet. Set things up in the other tabs, then click “Save current look”.")
        self.empty.setObjectName("Muted")
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty.setWordWrap(True)
        lv.addWidget(self.empty)
        root.addWidget(left, 1)

        panel = QFrame()
        panel.setObjectName("Panel")
        panel.setFixedWidth(300)
        pl = QVBoxLayout(panel)
        pl.setContentsMargins(24, 24, 24, 24)
        pl.setSpacing(10)
        self.name = QLabel()
        self.name.setObjectName("Section")
        self.contents = QLabel()
        self.contents.setObjectName("Muted")
        self.contents.setWordWrap(True)
        pl.addWidget(self.name)
        pl.addWidget(self.contents)
        pl.addSpacing(6)
        self.root_boxes: dict[str, QCheckBox] = {}
        for key in sorted(looks.ROOT, key=looks.ORDER.index):
            box = QCheckBox(f"Also restore {looks.LABELS[key].lower()}\n(asks for your password)")
            self.root_boxes[key] = box
            pl.addWidget(box)
        pl.addStretch(1)
        self.status = QLabel()
        self.status.setObjectName("Muted")
        self.status.setWordWrap(True)
        pl.addWidget(self.status)
        row = QHBoxLayout()
        self.rename_btn = QPushButton("Rename")
        self.rename_btn.clicked.connect(self._rename)
        self.delete_btn = QPushButton("Delete")
        self.delete_btn.clicked.connect(self._delete)
        row.addWidget(self.rename_btn)
        row.addWidget(self.delete_btn)
        pl.addLayout(row)
        self.restore_btn = QPushButton("Restore look")
        self.restore_btn.setObjectName("Primary")
        self.restore_btn.setMinimumHeight(40)
        self.restore_btn.clicked.connect(self._restore)
        pl.addWidget(self.restore_btn)
        root.addWidget(panel)

        self.reload()

    # ---- list
    def reload(self, select: str | None = None):
        keep = select or self.current_id()
        self.list.blockSignals(True)
        self.list.clear()
        active = (looks.active() or {}).get("id")
        for look in looks.all_looks():
            img = QImage(str(looks.thumb_path(look["id"])))
            pm = placeholder() if img.isNull() else QPixmap.fromImage(
                img.scaled(THUMB, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                           Qt.TransformationMode.SmoothTransformation))
            icon = QIcon(pm)
            icon.addPixmap(pm, QIcon.Mode.Selected)          # no selection tint on the thumbnail
            in_use = "  ·  in use" if look["id"] == active else ""
            item = QListWidgetItem(icon, f"{look['name']}{in_use}\n{when(look.get('created', ''))}")
            item.setData(ID_ROLE, look["id"])
            item.setTextAlignment(Qt.AlignmentFlag.AlignHCenter)
            self.list.addItem(item)
            if look["id"] == keep:
                self.list.setCurrentItem(item)
        if self.list.currentRow() < 0 and self.list.count():
            self.list.setCurrentRow(0)
        self.list.blockSignals(False)
        self.empty.setVisible(self.list.count() == 0)
        self.list.setVisible(self.list.count() > 0)
        self._show_details()

    def current_id(self) -> str | None:
        item = self.list.currentItem()
        return item.data(ID_ROLE) if item else None

    def _show_details(self):
        look = looks.get(self.current_id()) if self.current_id() else None
        for w in (self.rename_btn, self.delete_btn, self.restore_btn):
            w.setEnabled(look is not None)
        if look is None:
            self.name.setText("NO LOOK SELECTED")
            self.contents.setText("")
            for box in self.root_boxes.values():
                box.setVisible(False)
            return
        self.name.setText(look["name"].upper())
        lines = []
        for key in looks.parts(look):
            if key == "desktop":
                n = len(look["desktop"]["items"])
                lines.append(f"Desktop · {n} wallpaper{'s' if n != 1 else ''}")
            else:
                lines.append(f"{looks.LABELS[key]} · {look['tabs'][key].get('label', '')}")
        self.contents.setText("\n".join(lines) or "Nothing was applied with MuraL when this was saved.")
        for key, box in self.root_boxes.items():
            box.setVisible(key in look.get("tabs", {}))

    # ---- actions
    def _busy(self, busy: bool, text: str = ""):
        for w in (self.save_btn, self.rename_btn, self.delete_btn, self.restore_btn):
            w.setEnabled(not busy)
        if not busy:
            self._show_details()                 # Rename/Delete/Restore only with a look selected
        if text:
            self.status.setText(text)

    def _save(self):
        name, ok = QInputDialog.getText(self, "Save current look", "Name", text=looks.default_name())
        if not ok:
            return
        sig = self._sig
        self._busy(True, "Saving…")

        def work():
            try:
                return looks.save_current(name)
            except Exception as e:
                return f"Couldn't save: {e}"

        POOL.start(Job(work, lambda r: sig.saved.emit(r)))

    def _on_saved(self, result):
        self._busy(False)
        if isinstance(result, str):
            self.status.setText(result)
            return
        n = len(looks.parts(result))
        self.status.setText(f"Saved ✓  {n} part{'s' if n != 1 else ''} of your look." if n else
                            "Saved, but nothing is applied with MuraL yet, so there's nothing to restore.")
        self.reload(result["id"])

    def _rename(self):
        look = looks.get(self.current_id() or "")
        if look is None:
            return
        name, ok = QInputDialog.getText(self, "Rename look", "Name", text=look["name"])
        if ok and name.strip():
            looks.rename(look["id"], name)
            self.reload()

    def _delete(self):
        look = looks.get(self.current_id() or "")
        if look is None:
            return
        if QMessageBox.question(self, "Delete look?", f"Forget the look “{look['name']}”?\n\nThis only removes the "
                                "saved snapshot; your wallpapers and themes stay.") != QMessageBox.StandardButton.Yes:
            return
        looks.delete(look["id"])
        self.status.setText(f"Deleted “{look['name']}”.")
        self.reload()

    def _restore(self):
        look_id = self.current_id()
        if not look_id:
            return
        include = {k for k, box in self.root_boxes.items() if box.isVisible() and box.isChecked()}
        sig = self._sig
        self._busy(True, "Restoring…" + ("  Enter your password when asked." if include else ""))

        def work():
            try:
                return looks.restore(look_id, include, progress=sig.progress.emit)
            except Exception as e:
                return f"Couldn't restore: {e}"

        POOL.start(Job(work, lambda r: sig.restored.emit(r)))

    def _on_restored(self, results):
        self._busy(False)
        if isinstance(results, str):
            self.status.setText(results)
            return
        failed = [r for r in results if not r[1]]
        lines = [("·  " if ok else "✗  ") + f"{looks.LABELS[key]}: {msg}" for key, ok, msg in results
                 if not ok or msg.startswith("Skipped")]
        head = "Look restored ✓" if not failed else f"Restored, but {len(failed)} part(s) didn't apply:"
        self.status.setText("\n".join([head, *lines]))
        self.reload()
        self.restored.emit()
