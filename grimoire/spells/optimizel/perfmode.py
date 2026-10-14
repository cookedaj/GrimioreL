"""Performance mode: a few OptimizeL tweaks for gaming switched on together (from the tray), and off again.

It only flips tweaks that are off right now, and remembers exactly which ones it flipped, so "off" turns back
just those and leaves anything you switched on yourself in OptimizeL alone. All of them work instantly:

    performance   Performance power profile   (yours, no password)
    baloo         file indexing paused         (yours, no password)
    splitlock     split-lock throttling off    (system: one password prompt through OptimizeL's root helper)
"""
import json

from grimoire.paths import DATA
from grimoire.spells.optimizel import tweaks

NAMES = {"performance": "performance power profile", "baloo": "file indexing paused",
         "splitlock": "split-lock throttling off"}
IDS = tuple(NAMES)
STATE = DATA / "performance-mode.json"


def load() -> dict:
    try:
        d = json.loads(STATE.read_text())
        if isinstance(d, dict) and isinstance(d.get("changed"), list):
            return {"on": bool(d.get("on")), "changed": [i for i in d["changed"] if i in tweaks.BY_ID]}
    except (OSError, ValueError):
        pass
    return {"on": False, "changed": []}


def _save(d: dict):
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, indent=1))
    tmp.replace(STATE)


def is_on() -> bool:
    return load()["on"]


def describe(ids) -> str:
    return ", ".join(NAMES.get(i, i) for i in ids)


def turn_on(apply=tweaks.apply) -> dict:
    """Switch on whichever of IDS are off (not native, not unavailable). Slow (subprocesses, maybe a password
    prompt): call it off the UI thread. Returns {"changed": [...], "problems": [...]}."""
    d = load()
    todo = [i for i in IDS if i not in d["changed"] and tweaks.BY_ID[i].state() == "off"]
    problems = apply({i: True for i in todo}) if todo else []
    done = [i for i in todo if tweaks.BY_ID[i].is_on()]          # a cancelled password prompt changes nothing
    _save({"on": True, "changed": d["changed"] + done})
    return {"changed": done, "problems": problems}


def turn_off(apply=tweaks.apply) -> dict:
    """Turn back only what turn_on() changed. Whatever couldn't be undone (e.g. a cancelled prompt) stays
    recorded and the mode stays on, so the next "off" tries again. Returns {"changed", "problems", "left"}."""
    d = load()
    todo = [i for i in d["changed"] if tweaks.BY_ID[i].is_on()]   # you may have turned some off in OptimizeL
    problems = apply({i: False for i in todo}) if todo else []
    left = [i for i in todo if tweaks.BY_ID[i].is_on()]
    _save({"on": bool(left), "changed": left})
    return {"changed": [i for i in todo if i not in left], "problems": problems, "left": left}
