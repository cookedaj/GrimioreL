"""Where Grimoire keeps its files (XDG locations)."""
import os
from pathlib import Path

HOME = Path.home()
DATA = Path(os.environ.get("XDG_DATA_HOME", HOME / ".local/share")) / "grimoire"
CONFIG = Path(os.environ.get("XDG_CONFIG_HOME", HOME / ".config")) / "grimoire"
CACHE = Path(os.environ.get("XDG_CACHE_HOME", HOME / ".cache")) / "grimoire"
ASSETS = Path(__file__).resolve().parent / "assets"
ROOT = Path(__file__).resolve().parent.parent      # this copy: a checkout, ~/.local/share/grimoire/app or a package's
SYSTEM_BIN = Path("/usr/bin")

for _d in (DATA, CONFIG, CACHE):
    _d.mkdir(parents=True, exist_ok=True)


def packaged() -> str:
    """'deb', 'arch'… when a distro package installed this copy system-wide (it leaves a PACKAGED file in ROOT), else
    "". A packaged copy is updated by the package manager, never by Grimoire's own updater."""
    try:
        return (ROOT / "PACKAGED").read_text().strip()[:20] or "package"
    except OSError:
        return ""


def command(name: str) -> Path:
    """What autostart entries, hotkeys and launches run: the ~/.local/bin link of a per-user install, else a system
    package's /usr/bin command, else this copy's own bin/."""
    link = HOME / ".local/bin" / name
    if link.exists():
        return link
    if packaged() and (SYSTEM_BIN / name).exists():
        return SYSTEM_BIN / name
    return ROOT / "bin" / name


def unit_command(name: str) -> str:
    """command() for a systemd user unit's ExecStart (%h keeps per-user units free of the home path)."""
    cmd = command(name)
    return f"%h/.local/bin/{name}" if cmd == HOME / ".local/bin" / name or not packaged() else str(cmd)
