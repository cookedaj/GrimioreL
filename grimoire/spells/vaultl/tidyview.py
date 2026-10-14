# SPDX-License-Identifier: GPL-3.0-or-later
"""VaultL's tidy panels (TidyL before the merge): sorting rules, activity log with undo, big files and
duplicates. The sidebar's Tidy section picks the panel; the header carries Tidy now, Undo and the auto-tidy switch.
Tidy now always shows its preview first: nothing moves until the user has seen (and can untick) every file."""
import copy
import subprocess
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QFileSystemWatcher, QObject, Qt, QTimer, Signal
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QDialog, QFileDialog, QHBoxLayout, QHeaderView, QLabel,
                               QListWidget, QListWidgetItem, QMessageBox, QPushButton, QSpinBox, QStackedWidget,
                               QTableWidget, QTableWidgetItem, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from grimoire.fsutil import human, tilde
from grimoire.jobs import POOL, Job
from grimoire.paths import HOME
from grimoire.spells.vaultl import cli, tidy

# (sidebar label, glyph, panel title, what the panel is for)
PANELS = [("Rules", "tidy", "Auto-sort rules", "Where each kind of download goes, and when stale ones go to the Trash."),
          ("Activity", "clock", "Activity", "Everything VaultL sorted or trashed. Undo puts the last tidy back."),
          ("Big files", "bigfile", "Big files", "The largest files in your home folder."),
          ("Duplicates", "copies", "Duplicates", "Identical copies taking up space twice.")]


class _Signals(QObject):
    done = Signal(str, object)        # kind, result


def _rules(s: tidy.Settings) -> list[dict]:
    return [asdict(r) for r in s.rules]


