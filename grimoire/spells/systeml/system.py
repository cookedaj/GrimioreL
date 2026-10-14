"""SystemL's actions and lists: process signals and priority, systemd services, startup apps, disks.

Anything you own is done directly; anything that needs root goes through root-helper.sh with pkexec (one
password prompt). Every call that can take a moment is meant to run on a worker thread.
"""
import json
import os
import signal
import subprocess
from configparser import ConfigParser
from pathlib import Path

import psutil

from grimoire.fsutil import free_name, trash

HELPER = Path(__file__).with_name("root-helper.sh")
AUTOSTART = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "autostart"
SYSTEM_AUTOSTART = [Path("/etc/xdg/autostart")]
APP_DIRS = [Path.home() / ".local/share/applications", Path("/usr/share/applications"),
            Path("/var/lib/flatpak/exports/share/applications"),
            Path.home() / ".local/share/flatpak/exports/share/applications"]
MARK = "X-Grimoire-SystemL"
# startup entries Plasma needs to work; SystemL won't turn them off
ESSENTIAL = {"org.kde.plasmashell", "kglobalacceld", "polkit-kde-authentication-agent-1", "powerdevil",
             "pam_kwallet_init", "at-spi-dbus-bus", "xembedsniproxy", "gmenudbusmenuproxy", "im-launch",
             "org.kde.plasma-fallback-session-restore", "xdg-user-dirs", "xdg-user-dirs-kde"}
# services the root helper also refuses to stop; the page greys out Stop/Disable for them
CORE_UNITS = ("dbus", "systemd-", "sddm.service", "display-manager.service", "polkit.service", "user@",
              "getty@", "udisks2.service")
SIGNALS = {"TERM": signal.SIGTERM, "KILL": signal.SIGKILL, "STOP": signal.SIGSTOP, "CONT": signal.SIGCONT}


def run_root(*args: str) -> str:
    """root-helper.sh through pkexec. Raises RuntimeError("cancelled") if the password prompt is dismissed."""
    r = subprocess.run(["pkexec", "/usr/bin/bash", str(HELPER), *args], capture_output=True, text=True)
    if r.returncode in (126, 127) and not r.stderr.strip():
        raise RuntimeError("cancelled")
    if r.returncode:
        msg = (r.stderr or r.stdout).strip().splitlines()
        raise RuntimeError(msg[-1] if msg else f"helper failed ({r.returncode})")
    return r.stdout.strip()


# ---------------------------------------------------------------- processes
def send(pid: int, sig: str) -> str:
    """TERM ends politely, KILL forces, STOP pauses, CONT resumes. Asks for the password for others' processes."""
    if pid <= 2 or pid == os.getpid():
        raise RuntimeError("that process can't be stopped from here")
    try:
        os.kill(pid, SIGNALS[sig])
    except ProcessLookupError:
        return "already gone"
    except PermissionError:
        run_root("signal", str(pid), sig)
    return "done"


def renice(pid: int, nice: int) -> str:
    """Lower priority works on your own processes; raising it (negative nice) needs the password."""
    try:
        psutil.Process(pid).nice(nice)
    except psutil.NoSuchProcess:
        return "already gone"
    except psutil.AccessDenied:
        run_root("renice", str(pid), str(nice))
    return "done"


# ---------------------------------------------------------------- services
def _systemctl(user: bool, *args: str) -> str:
    cmd = ["systemctl", "--user"] if user else ["systemctl"]
    try:
        return subprocess.run([*cmd, *args], capture_output=True, text=True, timeout=15).stdout
    except (OSError, subprocess.TimeoutExpired):
        return ""


def services(user: bool) -> list[dict]:
    """Every service systemd knows: loaded ones with their state, plus installed-but-unloaded unit files."""
    units = {}
    try:
        for u in json.loads(_systemctl(user, "list-units", "--type=service", "--all", "-o", "json") or "[]"):
            if u["load"] == "not-found":
                continue
            units[u["unit"]] = {"unit": u["unit"], "description": u["description"], "active": u["active"],
                                "sub": u["sub"], "enabled": "", "memory": None, "pid": 0}
        for f in json.loads(_systemctl(user, "list-unit-files", "--type=service", "-o", "json") or "[]"):
            name = f["unit_file"]
            if f["state"] == "transient" or name.endswith("@.service"):
                continue
            units.setdefault(name, {"unit": name, "description": "", "active": "inactive", "sub": "dead",
                                    "enabled": "", "memory": None, "pid": 0})["enabled"] = f["state"]
    except (ValueError, KeyError):
        return []
    running = [n for n, u in units.items() if u["active"] in ("active", "activating", "reloading")]
    if running:
        cur = {}
        for line in _systemctl(user, "show", "-p", "Id,MemoryCurrent,MainPID", "--", *running).splitlines():
            k, _, v = line.partition("=")
            if k == "Id":
                cur = units.get(v, {})
            elif k == "MemoryCurrent" and v.isdigit() and int(v) < 2**60 and cur:
                cur["memory"] = int(v)
            elif k == "MainPID" and v.isdigit() and cur:
                cur["pid"] = int(v)
    return sorted(units.values(), key=lambda u: u["unit"].lower())


