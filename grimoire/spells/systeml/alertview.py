# SPDX-License-Identifier: GPL-3.0-or-later
"""SystemL's Alerts panel: the background-alerts switch (installs the timer), each alert's switch and threshold,
a test notification and the recent alerts. Settings save as you change them; the timer reads them on its next pass.
"""
import time

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (QComboBox, QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea, QSpinBox,
                               QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from grimoire.fsutil import human
from grimoire.jobs import POOL, Job
from grimoire.spells.systeml import alerts
from grimoire.widgets import Switch

# (settings key, title, what it watches, threshold field, lowest, highest, suffix)
ALERTS = [("ram", "Memory", "Warns when RAM use goes above", "percent", 50, 99, "%"),
          ("cpu_temp", "CPU temperature", "Warns when the CPU gets hotter than", "c", 50, 110, "°C"),
          ("gpu_temp", "GPU temperature", "Warns when the graphics card gets hotter than", "c", 50, 110, "°C"),
          ("hung", "Stuck apps", "Warns when a window stays \"Not Responding\" in KWin, or one of your processes "
           "hangs on a disk or device with no progress, for", "minutes", 1, 60, "min")]


class _Signals(QObject):
    loaded = Signal(object)          # (timer on, readings, history)
    sent = Signal(object)


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


def _row(title: str, sub: QLabel, *controls) -> QFrame:
    row = QFrame()
    row.setObjectName("Row")
    lay = QHBoxLayout(row)
    lay.setContentsMargins(18, 12, 16, 12)
    lay.setSpacing(12)
    text = QVBoxLayout()
    text.setSpacing(3)
    text.addWidget(_label(title, "RowTitle"))
    text.addWidget(sub)
    lay.addLayout(text, 1)
    for c in controls:
        lay.addWidget(c, 0, Qt.AlignmentFlag.AlignVCenter)
    return row


class AlertsPanel(QScrollArea):
    def __init__(self, page):
        super().__init__()
        self.page = page
        self.s = alerts.load_settings()
        self.sig = _Signals()
        self.sig.loaded.connect(self.loaded)
        self.sig.sent.connect(lambda ok: page.say("Test notification sent" if ok else
                                                  "Couldn't send a notification: is the notification service running?"))
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        inner = QWidget()
        inner.setObjectName("Page")
        col = QVBoxLayout(inner)
        col.setContentsMargins(0, 0, 12, 20)
        col.setSpacing(8)

        self.master = Switch()
        self.master.toggled.connect(self._set_on)
        self.state = _label("", "Muted", wrap=True)
        test = QPushButton("Send test notification")
        test.clicked.connect(self._test)
        self.cooldown = _spin(5, 720, "min", self.s["cooldown"], lambda v: self._set("cooldown", None, v))
        head = _row("Background alerts", self.state, test, self.master)
        col.addWidget(head)
        remind = QHBoxLayout()
        remind.setContentsMargins(18, 4, 16, 6)
        remind.addWidget(_label("While a problem lasts, remind again after", "Muted"))
        remind.addWidget(self.cooldown)
        remind.addStretch(1)
        col.addLayout(remind)

        col.addSpacing(6)
        col.addWidget(_label("Alerts", "SectionTitle"))
        self.readouts: dict[str, QLabel] = {}
        self.toggles: list[QWidget] = []
        for key, title, what, field, lo, hi, suffix in ALERTS:
            sub = _label("", "Muted", wrap=True)
            self.readouts[key] = sub
            sub.setProperty("what", what)
            spin = _spin(lo, hi, suffix, self.s[key][field], lambda v, k=key, f=field: self._set(k, f, v))
            sw = Switch()
            sw.setChecked(self.s[key]["on"])
            sw.toggled.connect(lambda on, k=key: self._set(k, "on", on))
            col.addWidget(_row(title, sub, spin, sw))

        col.addSpacing(6)
        col.addWidget(_label("Disk free space", "SectionTitle"))
        self.disks = QVBoxLayout()
        self.disks.setSpacing(8)
        col.addLayout(self.disks)

        col.addSpacing(6)
        col.addWidget(_label("Recent alerts", "SectionTitle"))
        self.history = QTreeWidget()
        self.history.setHeaderLabels(["When", "Alert", "Details"])
        self.history.setRootIsDecorated(False)
        self.history.setUniformRowHeights(True)
        self.history.setMinimumHeight(200)
        for c, w in ((0, 140), (1, 220)):
            self.history.header().resizeSection(c, w)
        col.addWidget(self.history)
        self.empty = _label("Nothing yet. Alerts show up here (and as notifications) when something crosses a line.",
                            "Muted", wrap=True)
        col.addWidget(self.empty)
        col.addStretch(1)
        self.setWidget(inner)
        self._fill_readouts({})

    # ------------------------------------------------------------ loading
    def load(self):
        POOL.start(Job(lambda: (alerts.enabled(), alerts.readings(), alerts.history()), self.sig.loaded.emit))

    def loaded(self, result):
        on, readings, hist = result
        self.master.blockSignals(True)
        self.master.setChecked(on)
        self.master.blockSignals(False)
        self._show_state(on)
        self._fill_readouts(readings)
        self._fill_disks(readings.get("disks", []))
        self._fill_history(hist)

    def _show_state(self, on: bool):
        self.state.setText("On: checked once a minute, even while SystemL is closed. Each alert notifies once, then "
                           "waits until it clears or the reminder time passes." if on else
                           "Off. Turn on to get notified in the background (adds a small systemd timer that runs "
                           "once a minute).")

    def _fill_readouts(self, r: dict):
        temps = r.get("temps", {})
        now = {"ram": f"{r['ram']:.0f}% now" if "ram" in r else "",
               "cpu_temp": (f"{temps['CPU']:.0f}°C now" if "CPU" in temps else "no CPU sensor found, so it stays quiet")
               if r else "",
               "gpu_temp": (f"{temps['GPU']:.0f}°C now" if "GPU" in temps else "no GPU sensor found, so it stays quiet")
               if r else "", "hung": ""}
        for key, lab in self.readouts.items():
            lab.setText(lab.property("what") + (f" · {now[key]}" if now[key] else ""))

    def _fill_disks(self, disks: list[dict]):
        while self.disks.count():
            w = self.disks.takeAt(0).widget()
            if w:
                w.deleteLater()
        if not disks:
            self.disks.addWidget(_label("No disks found.", "Muted"))
        for d in disks:
            rule = alerts.disk_rule(self.s, d)
            sub = _label(f"{d['device']} · {human(d['free'])} free of {human(d['total'])} · warns when free space "
                         "drops below", "Muted", wrap=True)
            spin = _spin(1, 9999, "", rule["value"], lambda v, m=d: self._set_disk(m, "value", v))
            unit = QComboBox()
            unit.addItems(["GB", "%"])
            unit.setCurrentText(rule["unit"])
            spin.setMaximum(100 if rule["unit"] == "%" else 9999)
            unit.currentTextChanged.connect(lambda u, m=d, sp=spin: (sp.setMaximum(100 if u == "%" else 9999),
                                                                     self._set_disk(m, "unit", u)))
            sw = Switch()
            sw.setChecked(rule["on"])
            sw.toggled.connect(lambda on, m=d: self._set_disk(m, "on", on))
            self.disks.addWidget(_row(d["mount"], sub, spin, unit, sw))

    def _fill_history(self, hist: list[dict]):
        self.history.clear()
        for a in reversed(hist[-50:]):
            self.history.addTopLevelItem(_item([time.strftime("%b %-d, %H:%M", time.localtime(a["t"])),
                                                a["title"], a["body"]]))
        self.history.setVisible(bool(hist))
        self.empty.setVisible(not hist)

    # ------------------------------------------------------------ changes
    def _set(self, key: str, field: str | None, value):
        if field is None:
            self.s[key] = value
        else:
            self.s[key][field] = value
        alerts.save_settings(self.s)

    def _set_disk(self, d: dict, field: str, value):
        rule = dict(alerts.disk_rule(self.s, d))
        rule[field] = value
        self.s["disks"][d["mount"]] = rule
        alerts.save_settings(self.s)

    def _set_on(self, on: bool):
        def work():
            alerts.set_enabled(on)
            return "on" if on else "off"
        self.page.act("Background alerts", work, then=self.load)

    def _test(self):
        POOL.start(Job(lambda: alerts.notify("SystemL alerts work", "This is how memory, temperature, disk and "
                                             "stuck-app alerts will look."), self.sig.sent.emit))


def _item(texts):
    it = QTreeWidgetItem(texts)
    it.setToolTip(2, texts[2])
    return it
