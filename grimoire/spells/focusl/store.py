# SPDX-License-Identifier: GPL-3.0-or-later
"""FocusL's files: settings, the live session state the background runner writes (and the page and CLI read), the
control file they use to steer it, and the history behind the stats. No Qt, so the runner stays light.
"""
import datetime as dt
import fcntl
import json
import os
import re
import time

from grimoire.paths import CACHE, CONFIG, DATA

SETTINGS = CONFIG / "focusl.json"
STATE = CACHE / "focusl-state.json"
CONTROL = CACHE / "focusl-control.json"
LOCK = CACHE / "focusl.lock"
LOG = CACHE / "focusl.log"
HISTORY = DATA / "focusl-history.json"
KEEP = 5000                      # history entries kept (years of sessions)

DEFAULTS = {
    "focus": 25, "short": 5, "long": 15, "rounds": 4,          # minutes; rounds of focus before the long break
    "auto_start": True,                                        # roll straight into the next phase
    "sound": True,                                             # a soft chime at each change
    "dnd": True,                                               # Plasma's Do Not Disturb while focusing
    "hide_crosshair": True,                                    # SightsL off while focusing, back after
    "block_apps": False, "apps": ["discord", "steam"],
    "app_action": "close",                                     # "warn" or "close" (after a warning and grace)
    "grace": 10,                                               # seconds between the warning and closing
    "block_sites": False, "sites": ["youtube.com", "reddit.com", "x.com"],
}
LIMITS = {"focus": (1, 180), "short": (1, 60), "long": (1, 120), "rounds": (1, 12), "grace": (0, 120)}
# never closed, whatever the list says: the desktop itself, shells, and Python (Grimoire runs in it)
PROTECTED = {"systemd", "kwin_wayland", "kwin_wayland_wrapper", "kwin_x11", "plasmashell", "ksmserver", "kded6",
             "xwayland", "dbus-daemon", "dbus-broker", "pipewire", "wireplumber", "pipewire-pulse", "sddm",
             "startplasma-wayland", "polkit-kde-authentication-agent-1", "bash", "sh", "zsh", "fish", "dash",
             "konsole", "python", "python3", "grimoire", "sudo", "pkexec", "kdeconnectd", "baloo_file"}
PHASES = {"focus": "Focus", "short": "Short break", "long": "Long break"}


# ---------------------------------------------------------------- json files
def _read(path, default):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return default


def _write(path, data):
    """Atomic, so the runner and the page never read a half-written file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
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


# ---------------------------------------------------------------- settings
def clean_app(name: str) -> str:
    """'Discord ' -> 'discord'; '' for anything that isn't a plain process name or is protected."""
    name = name.strip().lower()
    if not re.fullmatch(r"[a-z0-9][a-z0-9._+ -]{0,63}", name) or name in PROTECTED:
        return ""
    return name


def clean_site(text: str) -> str:
    """'https://www.YouTube.com/watch?v=…' -> 'youtube.com'; '' if it isn't a domain name."""
    s = text.strip().lower()
    s = re.sub(r"^[a-z][a-z0-9+.-]*://", "", s).split("/")[0].split("?")[0].split(":")[0].removeprefix("www.")
    ok = re.fullmatch(r"([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}", s) and len(s) <= 200
    return s if ok and s not in ("localhost", "localdomain") else ""


def _unique(items):
    return list(dict.fromkeys(i for i in items if i))


def load_settings() -> dict:
    """Saved settings over the defaults: wrong types dropped, numbers clamped, lists cleaned."""
    d = _read(SETTINGS, {})
    out = json.loads(json.dumps(DEFAULTS))
    if not isinstance(d, dict):
        return out
    for k, default in DEFAULTS.items():
        v = d.get(k)
        if isinstance(default, bool):
            if isinstance(v, bool):
                out[k] = v
        elif isinstance(default, int):
            if isinstance(v, int) and not isinstance(v, bool):
                lo, hi = LIMITS[k]
                out[k] = min(hi, max(lo, v))
        elif isinstance(default, list):
            if isinstance(v, list):
                clean = clean_app if k == "apps" else clean_site
                out[k] = _unique(clean(x) for x in v if isinstance(x, str))[:200]
        elif k == "app_action":
            if v in ("warn", "close"):
                out[k] = v
    return out


