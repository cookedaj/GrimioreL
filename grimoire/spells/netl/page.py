# SPDX-License-Identifier: GPL-3.0-or-later
"""NetL page: network monitor and quick controls. Overview (live traffic, addresses, on-demand checks), per-app
bandwidth, connections, Wi-Fi & VPN, and usage history, each a panel picked from the list on the left.

One Sampler reads the interface counters on a worker thread once a second while the page is on screen; per-app
TCP counters are read every 2 s while Apps is shown and every 10 s otherwise (so session totals keep adding up),
connections every 3 s while that panel is shown. Nothing is sampled while NetL is hidden. Once a minute (and on
hiding) what was measured goes into the usage file. Graphs and table helpers are SystemL's.
"""
import time
import traceback

import psutil
from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QIcon, QImage, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox, QFrame, QGridLayout, QHBoxLayout,
                               QHeaderView, QLineEdit, QMessageBox, QPushButton, QScrollArea, QStackedWidget,
                               QVBoxLayout, QWidget)

from grimoire.fsutil import human
from grimoire.glyphs import glyph
from grimoire.jobs import POOL, Job
from grimoire.spells.netl import probe, usage
from grimoire.spells.netl.usageview import UsagePanel
from grimoire.spells.netl.wifiview import WifiPanel
from grimoire.spells.systeml import system
from grimoire.spells.systeml.graph import SOFT, Graph
from grimoire.spells.systeml.page import NumItem, _label, _rate, _tree

PANELS = [("overview", "Overview", "net"), ("apps", "Apps", "grid"), ("conns", "Connections", "link"),
          ("wifi", "Wi-Fi && VPN", "wifi"), ("usage", "Usage history", "clock")]
RECORD_EVERY = 60            # seconds between writes to the usage file while open


class _Signals(QObject):
    sampled = Signal(object)
    acted = Signal(object)        # (what, message, ok, then, quiet)
    info = Signal(object)
    conns = Signal(object)
    check = Signal(object)        # (key, text)
    wifi = Signal(object)
    usage = Signal(object)
    timer = Signal(object)        # background recording on?


_icons: dict[str, QIcon | None] = {}
ICON_ALIASES = {"chrome": "google-chrome", "firefox-bin": "firefox", "steamwebhelper": "steam", "code": "vscode",
                "thunderbird-bin": "thunderbird"}


def app_icon(app: str) -> QIcon | None:
    """The app's theme icon turned gray, so the list stays black & white; None when the theme has none."""
    if app in _icons:
        return _icons[app]
    icon = None
    low = app.lower()
    for name in (ICON_ALIASES.get(low, low), low.split()[0] if low.split() else "", low.replace(" ", "-")):
        if name and QIcon.hasThemeIcon(name):
            src = QIcon.fromTheme(name).pixmap(32).toImage().convertToFormat(QImage.Format.Format_ARGB32)
            gray = src.convertToFormat(QImage.Format.Format_Grayscale8).convertToFormat(QImage.Format.Format_ARGB32)
            gray.setAlphaChannel(src.convertToFormat(QImage.Format.Format_Alpha8))
            icon = QIcon(QPixmap.fromImage(gray))
            break
    _icons[app] = icon
    return icon


