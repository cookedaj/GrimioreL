# SPDX-License-Identifier: GPL-3.0-or-later
"""NetL's readings: interface counters and rates, addresses, gateway and DNS, sockets from `ss`, per-app TCP
bandwidth, and the on-demand checks (latency, public IP).

Per-app bandwidth without root, nethogs-style but from the kernel's own per-socket counters: `ss -tinpe` lists every
TCP socket with its inode, the processes holding it (ss reads /proc/<pid>/fd, which works for your own processes)
and TCP's byte counters (bytes_received; bytes_acked for what really left, without retransmits). AppMeter keeps the
previous counters per inode and diffs them between samples. What that misses, and why:
  - UDP: the kernel keeps no per-socket byte counts for it, so QUIC (HTTP/3 in browsers), games and voice calls
    can't be split per app without root (pcap or eBPF). That traffic shows as "Not attributed".
  - Sockets of other users and system services: their counters are visible but not who owns them, so they add up
    under "System & other users".
  - The last bytes of a connection that closes between two samples.
Loopback sockets (127.0.0.1, ::1) never leave the machine and are left out.
"""
import ipaddress
import json
import re
import socket
import subprocess
import time
import urllib.request
from pathlib import Path

import psutil

from grimoire.spells.systeml.probe import app_name

SYS = Path("/sys/class/net")
VIRTUAL = ("veth", "docker", "br-", "virbr", "vnet", "vmnet", "lxc", "cni", "flannel")
_USERS = re.compile(r'\("((?:[^"\\]|\\.)*)",pid=(\d+),fd=\d+\)')
SYSTEM = "System & other users"


# ---------------------------------------------------------------- interfaces
def kind(name: str) -> str:
    d = SYS / name
    if name == "lo":
        return "Loopback"
    if (d / "wireless").exists() or (d / "phy80211").exists():
        return "Wi-Fi"
    if name.startswith(("wg", "tun", "tap", "ppp", "tailscale", "proton", "nordlynx", "mullvad")) \
            or (d / "tun_flags").exists():
        return "VPN"
    if (d / "bridge").exists() or name.startswith(VIRTUAL):
        return "Virtual"
    if (d / "device").exists():
        return "Ethernet" if not name.startswith("ww") else "Mobile"
    return "Other"


def physical(name: str) -> bool:
    """Real hardware: totals add these only, so a VPN (whose traffic also crosses the card) and VM bridges
    aren't counted twice."""
    return name != "lo" and (SYS / name / "device").exists()


def shown(name: str) -> bool:
    return name != "lo" and not name.startswith(VIRTUAL)


def counters() -> dict[str, tuple[int, int]]:
    """{interface: (bytes received, bytes sent)} since it came up."""
    return {n: (c.bytes_recv, c.bytes_sent) for n, c in psutil.net_io_counters(pernic=True).items()}


class Sampler:
    """Interface rates from the previous sample, like SystemL's; the first sample reads zero. One sample at a
    time (the page runs it on the pool behind a busy flag)."""

    def __init__(self):
        self.prev: tuple[float, dict] | None = None
        self.apps = AppMeter()

    def sample(self, with_tcp=False) -> dict:
        now, cur = time.monotonic(), counters()
        prev, self.prev = self.prev, (now, cur)
        dt = now - prev[0] if prev else 0.0
        ifaces = {}
        for name, (rx, tx) in cur.items():
            if not shown(name):
                continue
            old = prev[1].get(name) if prev else None
            down = max(0.0, (rx - old[0]) / dt) if old and dt else 0.0
            up = max(0.0, (tx - old[1]) / dt) if old and dt else 0.0
            ifaces[name] = {"down": down, "up": up, "rx": rx, "tx": tx, "kind": kind(name),
                            "physical": physical(name)}
        phys = [i for i in ifaces.values() if i["physical"]] or list(ifaces.values())
        snap = {"time": time.time(), "dt": dt, "ifaces": ifaces,
                "down": sum(i["down"] for i in phys), "up": sum(i["up"] for i in phys)}
        if with_tcp:
            snap["apps"] = self.apps.update(tcp_sockets())
        return snap