def save_settings(s: dict):
    _write(SETTINGS, s)


# ---------------------------------------------------------------- the live session
def running() -> bool:
    """True while a runner holds the lock (it's released by the kernel when the runner dies, however it dies)."""
    try:
        fd = os.open(LOCK, os.O_RDWR | os.O_CREAT, 0o600)
    except OSError:
        return False
    try:
        fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
        return False
    except BlockingIOError:
        return True
    finally:
        os.close(fd)                                               # drops our shared lock again


def load_state() -> dict:
    s = _read(STATE, {})
    return s if isinstance(s, dict) else {}


def write_state(s: dict):
    _write(STATE, s)


def live_state() -> dict:
    """The session as it stands; a state whose runner is gone reads as idle (with its leftovers kept)."""
    s = load_state()
    if s.get("phase", "idle") != "idle" and not running():
        s = {k: s[k] for k in ("crosshair_hidden", "sites_blocked") if k in s} | {"phase": "idle", "stale": True}
    s.setdefault("phase", "idle")
    return s


def left(s: dict, now: float | None = None) -> float:
    """Seconds left in the current phase."""
    if s.get("status") == "running" and isinstance(s.get("ends"), (int, float)):
        return max(0.0, s["ends"] - (now or time.time()))
    return float(s.get("left") or 0)


def send(cmd: str):
    """Ask the runner to pause, resume, skip or stop; it picks this up within half a second."""
    _write(CONTROL, {"cmd": cmd, "id": time.time_ns()})


def clock(seconds: float) -> str:
    """1122.4 -> '18:43' (rounded up, so 0:00 only shows at the very end)."""
    s = int(-(-seconds // 1))
    return f"{s // 3600}:{s // 60 % 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60}:{s % 60:02d}"


def status_line() -> str:
    s = live_state()
    if s["phase"] == "idle":
        n = stats()["today"]
        return f"Idle · {n} session{'' if n == 1 else 's'} today"
    word = {"focus": "Focusing", "short": "Short break", "long": "Long break"}[s["phase"]]
    if s.get("status") == "paused":
        return f"Paused · {word.lower()} · {clock(left(s))} left"
    if s.get("status") == "waiting":
        return f"Waiting · {PHASES[s['phase']].lower()} next"
    return f"{word} · {clock(left(s))} left"


# ---------------------------------------------------------------- history and stats
def history() -> list[dict]:
    h = _read(HISTORY, [])
    return [e for e in h if isinstance(e, dict) and isinstance(e.get("end"), (int, float))] \
        if isinstance(h, list) else []


def record(start: float, end: float, minutes: float, full: bool):
    """One focus phase: full when it ran to the end, else the minutes you did before stopping or skipping."""
    h = history()
    h.append({"start": round(start), "end": round(end), "minutes": round(minutes, 1), "full": full})
    _write(HISTORY, h[-KEEP:])


def stats(now: float | None = None, days: int = 14) -> dict:
    """today/week (full sessions; the week starts on Monday), total focus minutes, the streak of days with at least
    one full session (today counts once you've done one, and an empty today doesn't break it yet), and the last
    `days` days as (date, minutes, sessions) for the chart."""
    today = dt.date.fromtimestamp(now or time.time())
    per_day: dict[dt.date, list] = {}
    total = 0.0
    for e in history():
        d = dt.date.fromtimestamp(e["end"])
        m = float(e.get("minutes") or 0)
        total += m
        slot = per_day.setdefault(d, [0.0, 0])
        slot[0] += m
        slot[1] += bool(e.get("full"))
    monday = today - dt.timedelta(days=today.weekday())
    week = sum(v[1] for d, v in per_day.items() if monday <= d <= today)
    streak, d = 0, today if per_day.get(today, [0, 0])[1] else today - dt.timedelta(days=1)
    while per_day.get(d, [0, 0])[1]:
        streak += 1
        d -= dt.timedelta(days=1)
    chart = [(today - dt.timedelta(days=i), *per_day.get(today - dt.timedelta(days=i), [0.0, 0]))
             for i in range(days - 1, -1, -1)]
    return {"today": per_day.get(today, [0, 0])[1], "week": week, "minutes": total, "streak": streak, "days": chart}
