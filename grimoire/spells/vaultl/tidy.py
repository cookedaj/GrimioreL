"""VaultL's tidy engine (TidyL before the merge): sort ~/Downloads by file type, send stale installers and
archives to the Trash, undo moves, and find big files and duplicates.

Safety rules: only loose files directly in the watched folder are touched (never folders, hidden files,
in-progress downloads or anything changed in the last 2 minutes); nothing is ever deleted: cleanup goes
to the Trash via `gio trash`, and every move is logged so it can be undone. Files on the settings' ignore
list are never touched. preview() is the dry run; run() uses the same plan()/cleanup_plan(), so they can't disagree.
"""
import hashlib
import json
import os
import shutil
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from grimoire.fsutil import free_name, trash
from grimoire.paths import CONFIG, DATA, HOME

SETTINGS = CONFIG / "vaultl.json"
LOG = DATA / "vaultl" / "log.jsonl"
LEGACY = {SETTINGS: CONFIG / "tidyl.json", LOG: DATA / "tidyl" / "log.jsonl"}    # TidyL's files, before VaultL
SETTLE_SECONDS = 120
PARTIAL = (".part", ".crdownload", ".download", ".tmp", ".partial", ".!qB", ".opdownload")
SIDECARS = PARTIAL + (".aria2",)   # Firefox/aria2 keep an empty "name.ext" next to "name.ext.part" while downloading


@dataclass
class Rule:
    name: str
    extensions: list[str]
    dest: str                     # "~/..." path
    enabled: bool = True
    clean_days: int = 0           # >0: files in dest older than this go to the Trash


def default_rules() -> list[Rule]:
    return [
        Rule("Images", ["png", "jpg", "jpeg", "gif", "webp", "bmp", "svg", "heic", "avif", "tif", "tiff"],
             "~/Pictures/Downloaded"),
        Rule("Videos", ["mp4", "mkv", "webm", "mov", "avi", "m4v", "flv"], "~/Videos"),
        Rule("Audio", ["mp3", "wav", "flac", "ogg", "m4a", "aac", "opus"], "~/Music"),
        Rule("Documents", ["pdf", "doc", "docx", "odt", "txt", "md", "rtf", "xls", "xlsx", "ods", "csv",
                           "ppt", "pptx", "odp", "epub"], "~/Documents"),
        Rule("Disk images", ["iso", "img"], "~/Documents/ISOs"),
        Rule("Roblox", ["rbxl", "rbxlx", "rbxm", "rbxmx"], "~/Documents/Roblox"),
        Rule("3D models", ["fbx", "blend", "obj", "glb", "gltf", "stl", "dae"], "~/Documents/3D"),
        Rule("Fonts", ["ttf", "otf", "woff", "woff2"], "~/Downloads/Fonts"),
        Rule("Installers", ["deb", "rpm", "appimage", "run", "flatpakref", "flatpak", "snap", "exe", "msi"],
             "~/Downloads/Installers", clean_days=14),
        Rule("Archives", ["zip", "7z", "rar", "tar", "gz", "tgz", "xz", "bz2", "zst"], "~/Downloads/Archives",
             clean_days=14),
    ]


@dataclass
class Settings:
    watch: str = "~/Downloads"
    auto: bool = True
    rules: list[Rule] = field(default_factory=default_rules)
    ignore: list[str] = field(default_factory=list)   # full paths the user said to always leave alone
    broken: bool = False          # the file exists but can't be read: run() does nothing rather than use defaults

    @classmethod
    def load(cls) -> "Settings":
        try:
            d = json.loads(SETTINGS.read_text())
            ignore = d.get("ignore", [])
            if not isinstance(ignore, list) or not all(isinstance(p, str) for p in ignore):
                raise TypeError("ignore must be a list of paths")
            return cls(watch=d.get("watch", "~/Downloads"), auto=d.get("auto", True),
                       rules=[Rule(**r) for r in d["rules"]], ignore=ignore)
        except FileNotFoundError:
            return cls()
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            return cls(broken=True)

    def save(self):
        SETTINGS.parent.mkdir(parents=True, exist_ok=True)
        d = asdict(self)
        d.pop("broken")
        tmp = SETTINGS.with_suffix(".tmp")
        tmp.write_text(json.dumps(d, indent=2))
        tmp.replace(SETTINGS)     # atomic, so the timer never reads a half-written file

    def skip_always(self, paths):
        """Add files to the ignore list (and forget entries whose file is gone, so the list stays short)."""
        keep = [p for p in self.ignore if Path(p).exists() or Path(p).is_symlink()]
        self.ignore = keep + [str(p) for p in paths if str(p) not in keep]
        self.save()


def migrate():
    """Carry TidyL's rules and undo log over to VaultL once. Copies, so the old files stay as a backup."""
    for new, old in LEGACY.items():
        if not new.exists() and old.is_file():
            new.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(old, new)


migrate()