def is_core(unit: str) -> bool:
    return unit.startswith(CORE_UNITS)


def unit_action(user: bool, action: str, unit: str) -> str:
    if action not in ("start", "stop", "restart", "enable", "disable"):
        raise ValueError(action)
    if not user:
        run_root("unit", action, unit)
        return "done"
    r = subprocess.run(["systemctl", "--user", action, "--", unit], capture_output=True, text=True, timeout=60)
    if r.returncode:
        raise RuntimeError(r.stderr.strip().splitlines()[-1] if r.stderr.strip() else f"{action} failed")
    return "done"


def unit_log(user: bool, unit: str, lines=200) -> str:
    cmd = ["journalctl", "--user-unit" if user else "-u", unit, "-n", str(lines), "--no-pager", "-o", "short-iso"]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.TimeoutExpired):
        return "Couldn't read the log."
    return out.stdout.strip() or out.stderr.strip() or "No log lines yet."


def failed_count() -> int:
    n = 0
    for user in (False, True):
        n += len([l for l in _systemctl(user, "list-units", "--state=failed", "--plain", "--no-legend").splitlines()
                  if l.strip()])
    return n


# ---------------------------------------------------------------- startup apps
def _read(path: Path) -> dict:
    cp = ConfigParser(interpolation=None, strict=False)
    cp.optionxform = str
    try:
        cp.read(path, encoding="utf-8")
        return dict(cp["Desktop Entry"]) if cp.has_section("Desktop Entry") else {}
    except Exception:                  # a broken .desktop file just doesn't show
        return {}


def _on(entry: dict) -> bool:
    return entry.get("Hidden", "false").lower() != "true" and \
        entry.get("X-GNOME-Autostart-enabled", "true").lower() != "false"


def _shown_on_plasma(entry: dict) -> bool:
    only = [d for d in entry.get("OnlyShowIn", "").split(";") if d]
    nope = [d for d in entry.get("NotShowIn", "").split(";") if d]
    return (not only or "KDE" in only) and "KDE" not in nope


def startup_apps() -> list[dict]:
    """Autostart entries, the way Plasma sees them: your ~/.config/autostart files override system ones."""
    rows = {}
    for d in SYSTEM_AUTOSTART:
        for f in sorted(d.glob("*.desktop")):
            e = _read(f)
            if e:
                rows[f.name] = {"file": f.name, "system": f, "user": None, "entry": e}
    for f in sorted(AUTOSTART.glob("*.desktop")) if AUTOSTART.is_dir() else []:
        e = _read(f)
        row = rows.setdefault(f.name, {"file": f.name, "system": None, "entry": e})
        row["user"], row["entry"] = f, (row["entry"] | e if row["system"] else e)
    out = []
    for r in rows.values():
        e, stem = r["entry"], r["file"].removesuffix(".desktop")
        if not _shown_on_plasma(e):
            continue
        out.append({"file": r["file"], "name": e.get("Name", stem), "comment": e.get("Comment", ""),
                    "exec": e.get("Exec", ""), "icon": e.get("Icon", ""), "on": _on(e),
                    "essential": stem in ESSENTIAL, "source": "System" if r["system"] else "Yours",
                    "ours": bool(r["user"] and _read(r["user"]).get(MARK)), "removable": not r["system"]})
    return sorted(out, key=lambda r: (r["essential"], r["source"] == "System", r["name"].lower()))


