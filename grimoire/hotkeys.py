# SPDX-License-Identifier: GPL-3.0-or-later
"""Grimoire's global shortcuts, read and changed through KDE's KGlobalAccel over D-Bus.

Two sorts:
  action   a shortcut a running Grimoire process registers itself (SightsL's overlay: toggle / next crosshair).
           Any KGlobalAccel component named grimoire-* shows up too, so new spells' hotkeys appear on their own.
  command  a suggested Grimoire command (open Grimoire, tidy Downloads, ShotL captures…). KDE binds commands to
           .desktop components whose "_launch" action runs the file's Exec, which is what System Settings'
           "Add Command" does; Grimoire writes a hidden grimoire-hotkey-<id>.desktop for each one you bind.

Conflicts are checked against every other component's shortcuts (allShortcutInfos) before writing, since KDE would
silently drop a key that's already taken. All D-Bus goes through BUS (busctl --json), so tests swap in a stub.
"""
import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from grimoire import standalone

SERVICE, ROOT, IFACE = "org.kde.kglobalaccel", "/kglobalaccel", "org.kde.KGlobalAccel"
COMPONENT_IFACE = "org.kde.kglobalaccel.Component"
LAUNCH = "_launch"
CTRL, ALT, SHIFT, META = 0x04000000, 0x08000000, 0x02000000, 0x10000000


@dataclass
class Hotkey:
    component: str                 # KGlobalAccel unique name, e.g. "grimoire-sightc" or "grimoire-hotkey-tidy.desktop"
    action: str
    component_name: str            # friendly names, as KDE's Shortcuts settings show them
    name: str
    default: int = 0               # Qt key code; 0 = none
    kind: str = "action"           # action | command
    command: tuple = ()            # for commands: bin name + arguments
    keys: tuple = ()               # bound right now

    @property
    def id(self) -> list[str]:
        """KGlobalAccel's actionId: component, action, component friendly name, action friendly name."""
        return [self.component, self.action, self.component_name, self.name]


# ---------------------------------------------------------------- the catalog
def _sightsl() -> list[Hotkey]:
    from grimoire.spells.sightc import overlay
    return [Hotkey(overlay.COMPONENT, a, "Grimoire SightsL", name, key)
            for a, (name, key) in overlay.HOTKEYS.items()]


COMMANDS = [   # id, name, bin name + args; shown only when that command exists in bin/
    ("open", "Open Grimoire Linux", ("grimoire",)),
    ("tidy", "Tidy Downloads now", ("grimoire-vaultl", "tidy", "run")),
    ("crosshair", "Show/hide crosshair (start it if it's off)", ("grimoire-sightc", "toggle")),
    ("terminal", "Open TerminalL", ("grimoire-terminall",)),
    ("monitor", "Open SystemL", ("grimoire-systeml",)),
    ("shot-region", "Screenshot a region", ("grimoire-shotl", "region")),
    ("shot-window", "Screenshot a window", ("grimoire-shotl", "window")),
    ("shot-full", "Screenshot the whole screen", ("grimoire-shotl", "full")),
    ("record", "Start/stop screen recording", ("grimoire-shotl", "record", "toggle")),
]


def _commands() -> list[Hotkey]:
    return [Hotkey(f"grimoire-hotkey-{cid}.desktop", LAUNCH, f"Grimoire: {name}", name, 0, "command", cmd)
            for cid, name, cmd in COMMANDS if (standalone.BIN / cmd[0]).is_file()]


def catalog() -> list[Hotkey]:
    return _sightsl() + _commands()


# ---------------------------------------------------------------- D-Bus (through busctl, like overlay.py)
class Busctl:
    """The real thing. Every method returns busctl's decoded JSON "data" list."""

    def call(self, path: str, iface: str, method: str, sig: str = "", *args) -> list:
        cmd = ["busctl", "--user", "--json=short", "call", SERVICE, path, iface, method]
        if sig:
            cmd += [sig, *map(str, args)]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        except (OSError, subprocess.SubprocessError) as e:
            raise HotkeyError(f"Couldn't reach KDE's shortcut service: {e}") from None
        if r.returncode != 0:
            raise HotkeyError("KDE's shortcut service said: " + (r.stderr.strip() or f"exit {r.returncode}"))
        if not r.stdout.strip():
            return []
        try:
            return json.loads(r.stdout).get("data", [])
        except ValueError:
            raise HotkeyError("KDE's shortcut service sent an unexpected answer.") from None


BUS = Busctl()


class HotkeyError(RuntimeError):
    pass


def _as(items: list[str]) -> list:
    return [len(items), *items]


