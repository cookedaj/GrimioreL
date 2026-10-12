"""SightsL settings: one crosshair, saved as JSON. The overlay watches this file and redraws live.

Saved profiles live next to it in sightc-profiles.json; built-in presets are in PRESETS below.
"""
import base64
import json
from dataclasses import asdict, dataclass, fields

from grimoire.paths import CONFIG

FILE = CONFIG / "sightc.json"
PROFILES_FILE = CONFIG / "sightc-profiles.json"
STYLES = ["Cross", "Cross + dot", "Dot", "Circle", "Circle + dot", "Circle + cross", "Square", "T", "Chevron"]
COLORS = {
    "White": "#ffffff", "Black": "#000000", "Green": "#00ff66", "Cyan": "#00e5ff",
    "Red": "#ff2a2a", "Yellow": "#ffe600", "Magenta": "#ff3df2",
}
# (min, max) for every number, so a hand-edited file or a pasted code can't produce something absurd
LIMITS = {"opacity": (0.05, 1.0), "size": (1, 60), "thickness": (1, 10), "gap": (0, 30), "dot": (0, 10),
          "outline_width": (0, 4), "offset_x": (-400, 400), "offset_y": (-400, 400), "rotation": (0, 90)}
CODE_PREFIX = "SL1-"


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
    rotation: int = 0           # degrees; 45 turns a cross into an X
    round_caps: bool = False
    screen: str = ""            # output name (e.g. "DP-3"); empty = primary screen

    @classmethod
    def from_dict(cls, data: dict) -> "Crosshair":
        """Build from untrusted data: unknown keys dropped, wrong types replaced by defaults, numbers clamped."""
        c = cls()
        for f in fields(cls):
            if f.name not in data:
                continue
            v, default = data[f.name], getattr(c, f.name)
            if isinstance(default, bool):
                ok = isinstance(v, bool)
            elif isinstance(default, (int, float)):
                ok = isinstance(v, (int, float)) and not isinstance(v, bool)
                if ok:
                    lo, hi = LIMITS.get(f.name, (v, v))
                    v = type(default)(min(hi, max(lo, v)))
            else:
                ok = isinstance(v, str) and len(v) < 64
            if ok:
                setattr(c, f.name, v)
        if c.style not in STYLES:
            c.style = cls.style
        for k in ("color", "outline_color"):
            if not (getattr(c, k).startswith("#") and len(getattr(c, k)) in (4, 7, 9)):
                setattr(c, k, getattr(cls, k))
        return c

    @classmethod
    def load(cls) -> "Crosshair":
        try:
            return cls.from_dict(json.loads(FILE.read_text()))
        except (OSError, ValueError, TypeError, AttributeError):
            return cls()

    def save(self):
        tmp = FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(self), indent=2))
        tmp.replace(FILE)   # atomic, so the overlay never reads a half-written file

    def copy(self, **changes) -> "Crosshair":
        return Crosshair(**{**asdict(self), **changes})

    def look(self) -> dict:
        """The settings that define how it looks (not which screen it is on)."""
        d = asdict(self)
        d.pop("screen")
        return d

    # ---------------------------------------------------------------- share codes
    def code(self) -> str:
        """A short text code (only the non-default settings) to share a crosshair."""
        base = Crosshair().look()
        diff = {k: v for k, v in self.look().items() if v != base[k]}
        raw = json.dumps(diff, separators=(",", ":")).encode()
        return CODE_PREFIX + base64.urlsafe_b64encode(raw).decode().rstrip("=")

    @classmethod
    def from_code(cls, text: str) -> "Crosshair | None":
        text = text.strip()
        if not text.startswith(CODE_PREFIX) or len(text) > 2000:
            return None
        body = text[len(CODE_PREFIX):]
        try:
            data = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
        except (ValueError, TypeError):
            return None
        return cls.from_dict(data) if isinstance(data, dict) else None


# ---------------------------------------------------------------- presets and saved profiles
PRESETS = {
    "Classic": Crosshair(),
    "Pro": Crosshair(style="Cross", size=6, thickness=1, gap=3, color="#00ff66"),
    "Dot": Crosshair(style="Dot", dot=3, thickness=1),
    "Ring": Crosshair(style="Circle + dot", size=12, thickness=1, dot=1),
    "Scope": Crosshair(style="Circle + cross", size=16, thickness=1, gap=6),
    "T": Crosshair(style="T", size=8, thickness=2, gap=3, color="#00e5ff"),
    "X": Crosshair(style="Cross", size=7, thickness=2, gap=3, rotation=45),
    "Chevron": Crosshair(style="Chevron", size=8, thickness=2, round_caps=True),
}


def load_profiles() -> dict[str, Crosshair]:
    try:
        data = json.loads(PROFILES_FILE.read_text())
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(k)[:40]: Crosshair.from_dict(v) for k, v in data.items() if isinstance(v, dict)}


def save_profiles(profiles: dict[str, Crosshair]):
    tmp = PROFILES_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps({k: c.look() for k, c in profiles.items()}, indent=2))
    tmp.replace(PROFILES_FILE)


def cycle_order() -> list[Crosshair]:
    """What the next-crosshair hotkey steps through: your saved profiles, or the presets if you have none."""
    return list(load_profiles().values()) or list(PRESETS.values())
