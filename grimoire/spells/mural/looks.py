# SPDX-License-Identifier: GPL-3.0-or-later
"""MuraL Looks: the whole desktop look (every tab's applied design + options, and the wallpaper playlist) saved
as a named snapshot, and put back in one go through each tab's own apply().

Snapshots live in CONFIG/mural-looks.json (written atomically), thumbnails in CONFIG/mural-looks/<id>.png.
Restore runs on a worker thread: tabs' apply() may restart plasmashell or ask for a password.
"""
import json
import threading
import time
import uuid
from dataclasses import asdict
from datetime import datetime
from importlib import import_module
from pathlib import Path
from types import SimpleNamespace

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage

from grimoire.paths import CONFIG
from grimoire.spells.mural import plasma
from grimoire.spells.mural.screens import Design, load_state, save_state

FILE = CONFIG / "mural-looks.json"
THUMBS = CONFIG / "mural-looks"
THUMB_W, THUMB_H = 640, 360

# Restore order: the taskbar may restart plasmashell, so it goes first; the Style after it so the look's own
# Plasma style wins over the taskbar's; the wallpaper once plasmashell is surely back; root ones last.
ORDER = ["taskbar", "style", "colors", "icons", "cursor", "fonts", "windows", "motion", "terminal",
         "desktop", "lock", "splash", "login", "boot"]
ROOT = {"login", "boot"}             # these go through pkexec (a password prompt): only when ticked
LABELS = {"desktop": "Desktop", "lock": "Lock screen", "splash": "Splash", "login": "Login", "boot": "Boot",
          "taskbar": "Taskbar", "style": "Style", "windows": "Windows", "motion": "Motion", "colors": "Colors",
          "icons": "Icons", "fonts": "Fonts", "cursor": "Cursor", "terminal": "Terminal"}

_lock = threading.Lock()