# ---------------------------------------------------------------- addresses
def addresses() -> list[dict]:
    """Each shown interface with its state, speed, MAC and addresses (global IPv6 first, link-local last)."""
    stats, out = psutil.net_if_stats(), []
    for name, addrs in psutil.net_if_addrs().items():
        if not shown(name):
            continue
        st = stats.get(name)
        v4 = [a.address for a in addrs if a.family == socket.AF_INET]
        v6 = sorted((a.address.split("%")[0] for a in addrs if a.family == socket.AF_INET6),
                    key=lambda a: a.startswith("fe80"))
        mac = next((a.address for a in addrs if a.family == psutil.AF_LINK), "")
        out.append({"name": name, "kind": kind(name), "up": bool(st and st.isup), "speed": st.speed if st else 0,
                    "mtu": st.mtu if st else 0, "ipv4": v4, "ipv6": v6, "mac": mac})
    return sorted(out, key=lambda a: (not a["up"], not a["ipv4"], a["name"]))


def gateways() -> list[tuple[str, str]]:
    """[(gateway, interface)] for the default routes, IPv4 first."""
    out = []
    for fam in ("-4", "-6"):
        try:
            r = subprocess.run(["ip", "-j", fam, "route", "show", "default"], capture_output=True, text=True,
                               timeout=5)
            for route in json.loads(r.stdout or "[]"):
                if route.get("gateway"):
                    out.append((route["gateway"], route.get("dev", "")))
        except (OSError, ValueError, subprocess.TimeoutExpired):
            pass
    return out


def dns() -> list[tuple[str, str]]:
    """[(server, where)]: the real upstream servers from systemd-resolved, else /etc/resolv.conf."""
    out = []
    try:
        r = subprocess.run(["resolvectl", "dns"], capture_output=True, text=True, timeout=5)
        for line in r.stdout.splitlines():
            where, _, servers = line.partition(":")
            m = re.search(r"\((.+)\)", where)
            for s in servers.split():
                out.append((s, m.group(1) if m else where.strip()))
    except (OSError, subprocess.TimeoutExpired):
        pass
    if not out:
        try:
            for line in Path("/etc/resolv.conf").read_text().splitlines():
                if line.startswith("nameserver"):
                    out.append((line.split()[1], "resolv.conf"))
        except (OSError, IndexError):
            pass
    return out


# ---------------------------------------------------------------- sockets
def _addr(text: str) -> tuple[str, str]:
    """'192.168.1.5%eth0:443' or '[2600::1]:443' -> (host, port)."""
    host, _, port = text.rpartition(":")
    host = host.strip("[]").split("%")[0]
    return host, port


def _loopback(host: str) -> bool:
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return host in ("localhost", "*")


def _ss(args: list[str]) -> str:
    try:
        return subprocess.run(["ss", *args], capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.TimeoutExpired):
        return ""


def _procs(rest: str) -> list[tuple[str, int]]:
    return [(n.replace('\\"', '"'), int(p)) for n, p in _USERS.findall(rest)]


def _num(rest: str, key: str) -> int:
    m = re.search(rf"\b{key}:(\d+)", rest)
    return int(m.group(1)) if m else 0


def parse_tcp(text: str) -> list[dict]:
    """`ss -tinpeH` output: one line per socket, then a tab-indented line with its TCP info."""
    socks, cur = [], None
    for line in text.splitlines():
        if line.startswith(("\t", " ")) and cur is not None:
            cur["rx"] = _num(line, "bytes_received")
            cur["tx"] = _num(line, "bytes_acked")
            continue
        f = line.split(None, 5)
        if len(f) < 5:
            cur = None
            continue
        rest = f[5] if len(f) > 5 else ""
        lh, lp = _addr(f[3])
        rh, rp = _addr(f[4])
        cur = {"state": f[0], "local": (lh, lp), "remote": (rh, rp), "ino": _num(rest, "ino"),
               "procs": _procs(rest), "rx": 0, "tx": 0}
        if not (_loopback(lh) and _loopback(rh)):
            socks.append(cur)
    return socks


