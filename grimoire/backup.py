# SPDX-License-Identifier: GPL-3.0-or-later
"""Backup & restore of Grimoire's settings: one .grimoire-backup file (a zip with a manifest.json).

What goes in: the settings JSONs in CONFIG (and MuraL's saved-look thumbnails), the small state JSONs in DATA and,
only when asked, MuraL's wallpaper library. Never caches, the installed app, logs, or machine "undo" state that only
makes sense on the PC that wrote it (OptimizeL's originals, store-installed.json: restoring someone else's could
make an uninstall target the wrong folder).

A backup is untrusted input (it may come from a gist or a download), so inspect() checks everything before
anything is written: a zip and nothing else, size and count caps, only known relative paths under the two roots,
no absolute or ".." paths, no links or special files, no encryption, every file listed in the manifest with its
size and sha256, JSON that parses. Unknown files are ignored and shown as such. Nothing in a backup is executed.
restore() saves a safety backup of the current files first, then writes each file atomically (temp + rename).

No Qt here: the Settings page and the GitHub backup both use it.
"""
import hashlib
import io
import json
import os
import re
import stat
import time
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from grimoire import __version__
from grimoire.paths import CONFIG, DATA

FORMAT = "grimoire-backup"
FORMAT_VERSION = 1
SUFFIX = ".grimoire-backup"
SAFETY = DATA / "backups"                      # automatic copies made before every restore
ROOTS = {"config": CONFIG, "data": DATA}
IMAGES = r"\.(?:png|jpe?g|webp)"
MEDIA = r"\.(?:png|jpe?g|webp|gif|bmp|mp4|webm|mkv|mov)"
SEG = r"[^/]+"                                 # one path segment; _segment_ok() does the real check
RULES = [                                      # (pattern on the archive path, kind)
    (re.compile(rf"config/{SEG}\.json"), "settings"),
    (re.compile(rf"config/mural-looks/{SEG}{IMAGES}", re.I), "settings"),
    (re.compile(rf"data/{SEG}\.json"), "settings"),
    (re.compile(rf"data/mural/library/{SEG}{MEDIA}", re.I), "library"),
]
EXCLUDE = {"data/optimizel.json", "data/performance-mode.json"}     # machine undo state, see above
MAX_ARCHIVE = 4 << 30                          # the whole file
MAX_TOTAL = 4 << 30                            # everything it expands to
MAX_FILES = 2000                               # entries of any kind
MAX_SIZE = {"settings": 8 << 20, "library": 1 << 30}
MAX_MANIFEST = 2 << 20


class BackupError(ValueError):
    """Why a backup can't be read or restored, worded for the UI."""


@dataclass
class Entry:
    path: str                                  # in the archive, e.g. "config/sightc.json"
    size: int
    sha256: str
    kind: str                                  # settings | library
    status: str = ""                           # new | changed | unchanged


@dataclass
class Plan:
    """What a backup would restore; made by inspect(), carried out by restore()."""
    entries: list = field(default_factory=list)
    ignored: list = field(default_factory=list)          # archive paths Grimoire doesn't know
    created: str = ""
    app_version: str = ""
    source: object = None                      # Path or bytes, re-read by restore()
    digest: str = ""                           # sha256 of the whole archive, so it can't change in between

    def count(self, status: str) -> int:
        return sum(e.status == status for e in self.entries)


# ---------------------------------------------------------------- paths
def _segment_ok(s: str) -> bool:
    return (s not in ("", ".", "..") and not s.startswith(".") and "\\" not in s and len(s.encode()) <= 255
            and not any(ord(c) < 32 or ord(c) == 127 for c in s))


def kind_of(name: str) -> str | None:
    """The kind of a known archive path, or None for anything Grimoire wouldn't write."""
    if name in EXCLUDE or name.startswith("/") or PurePosixPath(name).as_posix() != name:
        return None
    if not all(_segment_ok(s) for s in name.split("/")):
        return None
    for rx, kind in RULES:
        if rx.fullmatch(name):
            return kind
    return None


