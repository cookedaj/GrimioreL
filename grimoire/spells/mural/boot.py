"""Boot tab: Grimoire's Plymouth boot animation, built on Plymouth's stock "two-step" engine
(the one Kubuntu's own logo uses), so password prompts and messages keep working.

Each design is a looping throbber rendered here frame by frame; installing needs root (pkexec).
"""
import math
import shutil
from pathlib import Path

from PIL import Image, ImageDraw
from PySide6.QtGui import QMovie
from PySide6.QtWidgets import QCheckBox, QComboBox, QGridLayout, QLabel, QPushButton

from grimoire.paths import CACHE
from grimoire.spells.mural.lock import _clover_mask, to_qimage
from grimoire.spells.mural.kde import run_root
from grimoire.spells.mural.screens import Design, ScreenTab, community_designs, community_entry

WORK = CACHE / "boot"
FRAMES = 48                                   # two-step loops the throbber; ~1.6 s at 30 fps
SIZES = {"Small": 0.75, "Medium": 1.0, "Large": 1.35}
POSITIONS = {"Center": 0.5, "Lower": 0.62}
DEFAULTS = {"size": "Medium", "position": "Center", "firmware_logo": False}
SS = 3                                        # supersampling for smooth edges

DESIGNS = [
    Design("pulse", "Pulse", "The five-leaf clover breathing slowly in the dark."),
]

_clover_cache: dict[tuple[str, int], Image.Image] = {}


def _clover(size: int, leaves=5) -> Image.Image:
    key = (str(leaves), size)
    if key not in _clover_cache:
        _clover_cache[key] = _clover_mask(size, "clover5.svg" if leaves == 5 else "clover4.svg")
    return _clover_cache[key]


def _rgba(w, h):
    return Image.new("RGBA", (w * SS, h * SS), (0, 0, 0, 0))


def _paste_white(canvas: Image.Image, mask: Image.Image, center, alpha=1.0):
    m = mask.point(lambda v: int(v * alpha))
    x, y = int(center[0] - m.width / 2), int(center[1] - m.height / 2)
    canvas.paste(Image.new("RGBA", m.size, (255, 255, 255, 255)), (x, y), m)


def _done(img: Image.Image, w, h) -> Image.Image:
    return img.resize((w, h), Image.LANCZOS)


def frames(design_id: str, scale: float) -> list[Image.Image]:
    """The looping animation for one design, as RGBA frames on transparent."""
    out = []
    for i in range(FRAMES):
        t = i / FRAMES                                    # 0..1 around the loop
        wave = 0.5 - 0.5 * math.cos(2 * math.pi * t)      # 0→1→0
        w = h = int(200 * scale)                          # Pulse: the clover breathing
        c = _rgba(w, h)
        size = int(96 * scale * SS * (0.96 + 0.06 * wave))
        _paste_white(c, _clover(size), (w * SS / 2, h * SS / 2), 0.75 + 0.25 * wave)
        out.append(_done(c, w, h))
    return out


