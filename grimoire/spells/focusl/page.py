"""FocusL page: the countdown ring with its controls, today's numbers and the last two weeks, and the session
settings. The timer itself lives in the background runner (runner.py); this page only reads its state file and sends
it commands, so closing the page or Grimoire never stops a session.
"""
import os
import time

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtWidgets import (QComboBox, QFrame, QHBoxLayout, QLabel, QLineEdit, QMenu, QPushButton, QScrollArea,
                               QSpinBox, QVBoxLayout, QWidget)

from grimoire.jobs import POOL, Job
from grimoire.spells.focusl import runner, store
from grimoire.spells.focusl.dial import Bars, Ring
from grimoire.spells.focusl.store import PHASES
from grimoire.widgets import Switch


class _Signals(QObject):
    unblocked = Signal(object)


def _label(text="", name="", wrap=False) -> QLabel:
    lab = QLabel(text)
    if name:
        lab.setObjectName(name)
    lab.setWordWrap(wrap)
    return lab


def _spin(lo, hi, suffix, value, on_change) -> QSpinBox:
    s = QSpinBox()
    s.setRange(lo, hi)
    if suffix:
        s.setSuffix(f" {suffix}")
    s.setValue(value)
    s.setFixedWidth(96)
    s.valueChanged.connect(on_change)
    return s


def _row(title: str, sub: str, *controls, below: QWidget | None = None) -> QFrame:
    row = QFrame()
    row.setObjectName("Row")
    outer = QVBoxLayout(row)
    outer.setContentsMargins(18, 12, 16, 12)
    outer.setSpacing(10)
    lay = QHBoxLayout()
    lay.setSpacing(12)
    text = QVBoxLayout()
    text.setSpacing(3)
    text.addWidget(_label(title, "RowTitle"))
    if sub:
        text.addWidget(_label(sub, "Muted", wrap=True))
    lay.addLayout(text, 1)
    for c in controls:
        lay.addWidget(c, 0, Qt.AlignmentFlag.AlignVCenter)
    outer.addLayout(lay)
    if below:
        outer.addWidget(below)
    return row


def _minutes(m: float) -> str:
    return f"{m / 60:.1f} h" if m >= 60 else f"{m:.0f} min"


