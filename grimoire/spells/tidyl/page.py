"""TidyL page: auto-tidy switch, sorting rules, activity log with undo, big files and duplicates."""
import subprocess
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QFileDialog, QHBoxLayout, QHeaderView, QLabel,
                               QListWidget, QListWidgetItem, QMessageBox, QPushButton, QSpinBox, QStackedWidget,
                               QTableWidget, QTableWidgetItem, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from grimoire.fsutil import human, tilde
from grimoire.jobs import POOL, Job
from grimoire.paths import HOME
from grimoire.spells.tidyl import cli, engine


class _Signals(QObject):
    done = Signal(str, object)        # kind, result


class TidyLPage(QWidget):
    def __init__(self):
        super().__init__()
        self.setObjectName("Page")
        self.settings = engine.Settings.load()
        self._sig = _Signals()
        self._sig.done.connect(self._on_done)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(40, 30, 40, 28)
        lay.setSpacing(14)

        head = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(2)
        t = QLabel("TidyL")
        t.setObjectName("Title")
        sub = QLabel(f"Keeps {tilde(engine.expand(self.settings.watch))} sorted and clears stale installers. "
                     "Nothing is ever deleted: cleanup goes to the Trash, and every move can be undone.")
        sub.setObjectName("Subtitle")
        sub.setWordWrap(True)
        titles.addWidget(t)
        titles.addWidget(sub)
        head.addLayout(titles, 1)
        self.undo_btn = QPushButton("Undo last tidy")
        self.undo_btn.clicked.connect(self._undo)
        self.now_btn = QPushButton("Tidy now")
        self.now_btn.clicked.connect(self._tidy_now)
        self.auto_btn = QPushButton()
        self.auto_btn.setObjectName("Primary")
        self.auto_btn.setMinimumSize(170, 40)
        self.auto_btn.clicked.connect(self._toggle_auto)
        for b in (self.undo_btn, self.now_btn, self.auto_btn):
            head.addWidget(b)
        lay.addLayout(head)

        self.status = QLabel()
        self.status.setObjectName("Muted")
        lay.addWidget(self.status)

        switch = QHBoxLayout()
        switch.setSpacing(0)
        self.views = QStackedWidget()
        self._switch = []
        for i, name in enumerate(("Rules", "Activity", "Big files", "Duplicates")):
            b = QPushButton(name)
            b.setObjectName("Segment")
            b.setProperty("pos", "first" if i == 0 else "last" if i == 3 else "mid")
            b.setCheckable(True)
            b.setChecked(i == 0)
            b.clicked.connect(lambda _=False, i=i: self._show(i))
            self._switch.append(b)
            switch.addWidget(b)
        switch.addStretch(1)
        lay.addLayout(switch)
        self.views.addWidget(self._rules_view())
        self.views.addWidget(self._activity_view())
        self.views.addWidget(self._big_view())
        self.views.addWidget(self._dupes_view())
        lay.addWidget(self.views, 1)
        self._refresh_auto()
        self._refresh_activity()

    # ------------------------------------------------------------------ header
    def _show(self, i):
        self.views.setCurrentIndex(i)
        for k, b in enumerate(self._switch):
            b.setChecked(k == i)
        if i == 1:
            self._refresh_activity()

    def _refresh_auto(self):
        on = cli.timer_active()
        self.auto_btn.setText("Auto-tidy: ON" if on else "Auto-tidy: OFF")
        last = next((e for e in engine.history(50) if e["action"] in ("move", "trash")), None)
        when = datetime.fromtimestamp(last["time"]).strftime("%b %-d, %-I:%M %p") if last else "never"
        self.status.setText(("Runs every 10 minutes in the background. " if on else "Paused. ")
                            + f"Last change: {when}.")

    def _toggle_auto(self):
        try:
            cli.set_auto(not cli.timer_active())
        except subprocess.CalledProcessError as e:
            QMessageBox.warning(self, "TidyL", f"Couldn't change the background timer: {e}")
        self._refresh_auto()

    def _tidy_now(self):
        r = engine.run(self.settings)
        msg = f"Sorted {r['moved']} file(s), cleaned {r['cleaned']} stale file(s)."
        if r["errors"]:
            msg += "  Problems: " + "; ".join(r["errors"][:3])
        self.status.setText(msg)
        self._refresh_activity()

    def _undo(self):
        n = engine.undo_last()
        self.status.setText(f"Moved {n} file(s) back." if n else "Nothing to undo.")
        self._refresh_activity()

    # ------------------------------------------------------------------ rules
    def _rules_view(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        self.table = QTableWidget(len(self.settings.rules), 5)
        self.table.setHorizontalHeaderLabels(["On", "Type", "Extensions", "Goes to", "Trash after"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setShowGrid(False)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        for c, width in ((0, 50), (1, 120), (3, 280), (4, 120)):
            self.table.setColumnWidth(c, width)
        for r, rule in enumerate(self.settings.rules):
            box = QCheckBox()
            box.setChecked(rule.enabled)
            box.toggled.connect(lambda on, rule=rule: self._set(rule, "enabled", on))
            cell = QWidget()
            cl = QHBoxLayout(cell)
            cl.setContentsMargins(14, 0, 0, 0)
            cl.addWidget(box)
            self.table.setCellWidget(r, 0, cell)
            self.table.setItem(r, 1, QTableWidgetItem(rule.name))
            ext = QTableWidgetItem("  ".join("." + e for e in rule.extensions))
            ext.setForeground(Qt.GlobalColor.gray)
            self.table.setItem(r, 2, ext)
            dest = QPushButton(rule.dest)
            dest.setObjectName("Link")
            dest.clicked.connect(lambda _=False, rule=rule, btn=dest: self._pick_dest(rule, btn))
            self.table.setCellWidget(r, 3, dest)
            days = QSpinBox()
            days.setRange(0, 365)
            days.setSpecialValueText("never")
            days.setSuffix(" days")
            days.setValue(rule.clean_days)
            days.valueChanged.connect(lambda d, rule=rule: self._set(rule, "clean_days", d))
            self.table.setCellWidget(r, 4, days)
            self.table.setRowHeight(r, 44)
        v.addWidget(self.table)
        note = QLabel("Only loose files directly in Downloads are sorted; folders, hidden files and downloads still "
                      "in progress are never touched. \"Trash after\" applies to files sitting in that rule's folder.")
        note.setObjectName("Muted")
        note.setWordWrap(True)
        v.addWidget(note)
        return w

    def _set(self, rule, key, value):
        setattr(rule, key, value)
        self.settings.save()

    def _pick_dest(self, rule, btn):
        start = str(engine.expand(rule.dest)) if engine.expand(rule.dest).exists() else str(HOME)
        d = QFileDialog.getExistingDirectory(self, f"Where should {rule.name.lower()} go?", start)
        if d:
            rule.dest = tilde(d)
            btn.setText(rule.dest)
            self.settings.save()

    # ------------------------------------------------------------------ activity
    def _activity_view(self) -> QWidget:
        self.activity = QListWidget()
        self.activity.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        return self.activity

    def _refresh_activity(self):
        self.activity.clear()
        undone = engine.undone_batches()
        for e in engine.history(300):
            when = datetime.fromtimestamp(e["time"]).strftime("%b %-d  %-I:%M %p")
            if e["action"] == "move":
                tail = "   (undone)" if e["batch"] in undone else ""
                text = f"{when}    {e['rule']:<12}  {Path(e['from']).name}  →  {tilde(Path(e['to']).parent)}{tail}"
            elif e["action"] == "trash":
                text = f"{when}    Trash         {Path(e['from']).name}  ({e['reason']})"
            else:
                text = f"{when}    Undo          moved {e['count']} file(s) back"
            self.activity.addItem(QListWidgetItem(text))
        if not self.activity.count():
            self.activity.addItem("Nothing yet. Files you download will show up here as TidyL sorts them.")

    # ------------------------------------------------------------------ big files
    def _big_view(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        row = QHBoxLayout()
        scan = QPushButton("Scan home folder")
        scan.clicked.connect(lambda: self._scan("big"))
        self.big_note = QLabel("Files over 50 MB anywhere in your home (system caches and app data skipped).")
        self.big_note.setObjectName("Muted")
        row.addWidget(scan)
        row.addWidget(self.big_note, 1)
        self.big_trash = QPushButton("Move selected to Trash")
        self.big_trash.clicked.connect(self._trash_big)
        row.addWidget(self.big_trash)
        v.addLayout(row)
        self.big = QTableWidget(0, 2)
        self.big.setHorizontalHeaderLabels(["Size", "File"])
        self.big.verticalHeader().setVisible(False)
        self.big.setShowGrid(False)
        self.big.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.big.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.big.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.big.setColumnWidth(0, 110)
        self.big.cellDoubleClicked.connect(lambda r, _: subprocess.Popen(
            ["dolphin", "--select", self.big.item(r, 1).data(Qt.ItemDataRole.UserRole)]))
        v.addWidget(self.big, 1)
        return w

    def _trash_big(self):
        rows = sorted({i.row() for i in self.big.selectedItems()})
        paths = [Path(self.big.item(r, 1).data(Qt.ItemDataRole.UserRole)) for r in rows]
        if not paths:
            return
        listing = "\n".join(tilde(p) for p in paths[:12]) + ("\n…" if len(paths) > 12 else "")
        if QMessageBox.question(self, "Move to Trash?",
                                f"Move {len(paths)} file(s) to the Trash?\n\n{listing}\n\n"
                                "You can restore them from the Trash in Dolphin.") != QMessageBox.StandardButton.Yes:
            return
        for r, p in sorted(zip(rows, paths), reverse=True):
            try:
                engine.trash_by_hand(p, "Big files", "you chose it")
                self.big.removeRow(r)
            except OSError as e:
                QMessageBox.warning(self, "TidyL", str(e))

    # ------------------------------------------------------------------ duplicates
    def _dupes_view(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        row = QHBoxLayout()
        scan = QPushButton("Find duplicates")
        scan.clicked.connect(lambda: self._scan("dupes"))
        self.dupe_note = QLabel("Identical files in Downloads, Documents, Pictures, Videos, Music and Desktop "
                                "(your Repo projects are left out).")
        self.dupe_note.setObjectName("Muted")
        row.addWidget(scan)
        row.addWidget(self.dupe_note, 1)
        clean = QPushButton("Trash extra copies")
        clean.clicked.connect(self._trash_dupes)
        row.addWidget(clean)
        v.addLayout(row)
        self.dupes = QTreeWidget()
        self.dupes.setHeaderLabels(["File", "Size"])
        self.dupes.setColumnWidth(0, 900)
        v.addWidget(self.dupes, 1)
        return w

    def _trash_dupes(self):
        extras = []
        for g in range(self.dupes.topLevelItemCount()):
            group = self.dupes.topLevelItem(g)
            extras += [group.child(i).data(0, Qt.ItemDataRole.UserRole) for i in range(1, group.childCount())]
        if not extras:
            return
        if QMessageBox.question(self, "Trash extra copies?",
                                f"Keep the first copy in each group and move the other {len(extras)} to the "
                                "Trash?") != QMessageBox.StandardButton.Yes:
            return
        for p in extras:
            try:
                engine.trash_by_hand(Path(p), "Duplicates", "duplicate copy")
            except OSError:
                pass
        self._scan("dupes")

    # ------------------------------------------------------------------ background scans
    def _scan(self, kind):
        note = self.big_note if kind == "big" else self.dupe_note
        note.setText("Scanning…")
        fn = engine.biggest if kind == "big" else engine.duplicates
        sig = self._sig
        POOL.start(Job(fn, lambda result: sig.done.emit(kind, result)))

    def _on_done(self, kind, result):
        if kind == "big":
            self.big.setRowCount(0)
            for n, p in result:
                r = self.big.rowCount()
                self.big.insertRow(r)
                self.big.setItem(r, 0, QTableWidgetItem(human(n)))
                item = QTableWidgetItem(tilde(p))
                item.setData(Qt.ItemDataRole.UserRole, str(p))
                self.big.setItem(r, 1, item)
            self.big_note.setText(f"{len(result)} files over 50 MB. Double-click to show one in Dolphin.")
        else:
            self.dupes.clear()
            wasted = 0
            for group in result:
                s = group[0].stat().st_size
                wasted += s * (len(group) - 1)
                top = QTreeWidgetItem([f"{group[0].name}  ×{len(group)}", human(s)])
                for i, p in enumerate(group):
                    child = QTreeWidgetItem([("keep    " if i == 0 else "extra   ") + tilde(p), ""])
                    child.setData(0, Qt.ItemDataRole.UserRole, str(p))
                    top.addChild(child)
                self.dupes.addTopLevelItem(top)
                top.setExpanded(True)
            self.dupe_note.setText(f"{len(result)} duplicate group(s), {human(wasted)} in extra copies."
                                   if result else "No duplicates found.")
