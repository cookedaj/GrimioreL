# SPDX-License-Identifier: GPL-3.0-or-later
"""SystemL's background alerts: a desktop notification when memory, a CPU/GPU temperature, a disk's free space or a
stuck app crosses its threshold, even while SystemL is closed.

    grimoire-systeml alerts [check|test|enable|disable|status]

A systemd user timer runs `check` once a minute: one cheap pass (psutil plus a couple of D-Bus calls, no Qt), so
nothing stays resident. Each condition is remembered in a small state file, so it notifies once, then stays quiet
until it clears (with a little hysteresis, so hovering at the line doesn't flap) or the cooldown passes. A check
never crashes: every alert is tried on its own and problems go to the log.

Stuck apps are two cheap signals: windows KWin itself marks "(Not Responding)" (it pings a window when it gets
focus or you try to close it, and its windows runner finds them by caption in a few ms), and your processes stuck
in uninterruptible sleep (D state) with no CPU or I/O progress between checks, which is what a frozen network
share or USB device looks like. A process merely busy at 100% is left alone: games and compilers do that on purpose.
"""
import json
import os
import subprocess
import sys
import time
import traceback

import psutil

from grimoire.paths import ASSETS, CACHE, CONFIG, DATA, HOME, unit_command

SETTINGS = CONFIG / "systeml-alerts.json"
STATE = CACHE / "systeml-alerts-state.json"
HISTORY = DATA / "systeml-alerts-history.json"
LOG = CACHE / "systeml-alerts.log"
UNIT = "grimoire-systeml-alerts"
UNITS = HOME / ".config/systemd/user"
KEEP = 100                       # alerts kept in the history
SLACK = 30                       # seconds of timer jitter forgiven on "for N minutes"
FS = {"ext4", "ext3", "btrfs", "xfs", "f2fs", "zfs", "vfat", "exfat", "ntfs", "ntfs3", "fuseblk"}
SKIP_MOUNTS = ("/snap", "/var/snap", "/var/lib/docker", "/boot")
NOT_RESPONDING = "(Not Responding)"

DEFAULTS = {
    "cooldown": 30,                                  # minutes before a condition that lasts notifies again
    "ram": {"on": True, "percent": 90},
    "cpu_temp": {"on": True, "c": 90},
    "gpu_temp": {"on": True, "c": 85},
    "hung": {"on": True, "minutes": 2},
    "disks": {},                                     # mount -> {"on", "value", "unit": "GB" | "%"}
}

SERVICE = """[Unit]
Description=Grimoire SystemL: check memory, temperatures, disks and stuck apps

[Service]
Type=oneshot
ExecStart={exe} alerts check
Nice=10
IOSchedulingClass=idle
"""
TIMER = """[Unit]
Description=Run Grimoire SystemL's alert check every minute

[Timer]
OnBootSec=2min
OnUnitActiveSec=1min
AccuracySec=10s

[Install]
WantedBy=timers.target
"""


# ---------------------------------------------------------------- files
def _read(path, default):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return default


