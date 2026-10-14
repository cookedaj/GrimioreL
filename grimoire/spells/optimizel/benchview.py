"""OptimizeL's Benchmark tab: run the quick tests, compare the latest run with a baseline, boot-time history."""
import subprocess
import time

from PySide6.QtCore import QObject, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (QAbstractItemView, QFrame, QGridLayout, QHBoxLayout, QHeaderView, QLabel, QPushButton,
                               QScrollArea, QSizePolicy, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from grimoire.jobs import POOL, Job
from grimoire.spells.optimizel import bench, tweaks


class _Signals(QObject):
    step = Signal(str)
    finished = Signal(object)
    loaded = Signal(object)


def _label(text="", name="", wrap=False) -> QLabel:
    lab = QLabel(text)
    if name:
        lab.setObjectName(name)
    lab.setWordWrap(wrap)
    return lab


def _fmt(v, unit: str) -> str:
    if v is None:
        return "–"
    if unit == "s":
        return f"{v:.2f} s"
    return f"{v:,.0f} {unit}" if v >= 1000 else f"{v:g} {unit}"


def _when(ts: float) -> str:
    return time.strftime("%b %d, %H:%M", time.localtime(ts))


class BootChart(QWidget):
    """Last boots as stacked bars (firmware / loader / kernel / services), lighter = later phase."""
    PHASES = (("boot_firmware", "#3a3a3a"), ("boot_loader", "#6a6a6a"), ("boot_kernel", "#a8a8a8"),
              ("boot_userspace", "#f2f2f2"))

    def __init__(self):
        super().__init__()
        self.boots: list[dict] = []
        self.setMinimumHeight(150)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_boots(self, boots):
        self.boots = boots[-14:]
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        if not self.boots:
            p.setPen(QColor("#6f6f6f"))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "No boots recorded yet")
            return
        top = max(b.get("boot_total", 0) for b in self.boots) or 1
        n = len(self.boots)
        gap = 8
        bw = min(46, (w - gap * (n - 1)) / n)
        base = h - 18
        for i, b in enumerate(self.boots):
            x = i * (bw + gap)
            y = base
            for key, color in self.PHASES:
                seg = (b.get(key) or 0) / top * (base - 16)
                p.fillRect(QRectF(x, y - seg, bw, seg), QColor(color))
                y -= seg
            p.setPen(QColor("#bdbdbd"))
            p.drawText(QRectF(x - 6, y - 16, bw + 12, 14), Qt.AlignmentFlag.AlignCenter, f"{b.get('boot_total', 0):.1f}")
            p.setPen(QColor("#6f6f6f"))
            p.drawText(QRectF(x - 6, base + 2, bw + 12, 14), Qt.AlignmentFlag.AlignCenter,
                       time.strftime("%m/%d", time.localtime(b.get("ts", 0))))


