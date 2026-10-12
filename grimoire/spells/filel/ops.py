"""FileL file operations. Everything goes through the normal Linux/KDE system: plain filesystem calls for
copy/move/rename, and `gio` for the Trash (the same freedesktop Trash Dolphin uses)."""
import shutil
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
        info = TRASH_FILES.parent / "info" / (p.name + ".trashinfo")
        orig = original_location(p)
        if not orig:
            errors.append(f"{p.name}: no record of where it came from")
            continue
        try:
            target = free_name(Path(orig))
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(p), str(target))
            info.unlink(missing_ok=True)
        except OSError as e:
            errors.append(f"{p.name}: {e.strerror or e}")
    return errors


def original_location(path: Path) -> str:
    info = TRASH_FILES.parent / "info" / (path.name + ".trashinfo")
    try:
        for line in info.read_text().splitlines():
            if line.startswith("Path="):
                return unquote(line[5:])
    except OSError:
        pass
    return ""


def empty_trash() -> str:
    """Permanently delete everything in the Trash (freedesktop spec: files/ + their info/ records).
    Only ever called after the user confirms in FileL."""
    problems = []
    trash_root = TRASH_FILES.parent
    for sub in ("files", "info"):
        d = trash_root / sub
        if not d.is_dir():
            continue
        for p in d.iterdir():
            try:
                if p.is_dir() and not p.is_symlink():
                    shutil.rmtree(p)
                else:
                    p.unlink()
            except OSError as e:
                problems.append(f"{p.name}: {e.strerror or e}")
    (trash_root / "directorysizes").unlink(missing_ok=True)
    return "; ".join(problems[:3])


def new_folder(parent: Path, name="New Folder") -> Path:
    target = free_name(parent / name)
    target.mkdir()
    return target


def rename(path: Path, new_name: str) -> Path:
    new_name = new_name.strip()
    if not new_name or "/" in new_name or new_name in (".", ".."):
        raise OSError("that isn't a valid name")
    target = path.with_name(new_name)
    if target.exists() and target != path:
        raise OSError(f"“{new_name}” already exists here")
    path.rename(target)
    return target


def folder_size(path: Path, limit=200_000) -> tuple[int, int]:
    """(bytes, files) under path; stops counting after `limit` files."""
    total = files = 0
    for p in path.rglob("*"):
        try:
            if p.is_file() and not p.is_symlink():
                total += p.stat().st_size
                files += 1
        except OSError:
            continue
        if files >= limit:
            break
    return total, files