def tcp_sockets() -> list[dict]:
    return parse_tcp(_ss(["-tinpeH"]))


def parse_all(text: str) -> list[dict]:
    """`ss -tuanpeH` output: every TCP/UDP socket, listening ones included."""
    rows = []
    for line in text.splitlines():
        f = line.split(None, 6)
        if len(f) < 6 or f[0] not in ("tcp", "udp"):
            continue
        rest = f[6] if len(f) > 6 else ""
        lh, lp = _addr(f[4])
        rh, rp = _addr(f[5])
        procs = _procs(rest)
        rows.append({"proto": f[0].upper(), "state": f[1], "local": lh, "lport": lp, "remote": rh, "rport": rp,
                     "listen": f[1] in ("LISTEN", "UNCONN") and rh in ("*", "0.0.0.0", "::"),
                     "ino": _num(rest, "ino"), "uid": _num(rest, "uid") if "uid:" in rest else None,
                     "pid": procs[0][1] if procs else 0, "pname": procs[0][0] if procs else ""})
    return rows


def connections() -> list[dict]:
    """Every socket with its process (yours) and app name."""
    rows = parse_all(_ss(["-tuanpeH"]))
    for r in rows:
        r["app"] = app_of(r["pid"], r["pname"]) if r["pid"] else ""
    return rows


_apps: dict[int, tuple[float, str]] = {}


def app_of(pid: int, comm: str) -> str:
    """The app a process counts under (SystemL's rule: the executable's name, so browser helpers count towards the
    browser), cached per process start time so a reused PID is looked up again."""
    try:
        p = psutil.Process(pid)
        started = p.create_time()
        hit = _apps.get(pid)
        if hit and hit[0] == started:
            return hit[1]
        try:
            exe = p.exe()
        except (psutil.AccessDenied, psutil.ZombieProcess):
            exe = ""
        name = app_name({"exe": exe, "name": p.name() or comm})
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return comm
    if len(_apps) > 2000:
        _apps.clear()
    _apps[pid] = (started, name)
    return name


class AppMeter:
    """Per-app TCP rates and session totals from per-socket counters (see the module docstring)."""

    def __init__(self):
        self.prev: dict[int, tuple[int, int]] = {}
        self.t: float | None = None
        self.totals: dict[str, list[int]] = {}      # app -> [down, up] since NetL opened
        self.pending: dict[str, list[int]] = {}     # app -> [down, up] not yet written to the usage file

    def update(self, socks: list[dict]) -> dict:
        now = time.monotonic()
        first, dt = self.t is None, now - self.t if self.t else 0.0
        self.t = now
        apps: dict[str, dict] = {}
        seen = {}
        for s in socks:
            key = s["ino"] or hash((s["local"], s["remote"]))
            seen[key] = (s["rx"], s["tx"])
            old = self.prev.get(key)
            if first:
                drx = dtx = 0                        # a baseline: counts from before NetL opened aren't a rate
            elif old is None or s["rx"] < old[0] or s["tx"] < old[1]:
                drx, dtx = s["rx"], s["tx"]          # opened since the last sample (or the inode was reused)
            else:
                drx, dtx = s["rx"] - old[0], s["tx"] - old[1]
            if s["procs"]:
                name, pid = s["procs"][0]
                app = app_of(pid, name)
            else:
                app, pid = SYSTEM, 0
            a = apps.setdefault(app, {"app": app, "down": 0.0, "up": 0.0, "conns": 0, "pids": set(),
                                      "bytes": [0, 0]})
            a["bytes"][0] += drx
            a["bytes"][1] += dtx
            a["conns"] += 1
            if pid:
                a["pids"].add(pid)
        self.prev = seen
        for a in apps.values():
            a["down"] = a["bytes"][0] / dt if dt else 0.0
            a["up"] = a["bytes"][1] / dt if dt else 0.0
            for bucket in (self.totals, self.pending):
                b = bucket.setdefault(a["app"], [0, 0])
                b[0] += a["bytes"][0]
                b[1] += a["bytes"][1]
        return {"apps": apps, "dt": dt, "first": first,
                "down": sum(a["bytes"][0] for a in apps.values()), "up": sum(a["bytes"][1] for a in apps.values())}

    def take_pending(self) -> dict[str, list[int]]:
        out, self.pending = self.pending, {}
        return {k: v for k, v in out.items() if v[0] or v[1]}