def all_shortcuts() -> list[dict]:
    """Every shortcut KDE knows: {component, component_name, action, name, keys, defaults}."""
    out = []
    for path in (BUS.call(ROOT, IFACE, "allComponents") or [[]])[0]:
        try:
            infos = (BUS.call(path, COMPONENT_IFACE, "allShortcutInfos") or [[]])[0]
        except HotkeyError:
            continue                                   # a component that went away meanwhile
        for action, name, comp, comp_name, *_ctx, keys, defaults in infos:
            out.append({"component": comp, "component_name": comp_name, "action": action, "name": name,
                        "keys": [k for k in keys if k], "defaults": [k for k in defaults if k]})
    return out


def load() -> tuple[list[Hotkey], list[dict]]:
    """Grimoire's hotkeys with their current keys, plus everything else (for conflict checks)."""
    everything = all_shortcuts()
    current = {(s["component"], s["action"]): s for s in everything}
    hotkeys = catalog()
    known = {(h.component, h.action) for h in hotkeys}
    for s in everything:                               # other grimoire components (new spells), as is
        if s["component"].startswith("grimoire") and (s["component"], s["action"]) not in known:
            hotkeys.append(Hotkey(s["component"], s["action"], s["component_name"], s["name"],
                                  (s["defaults"] or [0])[0]))
    for h in hotkeys:
        s = current.get((h.component, h.action))
        # not registered yet (the overlay never ran): its default is what it will get
        h.keys = tuple(s["keys"]) if s else ((h.default,) if h.default and h.kind == "action" else ())
    return hotkeys, everything


def check(key: int) -> str:
    """Why key makes a poor global shortcut ("" when fine): plain letters would fire while you type."""
    if not key:
        return ""
    base, mods = key & 0x01FFFFFF, key & (CTRL | ALT | META)
    special = 0x01000030 <= base <= 0x01000052 or base == 0x01000009 or base >= 0x01000060   # F-keys, Print, media
    return "" if mods or special else "Add Ctrl, Alt or Meta to it, so it doesn't fire while you type."


def conflicts(key: int, hotkey: Hotkey, everything: list[dict]) -> list[str]:
    """Who else uses key, as "Component: Action" (empty when it's free)."""
    if not key:
        return []
    return [f"{s['component_name']}: {s['name']}" for s in everything
            if key in s["keys"] and (s["component"], s["action"]) != (hotkey.component, hotkey.action)]


def _desktop_file(h: Hotkey) -> Path:
    share = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share")
    return share / "applications" / h.component


def _quote(arg: str) -> str:
    """Desktop-entry Exec quoting (the spec's double quotes and backslashes)."""
    if not any(c in arg for c in ' \t"\'\\$`<>|&;*?#()'):
        return arg
    return '"' + "".join("\\" + c if c in '"`$\\' else c for c in arg) + '"'


def _write_desktop(h: Hotkey):
    from grimoire.tray import command
    exe, *args = h.command
    f = _desktop_file(h)
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("[Desktop Entry]\nType=Application\n"
                 f"Name={h.component_name}\nExec={' '.join(_quote(a) for a in [str(command(exe)), *args])}\n"
                 "Icon=grimoire\nNoDisplay=true\nX-KDE-GlobalAccel-CommandShortcut=true\n")


def apply(h: Hotkey, key: int, everything: list[dict]) -> tuple[int, ...]:
    """Bind h to key (0 clears it). Refuses a key another shortcut uses. Returns the keys KDE now reports."""
    if check(key):
        raise HotkeyError(check(key))
    taken = conflicts(key, h, everything)
    if taken:
        raise HotkeyError(f"Already used by {taken[0]}" + (f" and {len(taken) - 1} more" if len(taken) > 1 else ""))
    if h.kind == "command":
        if key:
            _write_desktop(h)
        else:                                          # cleared: forget the component and its hidden launcher
            BUS.call(ROOT, IFACE, "unRegister", "as", *_as(h.id))
            _desktop_file(h).unlink(missing_ok=True)   # a file Grimoire wrote itself
            return ()
    BUS.call(ROOT, IFACE, "doRegister", "as", *_as(h.id))
    keys = [key] if key else []
    BUS.call(ROOT, IFACE, "setForeignShortcut", "asai", *_as(h.id), len(keys), *keys)
    got = (BUS.call(ROOT, IFACE, "shortcut", "as", *_as(h.id)) or [[]])[0]
    got = tuple(k for k in got if k)
    if key and key not in got:
        raise HotkeyError("KDE didn't accept that key (it may be reserved).")
    return got


def reset(h: Hotkey, everything: list[dict]) -> tuple[int, ...]:
    return apply(h, h.default, everything)


def text(key: int) -> str:
    """A Qt key code as KDE writes it, e.g. "Ctrl+Alt+X"."""
    from PySide6.QtGui import QKeySequence
    return QKeySequence(key).toString(QKeySequence.SequenceFormat.NativeText) if key else ""
