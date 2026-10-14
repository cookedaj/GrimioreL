"""LaunchL and Plasma: install the widget package, find the launcher in the panels, swap Kickoff for LaunchL in its
exact spot and put Kickoff back exactly as it was.

Everything that touches the panels is a plasmashell desktop script (evaluateScript). The script text is built by
replace_script()/restore_script() so it can be read and tested without running it. What a replacement changed is
recorded in CONFIG/launchl.json before anything runs, so "Restore Kickoff" can undo it later, even after a reboot.
No Qt here: uninstall.sh runs `python3 -m grimoire.spells.launchl restore`.
"""
import configparser
import json
import os
import shutil
import subprocess
import time
from pathlib import Path

from grimoire.paths import CONFIG, DATA

PLUGIN = "com.cookedaj.grimoire.launchl"
LAUNCHERS = ("org.kde.plasma.kickoff", "org.kde.plasma.kicker", "org.kde.plasma.kickerdash")
STATE = CONFIG / "launchl.json"
SPELLS_JSON = DATA / "launchl-spells.json"      # read by the widget: Grimoire's spells for its search
ICONS = DATA / "launchl-icons"


# ---- the package --------------------------------------------------------------------------------------------------

def _share() -> Path:
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share")


def source_dir() -> Path:
    """The package to install: from the installed app copy when there is one (nothing may point into a download),
    else from this checkout."""
    installed = DATA / "app" / "plasma" / PLUGIN
    return installed if installed.is_dir() else Path(__file__).resolve().parents[3] / "plasma" / PLUGIN


def installed_dir() -> Path:
    return _share() / "plasma" / "plasmoids" / PLUGIN


def _version(pkg: Path) -> str:
    try:
        return json.loads((pkg / "metadata.json").read_text())["KPlugin"]["Version"]
    except (OSError, ValueError, KeyError):
        return ""


def is_installed() -> bool:
    return (installed_dir() / "metadata.json").is_file()


def needs_update() -> bool:
    """True when the installed package differs from the one Grimoire ships (any file)."""
    src, dst = source_dir(), installed_dir()
    if not dst.is_dir():
        return False
    files = lambda d: {p.relative_to(d): p.read_bytes() for p in d.rglob("*") if p.is_file()}
    try:
        return files(src) != files(dst)
    except OSError:
        return True


