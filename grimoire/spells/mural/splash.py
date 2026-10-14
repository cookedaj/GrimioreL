"""Splash tab: Grimoire's animated splash (shown after login), installed as a Plasma look-and-feel package,
plus community splash screens.

Templates live in splash_designs/<id>.qml with these placeholders:
    @TAGLINE@ (JSON string)  @SHOW_TAGLINE@ (true/false)  @SPEED@ (0.6 slow … 1.6 fast)
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from PySide6.QtGui import QImage
from PySide6.QtWidgets import QCheckBox, QComboBox, QGridLayout, QLabel, QLineEdit, QPushButton

from grimoire.paths import ASSETS, CACHE, HOME
from grimoire.spells.mural.kde import kwrite
from grimoire.spells.mural.screens import Design, ScreenTab, community_designs, community_entry, render_lock

TEMPLATES = Path(__file__).with_name("splash_designs")
PACKAGE_ID = "com.cookedaj.grimoire.splash"
INSTALLED = HOME / ".local/share/plasma/look-and-feel" / PACKAGE_ID
PREVIEWS = CACHE / "splash-previews"
SPEEDS = {"Slow": 0.7, "Normal": 1.0, "Fast": 1.5}
DEFAULTS = {"tagline": "SURPASS YOUR LIMITS", "show_tagline": True, "speed": "Normal"}

DESIGNS = [
    Design("breathe", "Breathe", "The five-leaf clover breathing slowly above a hairline progress bar."),
]


def build(design_id: str, opts: dict, dest: Path):
    """Write a complete look-and-feel package for this design + options to dest."""
    qml = (TEMPLATES / f"{design_id}.qml").read_text()
    qml = (qml.replace("@TAGLINE@", json.dumps(opts.get("tagline", "SURPASS YOUR LIMITS").upper()))
              .replace("@SHOW_TAGLINE@", "true" if opts.get("show_tagline", True) else "false")
              .replace("@SPEED@", str(SPEEDS.get(opts.get("speed", "Normal"), 1.0))))
    if dest.exists():
        shutil.rmtree(dest)
    (dest / "contents/splash/images").mkdir(parents=True)
    (dest / "contents/splash/Splash.qml").write_text(qml)
    for svg in ("clover5.svg", "clover4.svg"):
        shutil.copy(ASSETS / svg, dest / "contents/splash/images" / svg)
    (dest / "metadata.json").write_text(json.dumps({
        "KPackageStructure": "Plasma/LookAndFeel",
        "KPlugin": {"Id": PACKAGE_ID, "Name": "Grimoire", "Description": "Grimoire splash (MuraL)",
                    "Authors": [{"Name": "cookedaj"}], "License": "GPL-3.0-or-later", "Version": "1.0"},
        "X-Plasma-APIVersion": "2",
    }, indent=2))


def _preview_path(design_id: str, opts: dict) -> Path:
    key = hashlib.sha1(json.dumps([design_id, opts, (TEMPLATES / f"{design_id}.qml").stat().st_mtime_ns],
                                  sort_keys=True).encode()).hexdigest()[:16]
    return PREVIEWS / f"{design_id}-{key}.png"


def render_preview(design_id: str, opts: dict) -> QImage:
    """Render (or reuse) a preview PNG of this design + options. Safe to call from worker threads."""
    png = _preview_path(design_id, opts)
    with render_lock(str(png)):
        if not png.exists():
            pkg = PREVIEWS / f"pkg-{png.stem}"
            build(design_id, opts, pkg)
            env = dict(os.environ, QT_QPA_PLATFORM="offscreen", QT_QUICK_BACKEND="software",
                       PYTHONPATH=str(Path(__file__).resolve().parents[3]))
            subprocess.run([sys.executable, "-m", "grimoire.spells.mural.qmlshot",
                            str(pkg / "contents/splash/Splash.qml"), str(png), "4"],
                           env=env, capture_output=True, timeout=30)
            shutil.rmtree(pkg, ignore_errors=True)
    img = QImage(str(png))
    if img.isNull():
        img = QImage(1280, 720, QImage.Format.Format_RGB32)
        img.fill(0)
    return img


class SplashTab(ScreenTab):
    key = "splash"
    subtitle = "The animation right after you log in, while Plasma loads. Previews are rendered from the real QML."
    apply_label = "Apply splash"
    store = ["splash"]

    def designs(self):
        PREVIEWS.mkdir(parents=True, exist_ok=True)
        return DESIGNS + community_designs("splash")

    def build_options(self, lay):
        grid = QGridLayout()
        grid.setVerticalSpacing(8)
        self.tagline = QLineEdit()
        self.tagline.setMaxLength(40)
        self.tagline.textChanged.connect(self.changed)
        self.speed = QComboBox()
        self.speed.addItems(list(SPEEDS))
        self.speed.currentTextChanged.connect(self.changed)
        grid.addWidget(QLabel("Tagline"), 0, 0)
        grid.addWidget(self.tagline, 0, 1)
        grid.addWidget(QLabel("Speed"), 1, 0)
        grid.addWidget(self.speed, 1, 1)
        lay.addLayout(grid)
        self.show_tagline = QCheckBox("Show tagline")
        self.show_tagline.toggled.connect(self.changed)
        lay.addWidget(self.show_tagline)
        lay.addSpacing(6)
        play = QPushButton("Play it now")
        play.setToolTip("Runs this splash in a window for a few seconds")
        play.clicked.connect(self._play)
        lay.addWidget(play)

    def options(self):
        return {"tagline": self.tagline.text().strip() or "SURPASS YOUR LIMITS",
                "show_tagline": self.show_tagline.isChecked(), "speed": self.speed.currentText()}

    def set_options(self, o):
        o = {**DEFAULTS, **o}
        self.tagline.setText(o["tagline"])
        self.show_tagline.setChecked(o["show_tagline"])
        self.speed.setCurrentText(o["speed"])

    def preview(self, design, o):
        return render_preview(design.id, o)

    def _play(self):
        if self.current().id.startswith("store:"):
            pkg = Path(community_entry(self.current().id)["path"])
        else:
            pkg = PREVIEWS / "pkg-play"
            build(self.current().id, self.options(), pkg)
        subprocess.Popen(["timeout", "12", "ksplashqml", "--test", "--window", str(pkg)],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)

    def apply(self, design, o):
        if design.id.startswith("store:"):
            theme = community_entry(design.id)["ident"]
        else:
            build(design.id, o, INSTALLED)
            theme = PACKAGE_ID
        kwrite("ksplashrc", "KSplash", "Theme", theme)
        kwrite("ksplashrc", "KSplash", "Engine", "KSplashQML")
        return "Applied ✓  You'll see it at your next login."
