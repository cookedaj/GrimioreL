"""The current desktop wallpaper, scaled for previews (shared by the interface tabs)."""
from functools import lru_cache

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage

from grimoire.spells.mural import plasma as desktop


@lru_cache(maxsize=2)
def wallpaper(w: int, h: int) -> QImage:
    """The first image of the current MuraL desktop playlist, for realistic previews."""
    for p in desktop.Settings.load().items:
        img = QImage(p)
        if not img.isNull():
            return img.scaled(w, h, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                              Qt.TransformationMode.SmoothTransformation).copy(0, 0, w, h)
    img = QImage(w, h, QImage.Format.Format_RGB32)
    img.fill(QColor("#0b0b0b"))
    return img