def _write(path, data):
    """Atomic, so the timer and the window never read a half-written file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=1))
    tmp.replace(path)


def log(msg: str):
    try:
        if LOG.exists() and LOG.stat().st_size > 200_000:          # keep the newer half
            LOG.write_text(LOG.read_text()[-100_000:])
        with LOG.open("a") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + msg.rstrip() + "\n")
    except OSError:
        pass


def load_settings() -> dict:
    """The saved settings over the defaults; a broken file reads as the defaults (and is left for you to see)."""
    d = _read(SETTINGS, {})
    out = json.loads(json.dumps(DEFAULTS))
    if not isinstance(d, dict):
        return out
    for k, v in d.items():
        if k == "disks" and isinstance(v, dict):
            out[k] = v                                   # each rule is checked by disk_rule()
        elif isinstance(out.get(k), dict) and isinstance(v, dict):
            # same type as the default only: a hand-edited "90" or 90.5 would crash the panel's spin boxes
            out[k].update({f: x for f, x in v.items() if f in out[k] and type(x) is type(out[k][f])})
        elif k in out and type(v) is type(out[k]):
            out[k] = v
    return out


def save_settings(s: dict):
    _write(SETTINGS, s)


def history() -> list[dict]:
    h = _read(HISTORY, [])
    return h if isinstance(h, list) else []


# ---------------------------------------------------------------- readings
def mounts() -> list[dict]:
    """Real file systems worth watching, one per device (btrfs mounts the same one at / and /home)."""
    out, seen = [], set()
    for p in psutil.disk_partitions(all=False):
        if p.fstype not in FS or p.device in seen or p.mountpoint.startswith(SKIP_MOUNTS):
            continue
        try:
            u = psutil.disk_usage(p.mountpoint)
        except OSError:
            continue
        if not u.total:                          # some FUSE mounts report no size; free % would divide by zero
            continue
        seen.add(p.device)
        out.append({"mount": p.mountpoint, "device": p.device, "free": u.free, "total": u.total})
    return out


def disk_rule(s: dict, d: dict) -> dict:
    """A mount's rule: what you set, else 10 GB free on big disks, 10 % on small ones, off under 1 GB (EFI)."""
    rule = s["disks"].get(d["mount"])
    if isinstance(rule, dict) and isinstance(rule.get("on"), bool) and rule.get("unit") in ("GB", "%") \
            and type(rule.get("value")) is int:             # a hand-edited bad rule falls back to the default
        return rule
    if d["total"] < 2**30:
        return {"on": False, "value": 10, "unit": "%"}
    return {"on": True, "value": 10, "unit": "GB" if d["total"] >= 50 * 2**30 else "%"}


def temps(with_gpu=True) -> dict[str, float]:
    """CPU and GPU temperature, whichever sensors exist (NVIDIA's comes from nvidia-smi)."""
    from grimoire.spells.systeml import probe
    t = {k: v for k, v in probe.temps().items() if k in ("CPU", "GPU")}
    if with_gpu and "GPU" not in t:
        g = probe.gpu()
        if g and g["temp"] is not None:
            t["GPU"] = g["temp"]
    return t


def ram() -> tuple[float, int, int]:
    m = psutil.virtual_memory()
    used = m.total - m.available
    return used / m.total * 100, used, m.total


def readings() -> dict:
    """Current values for the settings panel."""
    return {"ram": ram()[0], "temps": temps(), "disks": mounts()}


def _bus():
    import dbus
    return dbus.SessionBus()


def unresponsive_windows() -> dict[str, str]:
    """{window id: app caption} for windows KWin marks as not responding; empty when KWin can't be asked."""
    try:
        runner = _bus().get_object("org.kde.KWin", "/WindowsRunner")
        matches = runner.Match(NOT_RESPONDING, dbus_interface="org.kde.krunner1", timeout=3)
    except Exception as e:                       # no KWin (another desktop, early at login): skip quietly
        log(f"KWin not reachable: {e}")
        return {}
    return {str(m[0]): str(m[1]).removesuffix(NOT_RESPONDING).strip(" —-") for m in matches
            if str(m[1]).endswith(NOT_RESPONDING)}


def stuck_procs() -> dict[str, dict]:
    """Your processes in uninterruptible sleep right now, with their CPU and I/O counters."""
    out, me = {}, os.getuid()
    for p in psutil.process_iter(["name", "status", "uids", "create_time"]):
        i = p.info
        if i["status"] != psutil.STATUS_DISK_SLEEP or not i["uids"] or i["uids"].real != me:
            continue
        try:
            ct = p.cpu_times()
            try:
                io = p.io_counters()
                io = io.read_chars + io.write_chars
            except (psutil.AccessDenied, AttributeError):
                io = 0
            out[f"proc:{p.pid}:{i['create_time']:.0f}"] = {"name": i["name"], "pid": p.pid,
                                                             "cpu": round(ct.user + ct.system, 2), "io": io}
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return out


def biggest_app() -> str:
    from grimoire.spells.systeml.history import per_app
    rows = []
    for p in psutil.process_iter(["pid", "ppid", "name", "exe", "memory_info"]):
        i = p.info
        if i["memory_info"]:
            rows.append({"name": i["name"] or "", "exe": i["exe"] or "", "kernel": i["ppid"] == 2, "cpu": 0.0,
                         "mem": i["memory_info"].rss})
    apps = per_app(rows)
    if not apps:
        return ""
    name, (_, mem, _) = max(apps.items(), key=lambda kv: kv[1][1])
    return f"{name} uses the most ({mem / 2**30:.1f} GB)."