def install():
    """Install or upgrade the widget with kpackagetool6. Raises RuntimeError with its message on failure."""
    src = source_dir()
    if not (src / "metadata.json").is_file():
        raise RuntimeError(f"LaunchL's package is missing from {src}")
    mode = "-u" if is_installed() else "-i"
    r = subprocess.run(["kpackagetool6", "--type", "Plasma/Applet", mode, str(src)], capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError((r.stderr or r.stdout).strip() or "kpackagetool6 failed")
    write_spells()


def uninstall_package():
    r = subprocess.run(["kpackagetool6", "--type", "Plasma/Applet", "-r", PLUGIN], capture_output=True, text=True)
    if r.returncode and is_installed():
        raise RuntimeError((r.stderr or r.stdout).strip() or "kpackagetool6 failed")


def write_spells():
    """The spells list LaunchL's search offers ("MuraL", "SightsL", ...), with each spell's icon as a PNG.
    Icons need Qt; without a display they're simply left out and the widget draws the clover instead."""
    from grimoire.spells import SPELLS
    entries = [{"id": s.id, "name": s.name, "tagline": s.tagline.split(":")[0].split(".")[0]} for s in SPELLS]
    try:
        from PySide6.QtWidgets import QApplication
        from grimoire.standalone import app_icon
        if QApplication.instance() or os.environ.get("QT_QPA_PLATFORM") == "offscreen":
            if not QApplication.instance():
                write_spells.app = QApplication([])             # painting needs one; kept alive here
            ICONS.mkdir(parents=True, exist_ok=True)
            for s, e in zip(SPELLS, entries):
                path = ICONS / f"{s.id}.png"
                app_icon(s.icon, 64).save(str(path))
                e["icon"] = str(path)
    except ImportError:
        pass
    SPELLS_JSON.write_text(json.dumps(entries, indent=1))


# ---- reading the panels (read-only) -------------------------------------------------------------------------------

def plasma_script(script: str) -> subprocess.CompletedProcess:
    return subprocess.run(["qdbus6", "org.kde.plasmashell", "/PlasmaShell", "org.kde.PlasmaShell.evaluateScript",
                           script], capture_output=True, text=True, timeout=20)


def _run(script: str) -> str:
    """Run a desktop script; returns what it printed. RuntimeError when plasmashell isn't there or the script threw."""
    try:
        r = plasma_script(script)
    except (OSError, subprocess.TimeoutExpired) as err:
        raise RuntimeError(f"couldn't reach plasmashell: {err}")
    out = r.stdout.strip()
    if r.returncode or out.startswith("Error:"):
        raise RuntimeError((r.stderr or out).strip() or "plasmashell rejected the script")
    return out


# dumps a widget's whole config (keys and nested groups) so it can be written back key by key
_DUMP_JS = """
function dumpConfig(w, path) {
    w.currentConfigGroup = path;
    var r = {keys: {}, groups: {}};
    var ks = w.configKeys;
    for (var i = 0; i < ks.length; i++) { r.keys[ks[i]] = w.readConfig(ks[i]); }
    var gs = w.configGroups;
    for (var j = 0; j < gs.length; j++) { r.groups[gs[j]] = dumpConfig(w, path.concat([gs[j]])); }
    w.currentConfigGroup = path;
    return r;
}
"""

SCAN_JS = _DUMP_JS + """
var out = [];
var ps = panels();
for (var i = 0; i < ps.length; i++) {
    var p = ps[i];
    p.currentConfigGroup = ["General"];
    var order = String(p.readConfig("AppletOrder", ""));
    p.currentConfigGroup = [];
    var ws = p.widgets();
    var list = [];
    for (var j = 0; j < ws.length; j++) {
        var w = ws[j];
        var g = w.geometry;
        var item = {id: w.id, type: w.type, shortcut: String(w.globalShortcut || ""),
                    geometry: {x: g.x, y: g.y, width: g.width, height: g.height}};
        if (LAUNCHERS.indexOf(w.type) >= 0) { item.config = dumpConfig(w, []); }
        list.push(item);
    }
    out.push({id: p.id, location: String(p.location), screen: p.screen, formFactor: String(p.formFactor),
              order: order, widgets: list});
}
print(JSON.stringify(out));
"""


def scan() -> list[dict]:
    """Every panel with its widgets in order; launchers (Kickoff, Kicker, LaunchL, ...) include their config."""
    script = f"var LAUNCHERS = {json.dumps(list(LAUNCHERS) + [PLUGIN])};\n" + SCAN_JS
    return json.loads(_run(script) or "[]")


def ordered(panel: dict) -> list[dict]:
    """A panel's widgets in their on-screen order (AppletOrder), unlisted ones at the end as the panel does."""
    order = [int(x) for x in panel.get("order", "").split(";") if x.strip().isdigit()]
    rank = {wid: i for i, wid in enumerate(order)}
    return sorted(panel["widgets"], key=lambda w: rank.get(w["id"], len(order) + w["id"]))


def in_panel(panels: list[dict] | None = None) -> bool:
    try:
        panels = scan() if panels is None else panels
    except (RuntimeError, ValueError):
        return False
    return any(w["type"] == PLUGIN for p in panels for w in p["widgets"])


def status() -> str:
    if not is_installed():
        return "Not installed"
    try:
        here = in_panel(scan())
    except (RuntimeError, ValueError):
        return "Installed · Plasma isn't answering"
    update = " · update ready" if needs_update() else ""
    return ("In your panel" if here else "Installed, not in your panel") + update


# ---- favorites ------------------------------------------------------------------------------------------------------
# All launchers share one set of favorites (activity stats, agent org.kde.plasma.favorites.applications); each launcher
# instance only keeps its own order of them, under its client id in kactivitymanagerd-statsrc.

def favorites_client(launcher: str, widget_id: int) -> str:
    """The activity-stats client id a Kickoff/Kicker instance keeps its favorites order under."""
    short = {"org.kde.plasma.kickerdash": "org.kde.plasma.kicker"}.get(launcher, launcher)
    return f"{short}.favorites.instance-{widget_id}"


def favorites(client: str) -> list[str]:
    """The favorites a client shows, in order (KActivities keeps the order in kactivitymanagerd-statsrc)."""
    cfg = configparser.ConfigParser(interpolation=None, strict=False)
    path = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "kactivitymanagerd-statsrc"
    try:
        cfg.read(path)
    except (configparser.Error, OSError):
        return []
    section = f"Favorites-{client}-global"
    if not cfg.has_section(section):
        section = next((s for s in cfg.sections() if s.startswith(f"Favorites-{client}-")), "")
    if not section:
        return []
    return [x for x in cfg.get(section, "ordering", fallback="").split(",") if x]


def write_order(client: str, favs: list[str]):
    """Give a (new) launcher instance the favorites order another one had. It reads it on its next start."""
    if not favs:
        return
    activity = subprocess.run(["qdbus6", "org.kde.ActivityManager", "/ActivityManager/Activities", "CurrentActivity"],
                              capture_output=True, text=True).stdout.strip()
    for suffix in ["global"] + ([activity] if activity else []):
        subprocess.run(["kwriteconfig6", "--file", "kactivitymanagerd-statsrc", "--group", f"Favorites-{client}-{suffix}",
                        "--key", "ordering", ",".join(favs)], capture_output=True)


def _old_style(fav: str) -> str:
    """'applications:org.kde.konsole.desktop' -> 'org.kde.konsole.desktop', the form Kickoff's portOldFavorites reads."""
    return fav.removeprefix("applications:")


# ---- replacing and restoring ----------------------------------------------------------------------------------------

def find_launcher(panels: list[dict]) -> tuple[dict, dict, int] | None:
    """(panel, widget, position) of the first Kickoff/Kicker/Dashboard in a panel."""
    for p in panels:
        for i, w in enumerate(ordered(p)):
            if w["type"] in LAUNCHERS:
                return p, w, i
    return None


def _js(v) -> str:
    return json.dumps(v)


def replace_script(record: dict) -> str:
    """Desktop script: add LaunchL right where the recorded launcher sits (the panel inserts a widget added at a
    point in front of whatever is there), point it at the same favorites, copy the global shortcut, then remove
    the old launcher. It checks everything before changing anything, and prints the new widget's id."""
    return f"""
var panel = panelById({_js(record["panel"])});
if (!panel) {{ throw new Error("the panel is gone"); }}
var old = panel.widgetById({_js(record["widget"])});
if (!old || old.type !== {_js(record["type"])}) {{ throw new Error("the launcher has moved since it was recorded"); }}
var g = old.geometry;
var x = Math.max(0, g.x + 1), y = Math.max(0, g.y + 1);
var w = panel.addWidget({_js(PLUGIN)}, x, y, g.width, g.height);
if (!w) {{ throw new Error("Plasma couldn't create LaunchL (is the widget installed?)"); }}
w.currentConfigGroup = ["General"];
w.writeConfig("favoritesClient", {_js(record["favorites_client"])});
w.writeConfig("favoritesPortedToKAstats", true);
w.currentConfigGroup = [];
var shortcut = {_js(record.get("shortcut", ""))};
if (shortcut) {{ old.globalShortcut = ""; w.globalShortcut = shortcut; }}
w.reloadConfig();
old.remove();
print(w.id);
""".strip() + "\n"


def _write_config_js(var: str, config: dict, path: list[str] | None = None) -> list[str]:
    """JS lines writing a dumpConfig() tree back into widget `var`."""
    path = path or []
    lines = []
    if config.get("keys"):
        lines.append(f"{var}.currentConfigGroup = {_js(path)};")
        lines += [f"{var}.writeConfig({_js(k)}, {_js(v)});" for k, v in config["keys"].items()]
    for name, sub in config.get("groups", {}).items():
        lines += _write_config_js(var, sub, path + [name])
    return lines


def restore_script(record: dict, favs: list[str]) -> str:
    """Desktop script: put the recorded launcher back where LaunchL now sits, with its recorded config and shortcut,
    then remove LaunchL. Prints the restored widget's id. The favorites list goes into its config too (Kickoff
    imports it only when no favorites exist at all, which then covers a wiped activity database)."""
    config = json.loads(json.dumps(record.get("config") or {}))       # a copy we can adjust
    general = config.setdefault("groups", {}).setdefault("General", {"keys": {}, "groups": {}})
    general.setdefault("keys", {})
    general["keys"]["favorites"] = [_old_style(f) for f in favs]
    general["keys"]["favoritesPortedToKAstats"] = False
    writes = "\n".join(_write_config_js("k", config))
    return f"""
var panel = panelById({_js(record["panel"])});
if (!panel) {{ throw new Error("the panel LaunchL replaced the launcher in is gone"); }}
var l = panel.widgetById({_js(record.get("launchl", -1))});
if (!l || l.type !== {_js(PLUGIN)}) {{
    l = null;
    var ws = panel.widgets({_js(PLUGIN)});
    if (ws.length) {{ l = ws[0]; }}
}}
var k;
if (l) {{
    var g = l.geometry;
    k = panel.addWidget({_js(record["type"])}, Math.max(0, g.x + 1), Math.max(0, g.y + 1), g.width, g.height);
}} else {{
    k = panel.addWidget({_js(record["type"])});
}}
if (!k) {{ throw new Error("Plasma couldn't create the launcher"); }}
{writes}
k.currentConfigGroup = [];
var shortcut = {_js(record.get("shortcut", ""))};
if (l && l.globalShortcut) {{ shortcut = String(l.globalShortcut); l.globalShortcut = ""; }}
if (shortcut) {{ k.globalShortcut = shortcut; }}
k.reloadConfig();
if (l) {{ l.remove(); }}
print(k.id);
""".strip() + "\n"


def load_state() -> dict:
    try:
        return json.loads(STATE.read_text())
    except (OSError, ValueError):
        return {}


def save_state(state: dict):
    STATE.write_text(json.dumps(state, indent=1))


def plan_replace(panels: list[dict] | None = None) -> dict:
    """Record the launcher LaunchL would replace: panel, widget, position, geometry, config, shortcut, favorites.
    Raises RuntimeError when there's nothing to replace."""
    panels = scan() if panels is None else panels
    if in_panel(panels):
        raise RuntimeError("LaunchL is already in your panel")
    found = find_launcher(panels)
    if not found:
        raise RuntimeError("no Kickoff, Kicker or Application Dashboard found in your panels")
    panel, widget, position = found
    client = favorites_client(widget["type"], widget["id"])
    return {"panel": panel["id"], "widget": widget["id"], "type": widget["type"], "position": position,
            "order": [w["id"] for w in ordered(panel)], "geometry": widget["geometry"],
            "config": widget.get("config", {}), "shortcut": widget.get("shortcut", ""),
            "favorites_client": client, "favorites": favorites(client),
            "recorded": time.strftime("%Y-%m-%dT%H:%M:%S%z")}


def replace(dry_run: bool = False) -> dict:
    """Swap the panel's launcher for LaunchL. The record is saved before the script runs. dry_run returns the
    record with the script in it and changes nothing."""
    if not is_installed():
        raise RuntimeError("install LaunchL first")
    record = plan_replace()
    record["script"] = replace_script(record)
    if dry_run:
        return record
    state = load_state()
    state["replaced"] = record
    save_state(state)
    out = _run(record["script"])
    record["launchl"] = int(out.splitlines()[-1]) if out and out.splitlines()[-1].isdigit() else -1
    record.pop("script", None)
    record["check"] = _position_check(record)
    state["replaced"] = record
    save_state(state)
    return record


def _position_check(record: dict) -> str:
    """'' when LaunchL ended up at the recorded position, else what happened (the swap itself still worked)."""
    try:
        panel = next(p for p in scan() if p["id"] == record["panel"])
    except (StopIteration, RuntimeError, ValueError):
        return "couldn't read the panel back"
    ids = [w["id"] for w in ordered(panel)]
    if record.get("launchl") in ids and ids.index(record["launchl"]) == record["position"]:
        return ""
    return f"LaunchL landed at position {ids.index(record['launchl']) + 1 if record.get('launchl') in ids else '?'}" \
        f" instead of {record['position'] + 1}; drag it into place in Edit Mode"


def restore(dry_run: bool = False) -> dict:
    """Put the recorded launcher back where LaunchL is and remove LaunchL, then give it the favorites order LaunchL
    had (the same client as the old launcher, so reordering done meanwhile carries over)."""
    record = load_state().get("replaced")
    if not record:
        raise RuntimeError("there's no recorded launcher to restore")
    favs = favorites(record["favorites_client"]) or record.get("favorites", [])
    script = restore_script(record, favs)
    if dry_run:
        return {"script": script, **record}
    out = _run(script)
    new_id = int(out.splitlines()[-1]) if out and out.splitlines()[-1].isdigit() else -1
    if new_id >= 0:
        write_order(favorites_client(record["type"], new_id), favs)
    state = load_state()
    state.pop("replaced", None)
    state["restored"] = {"type": record["type"], "panel": record["panel"], "widget": new_id,
                         "at": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
    save_state(state)
    return record


def can_restore() -> bool:
    return bool(load_state().get("replaced"))


def cleanup_icons():
    """Generated icons only (Grimoire's own files)."""
    shutil.rmtree(ICONS, ignore_errors=True)
