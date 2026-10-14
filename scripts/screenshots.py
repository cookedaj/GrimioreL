# SPDX-License-Identifier: GPL-3.0-or-later
"""Render the README screenshots (docs/screenshots/*.png) offscreen, in a throwaway home, so nothing personal shows.

    python3 scripts/screenshots.py [name ...]        all of them, or e.g. hub vaultl terminall

It sets up ~/.cache/grimoire-screenshots/home (demo files for VaultL, a plain bash prompt for TerminalL, no session
bus, its own runtime dir), re-runs itself there with QT_QPA_PLATFORM=offscreen, opens the hub at 1440x900 on each
page, lets it load, grabs it and shrinks the PNG with Pillow. Look at every image before committing it: live pages
(SystemL, NetL) show this machine's numbers.
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "docs" / "screenshots"
BOX = Path.home() / ".cache" / "grimoire-screenshots"
W, H = 1440, 900
PAGES = ["hub", "mural", "sightc", "vaultl", "optimizel", "systeml", "terminall", "shotl", "focusl", "netl", "launchl",
         "settings", "tray"]


# ---------------------------------------------------------------- the sandbox
def _image(path: Path, seed: int, size=(960, 540)):
    """Abstract black & white art, so VaultL's thumbnails and MuraL's library have something to show."""
    import math
    from PIL import Image, ImageDraw, ImageFilter
    w, h = size
    img = Image.new("L", size, 8)
    d = ImageDraw.Draw(img)
    style = seed % 4
    if style == 0:                                       # ripples
        cx, cy = w * 0.62, h * 0.55
        for r in range(int(w), 0, -14):
            d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=int(30 + 200 * (1 - r / w) ** 2), width=2)
    elif style == 1:                                     # dunes
        for k in range(26):
            y0 = h * (0.25 + k * 0.03)
            pts = [(x, y0 + 40 * math.sin(x / (90 + seed * 7) + k * 0.35)) for x in range(0, w + 8, 8)]
            d.line(pts, fill=int(40 + k * 8), width=3)
    elif style == 2:                                     # moon
        d.ellipse([w * 0.58, h * 0.18, w * 0.58 + h * 0.5, h * 0.68], fill=225)
        d.ellipse([w * 0.62, h * 0.14, w * 0.62 + h * 0.5, h * 0.64], fill=8)
        for i in range(160):
            x, y = (i * 7919 + seed * 31) % w, (i * 104729) % int(h * 0.8)
            d.point((x, y), fill=120 + i % 120)
    else:                                                # rain
        for i in range(0, w, 6):
            y = (i * 37 + seed * 11) % h
            d.line([(i, y), (i - 30, y + 160)], fill=50 + (i * 13) % 150, width=1)
    img = img.filter(ImageFilter.GaussianBlur(0.6))
    img.convert("RGB").save(path)


def sandbox() -> Path:
    home = BOX / "home"
    if BOX.exists():
        shutil.rmtree(BOX)                                   # our own throwaway folder, never user files
    for d in ("Desktop", "Documents/Projects", "Downloads", "Music", "Pictures/Wallpapers", "Videos", ".config",
              ".local/share", ".cache"):
        (home / d).mkdir(parents=True, exist_ok=True)
    files = {
        "Documents/Notes.md": "# Notes\n", "Documents/Budget 2026.ods": "", "Documents/Thesis draft.pdf": "%PDF-1.4\n",
        "Documents/Projects/README.md": "# Project\n", "Music/Intro.flac": "", "Music/Lo-fi mix.mp3": "",
        "Videos/Clip.mp4": "", "Downloads/setup-1.4.2.deb": "", "Downloads/report-q3.pdf": "%PDF-1.4\n",
        "Downloads/fonts.zip": "", "Downloads/song.mp3": "", "Downloads/notes.txt": "hello\n",
        "Downloads/editor.AppImage": "", "Downloads/data.csv": "a,b\n1,2\n", "Downloads/invoice.pdf": "%PDF-1.4\n",
    }
    for rel, text in files.items():
        (home / rel).write_text(text)
    library = home / ".local/share/grimoire/mural/library"
    library.mkdir(parents=True)
    for i, name in enumerate(("Ripples", "Dunes", "Moon", "Rain", "Dunes II", "Moonrise", "Drizzle", "Ripples II")):
        _image(library / f"{name}.png", i + (i // 4) * 5, (1920, 1080))
    for i, rel in enumerate(("Pictures/Wallpapers/Dune.png", "Pictures/Wallpapers/Rain.png", "Pictures/Mono.png",
                             "Downloads/photo-001.png", "Downloads/photo-002.png", "Downloads/screenshot.png")):
        _image(home / rel, i)
    (home / ".bashrc").write_text(
        "PS1='user@grimoire:\\w\\$ '\nexport LS_COLORS='di=1;37:ex=1;37:*.png=37:*.pdf=37'\nalias ls='ls --color=auto'\n"
        "export HISTFILE=/dev/null\n")
    (home / ".bash_profile").write_text("[ -f ~/.bashrc ] && . ~/.bashrc\n")
    run = BOX / "run"
    run.mkdir(mode=0o700)
    return home


# ---------------------------------------------------------------- rendering (inside the sandbox)
def render(names: list[str]):
    from PySide6.QtCore import QEventLoop, QTimer
    from PySide6.QtWidgets import QApplication

    app = QApplication(sys.argv[:1])
    app.setApplicationName("Grimoire Linux")
    from grimoire.app import Window, style_app
    style_app(app)

    def wait(ms):
        loop = QEventLoop()
        QTimer.singleShot(ms, loop.quit)
        loop.exec()

    private_addresses()
    offline_stubs()
    OUT.mkdir(parents=True, exist_ok=True)
    win = Window()
    win.resize(W, H)
    win.show()
    wait(1500)
    for name in names:
        if name == "tray":
            tray_shot(wait)
            continue
        page = "home" if name == "hub" else name
        if name == "shotl":
            seed_shots()
        win.open(page)
        prepare = PREPARE.get(name)
        if prepare:
            prepare(win.pages[page][1], wait)
        wait(WAIT.get(name, 2500))
        save(win.grab(), name)


def private_addresses():
    """NetL lists this machine's IPs and MACs; swap them for documentation addresses (RFC 5737 / 3849)."""
    from grimoire.spells.netl import probe
    real = probe.addresses

    def addresses():
        out = real()
        for i, a in enumerate(out):
            a["ipv4"] = [f"192.0.2.{10 + i}"] if a["ipv4"] else []
            a["ipv6"] = [f"2001:db8::{10 + i}", f"fe80::{10 + i}"] if a["ipv6"] else []
            a["mac"] = f"02:00:00:00:00:{10 + i:02x}" if a["mac"] else ""
        return out
    dev = next((d for _, d in probe.gateways()), "eth0")
    probe.addresses = addresses
    probe.gateways = lambda: [("192.0.2.1", dev)]
    probe.dns = lambda: [("192.0.2.1", dev), ("2001:db8::1", dev)]