def target(name: str) -> Path:
    """Where an archive path lives on this PC; refuses anything that would land outside its root."""
    top, _, rest = name.partition("/")
    root = ROOTS[top]
    dest = root / rest
    if not dest.parent.resolve().is_relative_to(root.resolve()):
        raise BackupError(f"{name} would be written outside Grimoire's folders.")
    return dest


def collect(include_library=False) -> list[tuple[str, Path]]:
    """(archive path, file) for everything a backup of this PC holds. Links and odd files are skipped."""
    found = []
    for top, root in ROOTS.items():
        if not root.is_dir():
            continue
        for p in sorted(root.rglob("*")):
            rel = p.relative_to(root).as_posix()
            name = f"{top}/{rel}"
            kind = kind_of(name)
            if kind is None or (kind == "library" and not include_library):
                continue
            try:
                st = p.lstat()
            except OSError:
                continue
            if not stat.S_ISREG(st.st_mode) or st.st_size > MAX_SIZE[kind]:   # lstat: a link isn't S_ISREG
                continue
            found.append((name, p))
    return found


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------- export
def _write(out, include_library: bool) -> dict:
    files, manifest = collect(include_library), []
    with zipfile.ZipFile(out, "w") as z:
        for name, p in files:
            data = p.read_bytes()
            if name.endswith(".json"):
                try:
                    json.loads(data)
                except ValueError:
                    continue                          # a half-written or broken file isn't worth saving
            manifest.append({"path": name, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()})
            z.writestr(zipfile.ZipInfo(name, time.localtime()[:6]), data,
                       zipfile.ZIP_DEFLATED if name.endswith(".json") else zipfile.ZIP_STORED)
        meta = {"format": FORMAT, "format_version": FORMAT_VERSION, "app_version": __version__,
                "created": datetime.now(timezone.utc).isoformat(timespec="seconds"), "files": manifest}
        z.writestr("manifest.json", json.dumps(meta, indent=1), zipfile.ZIP_DEFLATED)
    return meta


def export(dest: Path, include_library=False) -> dict:
    """Write a backup to dest (atomically; dest's folder must exist). Returns its manifest."""
    tmp = dest.with_name(f".{dest.name}.tmp")
    try:
        with open(tmp, "wb") as f:
            meta = _write(f, include_library)
            f.flush()
            os.fsync(f.fileno())
        tmp.replace(dest)
    finally:
        tmp.unlink(missing_ok=True)                   # our own temp file, only left over on failure
    return meta


def export_bytes(include_library=False) -> bytes:
    buf = io.BytesIO()
    _write(buf, include_library)
    return buf.getvalue()


def default_name() -> str:
    return f"grimoire-{datetime.now().strftime('%Y-%m-%d')}{SUFFIX}"


# ---------------------------------------------------------------- inspect
def _open(source) -> zipfile.ZipFile:
    if isinstance(source, (bytes, bytearray)):
        if len(source) > MAX_ARCHIVE:
            raise BackupError("The backup is larger than the safety limit.")
        if not zipfile.is_zipfile(io.BytesIO(source)):
            raise BackupError("That isn't a Grimoire backup (not a zip file).")
        return zipfile.ZipFile(io.BytesIO(source))
    path = Path(source)
    try:
        st = path.stat()
    except OSError as e:
        raise BackupError(f"Couldn't open the backup: {e.strerror or e}") from None
    if not stat.S_ISREG(st.st_mode):
        raise BackupError("That isn't a file.")
    if st.st_size > MAX_ARCHIVE:
        raise BackupError("The backup is larger than the safety limit.")
    if not zipfile.is_zipfile(path):
        raise BackupError("That isn't a Grimoire backup (not a zip file).")
    return zipfile.ZipFile(path)


def _digest(source) -> str:
    return hashlib.sha256(source).hexdigest() if isinstance(source, (bytes, bytearray)) else _sha(Path(source))


