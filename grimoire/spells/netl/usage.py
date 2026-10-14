"""NetL's usage history: bytes per interface per day and per month, plus per app where NetL measured it.

    grimoire-netl usage [record|enable|disable|status|show]

How it's recorded: `record` reads the kernel's interface counters (/sys/class/net/*/statistics, via psutil) and
adds what grew since the last reading. A systemd user timer runs it every 5 minutes when you turn background
recording on (one short pass, no Qt, nothing resident); NetL also runs it once a minute while it's open. Both share
the same last-seen counters, so nothing is counted twice. Counters restart at zero after a reboot or when an
interface is re-created (a USB adapter, a VPN coming back up); a new boot id or a counter that went down means
"everything it shows now is new". Traffic in the last few minutes before a shutdown is the one thing missed.

Sampling only while NetL is open would undercount and vnstat isn't installed by default, hence the timer.
Per-app numbers are TCP only and only while NetL is open (see probe.py for why).

The file is small: one [down, up] pair per interface per day (kept DAYS days) and per month (kept for good), and per
app per day/month (busiest APPS kept).
"""
import fcntl
import json
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path

from grimoire.paths import CACHE, DATA, HOME

FILE = DATA / "netl-usage.json"
LOCK = CACHE / "netl-usage.lock"
UNIT = "grimoire-netl-usage"
UNITS = HOME / ".config/systemd/user"
DAYS = 400                     # daily rows kept; months are kept for good
APPS = 40                      # apps kept per day / month
BOOT_ID = Path("/proc/sys/kernel/random/boot_id")

SERVICE = """[Unit]
Description=Grimoire NetL: add up network usage per interface

[Service]
Type=oneshot
ExecStart=%h/.local/bin/grimoire-netl usage record
Nice=10
IOSchedulingClass=idle
"""
TIMER = """[Unit]
Description=Record Grimoire NetL's network usage every 5 minutes

[Timer]
OnBootSec=1min
OnUnitActiveSec=5min
AccuracySec=30s

[Install]
WantedBy=timers.target
"""


def _empty() -> dict:
    return {"v": 1, "boot": "", "last": {}, "days": {}, "months": {}, "app_days": {}, "app_months": {}}


def load() -> dict:
    try:
        data = json.loads(FILE.read_text())
        if isinstance(data, dict) and data.get("v") == 1:
            return _empty() | data
    except (OSError, ValueError):
        pass
    return _empty()


def _save(data: dict):
    FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = FILE.with_name(FILE.name + ".tmp")
    tmp.write_text(json.dumps(data, separators=(",", ":")))
    tmp.replace(FILE)


@contextmanager
def _locked():
    """The timer and an open NetL may record at the same moment; one waits for the other."""
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    with open(LOCK, "w") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def boot_id() -> str:
    try:
        return BOOT_ID.read_text().strip()
    except OSError:
        return ""


def _add(bucket: dict, key: str, name: str, rx: int, tx: int):
    row = bucket.setdefault(key, {}).setdefault(name, [0, 0])
    row[0] += rx
    row[1] += tx


def apply(data: dict, current: dict[str, tuple[int, int]], boot: str, now: float) -> dict[str, list[int]]:
    """Fold one reading into data; returns what it added per interface. Pure, so it's easy to test."""
    first = not data["last"] and not data["boot"]
    rebooted = bool(data["boot"]) and boot != data["boot"]
    last, added = data["last"], {}
    for name, (rx, tx) in current.items():
        old = last.get(name)
        if first:
            continue                                   # the very first reading only sets the baseline
        if rebooted or old is None or rx < old[0] or tx < old[1]:
            drx, dtx = rx, tx                          # counters restarted (or a new interface): all of it is new
        else:
            drx, dtx = rx - old[0], tx - old[1]
        if drx or dtx:
            added[name] = [drx, dtx]
    day, month = time.strftime("%Y-%m-%d", time.localtime(now)), time.strftime("%Y-%m", time.localtime(now))
    for name, (drx, dtx) in added.items():
        _add(data["days"], day, name, drx, dtx)
        _add(data["months"], month, name, drx, dtx)
    data["last"] = {n: [rx, tx] for n, (rx, tx) in current.items()}
    data["boot"] = boot
    data["t"] = now
    for key in sorted(data["days"])[:-DAYS]:
        del data["days"][key]
    for key in sorted(data["app_days"])[:-DAYS]:
        del data["app_days"][key]
    return added