def offline_stubs():
    """There's no session bus in the sandbox: show KDE's shortcut list and the panel as a fresh Plasma has them."""
    from grimoire import hotkeys
    from grimoire.spells.launchl import panel
    from grimoire.spells.sightc import overlay

    class Bus:
        def call(self, path, iface, method, sig="", *args):
            if method == "allComponents":
                return [["/component/sightsl"]]
            if method == "allShortcutInfos":
                return [[[a, n, overlay.COMPONENT, "Grimoire SightsL", "", "", [k], [k]]
                         for a, (n, k) in overlay.HOTKEYS.items()]]
            return [[]]
    hotkeys.BUS = Bus()
    panel.is_installed = lambda: True
    panel.needs_update = lambda: False
    panel.load_state = lambda: {}
    panel.scan = lambda: [{"id": 1, "order": "2;3;4", "widgets": [
        {"id": 2, "type": "org.kde.plasma.kickoff"}, {"id": 3, "type": "org.kde.plasma.icontasks"},
        {"id": 4, "type": "org.kde.plasma.systemtray"}]}]


def seed_shots():
    """ShotL's gallery: the pages rendered so far, as if they were screenshots taken today."""
    import time
    from grimoire.spells.shotl import shots
    folder = shots.folder()
    folder.mkdir(parents=True, exist_ok=True)
    for i, name in enumerate(("hub", "mural", "sightc", "vaultl", "optimizel", "systeml", "terminall")):
        src = OUT / f"{name}.png"
        if src.is_file():
            dst = folder / time.strftime(f"Screenshot_%Y-%m-%d_%H-%M-{i:02d}.png")
            shutil.copy(src, dst)
            shots.add(dst)


