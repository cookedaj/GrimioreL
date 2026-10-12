"""Icons tab: the icon theme. Your current theme plus community icon packs; previews draw real icons
from each theme's own files (following its Inherits= chain for anything it doesn't include).
"""
import subprocess
from configparser import ConfigParser
from functools import lru_cache
from pathlib import Path

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

from grimoire.paths import HOME
from grimoire.spells.mural import store as community
from grimoire.spells.mural.screens import Design, ScreenTab

SEARCH = [HOME / ".local/share/icons", HOME / ".icons", Path("/usr/share/icons")]
FLATPAK = [Path("/var/lib/flatpak/exports/share/icons/hicolor"),       # Flatpak apps register icons here
           HOME / ".local/share/flatpak/exports/share/icons/hicolor"]
CHANGE_ICONS = "/usr/lib/x86_64-linux-gnu/libexec/plasma-changeicons"
SAMPLE = [("system-file-manager", "Files"), ("utilities-terminal", "Terminal"), ("firefox", "Firefox"),
          ("systemsettings", "Settings"), ("steam", "Steam"), ("com.discordapp.Discord", "Discord"),
          ("com.spotify.Client", "Spotify"), ("com.obsproject.Studio", "OBS"), ("folder", "Folder"),
          ("user-home", "Home"), ("folder-download", "Downloads"), ("user-trash", "Trash"),
          ("text-x-generic", "Text"), ("image-x-generic", "Image"), ("video-x-generic", "Video"),
          ("audio-x-generic", "Audio"), ("application-x-executable", "App"), ("preferences-desktop-wallpaper", "Wallpaper")]
SIZE_ORDER = ["scalable", "96", "64", "48", "256", "128", "32", "96x96", "64x64", "48x48", "256x256", "128x128"]


def theme_dir(name: str) -> Path | None:
    return next((base / name for base in SEARCH if (base / name / "index.theme").is_file()), None)


def theme_name(name: str) -> str:
    d = theme_dir(name)
    if not d:
        return name
    c = ConfigParser(interpolation=None, strict=False)
    c.read(d / "index.theme", encoding="utf-8")
    return c.get("Icon Theme", "Name", fallback=name)


@lru_cache(maxsize=32)
def _index(theme: str) -> dict:
    """icon name -> best file in this theme (prefers scalable, then larger sizes)."""
    d = theme_dir(theme)
    found: dict[str, tuple[int, Path]] = {}
    if not d:
        return {}
    for f in d.rglob("*"):
        if f.suffix not in (".svg", ".png") or not f.is_file():
            continue
        path = str(f)
        rank = next((i for i, s in enumerate(SIZE_ORDER) if f"/{s}/" in path), 99)
        if f.stem not in found or rank < found[f.stem][0]:
            found[f.stem] = (rank, f)
    return {k: v[1] for k, v in found.items()}


def find_icon(theme: str, name: str, seen=None) -> Path | None:
    seen = seen or set()
    if theme in seen:
        return None
    seen.add(theme)
    hit = _index(theme).get(name)
    if hit:
        return hit
    d = theme_dir(theme)
    if d:
        c = ConfigParser(interpolation=None, strict=False)
        c.read(d / "index.theme", encoding="utf-8")
        for parent in c.get("Icon Theme", "Inherits", fallback="hicolor").split(","):
            hit = find_icon(parent.strip(), name, seen)
            if hit:
                return hit
    for base in FLATPAK:                                   # last resort: the app's own Flatpak icon
        for sub in ("scalable/apps", "512x512/apps", "256x256/apps", "128x128/apps", "64x64/apps", "48x48/apps"):
            for ext in (".svg", ".png"):
                if (base / sub / f"{name}{ext}").is_file():
                    return base / sub / f"{name}{ext}"
    return None


def current() -> str:
    r = subprocess.run(["kreadconfig6", "--file", "kdeglobals", "--group", "Icons", "--key", "Theme"],
                       capture_output=True, text=True)
    return r.stdout.strip() or "breeze"


def render(theme: str, w=1280, h=720) -> QImage:
    img = QImage(w, h, QImage.Format.Format_RGB32)
    img.fill(QColor(10, 10, 10))
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    cols, size = 6, 84
    cell_w, cell_h = w / (cols + 1), 190
    for k, (name, label) in enumerate(SAMPLE):
        cx = cell_w * (k % cols + 1)
        cy = 120 + (k // cols) * cell_h
        rect = QRectF(cx - size / 2, cy - size / 2, size, size)
        path = find_icon(theme, name)
        if path and path.suffix == ".svg":
            QSvgRenderer(str(path)).render(p, rect)
        elif path:
            p.drawImage(rect, QImage(str(path)))
        else:
            p.setPen(QColor(50, 50, 50))
            p.drawRoundedRect(rect, 12, 12)
        p.setPen(QColor(140, 140, 140))
        p.setFont(QFont("IBM Plex Sans", 10))
        p.drawText(QRectF(cx - 80, cy + size / 2 + 10, 160, 22), Qt.AlignmentFlag.AlignCenter, label)
    p.end()
    return img


class IconsTab(ScreenTab):
    key = "icons"
    subtitle = "Your icon theme. Previews draw real icons from each theme's files. Applies instantly."
    apply_label = "Apply icons"
    store = ["icons"]

    def designs(self):
        cur = current()
        own = [Design(cur, theme_name(cur), "The icon theme you're using now.")]
        return own + [Design(e["ident"], e["name"], f"Community · by {e['author'] or 'unknown'}")
                      for e in community.installed("icons") if e["ident"] != cur]

    def preview(self, design, o):
        return render(design.id)

    def apply(self, design, o):
        r = subprocess.run([CHANGE_ICONS, design.id], capture_output=True, text=True)
        if r.returncode:
            raise RuntimeError((r.stderr or r.stdout).strip() or "plasma-changeicons failed")
        return "Applied ✓"