# ---------------------------------------------------------------- notifications
def _icon() -> str:
    """Grimoire's icon by theme name when installed, else the file it's drawn from."""
    share = os.environ.get("XDG_DATA_HOME") or str(HOME / ".local/share")
    installed = os.path.exists(f"{share}/icons/hicolor/scalable/apps/grimoire.svg")
    return "grimoire" if installed else str(ASSETS / "clover5.svg")


def notify(title: str, body: str, urgent=False) -> bool:
    """One desktop notification from "SystemL", over D-Bus; notify-send if dbus-python is missing."""
    icon, urgency = _icon(), 2 if urgent else 1
    try:
        import dbus
        n = _bus().get_object("org.freedesktop.Notifications", "/org/freedesktop/Notifications")
        n.Notify("SystemL", dbus.UInt32(0), icon, title, body, dbus.Array([], signature="s"),
                 {"desktop-entry": "grimoire", "urgency": dbus.Byte(urgency)}, -1,
                 dbus_interface="org.freedesktop.Notifications", timeout=5)
        return True
    except Exception as e:
        log(f"D-Bus notify failed ({e}); trying notify-send")
    try:
        return subprocess.run(["notify-send", "-a", "SystemL", "-i", icon, "-u", ("normal", "critical")[urgent],
                               "-h", "string:desktop-entry:grimoire", title, body],
                              capture_output=True, timeout=5).returncode == 0
    except (OSError, subprocess.TimeoutExpired) as e:
        log(f"notify-send failed: {e}")
        return False


# ---------------------------------------------------------------- the check
# Each section yields (key, bad, clear, title, body, urgent); neither bad nor clear is the hysteresis band, where
# nothing changes. Sections run one by one, so a broken sensor only skips its own.
def _ram(s: dict, state: dict, now: float):
    if s["ram"]["on"]:
        pct, used, total = ram()
        lim = s["ram"]["percent"]
        bad = pct >= lim
        yield ("ram", bad, pct < lim - 5, "Memory almost full",
               f"RAM is {pct:.0f}% used ({used / 2**30:.1f} of {total / 2**30:.0f} GB). "
               + (biggest_app() if bad else ""), False)


def _temps(s: dict, state: dict, now: float):
    want = {"CPU": s["cpu_temp"], "GPU": s["gpu_temp"]}
    if any(w["on"] for w in want.values()):
        t = temps(with_gpu=s["gpu_temp"]["on"])
        for name, w in want.items():
            if w["on"] and name in t:             # a missing sensor just isn't checked
                yield (f"temp:{name}", t[name] >= w["c"], t[name] < w["c"] - 5, f"{name} is running hot",
                       f"{name} temperature is {t[name]:.0f}°C (alert at {w['c']}°C).", True)


def _disks(s: dict, state: dict, now: float):
    for d in mounts():
        rule = disk_rule(s, d)
        if not rule["on"]:
            continue
        free_gb, free_pct = d["free"] / 2**30, d["free"] / d["total"] * 100
        val = free_gb if rule["unit"] == "GB" else free_pct
        lim = rule["value"]
        yield (f"disk:{d['mount']}", val < lim, val > lim * 1.1 + (0.5 if rule["unit"] == "GB" else 1),
               f"{d['mount']} is almost full",
               f"{d['mount']} has {free_gb:.1f} GB free ({free_pct:.0f}%; alert below {lim} {rule['unit']}).", False)