def save(pixmap, name):
    path = OUT / f"{name}.png"
    pixmap.save(str(path))
    shrink(path)
    print(f"{path.relative_to(REPO)}  {path.stat().st_size // 1024} KB")


def shrink(path: Path, limit=300 * 1024):
    """Grimoire is black & white, so a 64-color palette is visually lossless and keeps PNGs small."""
    from PIL import Image
    img = Image.open(path).convert("RGB")
    for colors in (128, 64, 32):
        img.quantize(colors=colors, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE).save(
            path, optimize=True)
        if path.stat().st_size <= limit:
            break


def tray_shot(wait):
    """The tray's icon (CPU/RAM bars) and its menu, side by side on Grimoire's black."""
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtGui import QColor, QFont, QPainter, QPixmap
    from grimoire import tray
    from grimoire.glyphs import meter
    t = tray.Tray()
    t.timer.stop()
    m = t.menu
    m.adjustSize()
    m.popup(QPoint(0, 0))
    wait(400)
    menu = m.grab()
    m.hide()
    pad, icon = 48, 96
    canvas = QPixmap(menu.width() + icon + pad * 3, max(menu.height(), icon) + pad * 2)
    canvas.fill(QColor("#0b0b0b"))
    p = QPainter(canvas)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.drawPixmap(pad, pad, meter(38, 61, icon))
    p.setPen(QColor("#8a8a8a"))
    p.setFont(QFont("IBM Plex Sans", 10))
    p.drawText(pad, pad + icon + 10, icon, 40, Qt.AlignmentFlag.AlignHCenter, "CPU   RAM")
    p.drawPixmap(pad * 2 + icon, pad, menu)
    p.end()
    save(canvas, "tray")


def _vaultl(page, wait):
    page.navigate(Path.home() / "Downloads")


def _terminal(page, wait):
    """Type a couple of harmless commands into the first terminal."""
    wait(1500)
    from PySide6.QtWidgets import QWidget
    term = next((w for w in page.findChildren(QWidget) if hasattr(w, "session")), None)
    if term is None:
        return
    demo = ("clear; cd ~; ls --color=always; echo; "
            "printf '\\e[1mGrimoire Linux\\e[0m  \\e[2mblack & white, full color when asked\\e[0m\\n'; "
            "for c in 1 2 3 4 5 6; do printf \"\\e[4${c}m   \\e[0m\"; done; printf '\\n'; "
            "for i in $(seq 232 255); do printf \"\\e[48;5;${i}m  \"; done; printf '\\e[0m\\n'\n")
    term.session.write(demo.encode())


PREPARE = {"vaultl": _vaultl, "terminall": _terminal}
WAIT = {"mural": 6000, "systeml": 30000, "netl": 30000, "optimizel": 5000, "terminall": 3500, "vaultl": 3000}


def main():
    names = [a for a in sys.argv[1:] if a in PAGES] or PAGES
    if os.environ.get("GRIMOIRE_SCREENSHOTS") == "1":
        render(names)
        return
    home = sandbox()
    env = {k: v for k, v in os.environ.items() if not k.startswith(("XDG_", "DBUS_", "KDE_", "WAYLAND", "DISPLAY"))}
    env |= {"HOME": str(home), "XDG_CONFIG_HOME": str(home / ".config"), "XDG_DATA_HOME": str(home / ".local/share"),
            "XDG_CACHE_HOME": str(home / ".cache"), "XDG_RUNTIME_DIR": str(BOX / "run"),
            "DBUS_SESSION_BUS_ADDRESS": "unix:path=/nonexistent", "QT_QPA_PLATFORM": "offscreen",
            "SHELL": "/bin/bash", "USER": "user", "LOGNAME": "user", "HOSTNAME": "grimoire",
            "GRIMOIRE_NO_UPDATE_CHECK": "1", "GRIMOIRE_SCREENSHOTS": "1", "PYTHONPATH": str(REPO),
            "PYTHONSAFEPATH": "1"}
    try:
        subprocess.run([sys.executable, __file__, *names], env=env, cwd=home, check=True, timeout=600)
    finally:
        shutil.rmtree(BOX, ignore_errors=True)


if __name__ == "__main__":
    main()