class PreviewDialog(QDialog):
    """Tidy now's dry run: every planned move and cleanup, each with a tick box (untick to leave it alone this
    time) and an "Always skip" box (remember it in settings so tidy never touches that file)."""
    COLS = ["File", "Goes to", "Rule", "Always skip"]

    def __init__(self, p: tidy.Preview, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Tidy preview")
        self.resize(940, 560)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 18, 22, 16)
        lay.setSpacing(10)
        title = QLabel("Tidy preview")
        title.setObjectName("Title")
        lay.addWidget(title)
        sub = QLabel("Nothing has moved yet. Untick anything you want left alone this time.")
        sub.setObjectName("Subtitle")
        lay.addWidget(sub)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(self.COLS)
        self.tree.setRootIsDecorated(False)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        hh = self.tree.header()
        hh.setStretchLastSection(False)
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for c, width in ((1, 300), (2, 110), (3, 100)):
            self.tree.setColumnWidth(c, width)
        self.moves = self._group(f"Would move {cli.plural(len(p.moves), 'file')}",
                                 [(f, (tilde(dest.parent), rule)) for f, dest, rule in p.moves], p.moves)
        self.cleanups = self._group(f"Would send {cli.plural(len(p.cleanups), 'file')} to the Trash",
                                    [(f, (f"Trash · {reason}", rule)) for f, rule, reason in p.cleanups], p.cleanups)
        self._syncing = False
        self.tree.itemChanged.connect(self._changed)
        lay.addWidget(self.tree, 1)

        foot = QHBoxLayout()
        self.count = QLabel()
        self.count.setObjectName("Muted")
        foot.addWidget(self.count, 1)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        self.run_btn = QPushButton("Run")
        self.run_btn.setObjectName("Primary")
        self.run_btn.setMinimumWidth(110)
        self.run_btn.clicked.connect(self.accept)
        foot.addWidget(cancel)
        foot.addWidget(self.run_btn)
        lay.addLayout(foot)
        self._changed()

    def _group(self, label, rows, entries) -> QTreeWidgetItem | None:
        if not rows:
            return None
        top = QTreeWidgetItem([label, "", "", ""])
        top.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable)   # ticks the whole group
        top.setCheckState(0, Qt.CheckState.Checked)
        f = top.font(0)
        f.setBold(True)
        top.setFont(0, f)
        self.tree.addTopLevelItem(top)
        for (path, (where, rule)), entry in zip(rows, entries):
            item = QTreeWidgetItem([path.name, where, rule, ""])
            item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(0, Qt.CheckState.Checked)
            item.setCheckState(3, Qt.CheckState.Unchecked)
            item.setToolTip(0, tilde(path))
            item.setData(0, Qt.ItemDataRole.UserRole, entry)
            for c in (1, 2):
                item.setForeground(c, Qt.GlobalColor.gray)
            top.addChild(item)
        top.setExpanded(True)
        return top

    def _rows(self, top):
        return [top.child(i) for i in range(top.childCount())] if top else []

    def _changed(self, item=None, col=0):
        if item is not None and not self._syncing:
            self._syncing = True                              # the ticks below fire itemChanged again
            on = item.checkState(col) == Qt.CheckState.Checked
            if item.parent() is None:                        # a group row: tick/untick all of it
                for row in self._rows(item):
                    row.setCheckState(0, item.checkState(0))
                    if on:
                        row.setCheckState(3, Qt.CheckState.Unchecked)
            elif col == 3 and on:
                item.setCheckState(0, Qt.CheckState.Unchecked)   # always skip implies skip now
            elif col == 0 and on:
                item.setCheckState(3, Qt.CheckState.Unchecked)
            if item.parent() is not None:
                top = item.parent()
                states = {r.checkState(0) for r in self._rows(top)}
                top.setCheckState(0, states.pop() if len(states) == 1 else Qt.CheckState.PartiallyChecked)
            self._syncing = False
        ticked = self.chosen()[0]
        a, cl = ticked.moves, ticked.cleanups
        self.count.setText(f"{cli.plural(len(a), 'move')} and {cli.plural(len(cl), 'file')} to the Trash ticked. "
                           "Moves can be undone; trashed files can be restored from the Trash.")
        self.run_btn.setEnabled(bool(a or cl))

    def chosen(self) -> tuple[tidy.Preview, list[Path]]:
        """(the ticked part of the preview, files to always skip)."""
        ticked = lambda top: [i.data(0, Qt.ItemDataRole.UserRole) for i in self._rows(top)
                              if i.checkState(0) == Qt.CheckState.Checked]
        skip = [i.data(0, Qt.ItemDataRole.UserRole)[0] for top in (self.moves, self.cleanups)
                for i in self._rows(top) if i.checkState(3) == Qt.CheckState.Checked]
        return tidy.Preview(ticked(self.moves), ticked(self.cleanups)), skip


