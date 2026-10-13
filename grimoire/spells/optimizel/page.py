"""OptimizeL page: a scan of this PC as grouped on/off switches. Flipping switches only stages changes; the bar at
the bottom applies them in one go (one password prompt for all the system ones)."""
from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea, QSizePolicy, QVBoxLayout,
                               QWidget)

from grimoire.glyphs import glyph
from grimoire.jobs import POOL, Job
from grimoire.spells.optimizel import tweaks
from grimoire.widgets import Switch


class _Signals(QObject):
    scanned = Signal(object)
    applied = Signal(object)


def _label(text="", name="", wrap=False) -> QLabel:
    lab = QLabel(text)
    if name:
        lab.setObjectName(name)
    lab.setWordWrap(wrap)
    return lab


def _badge(text: str, solid=False) -> QLabel:
    return _label(text.upper(), "BadgeSolid" if solid else "Badge")


def _repolish(w: QWidget):
    w.style().unpolish(w)
    w.style().polish(w)


class Row(QFrame):
    """One tweak: title, badges, why, the live value, and its switch."""
    flipped = Signal(str, bool)

    def __init__(self, t: tweaks.Tweak):
        super().__init__()
        self.t = t
        self.state = "off"
        self.setObjectName("Row")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(20, 16, 18, 16)
        lay.setSpacing(18)
        text = QVBoxLayout()
        text.setSpacing(5)
        top = QHBoxLayout()
        top.setSpacing(8)
        self.title = _label(t.title, "RowTitle")
        top.addWidget(self.title)
        holder = QWidget()                 # in a narrow window badges get clipped, never the switch
        holder.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.badges = QHBoxLayout(holder)
        self.badges.setContentsMargins(0, 0, 0, 0)
        self.badges.setSpacing(6)
        self.badges.addStretch(1)
        top.addWidget(holder, 1)
        text.addLayout(top)
        self.why = _label(t.why, "Muted", wrap=True)
        text.addWidget(self.why)
        self.value = _label("", "Value")
        self.value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        text.addWidget(self.value)
        lay.addLayout(text, 1)

        self.switch = Switch()
        self.switch.toggled.connect(lambda on: self.flipped.emit(t.id, on))
        self.done = QLabel()
        self.done.setObjectName("Done")
        lay.addWidget(self.switch, 0, Qt.AlignmentFlag.AlignVCenter)
        lay.addWidget(self.done, 0, Qt.AlignmentFlag.AlignVCenter)

    def show_state(self, info: dict, pending: bool | None):
        """info is one scan result; pending is the staged on/off, or None when nothing is staged."""
        self.state = info["state"]
        on = self.state == "on"
        while self.badges.count() > 1:      # keep the trailing stretch
            self.badges.takeAt(0).widget().deleteLater()
        badges = []
        if info["note"]:
            badges.append(_badge(info["note"], solid=True))
        if self.state in ("on", "off"):
            if self.t.when != "now":
                badges.append(_badge(tweaks.WHEN[self.t.when]))
            if self.t.root:
                badges.append(_badge("Password"))
            if self.t.installs and self.state == "off":
                b = _badge("Installs a package")
                b.setToolTip(f"Turning this on installs {self.t.installs} from Ubuntu's archive")
                badges.append(b)
            if self.t.recommended and self.state == "off":
                badges.append(_badge("Recommended"))
        for i, b in enumerate(badges):
            self.badges.insertWidget(i, b)

        live = info["current"]
        if self.state == "na":
            self.value.setText(info["reason"])
        elif self.state == "native":
            self.value.setText(f"{live}" if live else "")
        elif pending is not None:
            self.value.setText(f"{live}   →   {self.t.target if pending else 'back to how it was'}")
        else:
            self.value.setText(live if on else f"{live}   →   {self.t.target}")

        switchable = self.state in ("on", "off")
        self.switch.setVisible(switchable)
        self.done.setVisible(not switchable)
        if self.state == "native":
            self.done.setText("Already set")
        elif self.state == "na":
            self.done.setText("Not needed")
        self.switch.blockSignals(True)
        self.switch.setChecked(on if pending is None else pending)
        self.switch.blockSignals(False)
        self.setProperty("pending", pending is not None)
        self.setProperty("muted", self.state in ("na", "native"))
        for w in (self, self.title):
            _repolish(w)


