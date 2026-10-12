"""Bridge to Plasma: applies MuraL settings to every desktop through plasmashell's scripting API."""
import json
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path

from PySide6.QtCore import QUrl

from grimoire.paths import CONFIG

PLUGIN = "com.cookedaj.grimoire.mural"
STATE = CONFIG / "mural.json"
FILL_MODES = {"Crop": 2, "Fit": 1, "Stretch": 0}


@dataclass
class Settings:
    items: list[str] = field(default_factory=list)   # absolute paths, in playlist order
    interval_min: int = 5
    fade_s: float = 1.2
    shuffle: bool = False
    fill: str = "Crop"
    pause_fullscreen: bool = True
    muted: bool = True

    @classmethod
    def load(cls) -> "Settings":
        try:
            data = json.loads(STATE.read_text())
            return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
        except (OSError, ValueError, TypeError):
            return cls()

    def save(self):
        STATE.write_text(json.dumps(asdict(self), indent=2))


def _js(value) -> str:
    """Python value -> JavaScript literal."""
    return json.dumps(value)


def apply(s: Settings):
    """Switch every desktop to MuraL and write its config. Raises RuntimeError on failure."""
    urls = [QUrl.fromLocalFile(str(Path(p))).toString() for p in s.items]
    values = {
        "Items": json.dumps(urls),
        "Interval": max(5, int(s.interval_min * 60)),
        "FadeMs": int(s.fade_s * 1000),
        "Shuffle": s.shuffle,
        "FillMode": FILL_MODES.get(s.fill, 2),
        "PauseOnFullscreen": s.pause_fullscreen,
        "Muted": s.muted,
    }
    writes = "\n".join(f"    d.writeConfig({_js(k)}, {_js(v)});" for k, v in values.items())
    script = f"""
var ds = desktops();
for (var i = 0; i < ds.length; i++) {{
    var d = ds[i];
    d.wallpaperPlugin = {_js(PLUGIN)};
    d.currentConfigGroup = ["Wallpaper", {_js(PLUGIN)}, "General"];
{writes}
}}
"""
    result = subprocess.run(
        ["qdbus6", "org.kde.plasmashell", "/PlasmaShell", "org.kde.PlasmaShell.evaluateScript", script],
        capture_output=True, text=True)
    if result.returncode != 0 or result.stdout.strip():
        raise RuntimeError((result.stderr or result.stdout).strip() or "plasmashell rejected the script")
    s.save()
