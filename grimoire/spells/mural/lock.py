"""Lock screen tab: 5 black & white backgrounds for Plasma's lock screen (+ dim, blur, clock options).

Only the background and the stock lock screen's own options are changed; the unlock UI itself stays
Plasma's, so a bad design can never lock you out.
"""
import math
from datetime import datetime
from functools import lru_cache

from PIL import Image, ImageFilter, ImageOps
from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QCheckBox, QGridLayout, QLabel

from grimoire.paths import ASSETS, DATA
from grimoire.spells.mural import library
from grimoire.spells.mural.kde import kwrite
from grimoire.spells.mural.screens import Design, ScreenTab
from grimoire.widgets import Slider

OUT = DATA / "mural" / "screens"
OUT.mkdir(parents=True, exist_ok=True)
W, H = 2560, 1440

DESIGNS = [
    Design("negative", "Negative", "Anti-Magic inverted: white Asta and wings on pure black. Striking but calm."),
]


@lru_cache(maxsize=16)
def _covered(name: str, w: int, h: int) -> Image.Image | None:
    """Library image, grayscale, cropped to w x h. Cached: sliders re-render often."""
    p = library.LIBRARY / name
    return _cover(Image.open(p).convert("L"), w, h) if p.exists() else None


def _cover(im: Image.Image, w: int, h: int) -> Image.Image:
    s = max(w / im.width, h / im.height)
    im = im.resize((math.ceil(im.width * s), math.ceil(im.height * s)), Image.LANCZOS)
    x, y = (im.width - w) // 2, (im.height - h) // 2
    return im.crop((x, y, x + w, y + h))


def _clover_mask(size: int, svg: str = "clover5.svg") -> Image.Image:
    """A Grimoire clover emblem (clover5.svg / clover4.svg) rendered as an L mask (white = clover)."""
    img = QImage(size, size, QImage.Format.Format_ARGB32)
    img.fill(0)
    p = QPainter(img)
    QSvgRenderer(str(ASSETS / svg)).render(p)
    p.end()
    alpha = img.convertToFormat(QImage.Format.Format_Alpha8)
    # Qt pads each row to 4 bytes, so pass the real row stride
    return Image.frombuffer("L", (size, size), bytes(alpha.constBits()), "raw", "L", alpha.bytesPerLine(), 1).copy()


def render(design_id: str, dim: int, blur: int, w=W, h=H) -> Image.Image:
    """Grayscale lock background. dim 0..90 (%), blur 0..40 (px at 2560 wide)."""
    scale = w / W
    if design_id.startswith("img:"):                    # any image in the MuraL library
        src = _covered(design_id[4:], w, h)
        im = src.copy() if src else Image.new("L", (w, h), 0)
    else:                                               # Negative: Anti-Magic, inverted
        src = _covered("anti-magic.png", w, h)
        im = ImageOps.invert(src).point(lambda v: int(v * 0.7)) if src else Image.new("L", (w, h), 0)
    if blur:
        im = im.filter(ImageFilter.GaussianBlur(blur * scale))
    if dim:
        im = im.point(lambda v: int(v * (1 - dim / 100)))
    return im


def to_qimage(im: Image.Image) -> QImage:
    im = im.convert("RGB")
    return QImage(im.tobytes(), im.width, im.height, im.width * 3, QImage.Format.Format_RGB888).copy()


class LockTab(ScreenTab):
    key = "lock"
    subtitle = ("Background for the lock screen. Plasma's own clock and password field sit on top — "
                "the preview mocks their position.")
    apply_label = "Apply to lock screen"
    store = ["wallhaven-bw", "wallhaven-bc", "wallpaper"]

    def designs(self):
        pics = [p for p in library.items() if not library.is_video(p)]
        return DESIGNS + [Design(f"img:{p.name}", p.stem, "From your MuraL library (wallpapers you add or "
                                                          "install from Community show up here).") for p in pics]

    def build_options(self, lay):
        grid = QGridLayout()
        grid.setVerticalSpacing(8)
        self.dim = Slider(0, 90, "%", self.changed)
        self.blur = Slider(0, 40, " px", self.changed)
        grid.addWidget(QLabel("Dim"), 0, 0)
        grid.addWidget(self.dim, 0, 1)
        grid.addWidget(QLabel("Blur"), 1, 0)
        grid.addWidget(self.blur, 1, 1)
        lay.addLayout(grid)
        self.clock = QCheckBox("Always show the clock")
        self.clock_idle = QCheckBox("Hide clock when idle")
        self.media = QCheckBox("Show media controls")
        for c in (self.clock, self.clock_idle, self.media):
            c.toggled.connect(self.changed)
            lay.addWidget(c)

    def options(self):
        return {"dim": self.dim.value(), "blur": self.blur.value(), "clock": self.clock.isChecked(),
                "clock_idle": self.clock_idle.isChecked(), "media": self.media.isChecked()}

    def set_options(self, o):
        self.dim.setValue(o.get("dim", 20))
        self.blur.setValue(o.get("blur", 0))
        self.clock.setChecked(o.get("clock", True))
        self.clock_idle.setChecked(o.get("clock_idle", False))
        self.media.setChecked(o.get("media", False))

    def preview(self, design, o):
        img = to_qimage(render(design.id, o.get("dim", 20), o.get("blur", 0), 1280, 720))
        if o.get("clock", True):
            p = QPainter(img)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
            now = datetime.now()
            p.setPen(QColor(255, 255, 255, 235))
            p.setFont(QFont("IBM Plex Sans", 56, QFont.Weight.Light))
            p.drawText(QRect(0, 170, 1280, 90), Qt.AlignmentFlag.AlignHCenter, now.strftime("%-I:%M"))
            p.setFont(QFont("IBM Plex Sans", 15))
            p.setPen(QColor(255, 255, 255, 190))
            p.drawText(QRect(0, 262, 1280, 30), Qt.AlignmentFlag.AlignHCenter, now.strftime("%A, %B %-d"))
            p.end()
        return img

    def apply(self, design, o):
        path = OUT / ("lock-" + design.id.replace("img:", "img-").replace("/", "_") + ".png")
        render(design.id, o["dim"], o["blur"]).save(path, optimize=True)
        url = path.as_uri()
        image = ["Greeter", "Wallpaper", "org.kde.image", "General"]
        lnf = ["Greeter", "LnF", "General"]
        kwrite("kscreenlockerrc", "Greeter", "WallpaperPlugin", "org.kde.image")
        kwrite("kscreenlockerrc", image, "Image", url)
        kwrite("kscreenlockerrc", image, "PreviewImage", url)
        for key, opt in (("alwaysShowClock", "clock"), ("hideClockWhenIdle", "clock_idle"),
                         ("showMediaControls", "media")):
            kwrite("kscreenlockerrc", lnf, key, str(o[opt]).lower(), "bool")
        return "Applied ✓  Lock with Meta+L to see it."
