"""NetL's quick controls: NetworkManager through nmcli (current connection, Wi-Fi networks, radios, VPNs).

Everything here is a short nmcli call meant for a worker thread. Reads use nmcli's terse output (-t: fields split
by ':', a literal ':' escaped as '\\:'). Writes are the same things Plasma's network applet does, as you, through
NetworkManager's own permissions (no root, no pkexec).

Wi-Fi passwords never go on a command line (where any user could read them in /proc/<pid>/cmdline): a new network
gets a profile without its key, then `nmcli connection up … passwd-file F`, where F is a 0600 file created fresh in
$XDG_RUNTIME_DIR (a per-user tmpfs, so it never touches the disk) and removed as soon as nmcli returns. nmcli hands
the key to NetworkManager over D-Bus, which stores it in the profile like Plasma does.
"""
import os
import re
import secrets
import shutil
import subprocess
from pathlib import Path

RUN = subprocess.run          # tests swap this for a stub, so nothing really changes the network
VPN_TYPES = {"vpn", "wireguard"}
SKIP_DEVICES = {"loopback", "bridge", "tun", "wifi-p2p", "dummy", "veth"}


def available() -> bool:
    return shutil.which("nmcli") is not None


def split(line: str) -> list[str]:
    """One line of `nmcli -t` output as fields (undoing its \\: and \\\\ escapes)."""
    out, cur, esc = [], [], False
    for ch in line:
        if esc:
            cur.append(ch)
            esc = False
        elif ch == "\\":
            esc = True
        elif ch == ":":
            out.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    out.append("".join(cur))
    return out


