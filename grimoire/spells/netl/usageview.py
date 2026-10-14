"""NetL's Usage history panel: bytes per day or per month as black & white bars and a table, per interface or all
of them, the apps NetL measured in the picked day or month, and the switch for background recording (the timer
in usage.py).
"""
import time

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QHeaderView, QPushButton, QVBoxLayout, QWidget

from grimoire.fsutil import human
from grimoire.jobs import POOL, Job
from grimoire.spells.netl import usage
from grimoire.spells.systeml.alertview import _row
from grimoire.spells.systeml.graph import BG, DIM, EDGE, GRID, INK, SOFT, _font
from grimoire.spells.systeml.page import NumItem, _label, _tree
from grimoire.widgets import Switch

SHOWN = {"days": 31, "months": 12}


class UsageBars(QWidget):
    """Download as a solid white bar, upload as a gray one beside it, one pair per day or month."""

    def __init__(self):
        super().__init__()
        self.rows: list[tuple[str, int, int]] = []
        self.setMinimumHeight(170)

    def set_rows(self, rows):
        self.rows = rows
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(EDGE)
        p.setBrush(BG)
        p.drawRoundedRect(r, 10, 10)
        area = r.adjusted(16, 30, -16, -26)
        p.setFont(_font(11))
        p.setPen(DIM)
        p.drawText(r.adjusted(16, 10, -16, 0), Qt.AlignmentFlag.AlignLeft, "↓ DOWNLOAD   ↑ UPLOAD")
        if not self.rows:
            p.setPen(SOFT)
            p.drawText(area, Qt.AlignmentFlag.AlignCenter, "Nothing recorded yet")
            p.end()
            return
        top = max(max(max(rx, tx) for _, rx, tx in self.rows), 1)
        p.drawText(r.adjusted(16, 10, -16, 0), Qt.AlignmentFlag.AlignRight, f"max {human(top)}")
        p.setPen(GRID)
        for i in range(4):
            y = area.top() + area.height() * i / 3
            p.drawLine(int(area.left()), int(y), int(area.right()), int(y))
        slot = area.width() / len(self.rows)
        bw = max(1.5, min(14.0, slot * 0.36))
        p.setPen(Qt.PenStyle.NoPen)
        every = max(1, len(self.rows) // 8)
        for i, (label, rx, tx) in enumerate(self.rows):
            x = area.left() + slot * i + slot / 2
            for j, (v, color) in enumerate(((rx, INK), (tx, SOFT))):
                h = area.height() * v / top
                p.setBrush(color)
                p.drawRoundedRect(QRectF(x - bw - 1 + j * (bw + 2), area.bottom() - h, bw, h), 2, 2)
            if i % every == 0 or i == len(self.rows) - 1:
                p.setPen(DIM)
                p.setFont(_font(10, mono=True))
                p.drawText(QRectF(x - 30, area.bottom() + 6, 60, 14), Qt.AlignmentFlag.AlignHCenter, label)
                p.setPen(Qt.PenStyle.NoPen)
        p.end()


class UsagePanel(QWidget):
    def __init__(self, page):
        super().__init__()
        self.page = page
        self.data = usage.load()
        self.period = "days"
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)
        self.timer_sw = Switch()
        self.timer_sub = _label("", "Muted", wrap=True)
        self.timer_sw.toggled.connect(self._toggle)
        lay.addWidget(_row("Record in the background", self.timer_sub, self.timer_sw))

        bar = QHBoxLayout()
        bar.setSpacing(0)
        self.segs = []
        for i, (name, key) in enumerate((("Days", "days"), ("Months", "months"))):
            b = QPushButton(name)
            b.setObjectName("Segment")
            b.setCheckable(True)
            b.setProperty("pos", "first" if i == 0 else "last")
            b.clicked.connect(lambda _=False, k=key: self.set_period(k))
            bar.addWidget(b)
            self.segs.append((b, key))
        bar.addSpacing(12)
        self.iface = QComboBox()
        self.iface.setMinimumWidth(200)
        self.iface.currentIndexChanged.connect(lambda _: self.fill())
        bar.addWidget(self.iface)
        bar.addStretch(1)
        self.sum = _label("", "Muted")
        bar.addWidget(self.sum)
        lay.addLayout(bar)

        self.bars = UsageBars()
        lay.addWidget(self.bars)
        tables = QHBoxLayout()
        tables.setSpacing(12)
        self.table = _tree(["Day", "Download", "Upload", "Total"])
        self.apps = _tree(["App (measured while NetL was open)", "Download", "Upload"])
        for t in (self.table, self.apps):
            h = t.header()
            h.setStretchLastSection(False)
            h.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
            for c in range(1, t.columnCount()):
                h.resizeSection(c, 100)
        self.table.itemSelectionChanged.connect(self._fill_apps)
        tables.addWidget(self.table, 1)
        tables.addWidget(self.apps, 1)
        lay.addLayout(tables, 1)
        page.sig.timer.connect(self._show_timer)
        self.set_period("days")

    def load(self):
        self.page.load_usage()
        POOL.start(Job(usage.enabled, self.page.sig.timer.emit))

    def _show_timer(self, on: bool):
        self.timer_sw.blockSignals(True)
        self.timer_sw.setChecked(on)
        self.timer_sw.blockSignals(False)
        last = self.data.get("t")
        when = time.strftime("%b %d %H:%M", time.localtime(last)) if last else "never"
        self.timer_sub.setText(("A user timer adds up every interface's counters every 5 minutes, even while NetL "
                                "is closed. " if on else "Off: usage only adds up while NetL is open (once a "
                                "minute). Turn on to count everything, every 5 minutes, with a cheap user timer. ")
                               + f"Last reading: {when}.")

    def _toggle(self, on: bool):
        self.page.act("Background recording", lambda: usage.set_enabled(on) or ("on" if on else "off"),
                      then=self.load)

    def set_data(self, data: dict):
        self.data = data
        names = ["All interfaces"] + usage.interfaces(data)
        if names != [self.iface.itemText(i) for i in range(self.iface.count())]:
            cur = self.iface.currentText()
            self.iface.blockSignals(True)
            self.iface.clear()
            self.iface.addItems(names)
            if cur in names:
                self.iface.setCurrentText(cur)
            self.iface.blockSignals(False)
        self.fill()

    def set_period(self, key: str):
        self.period = key
        for b, k in self.segs:
            b.setChecked(k == key)
        self.table.setHeaderLabels(["Day" if key == "days" else "Month", "Download", "Upload", "Total"])
        self.fill()

    def _ifaces(self) -> set[str] | None:
        i = self.iface.currentIndex()
        return usage.physical_set(self.data) if i <= 0 else {self.iface.currentText()}

    def fill(self):
        ifaces, period = self._ifaces(), self.period
        keys = sorted(self.data.get(period, {}))
        rows = [(k, *usage.totals(self.data, period, k, ifaces)) for k in keys]
        sel = self.table.currentItem().text(0) if self.table.currentItem() else None
        self.table.setSortingEnabled(False)
        self.table.clear()
        for k, rx, tx in rows:
            it = NumItem([k, human(rx), human(tx), human(rx + tx)])
            for c, v in enumerate([k, rx, tx, rx + tx]):
                it.setData(c, Qt.ItemDataRole.UserRole, v)
                if c:
                    it.setTextAlignment(c, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.table.addTopLevelItem(it)
        self.table.setSortingEnabled(True)
        self.table.sortItems(0, Qt.SortOrder.DescendingOrder)
        hit = self.table.findItems(sel, Qt.MatchFlag.MatchExactly, 0) if sel else []
        if hit:
            self.table.setCurrentItem(hit[0])
        elif self.table.topLevelItemCount():
            self.table.setCurrentItem(self.table.topLevelItem(0))
        recent = rows[-SHOWN[period]:]
        fmt = (lambda k: k[8:]) if period == "days" else (lambda k: time.strftime("%b", time.strptime(k, "%Y-%m")))
        self.bars.set_rows([(fmt(k), rx, tx) for k, rx, tx in recent])
        rx, tx = sum(r[1] for r in recent), sum(r[2] for r in recent)
        span = f"last {len(recent)} day(s)" if period == "days" else f"last {len(recent)} month(s)"
        self.sum.setText(f"{span}: ↓ {human(rx)}  ↑ {human(tx)}" if recent else "")
        self._fill_apps()

    def _fill_apps(self):
        it = self.table.currentItem()
        self.apps.setSortingEnabled(False)
        self.apps.clear()
        bucket = "app_days" if self.period == "days" else "app_months"
        for app, (rx, tx) in (self.data.get(bucket, {}).get(it.text(0), {}) if it else {}).items():
            row = NumItem([app, human(rx), human(tx)])
            for c, v in enumerate([app.lower(), rx, tx]):
                row.setData(c, Qt.ItemDataRole.UserRole, v)
                if c:
                    row.setTextAlignment(c, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.apps.addTopLevelItem(row)
        self.apps.setSortingEnabled(True)
        self.apps.sortItems(1, Qt.SortOrder.DescendingOrder)
