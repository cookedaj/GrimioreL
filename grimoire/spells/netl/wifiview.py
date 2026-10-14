"""NetL's Wi-Fi & VPN panel: the current connection, Wi-Fi and airplane-mode switches, networks in range (scanned
only when you press Scan), joining one (a black & white password prompt; see nm.py for how the key travels), and
a switch per VPN. Everything goes through NetworkManager as you, like Plasma's network applet.
"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QDialog, QFrame, QHBoxLayout, QHeaderView, QLineEdit, QMessageBox,
                               QPushButton, QScrollArea, QVBoxLayout, QWidget)

from grimoire.jobs import POOL, Job
from grimoire.spells.netl import nm, probe
from grimoire.spells.systeml.alertview import _row
from grimoire.spells.systeml.graph import Bar
from grimoire.spells.systeml.page import NumItem, _label, _tree
from grimoire.widgets import Switch


def snapshot(rescan=False) -> dict:
    """Everything the panel shows, read in one go on a worker thread."""
    if not nm.available():
        return {"missing": True}
    r = nm.radio()
    nets = nm.wifi_list(rescan) if r["wifi_hw"] and r["wifi"] else []
    prim = nm.primary()
    ips = {a["name"]: a["ipv4"] + a["ipv6"][:1] for a in probe.addresses()}
    return {"missing": False, "radio": r, "nets": nets, "saved": nm.saved_wifi() if nets else {},
            "primary": prim, "ips": ips.get(prim["device"], []) if prim else [], "vpns": nm.vpns(),
            "wifi_dev": nm.wifi_device()}


class PasswordDialog(QDialog):
    """Asks for a Wi-Fi password; the text only ever goes to nm.connect_wifi, never to a command line."""

    def __init__(self, parent, net: dict):
        super().__init__(parent)
        self.setWindowTitle(f"Join {net['ssid']}")
        self.setObjectName("Page")
        self.setMinimumWidth(420)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 22, 24, 18)
        lay.setSpacing(12)
        lay.addWidget(_label(net["ssid"], "RowTitle"))
        lay.addWidget(_label(f"{net['security'] or 'Open'} · signal {net['signal']}%. Enter the network's password.",
                             "Muted", wrap=True))
        self.edit = QLineEdit()
        self.edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.edit.setPlaceholderText("Password")
        lay.addWidget(self.edit)
        show = QCheckBox("Show password")
        show.toggled.connect(lambda on: self.edit.setEchoMode(QLineEdit.EchoMode.Normal if on
                                                              else QLineEdit.EchoMode.Password))
        lay.addWidget(show)
        btns = QHBoxLayout()
        btns.addStretch(1)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        self.ok = QPushButton("Connect")
        self.ok.setObjectName("Primary")
        self.ok.setDefault(True)
        self.ok.clicked.connect(self.accept)
        btns.addWidget(cancel)
        btns.addWidget(self.ok)
        lay.addLayout(btns)
        mgmt = nm.key_mgmt(net["security"])
        need = 8 if mgmt in ("wpa-psk", "sae") else 1      # WPA keys are 8 to 63 characters
        self.edit.textChanged.connect(lambda t: self.ok.setEnabled(need <= len(t) <= 63 or mgmt == "sae"
                                                                   and len(t) >= 1))
        self.ok.setEnabled(False)

    def password(self) -> str:
        return self.edit.text()


class WifiPanel(QScrollArea):
    def __init__(self, page):
        super().__init__()
        self.page = page
        self.data: dict = {}
        self._busy = False
        self._quiet = False                       # set while the switches are moved to match NetworkManager
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        inner = QWidget()
        inner.setObjectName("Page")
        col = QVBoxLayout(inner)
        col.setContentsMargins(0, 0, 12, 20)
        col.setSpacing(12)

        card = QFrame()
        card.setObjectName("Row")
        cl = QVBoxLayout(card)
        cl.setContentsMargins(20, 16, 20, 16)
        cl.setSpacing(6)
        top = QHBoxLayout()
        self.cur_name = _label("–", "RowTitle")
        self.cur_badge = _label("", "Badge")
        top.addWidget(self.cur_name)
        top.addWidget(self.cur_badge)
        top.addStretch(1)
        self.disc_btn = QPushButton("Disconnect")
        self.disc_btn.clicked.connect(self._disconnect)
        top.addWidget(self.disc_btn)
        cl.addLayout(top)
        self.cur_info = _label("", "Muted", wrap=True)
        self.cur_info.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        cl.addWidget(self.cur_info)
        self.signal = Bar()
        cl.addWidget(self.signal)
        col.addWidget(card)

        self.wifi_sw, self.air_sw = Switch(), Switch()
        self.wifi_sub = _label("", "Muted", wrap=True)
        self.air_sub = _label("Turns off Wi-Fi, mobile broadband and Bluetooth. Wired connections keep working.",
                              "Muted", wrap=True)
        col.addWidget(_row("Wi-Fi", self.wifi_sub, self.wifi_sw))
        col.addWidget(_row("Airplane mode", self.air_sub, self.air_sw))
        self.wifi_sw.toggled.connect(self._wifi)
        self.air_sw.toggled.connect(self._airplane)

        head = QHBoxLayout()
        head.addWidget(_label("Networks", "SectionTitle"))
        head.addStretch(1)
        self.scan_btn = QPushButton("Scan")
        self.scan_btn.setToolTip("Asks the Wi-Fi card to look for networks again (takes a few seconds)")
        self.scan_btn.clicked.connect(lambda: self.load(rescan=True))
        self.join_btn = QPushButton("Connect")
        self.join_btn.setObjectName("Primary")
        self.join_btn.clicked.connect(self._join)
        head.addWidget(self.scan_btn)
        head.addWidget(self.join_btn)
        col.addLayout(head)
        self.nets = _tree(["Network", "Signal", "Security", "Channel", ""])
        h = self.nets.header()
        h.setStretchLastSection(False)
        h.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for c, w in ((1, 90), (2, 140), (3, 90), (4, 120)):
            h.resizeSection(c, w)
        self.nets.setMinimumHeight(240)
        self.nets.itemSelectionChanged.connect(self._sel)
        self.nets.itemDoubleClicked.connect(lambda *_: self._join())
        col.addWidget(self.nets)

        col.addWidget(_label("VPN", "SectionTitle"))
        self.vpn_box = QVBoxLayout()
        self.vpn_box.setSpacing(8)
        col.addLayout(self.vpn_box)
        col.addStretch(1)
        self.setWidget(inner)
        page.sig.wifi.connect(self.loaded)
        self._sel()

    # ------------------------------------------------------------ loading
    def load(self, rescan=False):
        if self._busy:
            return
        self._busy = True
        if rescan:
            self.scan_btn.setText("Scanning…")
        POOL.start(Job(lambda: snapshot(rescan), self.page.sig.wifi.emit))

    def loaded(self, d: dict):
        self._busy = False
        self.scan_btn.setText("Scan")
        self.data = d
        if d.get("missing"):
            self.cur_name.setText("NetworkManager isn't available")
            self.cur_info.setText("nmcli wasn't found, so NetL can only monitor here.")
            for w in (self.wifi_sw, self.air_sw, self.scan_btn, self.join_btn, self.disc_btn):
                w.setEnabled(False)
            return
        r, prim = d["radio"], d["primary"]
        self._quiet = True
        self.wifi_sw.setChecked(r["wifi"])
        self.wifi_sw.setEnabled(r["wifi_hw"])
        self.air_sw.setChecked(nm.airplane(r))
        self._quiet = False
        self.wifi_sub.setText("No Wi-Fi card found (or it's switched off by a hardware key)." if not r["wifi_hw"]
                              else f"{len(d['nets'])} network(s) in range" if r["wifi"] else "Off")
        wifi_net = next((n for n in d["nets"] if n["active"]), None)
        if prim:
            kind = {"wifi": "Wi-Fi", "ethernet": "Wired", "gsm": "Mobile"}.get(prim["type"], prim["type"])
            self.cur_name.setText(prim["connection"])
            self.cur_badge.setText(kind.upper())
            self.cur_badge.show()
            bits = [prim["device"]] + d["ips"]
            if wifi_net and prim["type"] == "wifi":
                bits[1:1] = [f"signal {wifi_net['signal']}%", wifi_net["security"] or "open",
                             f"channel {wifi_net['chan']}", wifi_net["rate"]]
            self.cur_info.setText("  ·  ".join(b for b in bits if b))
        else:
            self.cur_name.setText("Not connected")
            self.cur_badge.hide()
            self.cur_info.setText("Pick a network below, or plug in a cable.")
        self.signal.setVisible(bool(wifi_net and prim and prim["type"] == "wifi"))
        self.signal.set((wifi_net["signal"] if wifi_net else 0) / 100)
        self.disc_btn.setEnabled(bool(prim))

        sel = self.nets.currentItem().text(0) if self.nets.currentItem() else None
        self.nets.setSortingEnabled(False)
        self.nets.clear()
        for n in d["nets"]:
            saved = n["ssid"] in d["saved"]
            tag = "Connected" if n["active"] else "Saved" if saved else ""
            it = NumItem([n["ssid"], f"{n['signal']}%", n["security"] or "Open", n["chan"], tag])
            for c, v in enumerate([n["ssid"].lower(), n["signal"], n["security"], int(n["chan"] or 0), tag]):
                it.setData(c, Qt.ItemDataRole.UserRole, v)
            it.setData(0, Qt.ItemDataRole.UserRole + 1, n)
            it.setTextAlignment(1, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.nets.addTopLevelItem(it)
        self.nets.setSortingEnabled(True)
        self.nets.sortItems(1, Qt.SortOrder.DescendingOrder)
        if sel:
            hit = self.nets.findItems(sel, Qt.MatchFlag.MatchExactly, 0)
            if hit:
                self.nets.setCurrentItem(hit[0])
        self._sel()
        self._fill_vpns(d["vpns"])

    def _fill_vpns(self, vpns: list[dict]):
        while self.vpn_box.count():
            w = self.vpn_box.takeAt(0).widget()
            if w:
                w.deleteLater()
        if not vpns:
            self.vpn_box.addWidget(_label("No VPN connections set up. Add one (OpenVPN, WireGuard, …) in System "
                                          "Settings > Wi-Fi & Internet; it shows up here with a switch.", "Muted",
                                          wrap=True))
            return
        for v in vpns:
            sw = Switch()
            sw.setChecked(v["active"])
            kind = "WireGuard" if v["type"] == "wireguard" else "VPN"
            sub = _label(f"{kind} · " + (f"connected on {v['device']}" if v["active"] else "off"), "Muted")
            sw.toggled.connect(lambda on, v=v: self.page.act(v["name"], lambda: nm.set_vpn(v["uuid"], on),
                                                             then=self.load))
            self.vpn_box.addWidget(_row(v["name"], sub, sw))

    # ------------------------------------------------------------ actions
    def current(self) -> dict | None:
        it = self.nets.currentItem()
        return it.data(0, Qt.ItemDataRole.UserRole + 1) if it else None

    def _sel(self):
        n = self.current()
        self.join_btn.setEnabled(bool(n) and not n["active"])

    def _join(self):
        n = self.current()
        if not n or n["active"]:
            return
        saved = self.data.get("saved", {}).get(n["ssid"])
        password = None
        if not saved and n["security"]:
            if nm.key_mgmt(n["security"]) is None:
                self.page.say(f"{n['ssid']} uses {n['security']}: join it from Plasma's network settings")
                return
            dlg = PasswordDialog(self, n)
            if dlg.exec() != QDialog.DialogCode.Accepted:
                return
            password = dlg.password()
            dlg.edit.clear()
        self.page.say(f"Connecting to {n['ssid']}…")
        self.page.act(n["ssid"], lambda: nm.connect_wifi(n, password, saved), then=self.load)

    def _disconnect(self):
        prim = self.data.get("primary")
        if prim and QMessageBox.question(self, "Disconnect", f"Disconnect {prim['connection']}? You'll be offline "
                                         "until you connect again.") == QMessageBox.StandardButton.Yes:
            self.page.act(prim["connection"], lambda: nm.disconnect(prim["device"]), then=self.load)

    def _wifi(self, on: bool):
        if self._quiet:
            return
        prim = self.data.get("primary")
        if not on and prim and prim["type"] == "wifi" and QMessageBox.question(
                self, "Wi-Fi", f"Turn Wi-Fi off? You're online through {prim['connection']}.") \
                != QMessageBox.StandardButton.Yes:
            self._reset()
            return
        self.page.act("Wi-Fi", lambda: nm.set_wifi(on), then=self.load)

    def _airplane(self, on: bool):
        if self._quiet:
            return
        if on and QMessageBox.question(self, "Airplane mode", "Turn on airplane mode? Wi-Fi, mobile broadband and "
                                       "Bluetooth go off.") != QMessageBox.StandardButton.Yes:
            self._reset()
            return
        self.page.act("Airplane mode", lambda: nm.set_airplane(on), then=self.load)

    def _reset(self):
        """Put the switches back where NetworkManager has them."""
        if self.data.get("radio"):
            self._quiet = True
            self.wifi_sw.setChecked(self.data["radio"]["wifi"])
            self.air_sw.setChecked(nm.airplane(self.data["radio"]))
            self._quiet = False