def preview(design_id: str, opts: dict, frame: int = FRAMES // 3, w=1280, h=720) -> Image.Image:
    o = {**DEFAULTS, **opts}
    scale = SIZES[o["size"]] * (w / 1920)
    f = frames(design_id, scale)[frame]
    bg = Image.new("RGB", (w, h), (0, 0, 0))
    bg.paste(f, (int(w / 2 - f.width / 2), int(h * POSITIONS[o["position"]] - f.height / 2)), f)
    if o["firmware_logo"]:
        d = ImageDraw.Draw(bg)
        d.text((w / 2, h * 0.9), "(motherboard logo)", fill=(90, 90, 90), anchor="mm")
    return bg


def _dialog_assets(dest: Path):
    """Minimal black & white password box assets for two-step."""
    entry = Image.new("RGBA", (360, 40), (0, 0, 0, 0))
    ImageDraw.Draw(entry).rectangle((0, 39, 359, 39), fill=(200, 200, 200, 255))
    entry.save(dest / "entry.png")
    bullet = Image.new("RGBA", (14, 14), (0, 0, 0, 0))
    ImageDraw.Draw(bullet).ellipse((3, 3, 10, 10), fill=(255, 255, 255, 255))
    bullet.save(dest / "bullet.png")
    lock = Image.new("RGBA", (40, 40), (0, 0, 0, 0))
    lock.paste(Image.new("RGBA", (40, 40), (255, 255, 255, 255)), (0, 0), _clover(40))
    lock.save(dest / "lock.png")


def stage(design_id: str, opts: dict, dest: Path):
    o = {**DEFAULTS, **opts}
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    for i, f in enumerate(frames(design_id, SIZES[o["size"]] * 1.333)):   # tuned for 2560x1440
        f.save(dest / f"throbber-{i + 1:04d}.png")
    _dialog_assets(dest)
    fw = "true" if o["firmware_logo"] else "false"
    (dest / "grimoire.plymouth").write_text(f"""[Plymouth Theme]
Name=Grimoire
Description=Grimoire MuraL boot animation ({design_id})
ModuleName=two-step

[two-step]
Font=IBM Plex Sans 12
TitleFont=IBM Plex Sans Light 30
ImageDir=/usr/share/plymouth/themes/grimoire
DialogHorizontalAlignment=.5
DialogVerticalAlignment=.72
TitleHorizontalAlignment=.5
TitleVerticalAlignment=.38
HorizontalAlignment=.5
VerticalAlignment={POSITIONS[o["position"]]}
WatermarkHorizontalAlignment=.5
WatermarkVerticalAlignment=.96
Transition=none
TransitionDuration=0.0
BackgroundStartColor=0x000000
BackgroundEndColor=0x000000
DialogClearsFirmwareBackground=true
MessageBelowAnimation=true

[boot-up]
UseEndAnimation=false
UseFirmwareBackground={fw}

[shutdown]
UseEndAnimation=false
UseFirmwareBackground={fw}

[reboot]
UseEndAnimation=false
UseFirmwareBackground={fw}

[updates]
SuppressMessages=true
""")


class BootTab(ScreenTab):
    key = "boot"
    subtitle = ("What you see while Linux starts and shuts down (Plymouth). Installing rebuilds the boot image, "
                "so it asks for your password and takes about a minute.")
    apply_label = "Install boot screen"
    apply_busy = "Installing… enter your password, then this takes about a minute."
    store = ["plymouth"]

    def designs(self):
        WORK.mkdir(parents=True, exist_ok=True)
        return DESIGNS + community_designs("plymouth")

    def build_options(self, lay):
        grid = QGridLayout()
        grid.setVerticalSpacing(8)
        self.size = QComboBox()
        self.size.addItems(list(SIZES))
        self.position = QComboBox()
        self.position.addItems(list(POSITIONS))
        for c in (self.size, self.position):
            c.currentTextChanged.connect(self.changed)
        grid.addWidget(QLabel("Size"), 0, 0)
        grid.addWidget(self.size, 0, 1)
        grid.addWidget(QLabel("Position"), 1, 0)
        grid.addWidget(self.position, 1, 1)
        lay.addLayout(grid)
        self.firmware = QCheckBox("Keep the motherboard logo")
        self.firmware.toggled.connect(self.changed)
        lay.addWidget(self.firmware)
        lay.addSpacing(6)
        play = QPushButton("Play animation")
        play.clicked.connect(self._play)
        lay.addWidget(play)
        restore = QPushButton("Restore previous boot screen")
        restore.clicked.connect(self._restore)
        lay.addWidget(restore)

    def options(self):
        return {"size": self.size.currentText(), "position": self.position.currentText(),
                "firmware_logo": self.firmware.isChecked()}

    def set_options(self, o):
        o = {**DEFAULTS, **o}
        self.size.setCurrentText(o["size"])
        self.position.setCurrentText(o["position"])
        self.firmware.setChecked(o["firmware_logo"])

    def preview(self, design, o):
        return to_qimage(preview(design.id, o))

    def thumbnail(self, design, o):
        """Boot animations are tiny at real size, so cards show a zoomed crop of the middle."""
        img = preview(design.id, {**o, "position": "Center"})
        w, h = img.size
        return to_qimage(img.crop((w * 0.34, h * 0.34, w * 0.66, h * 0.66)))

    def _selected(self, row, render=True):
        self._stop_movie()
        super()._selected(row, render)

    def _rerender(self):
        self._stop_movie()
        super()._rerender()

    def _stop_movie(self):
        movie = getattr(self, "_movie", None)
        if movie:
            movie.stop()
            self._movie = None

    def _play(self):
        """Animate the big preview with the real frames."""
        if self.current().id.startswith("store:"):
            self.status.setText("Community boot themes can only be previewed by rebooting.")
            return
        o = {**DEFAULTS, **self.options()}
        w = max(320, self.big.width())
        h = int(w * 9 / 16)
        if h > self.big.height():
            h = max(180, self.big.height())
            w = int(h * 16 / 9)
        scale = SIZES[o["size"]] * (w / 1920)
        bg = Image.new("RGB", (w, h), (0, 0, 0))
        shots = []
        for f in frames(self.current().id, scale) * 2:
            s = bg.copy()
            s.paste(f, (int(w / 2 - f.width / 2), int(h * POSITIONS[o["position"]] - f.height / 2)), f)
            shots.append(s)
        gif = WORK / "play.gif"
        shots[0].save(gif, save_all=True, append_images=shots[1:], duration=33, loop=0)
        self._stop_movie()
        self._movie = QMovie(str(gif))
        self.big.setMovie(self._movie)
        self._movie.start()

    def apply(self, design, o):
        if design.id.startswith("store:"):
            entry = community_entry(design.id)
            run_root("plymouth-install", entry["ident"], entry["path"])
            return "Installed ✓  You'll see it on your next reboot."
        staged = WORK / "install"
        stage(design.id, o, staged)
        run_root("plymouth", str(staged))
        return "Installed ✓  You'll see it on your next reboot."

    def _restore(self):
        def work():
            run_root("plymouth-restore")
            return "Previous boot screen restored."
        self.background(work, "Restoring… enter your password, then this takes about a minute.")

