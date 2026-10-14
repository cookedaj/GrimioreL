# SPDX-License-Identifier: GPL-3.0-or-later
"""Registry of spells (tools) shown in Grimoire. Add new spells to SPELLS."""
from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:               # background commands (alert checks, auto-tidy) import spells without loading Qt
    from PySide6.QtWidgets import QWidget


@dataclass(frozen=True)
class Spell:
    id: str
    name: str
    tagline: str
    page: Callable[[], "QWidget"]
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
    from grimoire.spells.mural.looks import active_name
    look = active_name()
    bits = ([f"Look · {look}"] if look else []) + bits
    return "   ".join(bits[:6]) or "Nothing applied yet"


def _sightc_status() -> str:
    from grimoire.spells.sightc import overlay
    return "Crosshair on · Ctrl+Alt+X hides it" if overlay.running_pid() else "Crosshair off"


def _vaultl():
    from grimoire.spells.vaultl.page import VaultLPage
    return VaultLPage()


def _vaultl_status() -> str:
    from grimoire.spells.vaultl import cli, tidy
    moved = sum(1 for e in tidy.history(2000) if e["action"] == "move")
    return "Default file manager · " + ("Auto-tidy on" if cli.timer_active() else "Auto-tidy off") \
        + f" · {moved} file(s) sorted so far"


def _optimizel():
    from grimoire.spells.optimizel.page import OptimizeLPage
    return OptimizeLPage()


def _optimizel_status() -> str:
    from grimoire.spells.optimizel import tweaks
    saved = tweaks.load_saved()
    on = sum(t.is_on() for t in tweaks.TWEAKS)
    waiting = sum(bool(tweaks.pending_note(t, saved)) for t in tweaks.TWEAKS)
    return f"{on} of {len(tweaks.TWEAKS)} optimizations on" + (f" · restart to finish {waiting}" if waiting else "")


def _systeml():
    from grimoire.spells.systeml.page import SystemLPage
    return SystemLPage()


def _systeml_status() -> str:
    import psutil
    from grimoire.spells.systeml import alerts
    mem = psutil.virtual_memory()
    return f"CPU {psutil.cpu_percent(interval=0.1):.0f}% · RAM {(mem.total - mem.available) / 2**30:.1f} of " \
        f"{mem.total / 2**30:.0f} GB · " + ("Alerts on" if alerts.enabled() else "Alerts off")


def _terminall():
    from grimoire.spells.terminall.page import TerminalLPage
    return TerminalLPage()


def _terminall_status() -> str:
    from grimoire.spells.terminall.page import status
    return status()


def _shotl():
    from grimoire.spells.shotl.page import ShotLPage
    return ShotLPage()


def _shotl_status() -> str:
    from grimoire.spells.shotl import shots
    return shots.status()


SPELLS = [
    Spell("mural", "MuraL", "Every screen and surface: wallpaper, lock, login, boot, taskbar, windows, colors, "
          "icons, fonts, cursor, terminal, plus the community store", _mural, "mural", _mural_status),
    Spell("sightc", "SightsL", "Crosshair overlay above every game, click-through", _sightc, "sight", _sightc_status),
    Spell("vaultl", "VaultL", "Your file manager with tidying built in: places, drives, previews, trash with "
          "restore, plus auto-sorted Downloads, undo, big files and duplicates", _vaultl, "vault", _vaultl_status),
    Spell("optimizel", "OptimizeL", "Tunes the PC for speed: CPU, memory, boot, network, startup apps and "
          "games. Every tweak is a switch that survives restarts and turns back off cleanly",
          _optimizel, "optimize", _optimizel_status),
    Spell("systeml", "SystemL", "Your system monitor: live graphs, processes, per-app history, services, startup "
          "apps, disks and background alerts", _systeml, "system", _systeml_status),
    Spell("terminall", "TerminalL", "Your terminal: tabs and splits, full color, scrollback search, profiles and "
          "saved commands, opening right in VaultL's folder", _terminall, "terminall", _terminall_status),
    Spell("shotl", "ShotL", "Screenshots and screen recordings: region, window or screen, a black & white editor "
          "to mark them up, and a gallery of every one", _shotl, "shot", _shotl_status),
]


def _focusl():
    from grimoire.spells.focusl.page import FocusLPage
    return FocusLPage()


def _focusl_status() -> str:
    from grimoire.spells.focusl import store
    return store.status_line()


SPELLS.append(Spell("focusl", "FocusL", "A focus timer in rounds with breaks: Do Not Disturb, no crosshair and your "
                    "distracting apps and sites kept away while you focus, plus your streak and stats",
                    _focusl, "focus", _focusl_status))


def _netl():
    from grimoire.spells.netl.page import NetLPage
    return NetLPage()


def _netl_status() -> str:
    from grimoire.spells.netl.probe import status_line
    return status_line()


SPELLS.append(Spell("netl", "NetL", "Your network: live traffic per interface and per app, connections, Wi-Fi and "
                    "VPN switches, and daily and monthly usage", _netl, "net", _netl_status))