# ---------------------------------------------------------------- on-demand checks
def ping(host: str, count=4) -> dict:
    """{'host', 'avg', 'min', 'max', 'loss'} in ms / %; 'error' when it got no answer."""
    try:
        r = subprocess.run(["ping", "-n", "-q", "-c", str(count), "-i", "0.25", "-W", "2", host],
                           capture_output=True, text=True, timeout=count * 3 + 5)
    except (OSError, subprocess.TimeoutExpired) as err:
        return {"host": host, "error": str(err)}
    loss = re.search(r"([\d.]+)% packet loss", r.stdout)
    rtt = re.search(r"= ([\d.]+)/([\d.]+)/([\d.]+)/", r.stdout)
    if not rtt:
        return {"host": host, "error": "no answer" if loss else (r.stderr.strip() or "ping failed"),
                "loss": float(loss.group(1)) if loss else 100.0}
    return {"host": host, "min": float(rtt.group(1)), "avg": float(rtt.group(2)), "max": float(rtt.group(3)),
            "loss": float(loss.group(1)) if loss else 0.0}


PUBLIC_IP = ("https://api.ipify.org", "https://icanhazip.com")


def public_ip() -> str:
    """Your address as the internet sees it: asks a public echo service, only when you press the button."""
    last = "no answer"
    for url in PUBLIC_IP:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Grimoire-NetL"})
            with urllib.request.urlopen(req, timeout=6) as r:
                text = r.read(100).decode().strip()
            return str(ipaddress.ip_address(text))
        except (OSError, ValueError) as err:
            last = str(err)
    raise RuntimeError(last)


class Names:
    """Reverse DNS, looked up lazily on its own small thread pool (a slow lookup never holds up sampling) and
    remembered, failures included, so each address is asked once."""

    def __init__(self):
        from concurrent.futures import ThreadPoolExecutor
        self.cache: dict[str, str] = {}
        self.pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="netl-rdns")

    def get(self, ip: str) -> str | None:
        """The name if known ('' when it has none); None while it's being looked up (asks the first time)."""
        if ip in self.cache:
            return self.cache[ip]
        try:
            addr = ipaddress.ip_address(ip)
        except ValueError:
            return ""
        if addr.is_unspecified or addr.is_loopback or addr.is_multicast:
            self.cache[ip] = ""
            return ""
        self.cache[ip] = None
        self.pool.submit(self._look, ip)
        return None

    def _look(self, ip: str):
        try:
            self.cache[ip] = socket.gethostbyaddr(ip)[0]
        except (OSError, UnicodeError):
            self.cache[ip] = ""


def status_line() -> str:
    """The home card's line: connection and current rates, read in a quarter of a second."""
    from grimoire.fsutil import human
    from grimoire.spells.netl import nm
    a = counters()
    time.sleep(0.25)
    b = counters()
    phys = [n for n in b if physical(n)] or [n for n in b if shown(n)]
    down = sum(b[n][0] - a.get(n, b[n])[0] for n in phys) * 4
    up = sum(b[n][1] - a.get(n, b[n])[1] for n in phys) * 4
    rates = f"↓ {human(max(0, down))}/s ↑ {human(max(0, up))}/s"
    p = nm.primary() if nm.available() else None
    if p is None:
        return f"Offline · {rates}" if not phys else rates
    what = {"wifi": "Wi-Fi", "ethernet": "Wired", "gsm": "Mobile"}.get(p["type"], p["type"].title())
    return f"{what} · {p['connection']} · {rates}"