def _read(z: zipfile.ZipFile, info: zipfile.ZipInfo, limit: int, sink=None) -> tuple[str, int]:
    """Stream one member (sha256, size), never past limit bytes; sink(chunk) gets the bytes if given."""
    h, n = hashlib.sha256(), 0
    with z.open(info) as f:
        while chunk := f.read(1 << 20):
            n += len(chunk)
            if n > limit:
                raise BackupError(f"{info.filename} is larger than it says (or than the limit).")
            h.update(chunk)
            if sink:
                sink(chunk)
    return h.hexdigest(), n


def _check_member(info: zipfile.ZipInfo):
    name = info.filename
    mode = info.external_attr >> 16
    if info.flag_bits & 0x1:
        raise BackupError("The backup is encrypted; Grimoire doesn't read those.")
    if stat.S_ISLNK(mode):
        raise BackupError(f"The backup contains a link ({name}); not restoring it.")
    if mode and stat.S_IFMT(mode) not in (0, stat.S_IFREG, stat.S_IFDIR):
        raise BackupError(f"The backup contains a special file ({name}); not restoring it.")
    parts = name.rstrip("/").split("/")
    if (name.startswith("/") or "\\" in name or "\x00" in name or re.match(r"[A-Za-z]:", name)
            or any(s in ("", ".", "..") for s in parts)):
        raise BackupError(f"The backup contains an unsafe path ({name!r}); not restoring it.")


def _manifest(z: zipfile.ZipFile) -> dict:
    try:
        info = z.getinfo("manifest.json")
    except KeyError:
        raise BackupError("That isn't a Grimoire backup (no manifest.json).") from None
    if info.file_size > MAX_MANIFEST:
        raise BackupError("The backup's manifest is too large.")
    raw = io.BytesIO()
    _read(z, info, MAX_MANIFEST, raw.write)
    try:
        meta = json.loads(raw.getvalue().decode())
    except (ValueError, UnicodeDecodeError, RecursionError):
        raise BackupError("The backup's manifest isn't valid JSON.") from None
    if not isinstance(meta, dict) or meta.get("format") != FORMAT:
        raise BackupError("That isn't a Grimoire backup.")
    v = meta.get("format_version")
    if not isinstance(v, int) or isinstance(v, bool) or v < 1:
        raise BackupError("The backup's manifest is damaged.")
    if v > FORMAT_VERSION:
        raise BackupError("This backup was made by a newer Grimoire; update Grimoire first.")
    files = meta.get("files")
    if not isinstance(files, list) or len(files) > MAX_FILES:
        raise BackupError("The backup's manifest is damaged.")
    listed = {}
    for f in files:
        ok = (isinstance(f, dict) and isinstance(f.get("path"), str) and isinstance(f.get("size"), int)
              and not isinstance(f.get("size"), bool) and f["size"] >= 0 and isinstance(f.get("sha256"), str)
              and re.fullmatch(r"[0-9a-f]{64}", f["sha256"]))
        if not ok or f["path"] in listed:
            raise BackupError("The backup's manifest is damaged.")
        listed[f["path"]] = f
    meta["files"] = listed
    return meta