def _row_item(texts, values, align_from=1) -> NumItem:
    it = NumItem(texts)
    for c, v in enumerate(values):
        it.setData(c, Qt.ItemDataRole.UserRole, v)
        if c >= align_from:
            it.setTextAlignment(c, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    return it


def _keep_selection(table, fill):
    """Refill a table while keeping its selected row (by first column) and scroll position."""
    sel = table.currentItem().text(0) if table.currentItem() else None
    scroll = table.verticalScrollBar().value()
    col, order = table.sortColumn(), table.header().sortIndicatorOrder()
    table.setSortingEnabled(False)
    table.clear()
    fill()
    table.setSortingEnabled(True)
    table.sortItems(col, order)
    if sel:
        hit = table.findItems(sel, Qt.MatchFlag.MatchExactly, 0)
        if hit:
            table.setCurrentItem(hit[0])
    table.verticalScrollBar().setValue(scroll)


# ---------------------------------------------------------------- overview
class OverviewPanel(QScrollArea):
    def __init__(self, page):
        super().__init__()
        self.page = page
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        inner = QWidget()
        inner.setObjectName("Page")
        col = QVBoxLayout(inner)
        col.setContentsMargins(0, 0, 12, 20)
        col.setSpacing(14)

        tiles = QHBoxLayout()
        tiles.setSpacing(12)
        self.tiles = {}
        for key, label in (("down", "Download"), ("up", "Upload"), ("today", "Today"), ("month", "This month")):
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
        col.addLayout(tiles)

        self.total = Graph("All traffic", fmt=_rate, top=None, labels=("↓", "↑"), two=True, height=190)
        col.addWidget(self.total)
        self.iface_grid = QGridLayout()
        self.iface_grid.setSpacing(12)
        self.iface_graphs: dict[str, Graph] = {}
        col.addLayout(self.iface_grid)

        head = QHBoxLayout()
        head.addWidget(_label("Addresses", "SectionTitle"))
        head.addStretch(1)
        refresh = QPushButton("Refresh")
        refresh.clicked.connect(self.load)
        head.addWidget(refresh)
        col.addLayout(head)
        self.addr = QGridLayout()
        self.addr.setHorizontalSpacing(24)
        self.addr.setVerticalSpacing(6)
        col.addLayout(self.addr)

        col.addWidget(_label("Checks", "SectionTitle"))
        col.addWidget(_label("Nothing here runs by itself: each check sends a few packets (or one web request for "
                             "the public IP) only when you press it.", "Muted", wrap=True))
        checks = QGridLayout()
        checks.setHorizontalSpacing(16)
        checks.setVerticalSpacing(8)
        self.check_labels = {}
        for i, (key, text) in enumerate((("public", "Show public IP"), ("gateway", "Ping gateway"),
                                         ("cloudflare", "Ping 1.1.1.1"))):
            b = QPushButton(text)
            b.clicked.connect(lambda _=False, k=key: self.run_check(k))
            lab = _label("", "Value")
            lab.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            checks.addWidget(b, i, 0)
            checks.addWidget(lab, i, 1)
            self.check_labels[key] = lab
        checks.setColumnStretch(1, 1)
        col.addLayout(checks)
        col.addStretch(1)
        self.setWidget(inner)
        self.gateway = ""
        page.sig.info.connect(self._fill_info)
        page.sig.check.connect(lambda r: self.check_labels[r[0]].setText(r[1]))

    def load(self):
        POOL.start(Job(lambda: (probe.addresses(), probe.gateways(), probe.dns()), self.page.sig.info.emit))

    def _fill_info(self, result):
        addrs, gws, servers = result
        while self.addr.count():
            w = self.addr.takeAt(0).widget()
            if w:
                w.deleteLater()
        row = 0

        def put(key, value, muted=False):
            nonlocal row
            self.addr.addWidget(_label(key.upper(), "StatLabel"), row, 0, Qt.AlignmentFlag.AlignTop)
            val = _label(value, "Muted" if muted else "", wrap=True)
            val.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            self.addr.addWidget(val, row, 1)
            row += 1
        for a in addrs:
            bits = [a["kind"], "up" if a["up"] else "down"]
            if a["up"] and a["speed"]:
                bits.append(f"{a['speed']} Mb/s" if a["speed"] < 1000 else f"{a['speed'] / 1000:g} Gb/s")
            lines = [" · ".join(bits)] + a["ipv4"] + a["ipv6"][:3] + ([f"MAC {a['mac']}"] if a["mac"] else [])
            put(a["name"], "\n".join(lines), muted=not a["up"])
        put("Gateway", "\n".join(f"{g}  ({dev})" for g, dev in gws) or "no default route")
        put("DNS", "\n".join(f"{s}  ({where})" for s, where in servers) or "none found")
        self.addr.setColumnStretch(1, 1)
        self.gateway = gws[0][0] if gws else ""

    def run_check(self, key: str):
        lab, sig = self.check_labels[key], self.page.sig
        if key == "public":
            lab.setText("asking…")

            def work():
                try:
                    return key, probe.public_ip()
                except Exception as err:
                    return key, f"couldn't tell: {err}"
        else:
            host = self.gateway if key == "gateway" else "1.1.1.1"
            if not host:
                lab.setText("no gateway (offline?)")
                return
            lab.setText(f"pinging {host}…")

            def work():
                r = probe.ping(host)
                if "error" in r:
                    return key, f"{host}: {r['error']}"
                return key, f"{host}: {r['avg']:.1f} ms average (min {r['min']:.1f}, max {r['max']:.1f}) · " \
                            f"{r['loss']:.0f}% lost"
        POOL.start(Job(work, sig.check.emit))

    def update_snap(self, s: dict):
        self.total.push(s["down"], s["up"])
        self.tiles["down"].setText(_rate(s["down"]))
        self.tiles["up"].setText(_rate(s["up"]))
        for name, i in s["ifaces"].items():
            g = self.iface_graphs.get(name)
            if g is None:
                g = Graph(f"{name} · {i['kind']}", fmt=_rate, top=None, labels=("↓", "↑"), two=True, height=130)
                n = len(self.iface_graphs)
                self.iface_grid.addWidget(g, n // 2, n % 2)
                self.iface_graphs[name] = g
            g.push(i["down"], i["up"], note=f"{human(i['rx'])} ↓ · {human(i['tx'])} ↑ since up")
        for name, g in self.iface_graphs.items():
            g.setVisible(name in s["ifaces"])

    def set_usage(self, data: dict):
        phys = usage.physical_set(data)
        for key, period, stamp in (("today", "days", "%Y-%m-%d"), ("month", "months", "%Y-%m")):
            rx, tx = usage.totals(data, period, time.strftime(stamp), phys)
            self.tiles[key].setText(human(rx + tx) if rx or tx else "–")
            self.tiles[key].setToolTip(f"↓ {human(rx)}   ↑ {human(tx)}")


# ---------------------------------------------------------------- apps
class AppsPanel(QWidget):
    def __init__(self, page):
        super().__init__()
        self.page = page
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)
        lay.addWidget(_label(
            "Per-app traffic from the kernel's own TCP counters, for your apps (no root needed). UDP has no per-socket "
            "counters, so QUIC (HTTP/3 in browsers), games and voice calls land in \"Not attributed\", along with "
            "packet headers and connections that closed between readings. Session totals count since NetL opened. "
            "Double-click an app to see its connections.", "Muted", wrap=True))
        self.table = _tree(["App", "Download", "Upload", "Session ↓", "Session ↑", "Connections"])
        h = self.table.header()
        h.setStretchLastSection(False)
        h.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for c in range(1, 6):
            h.resizeSection(c, 110)
        self.table.sortItems(1, Qt.SortOrder.DescendingOrder)
        self.table.itemDoubleClicked.connect(lambda it, _c: self.page.find_app(it.text(0)))
        lay.addWidget(self.table, 1)
        self.foot = _label("Measuring… the first reading sets the baseline.", "Muted", wrap=True)
        lay.addWidget(self.foot)

    def set_apps(self, a: dict, totals: dict, rest: tuple[float, float]):
        apps = a["apps"]

        def fill():
            names = set(apps) | {k for k, v in totals.items() if v[0] or v[1]}
            for name in names:
                cur = apps.get(name, {"down": 0.0, "up": 0.0, "conns": 0})
                tot = totals.get(name, [0, 0])
                it = _row_item([name, _rate(cur["down"]), _rate(cur["up"]), human(tot[0]), human(tot[1]),
                                str(cur["conns"]) if cur["conns"] else "–"],
                               [name.lower(), cur["down"], cur["up"], tot[0], tot[1], cur["conns"]])
                icon = app_icon(name) if name != probe.SYSTEM else glyph("net", 16)
                if icon:
                    it.setIcon(0, icon)
                self.table.addTopLevelItem(it)
        _keep_selection(self.table, fill)
        mine = sum(1 for n in apps if n != probe.SYSTEM)
        self.foot.setText(f"Not attributed right now: ↓ {_rate(rest[0])}  ↑ {_rate(rest[1])}   ·   {mine} app(s) "
                          "with connections · read every 2 s while this panel is open, every 10 s otherwise")


# ---------------------------------------------------------------- connections
class ConnsPanel(QWidget):
    def __init__(self, page):
        super().__init__()
        self.page = page
        self.rows: list[dict] = []
        self.names = probe.Names()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)
        bar = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Filter by app, address, port, host name or state")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.fill)
        bar.addWidget(self.search, 1)
        self.listening = QCheckBox("Listening")
        self.hosts = QCheckBox("Host names")
        self.hosts.setChecked(True)
        self.hosts.setToolTip("Looks up remote addresses' names (reverse DNS) in the background, once each")
        for c in (self.listening, self.hosts):
            c.toggled.connect(self.fill)
            bar.addWidget(c)
        lay.addLayout(bar)
        self.table = _tree(["Proto", "Local", "Remote", "Host", "State", "App", "PID"])
        h = self.table.header()
        h.setStretchLastSection(False)
        h.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        for c, w in ((0, 60), (1, 220), (2, 240), (4, 100), (5, 160), (6, 70)):
            h.resizeSection(c, w)
        self.table.sortItems(5, Qt.SortOrder.AscendingOrder)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.itemSelectionChanged.connect(self._sel)
        lay.addWidget(self.table, 1)
        acts = QHBoxLayout()
        self.info = _label("", "Muted")
        acts.addWidget(self.info, 1)
        self.copy_btn = QPushButton("Copy remote address")
        self.copy_btn.clicked.connect(self._copy)
        self.end_btn = QPushButton("End app")
        self.end_btn.setObjectName("Primary")
        self.end_btn.clicked.connect(self._end)
        acts.addWidget(self.copy_btn)
        acts.addWidget(self.end_btn)
        lay.addLayout(acts)
        self._busy = False
        page.sig.conns.connect(self.loaded)
        self._sel()

    def load(self):
        if self._busy:
            return
        self._busy = True

        def work():
            try:
                return probe.connections()
            except Exception:
                traceback.print_exc()
                return None
        POOL.start(Job(work, self.page.sig.conns.emit))

    def loaded(self, rows):
        self._busy = False
        if rows is not None:
            self.rows = rows
            self.fill()

    @staticmethod
    def _addr(host, port):
        return f"[{host}]:{port}" if ":" in host else f"{host}:{port}"

    def fill(self):
        q = self.search.text().lower().strip()
        shown, waiting = 0, False

        def fill():
            nonlocal shown, waiting
            for r in self.rows:
                if r["listen"] and not self.listening.isChecked():
                    continue
                host = ""
                if self.hosts.isChecked() and not r["listen"]:
                    name = self.names.get(r["remote"])
                    waiting |= name is None
                    host = name or ""
                app = r["app"] or ("system / other user" if not r["pid"] else r["pname"])
                remote = "" if r["listen"] else self._addr(r["remote"], r["rport"])
                local = self._addr(r["local"], r["lport"])
                state = "LISTEN" if r["listen"] else r["state"]
                if q and not any(q in t.lower() for t in (r["proto"], local, remote, host, state, app, str(r["pid"]))):
                    continue
                it = _row_item([r["proto"], local, remote, host, state, app, str(r["pid"]) if r["pid"] else ""],
                               [r["proto"], local, remote, host.lower(), state, app.lower(), r["pid"]], align_from=6)
                it.setData(0, Qt.ItemDataRole.UserRole + 1, r)
                if not r["pid"]:
                    it.setForeground(5, SOFT)
                self.table.addTopLevelItem(it)
                shown += 1
        _keep_selection(self.table, fill)
        self.count_text = f"{shown} of {len(self.rows)} sockets" + (" · looking up names…" if waiting else "")
        self._sel()

    def current(self) -> dict | None:
        it = self.table.currentItem()
        return it.data(0, Qt.ItemDataRole.UserRole + 1) if it else None

    def _sel(self):
        r = self.current()
        self.copy_btn.setEnabled(bool(r) and not r["listen"])
        guarded = bool(r) and system.is_protected(r["pname"])
        self.end_btn.setEnabled(bool(r) and bool(r["pid"]) and not guarded)
        if r and not r["pid"]:
            self.info.setText("Owned by a system service or another user: NetL can't tell which process, and "
                              "won't end it")
        elif r and guarded:
            self.info.setText(f"{r['pname']} keeps your session running, so it can't be ended from here")
        elif r:
            self.info.setText(f"{r['app']} · PID {r['pid']}")
        else:
            self.info.setText(getattr(self, "count_text", ""))

    def _copy(self):
        r = self.current()
        if r:
            QApplication.clipboard().setText(r["remote"])

    def _end(self):
        """SystemL's End process: TERM, checked against its protected list and the process start time."""
        r = self.current()
        if not r or not r["pid"] or system.is_protected(r["pname"]):
            return
        try:
            started = psutil.Process(r["pid"]).create_time()
        except psutil.Error:
            self.page.say(f"{r['app']}: already gone")
            return
        if QMessageBox.question(self, f"End {r['app']}", f"End {r['app']} (PID {r['pid']})? It gets the chance to "
                                "save and close.") != QMessageBox.StandardButton.Yes:
            return
        self.page.act(r["app"], lambda: system.send(r["pid"], "TERM", started), then=self.load)