def expand(p: str) -> Path:
    return Path(os.path.expanduser(p))


def _ext(path: Path) -> str:
    name = path.name.lower()
    for double in (".tar.gz", ".tar.xz", ".tar.bz2", ".tar.zst"):
        if name.endswith(double):
            return name.rsplit(".", 1)[-1]
    return path.suffix.lower().lstrip(".")


def _log(entry: dict):
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG, "a") as f:
        f.write(json.dumps({"time": time.time(), **entry}) + "\n")


def history(limit=200) -> list[dict]:
    """Newest-first log entries. A damaged line (e.g. a run cut off mid-write) is skipped, not fatal."""
    try:
        lines = LOG.read_text().splitlines()[-limit:]
    except OSError:
        return []
    out = []
    for line in reversed(lines):
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def trash_by_hand(path: Path, rule: str, reason: str):
    """Trash a file the user picked in VaultL (big files, duplicates) and log it. Raises OSError."""
    trash(path)
    _log({"action": "trash", "batch": "manual", "rule": rule, "from": str(path), "reason": reason})


# ---------------------------------------------------------------- sorting
def _age(st: os.stat_result, now: float) -> float:
    """Seconds since the file landed where it is. A move keeps mtime but updates ctime, so use the newer one."""
    return now - max(st.st_mtime, st.st_ctime)


def undone_files() -> dict[str, float]:
    """{path: when} for files an undo put back, so the next run doesn't sort them again."""
    out: dict[str, float] = {}
    for e in history(5000):
        if e["action"] == "undo":
            for f in e.get("files", []):
                out.setdefault(f, e["time"])
    return out


def plan(s: Settings) -> list[tuple[Path, Path, str]]:
    """[(file, destination, rule name)] for loose files that a rule matches."""
    watch = expand(s.watch)
    by_ext = {e: r for r in s.rules if r.enabled for e in r.extensions}
    ignore = set(s.ignore)
    now = time.time()
    moves = []
    if not watch.is_dir():
        return moves
    undone = undone_files()
    for f in sorted(watch.iterdir()):
        if not f.is_file() or f.is_symlink() or f.name.startswith(".") or str(f) in ignore:
            continue
        try:
            st = f.stat()
        except OSError:                       # vanished (a browser renaming its download)
            continue
        if now - st.st_mtime < SETTLE_SECONDS or f.name.lower().endswith(PARTIAL) \
                or any(f.with_name(f.name + x).exists() for x in SIDECARS):
            continue                          # still downloading / just landed
        if str(f) in undone and st.st_ctime <= undone[str(f)] + 5:
            continue                          # the user undid this move and hasn't touched the file since
        rule = by_ext.get(_ext(f))
        if not rule:
            continue
        dest_dir = expand(rule.dest)
        if dest_dir.resolve() == watch.resolve():
            continue
        moves.append((f, dest_dir / f.name, rule.name))
    return moves


def cleanup_plan(s: Settings) -> list[tuple[Path, str, str]]:
    """[(file, rule name, reason)] for stale files a rule's "Trash after" would send to the Trash.
    The one place that decides this, so the preview and run() can never disagree."""
    now = time.time()
    watch = expand(s.watch).resolve()
    ignore = set(s.ignore)
    out = []
    for rule in s.rules:
        if not rule.enabled or rule.clean_days <= 0:
            continue
        d = expand(rule.dest)
        if not d.is_dir() or d.resolve() in (watch, HOME.resolve(), *watch.parents):
            continue                          # cleanup only ever runs in a dedicated sorting folder
        exts = set(rule.extensions)
        for f in sorted(d.iterdir()):
            try:
                stale = f.is_file() and not f.is_symlink() and not f.name.startswith(".") \
                    and str(f) not in ignore and _ext(f) in exts and _age(f.stat(), now) > rule.clean_days * 86400
            except OSError:
                continue
            if stale:
                out.append((f, rule.name, f"older than {rule.clean_days} days"))
    return out


@dataclass
class Preview:
    """What a tidy pass would do right now. Nothing has moved yet."""
    moves: list[tuple[Path, Path, str]] = field(default_factory=list)     # (file, destination, rule)
    cleanups: list[tuple[Path, str, str]] = field(default_factory=list)   # (file, rule, reason)
    error: str = ""


def preview(s: Settings | None = None) -> Preview:
    """Dry run: the planned moves and cleanups, touching nothing."""
    s = s or Settings.load()
    if s.broken:
        return Preview(error=f"{SETTINGS} can't be read; nothing would be done")
    return Preview(plan(s), cleanup_plan(s))