def _set_key(path: Path, key: str, value: str):
    lines = path.read_text(encoding="utf-8").splitlines()
    in_entry, done = False, False
    for i, line in enumerate(lines):
        if line.startswith("["):
            if in_entry and not done:
                lines.insert(i, f"{key}={value}")
                done = True
                break
            in_entry = line.strip() == "[Desktop Entry]"
        elif in_entry and line.split("=", 1)[0].strip() == key:
            lines[i] = f"{key}={value}"
            done = True
    if not done:
        lines.append(f"{key}={value}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def set_startup(file: str, on: bool):
    """Off: a ~/.config/autostart override with Hidden=true (the freedesktop way; Plasma's own settings do the
    same). On: trash SystemL's own override, or flip Hidden back in a file that's yours."""
    if Path(file).name != file or not file.endswith(".desktop"):
        raise ValueError(file)
    stem = file.removesuffix(".desktop")
    if not on and stem in ESSENTIAL:
        raise RuntimeError("Plasma needs this to start; leaving it on")
    mine = AUTOSTART / file
    system = next((d / file for d in SYSTEM_AUTOSTART if (d / file).is_file()), None)
    if mine.is_file():
        if on and _read(mine).get(MARK) and system:
            trash(mine)                          # back to the untouched system entry
            return
        _set_key(mine, "Hidden", "false" if on else "true")
        if on and "X-GNOME-Autostart-enabled" in _read(mine):
            _set_key(mine, "X-GNOME-Autostart-enabled", "true")
        return
    if on or not system:
        return
    AUTOSTART.mkdir(parents=True, exist_ok=True)
    mine.write_text(system.read_text(encoding="utf-8"), encoding="utf-8")
    _set_key(mine, "Hidden", "true")
    _set_key(mine, MARK, "true")


def installed_apps() -> list[dict]:
    """Apps from the menu (name, file) for "Add to startup"."""
    seen = {}
    for d in APP_DIRS:
        for f in sorted(d.glob("*.desktop")) if d.is_dir() else []:
            if f.name in seen:
                continue
            e = _read(f)
            if not e or e.get("NoDisplay", "").lower() == "true" or e.get("Type") != "Application" or "Exec" not in e:
                continue
            seen[f.name] = {"name": e.get("Name", f.stem), "path": f, "comment": e.get("Comment", "")}
    return sorted(seen.values(), key=lambda a: a["name"].lower())


def add_startup(app_path: Path) -> Path:
    AUTOSTART.mkdir(parents=True, exist_ok=True)
    dest = AUTOSTART / app_path.name
    if dest.exists():
        _set_key(dest, "Hidden", "false")
        return dest
    dest = free_name(dest)
    dest.write_text(app_path.read_text(encoding="utf-8"), encoding="utf-8")
    return dest


def remove_startup(file: str):
    """Only your own entries can be removed, and they go to the Trash."""
    path = AUTOSTART / file
    if Path(file).name != file or not path.is_file() or any((d / file).exists() for d in SYSTEM_AUTOSTART):
        raise RuntimeError("only your own startup entries can be removed")
    trash(path)


# ---------------------------------------------------------------- disks
def drives() -> list[dict]:
    """Physical drives with their partitions, from lsblk, plus usage for mounted ones."""
    try:
        data = json.loads(subprocess.run(["lsblk", "-J", "-b", "-o", "NAME,MODEL,SIZE,TYPE,ROTA,TRAN,RM,"
                                          "MOUNTPOINTS,FSTYPE,LABEL"], capture_output=True, text=True,
                                         timeout=10).stdout)
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return []
    out = []
    for dev in data.get("blockdevices", []):
        if dev.get("type") not in ("disk",) or dev["name"].startswith(("loop", "zram", "ram")):
            continue
        kind = "NVMe SSD" if dev.get("tran") == "nvme" else "USB drive" if dev.get("tran") == "usb" else \
            "Hard drive" if dev.get("rota") else "SSD"
        parts = []
        for p in dev.get("children") or [dev]:
            mounts = [m for m in (p.get("mountpoints") or []) if m]
            usage = None
            if mounts and not mounts[0].startswith("[SWAP]"):
                try:
                    usage = psutil.disk_usage(mounts[0])
                except OSError:
                    pass
            parts.append({"name": p["name"], "size": p.get("size") or 0, "fs": p.get("fstype") or "",
                          "label": p.get("label") or "", "mounts": mounts, "used": usage.used if usage else None,
                          "total": usage.total if usage else None})
        out.append({"name": dev["name"], "model": (dev.get("model") or dev["name"]).strip(), "size": dev["size"],
                    "kind": kind, "removable": bool(dev.get("rm")) or dev.get("tran") == "usb", "parts": parts})
    return out


def disk_rates(prev: dict | None, dt: float) -> tuple[dict, dict]:
    """Per-drive read/write bytes per second since prev (as returned last time)."""
    now = psutil.disk_io_counters(perdisk=True) or {}
    rates = {}
    if prev and dt:
        for name, c in now.items():
            if name in prev:
                rates[name] = (max(0, c.read_bytes - prev[name].read_bytes) / dt,
                               max(0, c.write_bytes - prev[name].write_bytes) / dt)
    return now, rates


def unmount(device: str) -> str:
    r = subprocess.run(["udisksctl", "unmount", "-b", f"/dev/{device}"], capture_output=True, text=True, timeout=30)
    if r.returncode:
        raise RuntimeError(r.stderr.strip() or "couldn't unmount")
    return r.stdout.strip()
