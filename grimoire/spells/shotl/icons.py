# SPDX-License-Identifier: GPL-3.0-or-later
"""ShotL's own line icons (editor tools and capture modes), drawn like grimoire/glyphs.py: gray normally, white when
active. Kept here so the shared glyphs.py only gains the spell's rail icon."""
from functools import lru_cache

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap

from grimoire.glyphs import S, glyph


def _line(p, *pts):
    path = QPainterPath(QPointF(*pts[0]))
    for pt in pts[1:]:
        path.lineTo(QPointF(*pt))
    p.drawPath(path)


def _draw(name: str, p: QPainter):
    r = QRectF
    if name == "crop":
        _line(p, (7, 3.5), (7, 17), (20.5, 17))
        _line(p, (3.5, 7), (17, 7), (17, 20.5))
    elif name == "arrow":
        p.drawLine(QPointF(5, 19), QPointF(18.5, 5.5))
        _line(p, (10.5, 5.5), (18.5, 5.5), (18.5, 13.5))
    elif name == "box":
        p.drawRect(r(4.5, 6, 15, 12))
    elif name == "pen":
        path = QPainterPath(QPointF(3.5, 17))
        path.cubicTo(7, 8, 10, 8, 11.5, 13)
        path.cubicTo(13, 18, 17, 17, 20.5, 7)
        p.drawPath(path)
    elif name == "text":
        _line(p, (5.5, 7), (5.5, 4.5), (18.5, 4.5), (18.5, 7))
        p.drawLine(QPointF(12, 4.5), QPointF(12, 19.5))
        p.drawLine(QPointF(9, 19.5), QPointF(15, 19.5))
    elif name == "pixelate":
        for i, (x, y) in enumerate((x, y) for y in (4, 10, 16) for x in (4, 10, 16)):
            if i % 2 == 0:
                p.save()
                p.setBrush(p.pen().color())
                p.drawRect(r(x, y, 4, 4))
                p.restore()
            else:
                p.drawRect(r(x, y, 4, 4))
    elif name == "highlight":                         # a marker over a line of text
        _line(p, (6, 15), (13.5, 4.5), (18, 8), (10.5, 18.5), (6, 15))
        p.drawLine(QPointF(4, 21), QPointF(20, 21))
    elif name in ("undo", "redo"):
        d = 1 if name == "redo" else -1
        path = QPainterPath(QPointF(12 - 7 * d, 16))
        path.cubicTo(12 - 7 * d, 7, 12 + 6 * d, 6, 12 + 7 * d, 10)
        p.drawPath(path)
        _line(p, (12 + 3 * d, 9.5), (12 + 7.2 * d, 10.2), (12 + 7.8 * d, 6))
    elif name == "region":                            # dashed selection corners
        for (x, y), (dx, dy) in (((4, 4), (1, 1)), ((20, 4), (-1, 1)), ((4, 20), (1, -1)), ((20, 20), (-1, -1))):
            _line(p, (x, y + 4 * dy), (x, y), (x + 4 * dx, y))
        p.drawLine(QPointF(10, 4), QPointF(14, 4)); p.drawLine(QPointF(10, 20), QPointF(14, 20))
        p.drawLine(QPointF(4, 10), QPointF(4, 14)); p.drawLine(QPointF(20, 10), QPointF(20, 14))
    elif name == "window":
        p.drawRoundedRect(r(3.5, 5, 17, 14), 2, 2)
        p.drawLine(QPointF(3.5, 9), QPointF(20.5, 9))
    elif name == "record":
        p.drawEllipse(QPointF(12, 12), 8, 8)
        p.save(); p.setBrush(p.pen().color()); p.drawEllipse(QPointF(12, 12), 3.5, 3.5); p.restore()
    elif name == "stop":
        p.drawEllipse(QPointF(12, 12), 8, 8)
        p.save(); p.setBrush(p.pen().color()); p.drawRect(r(9, 9, 6, 6)); p.restore()
    elif name == "play":
        _line(p, (8, 5.5), (18.5, 12), (8, 18.5), (8, 5.5))
    elif name == "save":
        p.drawLine(QPointF(12, 4), QPointF(12, 14))
        _line(p, (8, 10.5), (12, 14.5), (16, 10.5))
        _line(p, (4.5, 15), (4.5, 19.5), (19.5, 19.5), (19.5, 15))
    elif name == "edit":
        _line(p, (5, 19), (5.5, 15.5), (15.5, 5.5), (18.5, 8.5), (8.5, 18.5), (5, 19))


def _pixmap(name: str, color: str, size: int) -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.scale(size / S, size / S)
    p.setPen(QPen(QColor(color), 1.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    p.setBrush(Qt.BrushStyle.NoBrush)
    _draw(name, p)
    p.end()
    return pm


OWN = {"crop", "arrow", "box", "pen", "text", "pixelate", "highlight", "undo", "redo", "region", "window", "record",
       "stop", "play", "save", "edit"}


@lru_cache(maxsize=64)
def icon(name: str, size: int = 20) -> QIcon:
    """ShotL's icon, or the shared glyph of that name (folder, trash, copies, desktop…)."""
    if name not in OWN:
        return glyph(name, size)
    ic = QIcon()
    for scale in (1, 2):
        s = size * scale
        ic.addPixmap(_pixmap(name, "#8c8c8c", s), QIcon.Mode.Normal, QIcon.State.Off)
        for mode, state in ((QIcon.Mode.Normal, QIcon.State.On), (QIcon.Mode.Active, QIcon.State.Off),
                            (QIcon.Mode.Active, QIcon.State.On)):
            ic.addPixmap(_pixmap(name, "#ffffff", s), mode, state)
        ic.addPixmap(_pixmap(name, "#3a3a3a", s), QIcon.Mode.Disabled, QIcon.State.Off)
    return ic