def inspect(source) -> Plan:
    """Validate a backup (a path or bytes) completely and say what restoring it would change. Raises BackupError."""
    try:
        with _open(source) as z:                       # size-checked before anything is read
            digest = _digest(source)
            infos = z.infolist()
            if len(infos) > MAX_FILES:
                raise BackupError("The backup holds more files than the safety limit.")
            names = [i.filename for i in infos]
            if len(set(names)) != len(names):
                raise BackupError("The backup lists a file twice; not restoring it.")
            for info in infos:
                _check_member(info)
            meta = _manifest(z)
            plan = Plan(created=str(meta.get("created", ""))[:40], app_version=str(meta.get("app_version", ""))[:20],
                        source=source, digest=digest)
            listed, total = meta["files"], 0
            for info in infos:
                name = info.filename
                if info.is_dir() or name == "manifest.json":
                    continue
                kind = kind_of(name)
                if kind is None:
                    plan.ignored.append(name)
                    continue
                m = listed.pop(name, None)
                if m is None:
                    raise BackupError(f"{name} isn't in the backup's manifest; not restoring it.")
                if info.file_size != m["size"] or m["size"] > MAX_SIZE[kind]:
                    raise BackupError(f"{name} is larger than it says (or than the limit).")
                total += m["size"]
                if total > MAX_TOTAL:
                    raise BackupError("The backup expands larger than the safety limit.")
                buf = io.BytesIO() if name.endswith(".json") else None
                sha, size = _read(z, info, m["size"], buf.write if buf else None)
                if sha != m["sha256"] or size != m["size"]:
                    raise BackupError(f"{name} doesn't match the backup's manifest (damaged or altered).")
                if buf is not None:
                    try:
                        json.loads(buf.getvalue().decode())
                    except (ValueError, UnicodeDecodeError, RecursionError):
                        raise BackupError(f"{name} isn't valid JSON; not restoring it.") from None
                plan.entries.append(Entry(name, size, sha, kind))
            missing = [p for p in listed if kind_of(p)]
            if missing:
                raise BackupError(f"The backup is missing {missing[0]}, which its manifest lists.")
    except zipfile.BadZipFile as e:
        raise BackupError(f"The backup is damaged: {e}") from None
    except (zipfile.LargeZipFile, NotImplementedError, EOFError, RuntimeError) as e:
        raise BackupError(f"The backup can't be read: {e}") from None
    except OSError as e:
        raise BackupError(f"Couldn't read the backup: {e.strerror or e}") from None
    for e in plan.entries:
        dest = target(e.path)
        if dest.is_symlink() or (dest.exists() and not dest.is_file()):
            raise BackupError(f"{e.path} is a link or folder on this PC; not replacing it.")
        e.status = "new" if not dest.exists() else "unchanged" if _sha(dest) == e.sha256 else "changed"
    plan.entries.sort(key=lambda e: ({"changed": 0, "new": 1, "unchanged": 2}[e.status], e.path))
    return plan


# ---------------------------------------------------------------- restore
def safety_backup(include_library=False) -> Path:
    """A copy of the current settings, made before a restore, in DATA/backups (never overwritten)."""
    SAFETY.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d-%H%M%S")
    dest, n = SAFETY / f"before-restore-{stamp}{SUFFIX}", 2
    while dest.exists():
        dest, n = SAFETY / f"before-restore-{stamp} ({n}){SUFFIX}", n + 1
    export(dest, include_library)
    return dest


def restore(plan: Plan, progress=lambda text: None) -> tuple[Path, list[str]]:
    """Write every new or changed file of an inspected backup. Returns (safety backup, restored paths)."""
    todo = [e for e in plan.entries if e.status in ("new", "changed")]
    if not todo:
        return None, []
    if _digest(plan.source) != plan.digest:
        raise BackupError("The backup file changed since it was checked; open it again.")
    progress("Saving a safety backup…")
    safety = safety_backup(include_library=any(e.kind == "library" and e.status == "changed" for e in todo))
    done = []
    try:
        _write_all(plan, todo, done, progress)
    except BackupError as err:
        raise BackupError(f"{err} Your settings from before are saved in {safety}.") from None
    return safety, done


def _write_all(plan: Plan, todo: list, done: list, progress):
    try:
        with _open(plan.source) as z:
            for e in todo:
                progress(f"Restoring {e.path}…")
                dest = target(e.path)
                if dest.is_symlink():
                    raise BackupError(f"{e.path} became a link on this PC; stopped.")
                dest.parent.mkdir(parents=True, exist_ok=True)
                tmp = dest.with_name(f".{dest.name}.restore-tmp")
                try:
                    with open(tmp, "wb") as f:
                        sha, _ = _read(z, z.getinfo(e.path), e.size, f.write)
                        f.flush()
                        os.fsync(f.fileno())
                    if sha != e.sha256:
                        raise BackupError(f"{e.path} changed while restoring; stopped.")
                    tmp.replace(dest)
                finally:
                    tmp.unlink(missing_ok=True)       # our own temp file, only left over on failure
                done.append(e.path)
    except zipfile.BadZipFile as err:
        raise BackupError(f"The backup is damaged: {err}") from None
    except OSError as err:
        raise BackupError(f"Couldn't write {err.filename or 'a file'}: {err.strerror or err}") from None
