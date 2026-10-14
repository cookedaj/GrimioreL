# SPDX-License-Identifier: GPL-3.0-or-later
"""Taking stills. Spectacle's background mode is the backend: it's KWin's authorized screenshot client, so it grabs
any screen or the active window without a permission prompt in ~0.4 s. Regions and single monitors are cut from a
full grab (region.py draws the selector), so they look the same whatever Spectacle's own settings are. Without
Spectacle, the xdg-desktop-portal Screenshot call (portal.py) grabs the whole desktop instead."""
import shutil
import subprocess
import time
from pathlib import Path

from grimoire.spells.shotl.shots import TEMP

FLAGS = {"full": "-f", "screen": "-m", "window": "-a"}     # all screens, the one under the pointer, active window


class CaptureError(RuntimeError):
    pass


def backend() -> str:
    """'spectacle', 'portal', or '' when nothing can take a screenshot."""
    if shutil.which("spectacle"):
        return "spectacle"
    try:
        import dbus  # noqa: F401
        import gi    # noqa: F401
        return "portal"
    except ImportError:
        return ""


def grab(mode: str, pointer=False) -> Path:
    """Grab to a temporary PNG and return its path. mode: full, screen or window."""
    TEMP.mkdir(parents=True, exist_ok=True)
    for old in TEMP.glob("grab-*.png"):            # our scratch copies a failed or late grab left behind
        if old.stat().st_mtime < time.time() - 600:
            old.unlink(missing_ok=True)
    out = TEMP / f"grab-{time.time_ns()}.png"
    how = backend()
    if how == "spectacle":
        cmd = ["spectacle", "-b", "-n", FLAGS[mode], "-o", str(out)] + (["-p"] if pointer else [])
        for attempt in range(2):       # right after another shot, Spectacle can hand the job to the exiting
            try:                       # instance and save nothing; a second try a moment later works
                r = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
            except subprocess.TimeoutExpired:
                raise CaptureError("Spectacle didn't answer in 20 s")
            if out.is_file() and out.stat().st_size:
                break
            time.sleep(0.4)
        if not out.is_file() or out.stat().st_size == 0:
            msg = [ln for ln in r.stderr.splitlines() if "Tesseract" not in ln]
            raise CaptureError("Spectacle took no screenshot" + (f": {msg[-1]}" if msg else ""))
        return out
    if how == "portal":
        if mode == "window":
            raise CaptureError("Window shots need Spectacle (sudo apt install kde-spectacle)")
        from grimoire.spells.shotl import portal
        try:
            portal.screenshot(out)
        except Exception as e:                 # PortalError, D-Bus, a file it couldn't copy
            raise CaptureError(f"The desktop portal took no screenshot: {e}") from e
        return out
    raise CaptureError("Nothing here can take screenshots: install Spectacle (sudo apt install kde-spectacle)")


def take(path: Path):
    """Pop a temporary grab: its pixels as a QImage, the temp file removed (it's our own scratch copy)."""
    from PySide6.QtGui import QImage
    img = QImage(str(path))
    path.unlink(missing_ok=True)
    if img.isNull():
        raise CaptureError("The screenshot couldn't be read")
    return img


def screen_rect(img, screen):
    """Where one QScreen sits inside a full-desktop grab, in the grab's pixels (it's scaled like the screens)."""
    from PySide6.QtCore import QRect
    from PySide6.QtGui import QGuiApplication
    virt = QRect()
    for s in QGuiApplication.screens():
        virt = virt.united(s.geometry())
    k = img.width() / max(1, virt.width())
    g = screen.geometry()
    return QRect(round((g.x() - virt.x()) * k), round((g.y() - virt.y()) * k), round(g.width() * k),
                 round(g.height() * k)).intersected(img.rect())


# ---------------------------------------------------------------- clipboard
def copy_image(img) -> str:
    """Put an image on the clipboard. wl-copy keeps serving it after we quit; otherwise Qt owns it, and on Wayland
    the clipboard empties when its owner exits, so callers keep running (hold_clipboard) or Klipper takes over."""
    if shutil.which("wl-copy"):
        from PySide6.QtCore import QBuffer, QIODevice
        buf = QBuffer()
        buf.open(QIODevice.OpenModeFlag.WriteOnly)
        img.save(buf, "PNG")
        try:
            subprocess.run(["wl-copy", "--type", "image/png"], input=bytes(buf.data()), timeout=10, check=True)
            return "wl-copy"
        except (OSError, subprocess.SubprocessError):
            pass
    from PySide6.QtGui import QGuiApplication
    QGuiApplication.clipboard().setImage(img)
    return "qt"


def copy_file(path: Path):
    """Copy a file as a file (paste into Dolphin/VaultL/chat apps) plus, for images, its pixels."""
    from PySide6.QtCore import QMimeData, QUrl
    from PySide6.QtGui import QGuiApplication, QImage
    data = QMimeData()
    data.setUrls([QUrl.fromLocalFile(str(path))])
    img = QImage(str(path))
    if not img.isNull():
        data.setImageData(img)
    QGuiApplication.clipboard().setMimeData(data)


def hold_clipboard(app, minutes=10):
    """For the CLI: stay alive while our image is on the clipboard (lost ownership or timeout ends it)."""
    from PySide6.QtCore import QTimer
    cb = app.clipboard()
    cb.dataChanged.connect(lambda: None if cb.ownsClipboard() else app.quit())
    QTimer.singleShot(minutes * 60_000, app.quit)
    return app.exec()