class FocusLPage(QWidget):
    def __init__(self):
        super().__init__()
        self.setObjectName("Page")
        self.s = store.load_settings()
        self._shown_status = None
        self._phase_key = None
        self.sig = _Signals()
        self.sig.unblocked.connect(self._unblocked)

        root = QVBoxLayout(self)
        root.setContentsMargins(40, 30, 40, 22)
        root.setSpacing(18)
        titles = QVBoxLayout()
        titles.setSpacing(2)
        titles.addWidget(_label("FocusL", "Title"))
        titles.addWidget(_label("Focus in rounds with breaks between. While you focus: Do Not Disturb, no crosshair, "
                                "and the apps and sites you pick kept away. The timer keeps going when you close "
                                "Grimoire.", "Subtitle", wrap=True))
        root.addLayout(titles)

        tiles = QHBoxLayout()
        tiles.setSpacing(12)
        self.tiles = {}
        for key, label in (("today", "Today"), ("week", "This week"), ("minutes", "Focus time"),
                           ("streak", "Streak")):
            tile = QFrame()
            tile.setObjectName("Stat")
            tl = QVBoxLayout(tile)
            tl.setContentsMargins(18, 12, 18, 12)
            tl.setSpacing(0)
            num = _label("–", "StatNum")
            tl.addWidget(num)
            tl.addWidget(_label(label.upper(), "StatLabel"))
            tiles.addWidget(tile, 1)
            self.tiles[key] = num
        root.addLayout(tiles)

        body = QHBoxLayout()
        body.setSpacing(28)
        left = QVBoxLayout()
        left.setSpacing(14)
        self.ring = Ring()
        left.addWidget(self.ring, 1)
        self.buttons = QHBoxLayout()
        self.buttons.setSpacing(10)
        self.primary = QPushButton()
        self.primary.setObjectName("Primary")
        self.primary.setMinimumSize(170, 40)
        self.primary.clicked.connect(self._primary)
        self.skip_btn = QPushButton("Skip")
        self.skip_btn.setToolTip("End this phase now and go on to the next")
        self.skip_btn.clicked.connect(lambda: self._send("skip"))
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setToolTip("End the session: Do Not Disturb off, crosshair and sites back")
        self.stop_btn.clicked.connect(self._stop)
        self.buttons.addStretch(1)
        for b in (self.primary, self.skip_btn, self.stop_btn):
            b.setMinimumHeight(40)
            self.buttons.addWidget(b)
        self.buttons.addStretch(1)
        left.addLayout(self.buttons)

        self.leftover = QFrame()
        self.leftover.setObjectName("Pending")
        ll = QHBoxLayout(self.leftover)
        ll.setContentsMargins(18, 10, 12, 10)
        ll.addWidget(_label("Sites are still blocked from a session that stopped before it could clean up.",
                            "PendingText", wrap=True), 1)
        self.unblock_btn = QPushButton("Unblock")
        self.unblock_btn.setObjectName("Primary")
        self.unblock_btn.clicked.connect(self._unblock)
        ll.addWidget(self.unblock_btn)
        self.leftover.hide()
        left.addWidget(self.leftover)

        chart_head = QHBoxLayout()
        chart_head.addWidget(_label("Last 14 days", "SectionTitle"))
        chart_head.addStretch(1)
        self.chart_note = _label("", "Muted")
        chart_head.addWidget(self.chart_note)
        left.addLayout(chart_head)
        self.bars = Bars()
        left.addWidget(self.bars)
        body.addLayout(left, 1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFixedWidth(470)
        inner = QWidget()
        inner.setObjectName("Page")
        col = QVBoxLayout(inner)
        col.setContentsMargins(0, 0, 12, 20)
        col.setSpacing(8)
        self._build_settings(col)
        col.addStretch(1)
        scroll.setWidget(inner)
        body.addWidget(scroll)
        root.addLayout(body, 1)

        self.toast = _label("", "Toast", wrap=True)
        self.toast.hide()
        root.addWidget(self.toast)
        self._toast_timer = QTimer(self, singleShot=True, interval=9000, timeout=self.toast.hide)
        self.timer = QTimer(self, interval=250, timeout=self.refresh)

    # ------------------------------------------------------------ settings
    def _build_settings(self, col: QVBoxLayout):
        s = self.s
        col.addWidget(_label("Session", "SectionTitle"))
        for key, title, sub, hi in (("focus", "Focus", "One round of focus", 180),
                                    ("short", "Short break", "Between rounds", 60),
                                    ("long", "Long break", "After the last round", 120)):
            col.addWidget(_row(title, sub, _spin(1, hi, "min", s[key], lambda v, k=key: self._set(k, v))))
        col.addWidget(_row("Rounds", "Focus rounds before the long break",
                           _spin(1, 12, "", s["rounds"], lambda v: self._set("rounds", v))))
        col.addWidget(_row("Start the next phase by itself", "Off: each break and round waits for you",
                           self._switch("auto_start")))
        col.addWidget(_row("Soft chime", "A quiet sound when a phase ends", self._switch("sound")))

        col.addSpacing(8)
        col.addWidget(_label("While you focus", "SectionTitle"))
        col.addWidget(_row("Do Not Disturb", "Plasma holds notifications back (critical ones still show). Ends "
                           "with the round, even if FocusL is closed by force", self._switch("dnd")))
        col.addWidget(_row("Hide the crosshair", "SightsL's overlay goes away, and comes back after if it was on",
                           self._switch("hide_crosshair")))

        apps = QWidget()
        al = QVBoxLayout(apps)
        al.setContentsMargins(0, 0, 0, 0)
        al.setSpacing(8)
        line = QHBoxLayout()
        self.apps_edit = QLineEdit(", ".join(s["apps"]))
        self.apps_edit.setPlaceholderText("discord, steam, spotify")
        self.apps_edit.editingFinished.connect(self._save_apps)
        pick = QPushButton("Running…")
        pick.setToolTip("Add an app that's open right now")
        pick.clicked.connect(lambda: self._pick_app(pick))
        line.addWidget(self.apps_edit, 1)
        line.addWidget(pick)
        al.addLayout(line)
        how = QHBoxLayout()
        self.action = QComboBox()
        self.action.addItem("Warn, then close", "close")
        self.action.addItem("Only warn", "warn")
        self.action.setCurrentIndex(0 if s["app_action"] == "close" else 1)
        self.action.currentIndexChanged.connect(lambda _: self._set("app_action", self.action.currentData()))
        how.addWidget(self.action, 1)
        how.addWidget(_label("after", "Muted"))
        how.addWidget(_spin(0, 120, "s", s["grace"], lambda v: self._set("grace", v)))
        al.addLayout(how)
        col.addWidget(_row("Block apps", "Process names. A blocked app gets a notification, then a polite quit "
                           "(the same as closing it) once the grace time is up", self._switch("block_apps"),
                           below=apps))

        self.sites_edit = QLineEdit(", ".join(s["sites"]))
        self.sites_edit.setPlaceholderText("youtube.com, reddit.com")
        self.sites_edit.editingFinished.connect(self._save_sites)
        col.addWidget(_row("Block sites", "Every browser, through /etc/hosts. That needs your password once when "
                           "the session starts and once when it ends, and sites stay blocked through the breaks. "
                           "Reload open tabs to see it", self._switch("block_sites"), below=self.sites_edit))
        col.addWidget(_label("Changes apply from the next phase of a running session.", "Muted"))

    def _switch(self, key: str) -> Switch:
        sw = Switch()
        sw.setChecked(self.s[key])
        sw.toggled.connect(lambda on: self._set(key, on))
        return sw

    def _set(self, key, value):
        self.s = store.load_settings() | {key: value}
        try:
            store.save_settings(self.s)
        except OSError as e:
            self.say(f"Couldn't save the settings: {e}")
        if key in ("focus", "rounds"):
            self.refresh()

    def _save_apps(self):
        raw = [a for a in self.apps_edit.text().replace("\n", ",").split(",") if a.strip()]
        clean = list(dict.fromkeys(filter(None, (store.clean_app(a) for a in raw))))
        bad = [a.strip() for a in raw if not store.clean_app(a)]
        self.apps_edit.setText(", ".join(clean))
        if bad:
            self.say(f"Left out {', '.join(bad)}: the desktop, shells and Python can't be blocked")
        if clean != self.s["apps"]:
            self._set("apps", clean)

    def _save_sites(self):
        raw = [a for a in self.sites_edit.text().replace(" ", ",").split(",") if a.strip()]
        clean = list(dict.fromkeys(filter(None, (store.clean_site(a) for a in raw))))
        bad = [a.strip() for a in raw if not store.clean_site(a)]
        self.sites_edit.setText(", ".join(clean))
        if bad:
            self.say(f"Left out {', '.join(bad)}: not a site name")
        if clean != self.s["sites"]:
            self._set("sites", clean)

    def _pick_app(self, btn: QPushButton):
        import psutil
        names = set()
        uid = os.getuid()
        for p in psutil.process_iter(["name", "uids"]):
            i = p.info
            n = store.clean_app(i["name"] or "")
            if n and i["uids"] and i["uids"].real == uid and not n.startswith(("kworker", "xdg-", "gvfs", "at-spi")):
                names.add(n)
        menu = QMenu(self)
        for n in sorted(names)[:60]:
            menu.addAction(n, lambda n=n: self._add_app(n))
        menu.exec(btn.mapToGlobal(btn.rect().bottomLeft()))

    def _add_app(self, name: str):
        cur = [a.strip() for a in self.apps_edit.text().split(",") if a.strip()]
        self.apps_edit.setText(", ".join(cur + [name]))
        self._save_apps()

    # ------------------------------------------------------------ session controls
    def _primary(self):
        st = store.live_state()
        if st["phase"] == "idle":
            if runner.start():
                self.say("Focus started. It keeps going if you close Grimoire."
                         + (" Your password is asked to block sites." if self.s["block_sites"] else ""))
        elif st.get("status") == "running":
            self._send("pause")
        else:
            self._send("resume")
        QTimer.singleShot(300, self.refresh)

    def _send(self, cmd: str):
        if store.running():
            store.send(cmd)
            QTimer.singleShot(700, self.refresh)

    def _stop(self):
        runner.stop()
        self.say("Session stopped" + (". Your password is asked to unblock the sites."
                                      if store.live_state().get("sites_blocked") else ""))
        QTimer.singleShot(700, self.refresh)

    def _unblock(self):
        self.unblock_btn.setEnabled(False)
        self.unblock_btn.setText("Unblocking…")
        POOL.start(Job(lambda: runner.recover(sites=True), self.sig.unblocked.emit))

    def _unblocked(self, err: str):
        self.unblock_btn.setEnabled(True)
        self.unblock_btn.setText("Unblock")
        self.say(f"Couldn't unblock: {err}" if err else "Sites unblocked")
        self.refresh()

    # ------------------------------------------------------------ display
    def refresh(self):
        st = store.live_state()
        if st.get("stale") and st.get("crosshair_hidden"):
            runner.recover()                       # a session died with the crosshair hidden: bring it back
        phase, status = st["phase"], st.get("status", "")
        rounds = int(st.get("rounds") or self.s["rounds"])
        rnd = int(st.get("round") or 1)
        if phase == "idle":
            length = self.s["focus"] * 60
            self.ring.show_state(1.0, store.clock(length), "READY", f"{self.s['rounds']} rounds of "
                                 f"{self.s['focus']} min", self.s["rounds"], 0, -1, True)
        else:
            left = store.left(st)
            length = max(1, st.get("length") or 1)
            done = rnd - 1 + (phase != "focus")
            top = PHASES[phase].upper() + (f" · {rnd} OF {rounds}" if phase == "focus" else "")
            if status == "paused":
                bottom = "Paused"
            elif status == "waiting":
                bottom = "Ready when you are"
            else:
                bottom = "until " + time.strftime("%H:%M", time.localtime(time.time() + left))
            self.ring.show_state(left / length, store.clock(left), top, bottom, rounds, done,
                                 rnd - 1 if phase == "focus" else -1, status != "running")
        key = (phase, status)
        if key != self._shown_status:
            self._shown_status = key
            self.primary.setText({"idle": "Start focus"}.get(phase) or
                                 {"running": "Pause", "paused": "Resume"}.get(status) or
                                 f"Start {PHASES[phase].lower()}")
            self.skip_btn.setVisible(phase != "idle")
            self.stop_btn.setVisible(phase != "idle")
        self.leftover.setVisible(phase == "idle" and bool(st.get("sites_blocked")))
        pk = (phase, rnd, status == "waiting")
        if pk != self._phase_key:                  # stats only change when a phase does
            self._phase_key = pk
            self.refresh_stats()

    def refresh_stats(self):
        s = store.stats()
        self.tiles["today"].setText(str(s["today"]))
        self.tiles["week"].setText(str(s["week"]))
        self.tiles["minutes"].setText(_minutes(s["minutes"]))
        self.tiles["streak"].setText(f"{s['streak']} day{'' if s['streak'] == 1 else 's'}")
        self.bars.set_days(s["days"])
        fortnight = sum(m for _, m, _ in s["days"])
        self.chart_note.setText(f"{_minutes(fortnight)} of focus" if fortnight else "No focus yet")

    def say(self, text: str):
        self.toast.setText(text)
        self.toast.show()
        self._toast_timer.start()

    def showEvent(self, e):
        super().showEvent(e)
        self._phase_key = None
        self.refresh()
        self.timer.start()

    def hideEvent(self, e):
        super().hideEvent(e)
        self.timer.stop()