def _trim_apps(bucket: dict, key: str):
    apps = bucket.get(key, {})
    if len(apps) > APPS:
        keep = sorted(apps, key=lambda a: sum(apps[a]), reverse=True)[:APPS]
        bucket[key] = {a: apps[a] for a in keep}


def record(apps: dict[str, list[int]] | None = None) -> dict[str, list[int]]:
    """Read the counters now and add the growth (plus per-app bytes NetL measured, if given)."""
    from grimoire.spells.netl.probe import counters, physical, shown
    current = {n: c for n, c in counters().items() if shown(n)}
    now = time.time()
    with _locked():
        data = load()
        added = apply(data, current, boot_id(), now)
        data.setdefault("physical", {}).update({n: physical(n) for n in current})
        if apps:
            day, month = time.strftime("%Y-%m-%d"), time.strftime("%Y-%m")
            for app, (rx, tx) in apps.items():
                _add(data["app_days"], day, app, rx, tx)
                _add(data["app_months"], month, app, rx, tx)
            _trim_apps(data["app_days"], day)
            _trim_apps(data["app_months"], month)
        _save(data)
    return added


# ---------------------------------------------------------------- reading it back
def totals(data: dict, period: str, key: str, ifaces: set[str] | None = None) -> tuple[int, int]:
    """[down, up] for one day ('days', '2026-10-13') or month ('months', '2026-10'), over ifaces (all if None)."""
    rows = data.get(period, {}).get(key, {})
    rx = sum(v[0] for n, v in rows.items() if ifaces is None or n in ifaces)
    tx = sum(v[1] for n, v in rows.items() if ifaces is None or n in ifaces)
    return rx, tx


def physical_set(data: dict) -> set[str] | None:
    """The hardware interfaces, which "All" adds up (a VPN's traffic already crossed one of them)."""
    phys = {n for n, p in data.get("physical", {}).items() if p}
    return phys or None


def interfaces(data: dict) -> list[str]:
    names = {n for bucket in (data["days"], data["months"]) for rows in bucket.values() for n in rows}
    return sorted(names)


# ---------------------------------------------------------------- the timer
def _systemctl(*args: str, check=False) -> subprocess.CompletedProcess:
    return subprocess.run(["systemctl", "--user", *args], capture_output=True, text=True, timeout=30, check=check)


def set_enabled(on: bool):
    """Install and start (or stop) the 5-minute user timer; recording once right away sets the baseline."""
    if on:
        UNITS.mkdir(parents=True, exist_ok=True)
        (UNITS / f"{UNIT}.service").write_text(SERVICE)
        (UNITS / f"{UNIT}.timer").write_text(TIMER)
        _systemctl("daemon-reload", check=True)
        _systemctl("enable", "--now", f"{UNIT}.timer", check=True)
        record()
    else:
        _systemctl("disable", "--now", f"{UNIT}.timer")


def enabled() -> bool:
    try:
        return _systemctl("is-active", "--quiet", f"{UNIT}.timer").returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def main(argv: list[str]):
    from grimoire.fsutil import human
    cmd = argv[0] if argv else "record"
    if cmd == "record":
        try:
            record()
        except Exception as err:          # a timer run never fails loudly; the next one tries again
            print(f"netl usage: {err}", file=sys.stderr)
    elif cmd in ("enable", "disable"):
        set_enabled(cmd == "enable")
        print(f"usage recording {'on' if cmd == 'enable' else 'off'}")
    elif cmd == "status":
        print("usage recording on" if enabled() else "usage recording off")
    elif cmd == "show":
        data = load()
        for day in sorted(data["days"])[-14:]:
            rx, tx = totals(data, "days", day)
            print(f"{day}  ↓ {human(rx):>10}  ↑ {human(tx):>10}")
        for month in sorted(data["months"])[-12:]:
            rx, tx = totals(data, "months", month)
            print(f"{month}     ↓ {human(rx):>10}  ↑ {human(tx):>10}")
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
