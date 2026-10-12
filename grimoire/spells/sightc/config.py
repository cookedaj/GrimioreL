"""SightsL settings: one crosshair, saved as JSON. The overlay watches this file and redraws live."""
import json
from dataclasses import asdict, dataclass

from grimoire.paths import CONFIG

FILE = CONFIG / "sightc.json"
STYLES = ["Cross", "Cross + dot", "Dot", "Circle", "Circle + dot", "T", "Chevron"]
COLORS = {
    "White": "#ffffff", "Black": "#000000", "Green": "#00ff66", "Cyan": "#00e5ff",
    "Red": "#ff2a2a", "Yellow": "#ffe600", "Magenta": "#ff3df2",
}


@dataclass
class Crosshair:
    style: str = "Cross + dot"
    color: str = "#ffffff"
    opacity: float = 1.0        # 0..1
    size: int = 10              # arm length / circle radius (px)
    thickness: int = 2
    gap: int = 4                # empty space between center and arms
    dot: int = 2                # center dot radius (styles with a dot)
    outline: bool = True
    outline_width: int = 1
    outline_color: str = "#000000"
    offset_x: int = 0
    offset_y: int = 0

    @classmethod
    def load(cls) -> "Crosshair":
        try:
            data = json.loads(FILE.read_text())
            return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
        except (OSError, ValueError, TypeError):
            return cls()

    def save(self):
        tmp = FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(self), indent=2))
        tmp.replace(FILE)   # atomic, so the overlay never reads a half-written file