def _hung(s: dict, state: dict, now: float):
    if s["hung"]["on"]:
        need = s["hung"]["minutes"] * 60 - SLACK
        streaks = state.setdefault("streaks", {})
        seen = set()
        for wid, caption in unresponsive_windows().items():
            key = f"win:{wid}"
            seen.add(key)
            since = streaks.setdefault(key, {"since": now})["since"]
            mins = round((now - since) / 60)
            yield (key, now - since >= need, False, f"{caption or 'An app'} isn't responding",
                   f"It hasn't responded for {mins} min. Wait a little, or close it from its window or SystemL's "
                   "Processes.", False)
        for key, p in stuck_procs().items():
            seen.add(key)
            old = streaks.get(key)
            if not old or old.get("cpu") != p["cpu"] or old.get("io") != p["io"]:
                streaks[key] = old = {"since": now, "cpu": p["cpu"], "io": p["io"]}   # still moving: restart
            mins = round((now - old["since"]) / 60)
            yield (key, now - old["since"] >= need, False, f"{p['name']} is stuck",
                   f"{p['name']} (PID {p['pid']}) has waited on a disk or device for {mins} min without progress, "
                   "often a frozen network share or USB drive.", False)
        for key in [k for k in streaks if k not in seen]:      # gone or recovered: forget it
            del streaks[key]
            yield (key, False, True, "", "", False)


def check(now: float | None = None) -> list[dict]:
    """One pass: notify for conditions that just went bad (or outlived the cooldown). Returns what it sent."""
    now = now or time.time()
    s = load_settings()
    state = _read(STATE, {})
    if not isinstance(state, dict):
        state = {}
    for k in ("active", "streaks"):               # a damaged state file must not break every check after it
        if not isinstance(state.get(k), dict):
            state[k] = {}
    active = state["active"]                      # key -> last notified time
    for k in [k for k, v in active.items() if type(v) not in (int, float)]:
        del active[k]
    streaks = state["streaks"]
    for k in [k for k, v in streaks.items() if not (isinstance(v, dict) and type(v.get("since")) in (int, float))]:
        del streaks[k]
    cooldown = max(1, s["cooldown"]) * 60
    sent = []
    for section in (_ram, _temps, _disks, _hung):
        try:
            items = list(section(s, state, now))
        except Exception:                          # one broken reading mustn't stop the rest (or crash)
            log(f"{section.__name__} failed:\n" + traceback.format_exc())
            continue
        for key, bad, clear, title, body, urgent in items:
            if bad and now - active.get(key, 0) >= cooldown:
                if notify(title, body, urgent):
                    active[key] = now
                    sent.append({"t": now, "key": key, "title": title, "body": body})
            elif clear:
                active.pop(key, None)
    if sent:
        _write(HISTORY, (history() + sent)[-KEEP:])
    _write(STATE, state)
    return sent


def check_safely():
    """What the timer runs: errors end up in the log, never as a failed unit spamming the journal."""
    try:
        for a in check():
            log(f"sent: {a['title']} — {a['body']}")
    except Exception:
        log("check crashed:\n" + traceback.format_exc())


# ---------------------------------------------------------------- the timer
def set_enabled(on: bool):
    """Install and start (or stop) the systemd user timer."""
    if on:
        UNITS.mkdir(parents=True, exist_ok=True)
        (UNITS / f"{UNIT}.service").write_text(SERVICE.format(exe=unit_command("grimoire-systeml")))
        (UNITS / f"{UNIT}.timer").write_text(TIMER)
        subprocess.run(["systemctl", "--user", "daemon-reload"], check=True, timeout=30)
        subprocess.run(["systemctl", "--user", "enable", "--now", f"{UNIT}.timer"], check=True, capture_output=True,
                       timeout=30)
    else:
        subprocess.run(["systemctl", "--user", "disable", "--now", f"{UNIT}.timer"], capture_output=True, timeout=30)


def enabled() -> bool:
    try:
        return subprocess.run(["systemctl", "--user", "is-active", "--quiet", f"{UNIT}.timer"],
                              timeout=10).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def main(argv: list[str]):
    cmd = argv[0] if argv else "check"
    if cmd == "check":
        check_safely()
    elif cmd == "test":
        print("sent" if notify("SystemL alerts work", "This is how memory, temperature, disk and stuck-app "
                               "alerts will look.") else "couldn't send a notification")
    elif cmd in ("enable", "disable"):
        set_enabled(cmd == "enable")
        print(f"alerts {'on' if cmd == 'enable' else 'off'}")
    elif cmd == "status":
        print("alerts on" if enabled() else "alerts off")
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
