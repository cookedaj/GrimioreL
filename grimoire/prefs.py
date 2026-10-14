"""Grimoire-wide preferences (CONFIG/settings.json) and the "open Grimoire at login" autostart entry.

Kept tiny and Qt-free: the hub, the Settings page and backups all read it. Never holds a secret: the GitHub
sign-in lives in the system keyring (keystore.py), only the backup gist's id is remembered here.
"""
import json
import os
from pathlib import Path

from grimoire.paths import CONFIG

FILE = CONFIG / "settings.json"
DEFAULTS = {"auto_update": True, "gist_id": ""}


def load() -> dict:
    try:
        data = json.loads(FILE.read_text())
    except (OSError, ValueError):
        data = {}
    out = dict(DEFAULTS)
    if isinstance(data, dict):
        if isinstance(data.get("auto_update"), bool):
            out["auto_update"] = data["auto_update"]
        gid = data.get("gist_id")
        if isinstance(gid, str) and gid.isalnum() and len(gid) <= 64:     # gist ids are hex
            out["gist_id"] = gid
    return out


def save(**changes):
    d = load() | changes
    FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(d, indent=1))
    tmp.replace(FILE)


def auto_update() -> bool:
    """The Settings switch; GRIMOIRE_NO_UPDATE_CHECK=1 still turns the automatic check off whatever it says."""
    return load()["auto_update"] and not os.environ.get("GRIMOIRE_NO_UPDATE_CHECK")


# ---------------------------------------------------------------- open at login
def autostart_file() -> Path:
    """Read late, so a sandbox XDG_CONFIG_HOME works in tests (like tray.autostart_file)."""
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "autostart/grimoire.desktop"


def open_at_login() -> bool:
    return autostart_file().exists()


def set_open_at_login(on: bool):
    from grimoire.tray import command
    f = autostart_file()
    if on:
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("[Desktop Entry]\nType=Application\nName=Grimoire\nComment=Open Grimoire at login\n"
                     f"Exec={command('grimoire')}\nIcon=grimoire\nX-KDE-autostart-phase=2\n")
    else:
        f.unlink(missing_ok=True)          # a file Grimoire wrote itself