def _nmcli(*args: str, timeout=20) -> subprocess.CompletedProcess:
    try:
        return RUN(["nmcli", *args], capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as err:
        return subprocess.CompletedProcess(args, 1, "", str(err))


def _rows(*args: str, n: int) -> list[list[str]]:
    r = _nmcli("-t", *args)
    return [f for f in (split(l) for l in r.stdout.splitlines() if l) if len(f) >= n] if r.returncode == 0 else []


def _check(r: subprocess.CompletedProcess, what: str) -> str:
    if r.returncode:
        msg = (r.stderr or r.stdout).strip().splitlines()
        raise RuntimeError((msg[-1].removeprefix("Error: ") if msg else f"{what} failed ({r.returncode})"))
    return "done"


# ---------------------------------------------------------------- reads
def devices() -> list[dict]:
    return [{"device": d, "type": t, "state": s, "connection": c}
            for d, t, s, c in _rows("-f", "DEVICE,TYPE,STATE,CONNECTION", "device", n=4)]


def primary() -> dict | None:
    """The connection that carries your traffic: the first connected device that isn't a bridge or loopback."""
    for d in devices():
        if d["state"] == "connected" and d["type"] not in SKIP_DEVICES and d["type"] not in VPN_TYPES:
            return d
    return None


def radio() -> dict:
    """{'wifi_hw', 'wifi', 'wwan_hw', 'wwan'}: True when enabled ('missing' hardware reads False)."""
    rows = _rows("-f", "WIFI-HW,WIFI,WWAN-HW,WWAN", "radio", n=4)
    vals = [v == "enabled" for v in rows[0]] if rows else [False] * 4
    return dict(zip(("wifi_hw", "wifi", "wwan_hw", "wwan"), vals))


def airplane(r: dict | None = None) -> bool:
    """Airplane mode as NetworkManager sees it: Wi-Fi and mobile radios both off."""
    r = r or radio()
    return not r["wifi"] and not r["wwan"]


def connections() -> list[dict]:
    return [{"name": n, "uuid": u, "type": t, "active": a == "yes", "device": d}
            for n, u, t, a, d in _rows("-f", "NAME,UUID,TYPE,ACTIVE,DEVICE", "connection", "show", n=5)]


def vpns() -> list[dict]:
    return [c for c in connections() if c["type"] in VPN_TYPES]


def saved_wifi() -> dict[str, str]:
    """{SSID: profile uuid} for the Wi-Fi networks you've joined before."""
    out = {}
    for c in connections():
        if c["type"] == "802-11-wireless":
            r = _nmcli("-g", "802-11-wireless.ssid", "connection", "show", "uuid", c["uuid"])
            ssid = r.stdout.strip().replace("\\:", ":") if r.returncode == 0 else ""
            out.setdefault(ssid or c["name"], c["uuid"])
    return out


def wifi_list(rescan=False) -> list[dict]:
    """Networks in range, strongest access point per name. rescan asks the card to look again (a few seconds)."""
    rows = _rows("-f", "IN-USE,SSID,BSSID,SIGNAL,SECURITY,CHAN,FREQ,RATE,DEVICE", "device", "wifi", "list",
                 "--rescan", "yes" if rescan else "no", n=9)
    best: dict[str, dict] = {}
    for inuse, ssid, bssid, signal, sec, chan, freq, rate, dev in rows:
        if not ssid:
            continue                                     # hidden networks: join them from Plasma's applet
        net = {"ssid": ssid, "bssid": bssid, "signal": int(signal) if signal.isdigit() else 0,
               "security": "" if sec in ("", "--") else sec, "chan": chan, "freq": freq, "rate": rate,
               "device": dev, "active": inuse == "*"}
        old = best.get(ssid)
        if old is None or net["active"] or (net["signal"] > old["signal"] and not old["active"]):
            best[ssid] = net
    return sorted(best.values(), key=lambda n: (not n["active"], -n["signal"]))


def wifi_device() -> str:
    return next((d["device"] for d in devices() if d["type"] == "wifi"), "")


# ---------------------------------------------------------------- writes
def key_mgmt(security: str) -> str | None:
    """The profile key type for a network's security string; None when NetL can't join it (enterprise, WEP)."""
    s = security.upper()
    if not s:
        return "none"
    if "802.1X" in s or "WEP" in s:
        return None
    if "WPA3" in s and "WPA2" not in s and "WPA1" not in s:
        return "sae"
    return "wpa-psk"


def _secret_file(password: str) -> Path:
    """A 0600 file in the per-user runtime dir (tmpfs) holding the key in nmcli's passwd-file format."""
    base = Path(os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}")
    path = base / f"grimoire-netl-{secrets.token_hex(8)}"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(f"802-11-wireless-security.psk:{password}\n")
    return path


def _up_with_key(uuid: str, password: str) -> subprocess.CompletedProcess:
    path = _secret_file(password)
    try:
        return _nmcli("connection", "up", "uuid", uuid, "passwd-file", str(path), timeout=60)
    finally:
        path.unlink(missing_ok=True)


def connect_wifi(net: dict, password: str | None = None, saved_uuid: str | None = None) -> str:
    """Join a network: a saved one by its profile (with a new key if given), an open one directly, a protected
    new one through a fresh profile + passwd-file. A new profile that fails to connect is removed again."""
    if saved_uuid:
        r = _up_with_key(saved_uuid, password) if password else _nmcli("connection", "up", "uuid", saved_uuid,
                                                                       timeout=60)
        return _check(r, "connect") and f"connected to {net['ssid']}"
    mgmt = key_mgmt(net["security"])
    if mgmt is None:
        raise RuntimeError(f"{net['security']} networks need Plasma's network settings")
    dev = ["ifname", net["device"]] if net.get("device") else []
    if mgmt == "none":
        _check(_nmcli("device", "wifi", "connect", net["ssid"], *dev, timeout=60), "connect")
        return f"connected to {net['ssid']}"
    if not password:
        raise RuntimeError("this network needs a password")
    r = _nmcli("connection", "add", "type", "wifi", "con-name", net["ssid"], "ssid", net["ssid"],
               *dev, "wifi-sec.key-mgmt", mgmt)
    _check(r, "create profile")
    uuid = _new_uuid(r.stdout)
    if not uuid:
        raise RuntimeError("NetworkManager didn't say which profile it made")
    r = _up_with_key(uuid, password)
    if r.returncode:
        _nmcli("connection", "delete", "uuid", uuid)      # a profile NetL just made, with a key that didn't work
    return _check(r, "connect") and f"connected to {net['ssid']}"


def _new_uuid(out: str) -> str:
    """nmcli prints "Connection 'X' (uuid) successfully added."; pull the uuid out of the parentheses."""
    m = re.search(r"\(([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\)", out)
    return m.group(1) if m else ""


def disconnect(device: str) -> str:
    return _check(_nmcli("device", "disconnect", device), "disconnect") and f"{device} disconnected"


def set_wifi(on: bool) -> str:
    _check(_nmcli("radio", "wifi", "on" if on else "off"), "Wi-Fi")
    return "Wi-Fi on" if on else "Wi-Fi off"


def set_airplane(on: bool) -> str:
    """Every radio NetworkManager handles, plus Bluetooth through rfkill (Plasma's desktop session gives you
    access to /dev/rfkill; when it doesn't, Bluetooth is simply left as it is)."""
    _check(_nmcli("radio", "all", "off" if on else "on"), "airplane mode")
    if shutil.which("rfkill"):
        try:
            RUN(["rfkill", "block" if on else "unblock", "bluetooth"], capture_output=True, timeout=10)
        except (OSError, subprocess.TimeoutExpired):
            pass
    return "airplane mode on" if on else "airplane mode off"


def set_vpn(uuid: str, on: bool) -> str:
    """Up asks for the VPN's secrets through Plasma's own prompt when it needs them."""
    _check(_nmcli("connection", "up" if on else "down", "uuid", uuid, timeout=90), "VPN")
    return "connected" if on else "disconnected"
