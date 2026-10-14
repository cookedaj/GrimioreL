# SPDX-License-Identifier: GPL-3.0-or-later
"""Login tab: the SDDM login screen, Grimoire's own "grimoire" theme (Card layout) plus
community themes.

Applying needs root, so it goes through pkexec (a password prompt) and root-helper.sh.
"""
import configparser
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from PySide6.QtGui import QImage
from PySide6.QtWidgets import QCheckBox, QComboBox, QGridLayout, QLabel, QPushButton

from grimoire.paths import ASSETS, CACHE
from grimoire.spells.mural import library
from grimoire.spells.mural.kde import run_root
from grimoire.spells.mural.screens import Design, ScreenTab, community_designs, community_entry, render_lock
from grimoire.widgets import Slider

THEME = Path(__file__).with_name("sddm_theme")
WORK = CACHE / "login"
DEFAULTS = {"background": "spirit-of-zephyr.png", "dim": 55, "clock24": False, "power": True}
NO_IMAGE = "Plain black"

DESIGNS = [
    Design("card", "Card", "A dark floating card with the clover over the art; small clock top-left."),
]


def stage(layout: str, opts: dict, dest: Path):
    """Copy the theme to dest with this layout, background and options baked into theme.conf."""
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(THEME, dest)
    shutil.copy(ASSETS / "clover5.svg", dest / "clover5.svg")
    bg = library.LIBRARY / opts.get("background", "")
    has_bg = opts.get("background") != NO_IMAGE and bg.is_file()
    if has_bg:
        shutil.copy(bg, dest / f"background{bg.suffix.lower()}")
    conf = configparser.ConfigParser()
    conf.optionxform = str
    conf["General"] = {
        "layout": layout,
        "background": f"background{bg.suffix.lower()}" if has_bg else "",
        "dim": str(opts.get("dim", 55)),
        "clock24": "true" if opts.get("clock24") else "false",
        "showPower": "true" if opts.get("power", True) else "false",
    }
    with open(dest / "theme.conf", "w") as f:
        conf.write(f, space_around_delimiters=False)


def _preview_png(layout: str, opts: dict) -> Path:
    stamp = max(p.stat().st_mtime_ns for p in THEME.iterdir())
    key = hashlib.sha1(json.dumps([layout, opts, stamp], sort_keys=True).encode()).hexdigest()[:16]
    return WORK / f"preview-{layout}-{key}.png"


def render_preview(layout: str, opts: dict) -> QImage:
    """Render (or reuse) a preview of this layout. Safe to call from worker threads."""
    png = _preview_png(layout, opts)
    with render_lock(str(png)):
        if not png.exists():
            staged = WORK / f"stage-{png.stem}"
            stage(layout, opts, staged)
            env = dict(os.environ, QT_QPA_PLATFORM="offscreen", QT_QUICK_BACKEND="software",
                       PYTHONPATH=str(Path(__file__).resolve().parents[3]))
            subprocess.run([sys.executable, "-m", "grimoire.spells.mural.sddmshot", str(staged), str(png)],
                           env=env, capture_output=True, timeout=30)
            shutil.rmtree(staged, ignore_errors=True)
    img = QImage(str(png))
    if img.isNull():
        img = QImage(1280, 720, QImage.Format.Format_RGB32)
        img.fill(0)
    return img


class LoginTab(ScreenTab):
    key = "login"
    subtitle = ("The login screen you see after boot (SDDM). Applying installs it system-wide, "
                "so it asks for your password once.")
    apply_label = "Install login screen"
    apply_busy = "Waiting for your password…"
    store = ["sddm"]

    def designs(self):
        WORK.mkdir(parents=True, exist_ok=True)
        return DESIGNS + community_designs("sddm")

    def build_options(self, lay):
        grid = QGridLayout()
        grid.setVerticalSpacing(8)
        self.background = QComboBox()
        self.background.addItems([p.name for p in library.items() if not library.is_video(p)] + [NO_IMAGE])
        self.background.currentTextChanged.connect(self.changed)
        self.dim = Slider(0, 90, "%", self.changed)
        grid.addWidget(QLabel("Background"), 0, 0)
        grid.addWidget(self.background, 0, 1)
        grid.addWidget(QLabel("Dim"), 1, 0)
        grid.addWidget(self.dim, 1, 1)
        lay.addLayout(grid)
        self.clock24 = QCheckBox("24-hour clock")
        self.power = QCheckBox("Show sleep / restart / shut down")
        for c in (self.clock24, self.power):
            c.toggled.connect(self.changed)
            lay.addWidget(c)
        lay.addSpacing(6)
        restore = QPushButton("Restore previous login screen")
        restore.clicked.connect(self._restore)
        lay.addWidget(restore)

    def options(self):
        return {"background": self.background.currentText(), "dim": self.dim.value(),
                "clock24": self.clock24.isChecked(), "power": self.power.isChecked()}

    def set_options(self, o):
        o = {**DEFAULTS, **o}
        self.background.setCurrentText(o["background"])
        self.dim.setValue(o["dim"])
        self.clock24.setChecked(o["clock24"])
        self.power.setChecked(o["power"])

    def preview(self, design, o):
        return render_preview(design.id, o)

    def apply(self, design, o):
        if design.id.startswith("store:"):
            entry = community_entry(design.id)
            run_root("sddm-install", entry["ident"], entry["path"])
            return "Installed ✓  You'll see it next time you log out or reboot."
        staged = WORK / "install"
        stage(design.id, o, staged)
        run_root("sddm", str(staged))
        return "Installed ✓  You'll see it next time you log out or reboot."

    def _restore(self):
        def work():
            run_root("sddm-restore")
            return "Previous login screen restored."
        self.background(work, "Waiting for your password…")
