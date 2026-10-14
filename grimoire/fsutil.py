# SPDX-License-Identifier: GPL-3.0-or-later
"""File helpers shared by several spells: safe names, the Trash, and friendly sizes/paths."""
import subprocess
from pathlib import Path

from grimoire.paths import HOME


def free_name(dest: Path) -> Path:
    """dest, or 'name (2).ext', 'name (3).ext'… if taken. Never overwrites (broken symlinks count as taken)."""
    if not dest.exists() and not dest.is_symlink():
        return dest
    stem, suffix = (dest.name, "") if dest.is_dir() else (dest.stem, dest.suffix)
    n = 2
    while True:
        cand = dest.with_name(f"{stem} ({n}){suffix}")
        if not cand.exists() and not cand.is_symlink():
            return cand
        n += 1


def trash(path: Path):
    """Move one file or folder to the freedesktop Trash (the one Dolphin uses). Raises OSError on failure."""
    r = subprocess.run(["gio", "trash", str(path)], capture_output=True, text=True)
    if r.returncode:
        raise OSError(r.stderr.strip() or f"couldn't trash {path}")


def human(n: float) -> str:
    """1536 -> '1.5 KB'."""
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def tilde(p: Path | str) -> str:
    """Show paths under home as ~/…"""
    s, home = str(p), str(HOME)
    return "~" + s[len(home):] if s == home or s.startswith(home + "/") else s
