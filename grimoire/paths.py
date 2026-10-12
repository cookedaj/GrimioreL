"""Where Grimoire keeps its files (XDG locations)."""
import os
from pathlib import Path

HOME = Path.home()
DATA = Path(os.environ.get("XDG_DATA_HOME", HOME / ".local/share")) / "grimoire"
CONFIG = Path(os.environ.get("XDG_CONFIG_HOME", HOME / ".config")) / "grimoire"
CACHE = Path(os.environ.get("XDG_CACHE_HOME", HOME / ".cache")) / "grimoire"
ASSETS = Path(__file__).resolve().parent / "assets"

for _d in (DATA, CONFIG, CACHE):
    _d.mkdir(parents=True, exist_ok=True)
