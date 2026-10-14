"""VaultL file operations. Everything goes through the normal Linux/KDE system: plain filesystem calls for
copy/move/rename, and `gio` for the Trash (the same freedesktop Trash Dolphin uses)."""
import os
import shutil
import time
from pathlib import Path
from urllib.parse import unquote

from grimoire.fsutil import free_name
from grimoire.fsutil import trash as trash_one
from grimoire.paths import HOME

TRASH_FILES = HOME / ".local/share/Trash/files"


def transfer(sources: list[Path], dest_dir: Path, move: bool, progress=None) -> tuple[int, list[str]]:
    """Copy or move sources into dest_dir. Returns (done, errors). Refuses to put a folder inside itself."""
    done, errors = 0, []
    for i, src in enumerate(sources):
        if progress:
            progress(i, len(sources), src.name)
        try:
            if src.is_dir() and (dest_dir.resolve() == src.resolve() or src.resolve() in dest_dir.resolve().parents):
                raise OSError("can't put a folder inside itself")
            if move and src.parent.resolve() == dest_dir.resolve():
                continue                                    # moving onto itself: nothing to do
            target = free_name(dest_dir / src.name)
            if move:
                shutil.move(str(src), str(target))
            elif src.is_dir() and not src.is_symlink():
                shutil.copytree(src, target, symlinks=True)
            else:
                shutil.copy2(src, target, follow_symlinks=False)
            done += 1
        except OSError as e:
            errors.append(f"{src.name}: {e.strerror or e}")
    return done, errors


def trash(paths: list[Path]) -> list[str]:
    """Send paths to the Trash. Returns one message per item that failed."""
    errors = []
    for p in paths:
        try:
            trash_one(p)
        except OSError as e:
            errors.append(f"{p.name}: {e}")
    return errors


def in_trash(path: Path) -> bool:
    try:
        return path.resolve().is_relative_to(TRASH_FILES.resolve())
    except OSError:
        return False


def restore(paths: list[Path]) -> list[str]:
    """Put trashed items back where they came from, per the freedesktop Trash spec (what KDE/Dolphin use):
    read the item's .trashinfo, move it back (recreating the folder; never overwriting), drop the .trashinfo."""
    errors = []
    for p in paths:
        orig = original_location(p)
        if not orig:
            errors.append(f"{p.name}: no record of where it came from")
            continue
        try:
            target = free_name(Path(orig))
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(p), str(target))
            _info_path(p).unlink(missing_ok=True)
        except OSError as e:
            errors.append(f"{p.name}: {e.strerror or e}")
    return errors


def _info_path(path: Path) -> Path:
    return TRASH_FILES.parent / "info" / (path.name + ".trashinfo")


def original_location(path: Path) -> str:
    """Where a trashed item came from ("" if unknown). Only top-level Trash items have a record: a file
    inside a trashed folder must not borrow the record of a different trashed item with the same name."""
    try:
        if path.parent.resolve() != TRASH_FILES.resolve():
            return ""
        for line in _info_path(path).read_text().splitlines():
            if line.startswith("Path="):
                return unquote(line[5:])
    except OSError:
        pass
    return ""


def delete_forever(paths: list[Path]) -> list[str]:
    """Permanently delete top-level Trash items and their .trashinfo records. A record goes only once its item
    is really gone, so a failure never leaves a file Restore can't place. Returns one message per failure.
    Only ever called after the user confirms in VaultL."""
    errors = []
    for p in paths:
        if p.parent.resolve() != TRASH_FILES.resolve():
            errors.append(f"{p.name}: not a Trash item")
            continue
        try:
            if p.is_dir() and not p.is_symlink():
                shutil.rmtree(p)
            else:
                p.unlink()
        except OSError as e:
            errors.append(f"{p.name}: {e.strerror or e}")
            if p.exists() or p.is_symlink():          # rmtree may have got part-way: keep the record
                continue
        _info_path(p).unlink(missing_ok=True)
    return errors


def empty_trash() -> list[str]:
    """Permanently delete everything in the Trash (freedesktop spec: files/ + their info/ records).
    Records of items that couldn't be deleted stay; records with no item left (orphans) go.
    Returns one message per item that couldn't be deleted. Only ever called after the user confirms in VaultL."""
    trash_root = TRASH_FILES.parent
    errors = delete_forever(list(TRASH_FILES.iterdir())) if TRASH_FILES.is_dir() else []
    info = trash_root / "info"
    if info.is_dir():
        for rec in info.glob("*.trashinfo"):
            item = TRASH_FILES / rec.name[:-len(".trashinfo")]
            if not item.exists() and not item.is_symlink():
                rec.unlink(missing_ok=True)
    (trash_root / "directorysizes").unlink(missing_ok=True)
    return errors


def new_folder(parent: Path, name="New Folder") -> Path:
    target = free_name(parent / name)
    target.mkdir()
    return target


PSEUDO = tuple(Path(p) for p in ("/proc", "/sys", "/dev", "/run"))   # kernel views, not files on a disk


def folder_size(path: Path, limit=200_000, seconds=3.0) -> tuple[int, int, bool]:
    """(bytes, files, complete) under path. Stays on path's own filesystem (so "/" doesn't count other drives,
    or /proc's fake 128 TB kcore), skips pseudo filesystems, and stops after `limit` files or `seconds`:
    complete is False then, and the numbers are a lower bound."""
    try:
        real = path.resolve()
        if any(real == p or real.is_relative_to(p) for p in PSEUDO):
            return 0, 0, False
        dev = real.stat().st_dev
    except OSError:
        return 0, 0, False
    total = files = 0
    deadline = time.monotonic() + seconds
    stack = [str(real)]
    while stack:
        try:
            with os.scandir(stack.pop()) as it:
                for e in it:
                    try:
                        if e.is_symlink():
                            continue
                        st = e.stat(follow_symlinks=False)
                        if st.st_dev != dev:
                            continue                       # another mount: a drive, tmpfs, /proc…
                        if e.is_dir(follow_symlinks=False):
                            if Path(e.path) not in PSEUDO:
                                stack.append(e.path)
                        elif e.is_file(follow_symlinks=False):
                            total += st.st_size
                            files += 1
                    except OSError:
                        continue
                    if files >= limit or time.monotonic() > deadline:
                        return total, files, False
        except OSError:                                    # a folder we can't read
            continue
    return total, files, True