# ---------------------------------------------------------------- the page
class NetLPage(QWidget):
    def __init__(self):
        super().__init__()
        self.setObjectName("Page")
        self.sig = _Signals()
        self.sampler = probe.Sampler()
        self._busy = False
        self._tick = 0
        self._last_record = time.monotonic()
        self._tcp_base: tuple[float, dict] | None = None      # interface bytes at the last per-app reading

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        nav = QFrame()
        nav.setObjectName("SubNav")
        nav.setFixedWidth(210)
        nl = QVBoxLayout(nav)
        nl.setContentsMargins(12, 26, 12, 16)
        nl.setSpacing(2)
        nl.addWidget(_label("NetL", "Title"))
        nl.addSpacing(12)
        nl.addWidget(_label("MONITOR", "NavSection"))
        self.nav = {}
        for pid, name, icon in PANELS:
            if pid == "wifi":
                nl.addSpacing(10)
                nl.addWidget(_label("CONTROL", "NavSection"))
            b = QPushButton(glyph(icon, 18), "  " + name)
            b.setObjectName("SubNavItem")
            b.setCheckable(True)
            b.clicked.connect(lambda _=False, p=pid: self.show_panel(p))
            nl.addWidget(b)
            self.nav[pid] = b
        nl.addStretch(1)
        self.foot = _label("", "Tiny")
        self.foot.setWordWrap(True)
        nl.addWidget(self.foot)
        root.addWidget(nav)

        right = QVBoxLayout()
        right.setContentsMargins(32, 26, 32, 18)
        right.setSpacing(14)
        self.heading = _label("", "PageHeading")
        right.addWidget(self.heading)
        self.stack = QStackedWidget()
        self.panels = {"overview": OverviewPanel(self), "apps": AppsPanel(self), "conns": ConnsPanel(self),
                       "wifi": WifiPanel(self), "usage": UsagePanel(self)}
        for p in self.panels.values():
            self.stack.addWidget(p)
        right.addWidget(self.stack, 1)
        self.toast = _label("", "Toast", wrap=True)
        self.toast.setTextFormat(Qt.TextFormat.PlainText)    # carries SSIDs and nmcli's messages
        self.toast.hide()
        right.addWidget(self.toast)
        self._toast_timer = QTimer(self, singleShot=True, interval=7000, timeout=self.toast.hide)
        root.addLayout(right, 1)

        self.sig.sampled.connect(self._sampled)
        self.sig.acted.connect(self._acted)
        self.sig.usage.connect(self._usage_loaded)
        self.timer = QTimer(self, interval=1000, timeout=self._sample)
        self.show_panel("overview")

    # ------------------------------------------------------------ sampling
    def showEvent(self, e):
        self.timer.start()
        self._sample()
        self.panels["overview"].load()
        self.load_usage()
        super().showEvent(e)

    def hideEvent(self, e):
        self.timer.stop()
        if not self._busy:                     # write what was measured; a sample in flight will do it next time
            self._busy = True
            sampler = self.sampler

            def work():
                self._record(sampler)
                return None
            POOL.start(Job(work, self.sig.sampled.emit))
        super().hideEvent(e)

    @staticmethod
    def _record(sampler):
        try:
            usage.record(sampler.apps.take_pending())
        except Exception:
            traceback.print_exc()

    def _sample(self):
        if self._busy:
            return
        self._busy = True
        self._tick += 1
        current = self.stack.currentWidget()
        on_apps = current is self.panels["apps"]
        with_tcp = self._tick % (2 if on_apps else 10) == 1 or self._tcp_base is None
        record = time.monotonic() - self._last_record >= RECORD_EVERY
        if record:
            self._last_record = time.monotonic()
        sampler, base = self.sampler, self._tcp_base

        def work():
            try:
                snap = sampler.sample(with_tcp=with_tcp)
                if with_tcp:                    # what the interfaces carried that no TCP socket accounts for
                    phys = {n: (i["rx"], i["tx"]) for n, i in snap["ifaces"].items() if i["physical"]}
                    now = time.monotonic()
                    if base and snap["apps"]["dt"]:
                        rx = sum(v[0] - base[1].get(n, v)[0] for n, v in phys.items())
                        tx = sum(v[1] - base[1].get(n, v)[1] for n, v in phys.items())
                        dt = now - base[0]
                        snap["rest"] = (max(0.0, (rx - snap["apps"]["down"]) / dt),
                                        max(0.0, (tx - snap["apps"]["up"]) / dt))
                    else:
                        snap["rest"] = (0.0, 0.0)
                    snap["tcp_base"] = (now, phys)
                    snap["totals"] = {k: list(v) for k, v in sampler.apps.totals.items()}
                if record:
                    self._record(sampler)
                    snap["usage"] = usage.load()
                return snap
            except Exception:                  # always answer, so _busy clears and the next tick tries again
                traceback.print_exc()
                return None
        POOL.start(Job(work, self.sig.sampled.emit))
        if current is self.panels["conns"] and self._tick % 3 == 1:
            self.panels["conns"].load()
        if current is self.panels["wifi"] and self._tick % 10 == 0:
            self.panels["wifi"].load()

    def _sampled(self, s):
        self._busy = False
        if s is None:
            return
        self.panels["overview"].update_snap(s)
        self.foot.setText(f"↓ {_rate(s['down'])}\n↑ {_rate(s['up'])}")
        if "apps" in s:
            self._tcp_base = s["tcp_base"]
            if not s["apps"]["first"]:
                self.panels["apps"].set_apps(s["apps"], s["totals"], s["rest"])
        if "usage" in s:
            self._usage_loaded(s["usage"])

    def load_usage(self):
        POOL.start(Job(usage.load, self.sig.usage.emit))

    def _usage_loaded(self, data):
        self.panels["overview"].set_usage(data)
        self.panels["usage"].set_data(data)

    # ------------------------------------------------------------ navigation
    def show_panel(self, pid: str):
        for p, b in self.nav.items():
            b.setChecked(p == pid)
        self.heading.setText(next(n for p, n, _ in PANELS if p == pid).replace("&&", "&"))
        panel = self.panels[pid]
        self.stack.setCurrentWidget(panel)
        if pid in ("conns", "wifi"):
            panel.load()
        elif pid == "usage":
            panel.load()

    def find_app(self, app: str):
        self.show_panel("conns")
        self.panels["conns"].search.setText("system / other user" if app == probe.SYSTEM else app)

    # ------------------------------------------------------------ actions
    def act(self, what: str, fn, then=None, quiet=False):
        """Run fn on the pool; report how it went in the toast, then call then() (e.g. reload a list)."""
        def work():
            try:
                return (what, fn() or "done", True, then, quiet)
            except Exception as err:                 # shown to the user, not a crash
                msg = str(err)
                return (what, "cancelled" if msg == "cancelled" else msg, False, then, quiet)
        POOL.start(Job(work, self.sig.acted.emit))

    def _acted(self, result):
        what, msg, ok, then, quiet = result
        if not ok or not quiet:
            self.say(f"{what}: {msg}" if ok else f"Couldn't change {what}: {msg}")
        if then:
            then()

    def say(self, text: str):
        self.toast.setText(text)
        self.toast.show()
        self._toast_timer.start()
