"""TerminalL settings: profiles (font, size, cursor shape, scrollback) and saved palette commands, as JSON."""
import json

from grimoire.paths import CONFIG

FILE = CONFIG / "terminall.json"
CURSORS = ["block", "underline", "bar"]
PROFILE = {"font": "IBM Plex Mono", "size": 11, "cursor": "block", "scrollback": 10000}
LIMITS = {"size": (6, 40), "scrollback": (0, 200000)}
COMMANDS = [
    {"name": "Disk usage here", "command": "du -sh -- * .[!.]* 2>/dev/null | sort -h"},
    {"name": "Git status", "command": "git status -sb"},
    {"name": "Git log, last 20", "command": "git log --oneline --graph -20"},
    {"name": "Listening ports", "command": "ss -tulpn"},
    {"name": "Free space", "command": "df -h -x tmpfs -x devtmpfs"},
    {"name": "Biggest files here", "command": "find . -xdev -type f -printf '%s\\t%p\\n' 2>/dev/null | sort -n | tail -20"},
]


def clean_profile(data) -> dict:
    """A profile from untrusted JSON: unknown keys dropped, wrong types replaced, numbers clamped."""
    p = dict(PROFILE)
    if not isinstance(data, dict):
        return p
    if isinstance(data.get("font"), str) and 0 < len(data["font"]) < 80:
        p["font"] = data["font"]
    if data.get("cursor") in CURSORS:
        p["cursor"] = data["cursor"]
    for k, (lo, hi) in LIMITS.items():
        v = data.get(k)
        if isinstance(v, int) and not isinstance(v, bool):
            p[k] = min(hi, max(lo, v))
    return p


def load() -> dict:
    try:
        data = json.loads(FILE.read_text())
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    raw = data.get("profiles") if isinstance(data.get("profiles"), dict) else {}
    profiles = {str(k)[:40]: clean_profile(v) for k, v in raw.items() if str(k).strip()} or {"Default": dict(PROFILE)}
    current = data.get("profile") if data.get("profile") in profiles else next(iter(profiles))
    cmds = data.get("commands") if isinstance(data.get("commands"), list) else COMMANDS
    cmds = [{"name": str(c["name"])[:80], "command": str(c["command"])[:2000]} for c in cmds
            if isinstance(c, dict) and isinstance(c.get("name"), str) and isinstance(c.get("command"), str)]
    return {"profile": current, "profiles": profiles, "commands": cmds}


def save(cfg: dict):
    tmp = FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(cfg, indent=2))
    tmp.replace(FILE)
