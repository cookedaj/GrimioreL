"""Registry of spells (tools) shown in Grimoire. Add new spells to SPELLS."""
from dataclasses import dataclass
from typing import Callable

from PySide6.QtWidgets import QWidget


@dataclass(frozen=True)
class Spell:
    id: str
    name: str
    tagline: str
    page: Callable[[], QWidget]
    icon: str                       # glyph name (grimoire/glyphs.py)
    status: Callable[[], str] = lambda: ""


def _mural():
    from grimoire.spells.mural.page import MuralPage
    return MuralPage()


def _sightc():
    from grimoire.spells.sightc.page import SightCPage
    return SightCPage()


def _mural_status() -> str:
    from grimoire.spells.mural.screens import load_state
    state = load_state()
    names = {"lock": "Lock", "splash": "Splash", "login": "Login", "boot": "Boot", "taskbar": "Taskbar",
             "terminal": "Terminal", "fonts": "Fonts", "cursor": "Cursor", "colors": "Colors", "style": "Style"}
    bits = [f"{label} · {state[k]['design'].removeprefix('store:').split(':')[-1].replace('_', ' ').title()}"
            for k, label in names.items() if k in state]
    return "   ".join(bits[:6]) or "Nothing applied yet"


def _sightc_status() -> str:
    from grimoire.spells.sightc import overlay
    return "Crosshair on · Ctrl+Alt+X hides it" if overlay.running_pid() else "Crosshair off"


def _tidyl():
    from grimoire.spells.tidyl.page import TidyLPage
    return TidyLPage()


def _tidyl_status() -> str:
    from grimoire.spells.tidyl import cli, engine
    moved = sum(1 for e in engine.history(2000) if e["action"] == "move")
    return ("Auto-tidy on" if cli.timer_active() else "Auto-tidy off") + f" · {moved} file(s) sorted so far"


SPELLS = [
    Spell("mural", "MuraL", "Every screen and surface: wallpaper, lock, login, boot, taskbar, windows, colors, "
          "icons, fonts, cursor, terminal, plus the community store", _mural, "mural", _mural_status),
    Spell("sightc", "SightsL", "Crosshair overlay above every game, click-through", _sightc, "sight", _sightc_status),
    Spell("tidyl", "TidyL", "Keeps Downloads sorted, clears stale installers, finds big files and duplicates",
          _tidyl, "tidy", _tidyl_status),
]
