"""MuraL library: a folder of wallpapers (images + videos) and their cached thumbnails."""
import hashlib
import shutil
import subprocess
from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QImage, QImageReader

from grimoire.paths import CACHE, DATA

LIBRARY = DATA / "mural" / "library"
THUMBS = CACHE / "mural-thumbs"
LIBRARY.mkdir(parents=True, exist_ok=True)
THUMBS.mkdir(parents=True, exist_ok=True)

IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".avif", ".tif", ".tiff"}
VIDEO_EXT = {".mp4", ".webm", ".mkv", ".mov", ".m4v", ".gif"}
THUMB_SIZE = QSize(288, 162)


def is_video(path: Path) -> bool:
    return path.suffix.lower() in VIDEO_EXT


def items() -> list[Path]:
    exts = IMAGE_EXT | VIDEO_EXT
    return sorted((p for p in LIBRARY.iterdir() if p.suffix.lower() in exts), key=lambda p: p.name.lower())


def add(paths) -> list[Path]:
    """Copy files into the library (so wallpapers survive if the originals move)."""
    added = []
    for src in map(Path, paths):
        if src.suffix.lower() not in IMAGE_EXT | VIDEO_EXT or not src.is_file():
            continue
        dst = LIBRARY / src.name
        n = 2
        while dst.exists() and not _same_file(src, dst):
            dst = LIBRARY / f"{src.stem}-{n}{src.suffix}"
            n += 1
        if not dst.exists():
            shutil.copy2(src, dst)
        added.append(dst)
    return added


def remove(path: Path):
    path.unlink(missing_ok=True)
    _thumb_path(path).unlink(missing_ok=True)


def _same_file(a: Path, b: Path) -> bool:
    return a.stat().st_size == b.stat().st_size and a.read_bytes()[:65536] == b.read_bytes()[:65536]


def _thumb_path(path: Path) -> Path:
    key = hashlib.sha1(f"{path}:{path.stat().st_mtime_ns if path.exists() else 0}".encode()).hexdigest()
    return THUMBS / f"{key}.jpg"


def thumbnail(path: Path) -> QImage:
    """Cached 320x180 cropped thumbnail. Videos use a frame from 1s in (needs ffmpeg)."""
    cached = _thumb_path(path)
    if cached.exists():
        return QImage(str(cached))
    if is_video(path):
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-ss", "1", "-i", str(path),
                        "-frames:v", "1", "-vf", "scale=640:-1", str(cached)], check=False)
        img = QImage(str(cached))
    else:
        reader = QImageReader(str(path))
        reader.setAutoTransform(True)
        size = reader.size()
        if size.isValid():   # decode at reduced size: much faster for 4K/8K images
            reader.setScaledSize(size.scaled(THUMB_SIZE * 2, Qt.AspectRatioMode.KeepAspectRatioByExpanding))
        img = reader.read()
    if img.isNull():
        return img
    img = img.scaled(THUMB_SIZE, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                     Qt.TransformationMode.SmoothTransformation)
    x, y = (img.width() - THUMB_SIZE.width()) // 2, (img.height() - THUMB_SIZE.height()) // 2
    img = img.copy(x, y, THUMB_SIZE.width(), THUMB_SIZE.height())
    img.save(str(cached), "JPG", 88)
    return img