def run(s: Settings | None = None, approved: Preview | None = None) -> dict:
    """One tidy pass: sort the watched folder, then clean stale files. Returns counts.
    With approved (a preview the user ticked through), only files in it are touched, and only if they are
    still planned now: nothing the user didn't see moves, and nothing that stopped qualifying does."""
    s = s or Settings.load()
    if s.broken:
        return {"moved": 0, "cleaned": 0, "errors": [f"{SETTINGS} can't be read; nothing done"]}
    ok_moves = None if approved is None else {str(f) for f, _, _ in approved.moves}
    ok_clean = None if approved is None else {str(f) for f, _, _ in approved.cleanups}
    batch = f"{time.time():.0f}"
    moved, cleaned, errors = 0, 0, []
    for src, dest, rule in plan(s):
        if ok_moves is not None and str(src) not in ok_moves:
            continue
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            final = free_name(dest)
            shutil.move(str(src), str(final))
            _log({"action": "move", "batch": batch, "rule": rule, "from": str(src), "to": str(final)})
            moved += 1
        except OSError as e:
            errors.append(f"{src.name}: {e}")
    for f, rule, reason in cleanup_plan(s):
        if ok_clean is not None and str(f) not in ok_clean:
            continue
        try:
            trash(f)
            _log({"action": "trash", "batch": batch, "rule": rule, "from": str(f), "reason": reason})
            cleaned += 1
        except OSError as e:
            errors.append(f"{f.name}: {e}")
    return {"moved": moved, "cleaned": cleaned, "errors": errors}


def undo_last() -> int:
    """Move the files of the most recent batch of moves back where they were. Returns how many."""
    entries = history(5000)
    done = undone_batches()
    batch = next((e["batch"] for e in entries if e["action"] == "move" and e["batch"] not in done), None)
    if batch is None:
        return 0
    back = []
    for e in entries:
        if e.get("batch") == batch and e["action"] == "move":
            src, dst = Path(e["to"]), Path(e["from"])
            if src.exists() and not dst.exists():
                try:
                    shutil.move(str(src), str(dst))
                    back.append(str(dst))
                except OSError:               # e.g. the watched folder is gone; leave the file where it is
                    continue
    _log({"action": "undo", "batch": batch, "count": len(back), "files": back})
    return len(back)


def undone_batches() -> set[str]:
    return {e["batch"] for e in history(5000) if e["action"] == "undo"}


# ---------------------------------------------------------------- insights
SKIP_DIRS = {".cache", ".local/share/Trash", ".var", "snap", ".local/share/flatpak", ".rokit", ".steam",
             ".local/share/Steam"}                       # relative to home
SKIP_NAMES = {".git", "node_modules", "__pycache__"}    # skipped at any depth


def _walk(root: Path, skip_repos=False):
    for dirpath, dirnames, filenames in os.walk(root):
        if skip_repos and ".git" in dirnames + filenames:     # a git repo or worktree (.git is a file there)
            dirnames[:] = []
            continue
        rel = os.path.relpath(dirpath, HOME)
        dirnames[:] = [d for d in dirnames if d not in SKIP_NAMES
                       and os.path.normpath(os.path.join(rel, d)) not in SKIP_DIRS]
        for name in filenames:
            p = Path(dirpath, name)
            try:
                if p.is_file() and not p.is_symlink():
                    yield p
            except OSError:
                continue


def biggest(root: Path = HOME, n=40, min_mb=50) -> list[tuple[int, Path]]:
    out = []
    for p in _walk(root):
        try:
            size = p.stat().st_size
        except OSError:
            continue
        if size >= min_mb * 1_000_000:
            out.append((size, p))
    return sorted(out, reverse=True)[:n]


def duplicates(roots=("~/Downloads", "~/Documents", "~/Pictures", "~/Videos", "~/Music", "~/Desktop"),
               min_kb=64) -> list[list[Path]]:
    """Groups of identical files (same size, then same SHA-1). Repo folders are left out on purpose."""
    by_size: dict[int, list[Path]] = {}
    seen: set[tuple[int, int]] = set()          # one file reached twice (symlinked root, hardlink) isn't a copy
    for r in roots:
        root = expand(r)
        if not root.is_dir():
            continue
        for p in _walk(root, skip_repos=True):   # code repos legitimately repeat files (worktrees etc.)
            try:
                st = p.stat()
            except OSError:
                continue
            size = st.st_size
            if (st.st_dev, st.st_ino) in seen:
                continue
            seen.add((st.st_dev, st.st_ino))
            if size >= min_kb * 1024:
                by_size.setdefault(size, []).append(p)
    groups: dict[tuple[int, str], list[Path]] = {}
    for size, paths in by_size.items():
        if len(paths) < 2:
            continue
        for p in paths:
            h = hashlib.sha1()
            try:
                with open(p, "rb") as f:
                    while chunk := f.read(1 << 20):
                        h.update(chunk)
            except OSError:
                continue
            groups.setdefault((size, h.hexdigest()), []).append(p)
    dupes = sorted(((size, g) for (size, _), g in groups.items() if len(g) > 1), key=lambda sg: -sg[0])
    return [sorted(g, key=lambda p: (len(str(p)), str(p))) for _, g in dupes]   # biggest first