class BenchView(QWidget):
    def __init__(self):
        super().__init__()
        self.setObjectName("Page")
        self.running = False
        self.data = bench.load()
        self._sig = _Signals()
        self._sig.step.connect(self._on_step)
        self._sig.finished.connect(self._on_finished)
        self._sig.loaded.connect(self._on_loaded)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        inner = QWidget()
        inner.setObjectName("Page")
        col = QVBoxLayout(inner)
        col.setContentsMargins(0, 0, 14, 24)
        col.setSpacing(14)
        scroll.setWidget(inner)
        outer.addWidget(scroll)

        head = QHBoxLayout()
        txt = QVBoxLayout()
        txt.setSpacing(2)
        txt.addWidget(_label("Before and after", "SectionTitle"))
        txt.addWidget(_label("About 15 seconds of fixed tests, no password: CPU, system calls, memory, a 512 MB disk "
                             "test in ~/.cache, and how late the scheduler wakes a task while every core is busy (a "
                             "stand-in for frame pacing). Run it before you change switches, then again after "
                             "(after a restart for boot and restart-only tweaks). Close games and big downloads "
                             "first so runs compare fairly.", "Muted", wrap=True))
        head.addLayout(txt, 1)
        self.base_btn = QPushButton("Use latest as baseline")
        self.base_btn.clicked.connect(self._latest_as_baseline)
        self.run_btn = QPushButton("Run benchmark")
        self.run_btn.setObjectName("Primary")
        self.run_btn.setMinimumSize(170, 40)
        self.run_btn.clicked.connect(self.run)
        head.addWidget(self.base_btn, 0, Qt.AlignmentFlag.AlignTop)
        head.addWidget(self.run_btn, 0, Qt.AlignmentFlag.AlignTop)
        col.addLayout(head)
        self.status = _label("", "Muted")
        col.addWidget(self.status)

        self.table = QFrame()
        self.table.setObjectName("Row")
        self.grid = QGridLayout(self.table)
        self.grid.setContentsMargins(20, 14, 20, 14)
        self.grid.setHorizontalSpacing(24)
        self.grid.setVerticalSpacing(6)
        col.addWidget(self.table)

        col.addWidget(_label("Boot time, last boots", "SectionTitle"))
        legend = _label("Bars stack firmware (darkest), boot loader, kernel and services (white). Recorded once per "
                        "boot whenever OptimizeL opens.", "Muted", wrap=True)
        col.addWidget(legend)
        chart_box = QFrame()
        chart_box.setObjectName("Row")
        cl = QVBoxLayout(chart_box)
        cl.setContentsMargins(20, 16, 20, 12)
        self.chart = BootChart()
        cl.addWidget(self.chart)
        self.boot_hint = _label("", "Value", wrap=True)
        cl.addWidget(self.boot_hint)
        col.addWidget(chart_box)

        col.addWidget(_label("Runs", "SectionTitle"))
        self.runs = QTableWidget(0, 7)
        self.runs.setHorizontalHeaderLabels(["When", "Switches on", "All cores", "Syscall", "Disk read", "Wake 99%",
                                             "Boot"])
        self.runs.verticalHeader().hide()
        self.runs.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.runs.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.runs.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.runs.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.runs.setMinimumHeight(220)
        col.addWidget(self.runs)
        pick = QHBoxLayout()
        pick.addStretch(1)
        self.pick_btn = QPushButton("Use selected run as baseline")
        self.pick_btn.clicked.connect(self._selected_as_baseline)
        pick.addWidget(self.pick_btn)
        col.addLayout(pick)
        col.addStretch(1)
        self.refresh()

    # ------------------------------------------------------------------ data
    def reload(self):
        """Record this boot (systemd-analyze, off the UI thread) and redraw."""
        sig = self._sig
        POOL.start(Job(lambda: (bench.record_boot(), _blame()), sig.loaded.emit))

    def _on_loaded(self, result):
        self.data, self.blame = result
        self.refresh()

    def refresh(self):
        d = self.data
        runs = d["runs"]
        latest = runs[-1] if runs else None
        base = bench.baseline_run(d)
        while self.grid.count():
            self.grid.takeAt(0).widget().deleteLater()
        heads = ["", "Baseline" + (f"  ·  {_when(base['ts'])}" if base else ""),
                 "Latest" + (f"  ·  {_when(latest['ts'])}" if latest else ""), "Change"]
        for c, h in enumerate(heads):
            self.grid.addWidget(_label(h.upper(), "StatLabel"), 0, c)
        row = 1
        boots = d["boots"]
        for group in bench.GROUPS:
            self.grid.addWidget(_label(group, "RowTitle"), row, 0)
            row += 1
            for key, (label, unit, _, g) in bench.METRICS.items():
                if g != group:
                    continue
                if group == "Boot":       # boot: the baseline run's boot vs this boot
                    first = base["r"] if base and key in base["r"] else (boots[0] if boots else {})
                    old = first.get(key)
                    new = boots[-1].get(key) if boots else None
                else:
                    old = base["r"].get(key) if base else None
                    new = latest["r"].get(key) if latest else None
                ch = bench.change(key, old, new) if base is not latest or group == "Boot" else None
                self.grid.addWidget(_label(label, "Muted"), row, 0)
                self.grid.addWidget(_label(_fmt(old, unit), "Value"), row, 1)
                self.grid.addWidget(_label(_fmt(new, unit), "Value"), row, 2)
                self.grid.addWidget(_change_label(ch, bench.noise(key)), row, 3)
                row += 1
        self.grid.setColumnStretch(0, 2)
        for c in (1, 2, 3):
            self.grid.setColumnStretch(c, 1)
        if boots:
            self.grid.addWidget(_label("Boot compares the baseline run's boot with this boot; restart after "
                                       "changing boot tweaks to see their effect.", "Muted", wrap=True), row, 0, 1, 4)

        self.chart.set_boots(boots)
        hint = []
        if boots and (boots[-1].get("boot_firmware") or 0) >= 6:
            hint.append(f"Firmware takes {boots[-1]['boot_firmware']:.1f} s before Linux even starts: turning on "
                        "Fast Boot in your BIOS/UEFI setup is the biggest boot win left (no switch here can "
                        "change it).")
        if getattr(self, "blame", None):
            hint.append("Slowest units this boot: " + ", ".join(self.blame))
        self.boot_hint.setText("\n".join(hint))
        self.boot_hint.setVisible(bool(hint))

        self.runs.setRowCount(len(runs))
        for i, r in enumerate(reversed(runs)):
            res = r.get("r", {})
            mark = "  (baseline)" if base and r["ts"] == base["ts"] else ""
            vals = [_when(r["ts"]) + mark, str(len(r.get("on", []))),
                    _fmt(res.get("cpu_multi"), "MB/s"), _fmt(res.get("syscall"), "ns"),
                    _fmt(res.get("disk_read"), "MB/s"), _fmt(res.get("wake_p99"), "µs"),
                    _fmt(res.get("boot_total"), "s")]
            for c, v in enumerate(vals):
                item = QTableWidgetItem(v)
                item.setData(Qt.ItemDataRole.UserRole, r["ts"])
                if c == 1:
                    item.setToolTip(", ".join(tweaks.BY_ID[t].title for t in r.get("on", []) if t in tweaks.BY_ID))
                self.runs.setItem(i, c, item)
        self.base_btn.setEnabled(bool(latest) and not self.running and base is not latest)
        self.pick_btn.setEnabled(bool(runs) and not self.running)
        if not self.running:
            self.status.setText("No runs yet: run it once now to get a baseline." if not runs else
                                f"{len(runs)} run(s) stored. Baseline: {_when(base['ts'])}.")

    # ------------------------------------------------------------------ running
    def run(self):
        if self.running:
            return
        self.running = True
        self.run_btn.setEnabled(False)
        self.run_btn.setText("Running…")
        self.status.setText("Starting…")
        sig = self._sig
        POOL.start(Job(lambda: _run_safely(sig.step.emit), sig.finished.emit))

    def _on_step(self, step):
        self.status.setText(f"Testing {step.lower()}…  keep the PC idle for a few seconds.")

    def _on_finished(self, entry):
        self.running = False
        self.run_btn.setEnabled(True)
        self.run_btn.setText("Run benchmark")
        self.data = bench.load()
        self.refresh()
        if isinstance(entry, str):
            self.status.setText(f"The benchmark failed: {entry}")
        elif entry.get("errors"):
            self.status.setText("Done, but some tests failed: " + "; ".join(entry["errors"]))

    def _latest_as_baseline(self):
        if self.data["runs"]:
            self._set_baseline(self.data["runs"][-1]["ts"])

    def _selected_as_baseline(self):
        items = self.runs.selectedItems()
        if items:
            self._set_baseline(items[0].data(Qt.ItemDataRole.UserRole))

    def _set_baseline(self, ts):
        d = bench.load()
        d["baseline"] = ts
        try:
            bench.save(d)
        except OSError as e:
            self.status.setText(f"Couldn't save: {e}")
            return
        self.data = d
        self.refresh()


def _change_label(ch, noise: float) -> QLabel:
    if ch is None:
        return _label("–", "Value")
    if abs(ch) < noise:
        return _label(f"{ch:+.1f}%  same", "Value")     # within run-to-run noise
    lab = _label(f"{'▲' if ch > 0 else '▼'} {abs(ch):.1f}% {'better' if ch > 0 else 'worse'}", "Value")
    lab.setProperty("strong", ch > 0)
    return lab


def _run_safely(step):
    try:
        return bench.run(step)
    except Exception as e:
        return str(e)


def _blame() -> list[str]:
    try:
        out = subprocess.run(["systemd-analyze", "blame", "--no-pager"], capture_output=True, text=True,
                             timeout=10).stdout.splitlines()
    except (OSError, subprocess.TimeoutExpired):
        return []
    lines = [ln.split() for ln in out[:5] if ln.strip()]
    return [f"{p[-1].removesuffix('.service')} {' '.join(p[:-1])}" for p in lines if len(p) >= 2]
