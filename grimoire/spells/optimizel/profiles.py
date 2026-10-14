"""One-click profiles: each is a plan of switches to flip, worked out from the latest scan, shown to you before
anything happens and then applied in one batch (one password prompt).

    recommended   every Safe, recommended tweak that's off
    max           Recommended plus everything else that speeds this PC up, Aggressive ones included (never CPU
                  mitigations, never ones that only remove features you might use)
    battery       turns off the tweaks that cost power or heat (only on PCs with a battery)
    restore       turns every OptimizeL change off, back to exactly how it was
"""
from dataclasses import dataclass

from grimoire.spells.optimizel import tweaks


@dataclass
class Profile:
    id: str
    name: str
    blurb: str


PROFILES = [
    Profile("recommended", "Recommended", "Safe tweaks only. Nothing can break; all undo with one click."),
    Profile("max", "Max performance", "Safe and Aggressive tweaks for speed. Read what each Aggressive one risks."),
    Profile("battery", "Battery / quiet", "Turns off the tweaks that cost power, heat or fan noise."),
    Profile("restore", "Restore everything", "Every OptimizeL change off, back to exactly how it was."),
]
BY_ID = {p.id: p for p in PROFILES}


def available() -> list[Profile]:
    return [p for p in PROFILES if p.id != "battery" or tweaks.has_battery()]


def plan(pid: str, states: dict[str, str]) -> dict[str, bool]:
    """{tweak id: turn on?} for this profile, given each tweak's scanned state."""
    out = {}
    for t in tweaks.TWEAKS:
        s = states.get(t.id)
        safe_pick = t.tier == "Safe" and t.recommended
        if pid == "recommended" and s == "off" and safe_pick:
            out[t.id] = True
        elif pid == "max" and s == "off" and (t.in_max or safe_pick):
            out[t.id] = True
        elif pid == "battery" and s == "on" and t.power:
            out[t.id] = False
        elif pid == "restore" and s == "on":
            out[t.id] = False
    return out