class TidyPanel(QWidget):
    """changed fires after anything that moves files, so the browser's Downloads bar can refresh.
    reveal(path) asks the browser to show a file (double-click in Big files).
    Settings are shared with other VaultL windows: every edit goes through tidy.edit() (reload, change one
    thing, save) and a watcher picks up edits made elsewhere, so no window writes back a stale copy."""
    changed = Signal()
    reveal = Signal(str)

    def __init__(self):
        super().__init__()
        self.settings = tidy.Settings.load()
        self._sig = _Signals()
        self._sig.done.connect(self._on_done)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 18, 22, 12)
        lay.setSpacing(12)

        head = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(2)
        self.title = QLabel()
        self.title.setObjectName("Title")
        self.subtitle = QLabel()
        self.subtitle.setObjectName("Subtitle")
        self.subtitle.setWordWrap(True)
        titles.addWidget(self.title)
        titles.addWidget(self.subtitle)
        head.addLayout(titles, 1)
        self.undo_btn = QPushButton("Undo last tidy")
        self.undo_btn.clicked.connect(self.undo)
        self.now_btn = QPushButton("Tidy now")
        self.now_btn.clicked.connect(self.tidy_now)
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
        self.next_line = QLabel()                     # live dry run, on the Rules and Activity panels
        self.next_line.setWordWrap(True)
        lay.addWidget(self.next_line)
        self._next_timer = QTimer(self, interval=30_000, timeout=self.refresh_next)

        self.views = QStackedWidget()
        self.views.addWidget(self._rules_view())
        self.views.addWidget(self._activity_view())
        self.views.addWidget(self._big_view())
        self.views.addWidget(self._dupes_view())
        lay.addWidget(self.views, 1)
        self.show_panel(0)
        self.refresh_auto()

        self._watcher = QFileSystemWatcher([str(tidy.SETTINGS.parent)], self)   # the save is an atomic rename,
        self._reload_timer = QTimer(self, singleShot=True, interval=150, timeout=self.reload)   # so watch the folder
        self._watcher.directoryChanged.connect(self._reload_timer.start)

    def reload(self):
        """Pick up settings another VaultL window (or the CLI) saved."""
        fresh = tidy.Settings.load()
        if asdict(fresh) != asdict(self.settings):
            old, self.settings = self.settings, fresh
            self._settings_changed(_rules(old) != _rules(fresh))

    def _settings_changed(self, rules_differ=True):
        if rules_differ:
            self._fill_rules()
        self._refresh_skipped()
        self.refresh_next()

    def _edit(self, change, rebuild=False) -> bool:
        """Save one change. The rule rows are rebuilt only when they no longer match what's shown (another
        window changed something too), so the control being used keeps its focus."""
        shown = copy.deepcopy(self.settings)
        change(shown)
        try:
            self.settings = tidy.edit(change)
        except (OSError, ValueError) as e:
            self.status.setText(f"Couldn't save the tidy settings: {e}")
            self.settings = tidy.Settings.load()
            self._settings_changed()
            return False
        self._settings_changed(rebuild or _rules(shown) != _rules(self.settings))
        return True

    # ------------------------------------------------------------------ header
    def show_panel(self, i):
        self.views.setCurrentIndex(i)
        _, _, title, sub = PANELS[i]
        self.title.setText(title)
        self.subtitle.setText(sub)
        if i == 1:
            self._refresh_activity()
        self.next_line.setVisible(i in (0, 1))
        self.refresh_next()

    def showEvent(self, e):
        super().showEvent(e)
        self._next_timer.start()
        self.refresh_next()

    def hideEvent(self, e):
        super().hideEvent(e)
        self._next_timer.stop()

    def refresh_next(self):
        """Re-run the dry run in the background for the "Next auto-tidy will…" line."""
        if self.views.currentIndex() in (0, 1) and self.isVisible():
            settings, sig = copy.deepcopy(self.settings), self._sig    # the worker never sees a half-edited rule
            POOL.start(Job(lambda: tidy.preview(settings), lambda result: sig.done.emit("next", result)))

    def _show_next(self, p: tidy.Preview):
        if p.error:
            self.next_line.setText(p.error)
            return
        on = self.auto_btn.text().endswith("ON")
        if not (p.moves or p.cleanups):
            self.next_line.setText("Next auto-tidy has nothing to do right now." if on
                                   else "Auto-tidy is paused. Nothing to tidy right now.")
            return
        what = f"move {cli.plural(len(p.moves), 'file')}"
        if p.cleanups:
            what += f" and send {cli.plural(len(p.cleanups), 'file')} to the Trash"
        lead = "Next auto-tidy will" if on else "Auto-tidy is paused; Tidy now would"
        self.next_line.setText(f"{lead} {what}. Tidy now shows the list first.")

    def watch_dir(self) -> Path:
        return tidy.expand(self.settings.watch)

    def summary(self) -> str:
        """One line on auto-tidy, for the header and the Downloads bar."""
        last = next((e for e in tidy.history(50) if e["action"] in ("move", "trash")), None)
        when = datetime.fromtimestamp(last["time"]).strftime("%b %-d, %-I:%M %p") if last else "never"
        on = cli.timer_active()
        return (f"Auto-tidy sorts {tilde(self.watch_dir())} every 10 minutes. " if on else "Auto-tidy is paused. ") \
            + f"Last change: {when}. Nothing is ever deleted: cleanup goes to the Trash and moves can be undone."

    def refresh_auto(self):
        on = cli.timer_active()
        self.auto_btn.setText("Auto-tidy: ON" if on else "Auto-tidy: OFF")
        self.status.setText(self.summary())
        self.refresh_next()

    def _toggle_auto(self):
        try:
            cli.set_auto(not cli.timer_active())
        except subprocess.CalledProcessError as e:
            QMessageBox.warning(self, "VaultL", f"Couldn't change the background timer: {e}")
        self.refresh_auto()
        self.changed.emit()

    def tidy_now(self) -> str:
        """Show the preview; run only what the user leaves ticked, and only on Run."""
        self.reload()
        p = tidy.preview(self.settings)
        if p.error or not (p.moves or p.cleanups):
            msg = p.error or "Nothing to tidy right now."
            self.status.setText(msg)
            self.refresh_next()
            return msg
        d = PreviewDialog(p, self)
        if d.exec() != QDialog.DialogCode.Accepted:
            self.status.setText("Tidy cancelled. Nothing moved.")
            return "Tidy cancelled. Nothing moved."
        approved, skip = d.chosen()
        return self._run(approved, skip)

    def _run(self, approved: tidy.Preview, skip) -> str:
        if skip:
            self._edit(lambda s: s.skip_always(skip))
        else:
            self.reload()                             # run with the ignore list as it is on disk now
        r = tidy.run(self.settings, approved)
        msg = f"Sorted {r['moved']} file(s), cleaned {r['cleaned']} stale file(s)."
        if r["errors"]:
            msg += "  Problems: " + "; ".join(r["errors"][:3])
        self.status.setText(msg)
        self._refresh_activity()
        self.refresh_next()
        self.changed.emit()
        return msg

    def undo(self) -> str:
        n = tidy.undo_last()
        msg = f"Moved {n} file(s) back." if n else "Nothing to undo."
        self.status.setText(msg)
        self._refresh_activity()
        self.refresh_next()
        self.changed.emit()
        return msg

    # ------------------------------------------------------------------ rules
    def _rules_view(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["On", "Type", "Extensions", "Goes to", "Trash after"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setShowGrid(False)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        for c, width in ((0, 50), (1, 120), (3, 280), (4, 120)):
            self.table.setColumnWidth(c, width)
        self._fill_rules()
        v.addWidget(self.table)
        note = QLabel("Only loose files directly in Downloads are sorted; folders, hidden files and downloads still "
                      "in progress are never touched. \"Trash after\" applies to files sitting in that rule's folder.")
        note.setObjectName("Muted")
        note.setWordWrap(True)
        v.addWidget(note)
        row = QHBoxLayout()
        self.skipped = QLabel()
        self.skipped.setObjectName("Muted")
        row.addWidget(self.skipped, 1)
        self.forget_btn = QPushButton("Stop skipping them")
        self.forget_btn.clicked.connect(self._forget_skipped)
        row.addWidget(self.forget_btn)
        v.addLayout(row)
        self._refresh_skipped()
        return w

    def _fill_rules(self):
        """(Re)build the rule rows from self.settings. Each control edits its rule by name."""
        self.table.setRowCount(len(self.settings.rules))
        for r, rule in enumerate(self.settings.rules):
            box = QCheckBox()
            box.setChecked(rule.enabled)
            box.toggled.connect(lambda on, name=rule.name: self._set(name, "enabled", on))
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
            dest.clicked.connect(lambda _=False, name=rule.name: self._pick_dest(name))
            self.table.setCellWidget(r, 3, dest)
            days = QSpinBox()
            days.setRange(0, 365)
            days.setSpecialValueText("never")
            days.setSuffix(" days")
            days.setValue(rule.clean_days)
            days.valueChanged.connect(lambda d, name=rule.name: self._set(name, "clean_days", d))
            self.table.setCellWidget(r, 4, days)
            self.table.setRowHeight(r, 44)

    def _refresh_skipped(self):
        n = len(self.settings.ignore)
        self.skipped.setText(f"{cli.plural(n, 'file')} you chose to always skip: "
                             + ", ".join(Path(p).name for p in self.settings.ignore[:4]) + ("…" if n > 4 else ""))
        self.skipped.setToolTip("\n".join(tilde(p) for p in self.settings.ignore))
        for w in (self.skipped, self.forget_btn):
            w.setVisible(bool(n))

    def _forget_skipped(self):
        self._edit(lambda s: setattr(s, "ignore", []))

    def _set(self, name, key, value, rebuild=False):
        def change(s):
            if rule := s.rule(name):
                setattr(rule, key, value)
        self._edit(change, rebuild)

    def _pick_dest(self, name):
        rule = self.settings.rule(name)
        if not rule:
            return
        start = str(tidy.expand(rule.dest)) if tidy.expand(rule.dest).exists() else str(HOME)
        d = QFileDialog.getExistingDirectory(self, f"Where should {name.lower()} go?", start)
        if d:
            self._set(name, "dest", tilde(d), rebuild=True)          # the button shows the new folder

    # ------------------------------------------------------------------ activity
    def _activity_view(self) -> QWidget:
        self.activity = QListWidget()
        self.activity.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        return self.activity

    def _refresh_activity(self):
        self.activity.clear()
        undone = tidy.undone_batches()
        for e in tidy.history(300):
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
            self.activity.addItem("Nothing yet. Files you download will show up here as VaultL sorts them.")

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
        self.big.cellDoubleClicked.connect(lambda r, _: self.reveal.emit(self.big.item(r, 1).data(Qt.ItemDataRole.UserRole)))
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
                                "You can restore them from the Trash in the sidebar.") != QMessageBox.StandardButton.Yes:
            return
        for r, p in sorted(zip(rows, paths), reverse=True):
            try:
                tidy.trash_by_hand(p, "Big files", "you chose it")
                self.big.removeRow(r)
            except OSError as e:
                QMessageBox.warning(self, "VaultL", str(e))

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
        failed = []
        for p in extras:
            try:
                tidy.trash_by_hand(Path(p), "Duplicates", "duplicate copy")
            except OSError as e:
                failed.append(f"{Path(p).name}: {e}")
        if failed:
            QMessageBox.warning(self, "VaultL", f"Couldn't trash {len(failed)} file(s):\n\n" + "\n".join(failed[:8]))
        self._scan("dupes")

    # ------------------------------------------------------------------ background scans
    def _scan(self, kind):
        note = self.big_note if kind == "big" else self.dupe_note
        note.setText("Scanning…")
        fn = tidy.biggest if kind == "big" else tidy.duplicates
        sig = self._sig
        POOL.start(Job(fn, lambda result: sig.done.emit(kind, result)))

    def _on_done(self, kind, result):
        if kind == "next":
            self._show_next(result)
        elif kind == "big":
            self.big.setRowCount(0)
            for n, p in result:
                r = self.big.rowCount()
                self.big.insertRow(r)
                self.big.setItem(r, 0, QTableWidgetItem(human(n)))
                item = QTableWidgetItem(tilde(p))
                item.setData(Qt.ItemDataRole.UserRole, str(p))
                self.big.setItem(r, 1, item)
            self.big_note.setText(f"{len(result)} files over 50 MB. Double-click one to show it in its folder.")
        else:
            self.dupes.clear()
            wasted = 0
            for group in result:
                try:
                    s = group[0].stat().st_size
                except OSError:                 # moved or deleted since the scan
                    continue
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