# ---------------------------------------------------------------- storage
def _load() -> dict:
    try:
        data = json.loads(FILE.read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write(data: dict):
    FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    tmp.replace(FILE)           # atomic: a crash never leaves a half-written file


def _change(fn):
    """Read-modify-write under the lock; fn(data) edits data in place and returns a result."""
    with _lock:
        data = _load()
        result = fn(data)
        _write(data)
        return result


def all_looks() -> list[dict]:
    """Saved looks, newest first."""
    return sorted(_load().get("looks", []), key=lambda l: l.get("created", ""), reverse=True)


def get(look_id: str) -> dict | None:
    return next((l for l in _load().get("looks", []) if l.get("id") == look_id), None)


def thumb_path(look_id: str) -> Path:
    return THUMBS / f"{look_id}.png"


# ---------------------------------------------------------------- capture
def design_label(key: str, design_id: str) -> str:
    """A readable name for a design id (store names come from the store registry)."""
    from grimoire.spells.mural import store
    entry = store.registry().get(design_id.removeprefix("store:"))
    if entry and entry.get("name"):
        return entry["name"]
    if key == "lock" and design_id.startswith("img:"):
        return Path(design_id[4:]).stem
    return design_id.removeprefix("store:").split(":")[-1].split("/")[-1].replace("_", " ").replace("-", " ").title()


def capture() -> dict:
    """What MuraL has applied right now: {tabs: {key: {design, options, label}}, desktop: Settings or None}."""
    state = load_state()
    tabs = {}
    for key in ORDER:
        saved = state.get(key) or {}
        if key != "desktop" and saved.get("design"):
            tabs[key] = {"design": saved["design"], "options": saved.get("options") or {},
                         "label": design_label(key, saved["design"])}
    s = plasma.Settings.load()
    return {"tabs": tabs, "desktop": asdict(s) if s.items else None}


def render_thumb(snap: dict) -> QImage:
    """The desktop as the look has it: wallpaper with its taskbar when there is one (worker-thread safe)."""
    from grimoire.spells.mural import backdrop, taskbar
    backdrop.wallpaper.cache_clear()            # the wallpaper may have changed since the last preview
    bar = snap["tabs"].get("taskbar")
    if bar and bar["design"] in taskbar.LAYOUTS:
        try:
            return taskbar.render(bar["design"], bar["options"], THUMB_W, THUMB_H)
        except Exception as e:                  # a broken preview must never stop the save
            print(f"MuraL looks: taskbar thumbnail failed: {e}")
    for p in (snap.get("desktop") or {}).get("items", []):
        img = QImage(p)
        if not img.isNull():
            return img.scaled(THUMB_W, THUMB_H, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                              Qt.TransformationMode.SmoothTransformation).copy(0, 0, THUMB_W, THUMB_H)
    img = QImage(THUMB_W, THUMB_H, QImage.Format.Format_RGB32)
    img.fill(QColor("#0b0b0b"))
    return img


def save_current(name: str) -> dict:
    """Snapshot the current look under this name; returns the new record."""
    snap = capture()
    look = {"id": uuid.uuid4().hex[:12], "name": name.strip() or "Untitled look",
            "created": datetime.now().isoformat(timespec="seconds"), **snap}
    THUMBS.mkdir(parents=True, exist_ok=True)
    render_thumb(snap).save(str(thumb_path(look["id"])))
    _change(lambda d: d.setdefault("looks", []).append(look))
    return look


def default_name() -> str:
    names = {l.get("name") for l in all_looks()}
    n = 1
    while f"Look {n}" in names:
        n += 1
    return f"Look {n}"


def rename(look_id: str, name: str) -> bool:
    def fn(d):
        for l in d.get("looks", []):
            if l.get("id") == look_id:
                l["name"] = name.strip() or l["name"]
                return True
        return False
    return _change(fn)


def delete(look_id: str) -> bool:
    """Forget the snapshot (its record and the thumbnail MuraL drew for it). Never touches wallpapers or themes."""
    def fn(d):
        before = len(d.get("looks", []))
        d["looks"] = [l for l in d.get("looks", []) if l.get("id") != look_id]
        if (d.get("active") or {}).get("id") == look_id:
            d.pop("active")
        return len(d["looks"]) != before
    gone = _change(fn)
    thumb_path(look_id).unlink(missing_ok=True)        # our own generated preview, not a user file
    return gone


# ---------------------------------------------------------------- restore
def _tab_class(key: str):
    from grimoire.spells.mural.page import TABS
    _, _, module, cls = next(t for t in TABS if t[2] == key)
    return getattr(import_module(f"grimoire.spells.mural.{module}"), cls)


def _headless(key: str):
    """A tab's designs()/apply() never touch its widgets, so they run on a bare stand-in instead of building
    the whole tab (which would start rendering every preview)."""
    return _tab_class(key), SimpleNamespace(key=key)


def _apply_tab(key: str, entry: dict) -> str:
    cls, me = _headless(key)
    design = next((d for d in cls.designs(me) if d.id == entry["design"]), None)
    if design is None:
        if entry["design"].startswith("store:"):
            raise RuntimeError("not installed any more: get it again from Community")
        design = Design(entry["design"], entry.get("label") or entry["design"], "")   # e.g. an icon theme in use
    msg = cls.apply(me, design, entry["options"]) or "Applied ✓"
    save_state(key, {"design": design.id, "options": entry["options"]})
    return msg


def _apply_desktop(settings: dict) -> str:
    s = plasma.Settings(**{k: v for k, v in settings.items() if k in plasma.Settings.__dataclass_fields__})
    missing = [p for p in s.items if not Path(p).exists()]
    s.items = [p for p in s.items if Path(p).exists()]
    if not s.items:
        raise RuntimeError("its wallpapers aren't in your library any more")
    try:
        plasma.apply(s)
    except RuntimeError:            # plasmashell may still be coming back from the taskbar's restart
        time.sleep(2)
        plasma.apply(s)
    return "Applied ✓" + (f"  ({len(missing)} missing wallpaper(s) left out)" if missing else "")


def parts(look: dict) -> list[str]:
    """The keys a look can restore, in restore order."""
    return [k for k in ORDER if (k == "desktop" and look.get("desktop")) or k in look.get("tabs", {})]


def restore(look_id: str, include_root: set[str] = frozenset(), progress=None) -> list[tuple[str, bool, str]]:
    """Re-apply every part of the look; root parts only when in include_root. Returns [(key, ok, message)]
    (skipped parts count as ok with a "skipped" message). progress(key) is called before each part."""
    look = get(look_id)
    if look is None:
        raise RuntimeError("that look is gone")
    results, applied = [], []
    for key in parts(look):
        if key in ROOT and key not in include_root:
            results.append((key, True, "Skipped (needs your password; tick it to include)"))
            continue
        if progress:
            progress(key)
        try:
            msg = _apply_desktop(look["desktop"]) if key == "desktop" else _apply_tab(key, look["tabs"][key])
            results.append((key, True, msg))
            applied.append(key)
        except Exception as e:          # one broken part must not stop the rest
            results.append((key, False, f"Couldn't apply: {e}"))
    if applied:
        _change(lambda d: d.__setitem__("active", {"id": look_id, "parts": applied}))
    return results


def active_name() -> str | None:
    look = active()
    return look.get("name") if look else None


def active() -> dict | None:
    """The last restored look, while what it applied is still what's applied."""
    data = _load()
    act = data.get("active") or {}
    look = next((l for l in data.get("looks", []) if l.get("id") == act.get("id")), None)
    if look is None:
        return None
    state = load_state()
    for key in act.get("parts", []):
        if key == "desktop":
            if plasma.Settings.load().items != [p for p in look["desktop"]["items"] if Path(p).exists()]:
                return None
        elif (state.get(key) or {}).get("design") != look["tabs"][key]["design"] \
                or (state.get(key) or {}).get("options") != look["tabs"][key]["options"]:
            return None
    return look
