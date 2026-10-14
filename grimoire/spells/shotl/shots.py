# SPDX-License-Identifier: GPL-3.0-or-later
"""ShotL's settings and history: where shots go, what happens after a capture, and the list of past captures.
No Qt here, so the status line and the recorder process can read it cheaply."""
import json
import os
import re
import time
from pathlib import Path

from grimoire.fsutil import free_name
from grimoire.paths import CACHE, CONFIG, DATA

SETTINGS = CONFIG / "shotl.json"
HISTORY = DATA / "shotl-history.json"
TEMP = CACHE / "shotl"                         # raw grabs before they're saved, video thumbnails
AFTER = {"edit": "Open the editor", "copy": "Copy and save", "save": "Save only"}
DEFAULTS = {"folder": "", "after": "edit", "delay": 0, "pointer": False, "sound": False, "restore_token": ""}
KEEP = 1000                                    # history entries kept (files stay; only the list is trimmed)
VIDEO = {".mp4", ".webm", ".mkv"}


def load() -> dict:
    try:
        saved = json.loads(SETTINGS.read_text())
    except (OSError, ValueError):
        saved = {}
    return DEFAULTS | {k: v for k, v in saved.items() if k in DEFAULTS and type(v) is type(DEFAULTS[k])}


def save(settings: dict):
    SETTINGS.parent.mkdir(parents=True, exist_ok=True)
    tmp = SETTINGS.with_suffix(".tmp")
    tmp.write_text(json.dumps(settings, indent=1))
    tmp.replace(SETTINGS)


def update(**changes):
    save(load() | changes)


def pictures() -> Path:
    """XDG Pictures folder (user-dirs.dirs), read late so a sandbox HOME works."""
    home = Path.home()
    conf = Path(os.environ.get("XDG_CONFIG_HOME") or home / ".config") / "user-dirs.dirs"
    try:
        m = re.search(r'^XDG_PICTURES_DIR="([^"]+)"', conf.read_text(), re.M)
        if m:
            return Path(m.group(1).replace("$HOME", str(home)))
    except OSError:
        pass
    return home / "Pictures"


def folder(settings: dict | None = None) -> Path:
    chosen = (settings or load())["folder"]
    return Path(chosen).expanduser() if chosen else pictures() / "Screenshots"


def new_path(video=False, ext="", reserve=True) -> Path:
    """A fresh dated name in the shots folder, e.g. Screenshot_2026-10-13_21-04-55.png; never an existing one.
    Reserved as an empty file unless reserve=False, so two captures in the same second can't pick the same name."""
    d = folder()
    d.mkdir(parents=True, exist_ok=True)
    stem = ("Recording_" if video else "Screenshot_") + time.strftime("%Y-%m-%d_%H-%M-%S")
    dest = d / (stem + (ext or (".mp4" if video else ".png")))
    return claim(dest) if reserve else free_name(dest)


def claim(dest: Path) -> Path:
    """free_name(dest), created empty in one step (O_EXCL) so no other writer can take it in the meantime."""
    while True:
        dest = free_name(dest)
        try:
            os.close(os.open(dest, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644))
            return dest
        except FileExistsError:
            continue


def release(path: Path):
    """Undo claim() when nothing got written: removes the file only while it's still our empty placeholder."""
    try:
        if path.is_file() and not path.is_symlink() and path.stat().st_size == 0:
            path.unlink()
    except OSError:
        pass


# ---------------------------------------------------------------- history
def _read() -> list[dict]:
    try:
        data = json.loads(HISTORY.read_text())
        return [e for e in data if isinstance(e, dict) and isinstance(e.get("path"), str)]
    except (OSError, ValueError):
        return []


def add(path: Path):
    entries = [e for e in _read() if e["path"] != str(path)]
    entries.append({"path": str(path), "time": time.time(), "video": path.suffix.lower() in VIDEO})
    HISTORY.parent.mkdir(parents=True, exist_ok=True)
    tmp = HISTORY.with_suffix(".tmp")
    tmp.write_text(json.dumps(entries[-KEEP:], indent=0))
    tmp.replace(HISTORY)


def entries() -> list[dict]:
    """Newest first, only files that still exist (moved or trashed ones drop out of the gallery)."""
    return [e for e in reversed(_read()) if Path(e["path"]).is_file()]


def ago(t: float) -> str:
    s = max(0, time.time() - t)
    for unit, n in (("day", 86400), ("h", 3600), ("min", 60)):
        if s >= n:
            k = int(s // n)
            return f"{k} {unit}{'s' if unit == 'day' and k > 1 else ''} ago"
    return "just now"


def status() -> str:
    from grimoire.spells.shotl import record
    rec = record.state()
    items = entries()
    shots = sum(not e["video"] for e in items)
    vids = len(items) - shots
    bits = [f"{shots} shot{'s' if shots != 1 else ''}"]
    if vids:
        bits.append(f"{vids} recording{'s' if vids != 1 else ''}")
    if rec:
        bits.insert(0, "Recording now")
    elif items:
        bits.append(f"last {ago(items[0]['time'])}")
    return " · ".join(bits)