class NavItem(QPushButton):
    """Group name on the left, "2/4" on the right."""

    def __init__(self, name: str):
        super().__init__()
        self.setObjectName("SubNavItem")
        self.setCheckable(True)
        self.setMinimumHeight(36)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 0, 10, 0)
        self.name = _label(name, "NavName")
        self.count = _label("", "NavCount")
        for w in (self.name, self.count):
            w.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        lay.addWidget(self.name)
        lay.addStretch(1)
        lay.addWidget(self.count)

    def setChecked(self, on):
        super().setChecked(on)
        self.name.setProperty("on", on)
        _repolish(self.name)


class OptimizeLPage(QWidget):
    def __init__(self):
        super().__init__()
        self.setObjectName("Page")
        self.info: dict[str, dict] = {}
        self.pending: dict[str, bool] = {}
        self.busy = False
        self._sig = _Signals()
        self._sig.scanned.connect(self._on_scanned)
        self._sig.applied.connect(self._on_applied)

        root = QVBoxLayout(self)
        root.setContentsMargins(40, 30, 40, 22)
        root.setSpacing(18)

        head = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(2)
        titles.addWidget(_label("OptimizeL", "Title"))
        titles.addWidget(_label("Tunes this PC for speed. Every switch stays put through restarts, and turning one "
                                "off puts back exactly what was there.", "Subtitle", wrap=True))
        head.addLayout(titles, 1)
        self.restore_btn = QPushButton("Turn all off")
        self.restore_btn.setToolTip("Stage every OptimizeL change to be undone")
        self.restore_btn.clicked.connect(self._stage_all_off)
        self.rescan_btn = QPushButton("Rescan")
        self.rescan_btn.clicked.connect(self.scan)
        self.rec_btn = QPushButton("Select recommended")
        self.rec_btn.setObjectName("Primary")
        self.rec_btn.setMinimumSize(190, 40)
        self.rec_btn.clicked.connect(self._stage_recommended)
        for b in (self.restore_btn, self.rescan_btn, self.rec_btn):
            head.addWidget(b, 0, Qt.AlignmentFlag.AlignTop)
        root.addLayout(head)

        stats = QHBoxLayout()
        stats.setSpacing(12)
        self.stats = {}
        for key, label in (("on", "On"), ("left", "Recommended left"), ("native", "Already optimal"),
                           ("finish", "Waiting on restart")):
            tile = QFrame()
            tile.setObjectName("Stat")
            tl = QVBoxLayout(tile)
            tl.setContentsMargins(18, 12, 18, 12)
            tl.setSpacing(0)
            num = _label("–", "StatNum")
            tl.addWidget(num)
            tl.addWidget(_label(label.upper(), "StatLabel"))
            stats.addWidget(tile, 1)
            self.stats[key] = num
        root.addLayout(stats)

        body = QHBoxLayout()
        body.setSpacing(28)
        nav = QVBoxLayout()
        nav.setSpacing(2)
        nav.addWidget(_label("GROUPS", "NavSection"))
        self.nav: dict[str, NavItem] = {}
        for g in tweaks.GROUPS:
            item = NavItem(g)
            item.clicked.connect(lambda _=False, g=g: self._jump(g))
            nav.addWidget(item)
            self.nav[g] = item
        nav.addStretch(1)
        navw = QWidget()
        navw.setFixedWidth(210)
        navw.setLayout(nav)
        body.addWidget(navw)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        inner = QWidget()
        inner.setObjectName("Page")
        col = QVBoxLayout(inner)
        col.setContentsMargins(0, 0, 14, 24)
        col.setSpacing(10)
        self.rows: dict[str, Row] = {}
        self.sections: dict[str, QWidget] = {}
        self.section_counts: dict[str, QLabel] = {}
        self.good_boxes: dict[str, QVBoxLayout] = {}
        for g in tweaks.GROUPS:
            head_row = QWidget()
            hl = QHBoxLayout(head_row)
            hl.setContentsMargins(2, 18 if self.sections else 0, 2, 4)
            hl.addWidget(_label(g, "SectionTitle"))
            hl.addStretch(1)
            cnt = _label("", "Muted")
            hl.addWidget(cnt)
            col.addWidget(head_row)
            self.sections[g] = head_row
            self.section_counts[g] = cnt
            for t in (t for t in tweaks.TWEAKS if t.group == g):
                row = Row(t)
                row.flipped.connect(self._flip)
                col.addWidget(row)
                self.rows[t.id] = row
            good = QVBoxLayout()
            good.setContentsMargins(4, 2, 0, 0)
            good.setSpacing(2)
            col.addLayout(good)
            self.good_boxes[g] = good
        col.addStretch(1)
        self.scroll.setWidget(inner)
        self.scroll.verticalScrollBar().valueChanged.connect(self._spy)
        body.addWidget(self.scroll, 1)
        root.addLayout(body, 1)

        self.bar = QFrame()
        self.bar.setObjectName("Pending")
        bl = QHBoxLayout(self.bar)
        bl.setContentsMargins(22, 12, 14, 12)
        bl.setSpacing(10)
        self.bar_text = _label("", "PendingText")
        self.bar_text.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        bl.addWidget(self.bar_text, 1)
        self.discard_btn = QPushButton("Discard")
        self.discard_btn.clicked.connect(self._discard)
        self.apply_btn = QPushButton("Apply changes")
        self.apply_btn.setObjectName("Primary")
        self.apply_btn.setMinimumWidth(150)
        self.apply_btn.clicked.connect(self._apply)
        bl.addWidget(self.discard_btn)
        bl.addWidget(self.apply_btn)
        root.addWidget(self.bar)

        self.toast = _label("", "Toast", wrap=True)
        self.toast.hide()
        root.addWidget(self.toast)
        self._toast_timer = QTimer(self, singleShot=True, interval=9000, timeout=self.toast.hide)

        self.nav[tweaks.GROUPS[0]].setChecked(True)
        self._refresh_bar()
        self.scan()

    # ------------------------------------------------------------------ scanning
    def scan(self):
        if self.busy:
            return
        self.rescan_btn.setText("Scanning…")
        sig = self._sig
        POOL.start(Job(_scan, sig.scanned.emit))

    def _on_scanned(self, result):
        self.rescan_btn.setText("Rescan")
        self.info = result["tweaks"]
        # drop staged flips that the system already matches (e.g. changed elsewhere)
        self.pending = {k: v for k, v in self.pending.items() if (self.info[k]["state"] == "on") != v}
        for tid, row in self.rows.items():
            row.show_state(self.info[tid], self.pending.get(tid))
        for g, box in self.good_boxes.items():
            while box.count():
                box.takeAt(0).widget().deleteLater()
            for text in result["checks"].get(g, []):
                box.addWidget(_good_line(text))
        self._refresh_counts()
        self._refresh_bar()

    def _refresh_counts(self):
        states = {tid: i["state"] for tid, i in self.info.items()}
        self.stats["on"].setText(str(sum(s == "on" for s in states.values())))
        self.stats["left"].setText(str(sum(s == "off" and tweaks.BY_ID[t].recommended for t, s in states.items())))
        checks = sum(self.good_boxes[g].count() for g in tweaks.GROUPS)
        self.stats["native"].setText(str(sum(s == "native" for s in states.values()) + checks))
        self.stats["finish"].setText(str(sum(bool(i["note"]) for i in self.info.values())))
        for g in tweaks.GROUPS:
            ids = [t.id for t in tweaks.TWEAKS if t.group == g]
            live = [i for i in ids if states.get(i) in ("on", "off")]
            on = sum(states.get(i) == "on" for i in live)
            self.nav[g].count.setText(f"{on}/{len(live)}" if live else "✓")
            self.section_counts[g].setText(f"{on} of {len(live)} on" if live else "Nothing to change")

    # ------------------------------------------------------------------ staging
    def _flip(self, tid, on):
        if (self.info.get(tid, {}).get("state") == "on") == on:
            self.pending.pop(tid, None)
        else:
            self.pending[tid] = on
        self.rows[tid].show_state(self.info[tid], self.pending.get(tid))
        self._refresh_bar()

    def _stage_recommended(self):
        for t in tweaks.TWEAKS:
            if t.recommended and self.info.get(t.id, {}).get("state") == "off":
                self.pending[t.id] = True
                self.rows[t.id].show_state(self.info[t.id], True)
        self._refresh_bar()

    def _stage_all_off(self):
        for tid, i in self.info.items():
            if i["state"] == "on":
                self.pending[tid] = False
                self.rows[tid].show_state(i, False)
        self._refresh_bar()

    def _discard(self):
        self.pending.clear()
        for tid, row in self.rows.items():
            row.show_state(self.info[tid], None)
        self._refresh_bar()

    def _refresh_bar(self):
        n = len(self.pending)
        self.bar.setVisible(bool(n) or self.busy)
        self.rec_btn.setEnabled(not self.busy and any(
            t.recommended and self.info.get(t.id, {}).get("state") == "off" and t.id not in self.pending
            for t in tweaks.TWEAKS))
        self.restore_btn.setEnabled(not self.busy and any(i["state"] == "on" for i in self.info.values()))
        if self.busy:
            self.bar_text.setText("Applying… if a password prompt opens, it's for the system changes.")
            return
        ons = sum(self.pending.values())
        offs = n - ons
        parts = [f"{ons} to turn on" if ons else "", f"{offs} to turn off" if offs else ""]
        roots = sum(tweaks.BY_ID[t].root for t in self.pending)
        later = {tweaks.BY_ID[t].when for t in self.pending} - {"now"}
        tail = []
        if roots:
            tail.append("asks for your password once")
        if "restart" in later:
            tail.append("some finish after a restart")
        elif "logout" in later:
            tail.append("some finish after you log out")
        self.bar_text.setText(" and ".join(p for p in parts if p) + (".   " + ", ".join(tail).capitalize() + "."
                                                                    if tail else "."))

    def _jump(self, g):
        self.scroll.verticalScrollBar().setValue(self.sections[g].y())
        for name, item in self.nav.items():
            item.setChecked(name == g)

    def _spy(self, value):
        current = tweaks.GROUPS[0]
        for g, w in self.sections.items():
            if w.y() <= value + 40:
                current = g
        for name, item in self.nav.items():
            item.setChecked(name == current)

    # ------------------------------------------------------------------ applying
    def _apply(self):
        if not self.pending or self.busy:
            return
        self.busy = True
        changes = dict(self.pending)
        for w in (self.apply_btn, self.discard_btn):
            w.setEnabled(False)
        for row in self.rows.values():
            row.switch.setEnabled(False)
        self._refresh_bar()
        sig = self._sig
        POOL.start(Job(lambda: (changes, tweaks.apply(changes)), sig.applied.emit))

    def _on_applied(self, result):
        changes, problems = result
        self.busy = False
        for w in (self.apply_btn, self.discard_btn):
            w.setEnabled(True)
        for row in self.rows.values():
            row.switch.setEnabled(True)
        self.pending.clear()
        cancelled = "You cancelled the password prompt" in problems
        done = {t: on for t, on in changes.items() if not (cancelled and tweaks.BY_ID[t].root)}
        ons = sum(done.values())
        parts = [f"turned on {ons}" if ons else "", f"turned off {len(done) - ons}" if len(done) - ons else ""]
        text = " and ".join(p for p in parts if p).capitalize() + "." if done else "Nothing changed."
        if cancelled:
            text += " System changes were skipped because the password prompt was cancelled."
        others = [p for p in problems if p != "You cancelled the password prompt"]
        if others:
            text += " Problems: " + "; ".join(others)
        self.toast.setText(text)
        self.toast.show()
        self._toast_timer.start()
        self.scan()


def _good_line(text: str) -> QWidget:
    w = QWidget()
    lay = QHBoxLayout(w)
    lay.setContentsMargins(0, 2, 0, 2)
    lay.setSpacing(8)
    icon = QLabel()
    icon.setPixmap(glyph("check", 14).pixmap(14, 14, QIcon.Mode.Normal))
    lay.addWidget(icon)
    lay.addWidget(_label(text, "GoodLine"), 1)
    return w


def _scan() -> dict:
    """Runs on a worker thread: every tweak's state and live value, plus the already-good checks."""
    saved = tweaks.load_saved()
    out = {}
    for t in tweaks.TWEAKS:
        try:
            state = t.state()
            out[t.id] = {"state": state, "current": t.current(), "reason": t.unavailable() if state == "na" else "",
                         "note": tweaks.pending_note(t, saved)}
        except Exception as e:          # one odd setting must never hide the rest
            out[t.id] = {"state": "na", "current": "", "reason": f"Couldn't read this: {e}", "note": ""}
    try:
        checks = tweaks.checks()
    except Exception:
        checks = {}
    return {"tweaks": out, "checks": checks}
