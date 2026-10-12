"""Grimoire's own monochrome line icons, drawn with QPainter so they stay black & white whatever icon
theme is installed. glyph(name) -> QIcon with a gray normal state and a white active/checked state.
"""
from functools import lru_cache

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtSvg import QSvgRenderer

from grimoire.paths import ASSETS

S = 24   # design grid; icons are drawn on a 24x24 canvas and scaled


def _draw(name: str, p: QPainter):
    r = QRectF
    if name == "home":
        path = QPainterPath(QPointF(4, 11))
        path.lineTo(12, 4); path.lineTo(20, 11)
        p.drawPath(path)
        p.drawRect(r(6.5, 10.5, 11, 9))
    elif name == "mural":                                  # framed picture
        p.drawRoundedRect(r(3.5, 5, 17, 14), 2, 2)
        path = QPainterPath(QPointF(5, 17)); path.lineTo(10, 11.5); path.lineTo(13.5, 15); path.lineTo(16, 12.5)
        path.lineTo(19.5, 16.5); p.drawPath(path)
        p.drawEllipse(QPointF(15.5, 9), 1.4, 1.4)
    elif name == "sight":                                  # crosshair
        p.drawEllipse(QPointF(12, 12), 6.5, 6.5)
        for a, b in (((12, 2.5), (12, 8)), ((12, 16), (12, 21.5)), ((2.5, 12), (8, 12)), ((16, 12), (21.5, 12))):
            p.drawLine(QPointF(*a), QPointF(*b))
    elif name == "desktop":
        p.drawRoundedRect(r(3, 4.5, 18, 12), 1.5, 1.5)
        p.drawLine(QPointF(9, 20), QPointF(15, 20)); p.drawLine(QPointF(12, 16.5), QPointF(12, 20))
    elif name == "lock":
        p.drawRoundedRect(r(5.5, 10.5, 13, 9.5), 2, 2)
        path = QPainterPath(QPointF(8.5, 10.5)); path.lineTo(8.5, 8)
        path.arcTo(r(8.5, 4.5, 7, 7), 180, -180); path.lineTo(15.5, 10.5); p.drawPath(path)
    elif name == "splash":                                 # sparkle
        path = QPainterPath(QPointF(12, 3.5))
        path.quadTo(13, 11, 20.5, 12); path.quadTo(13, 13, 12, 20.5)
        path.quadTo(11, 13, 3.5, 12); path.quadTo(11, 11, 12, 3.5); p.drawPath(path)
    elif name == "login":                                  # person
        p.drawEllipse(QPointF(12, 8.5), 3.5, 3.5)
        path = QPainterPath(QPointF(5, 20)); path.cubicTo(5.5, 13.5, 18.5, 13.5, 19, 20); p.drawPath(path)
    elif name == "boot":                                   # power
        path = QPainterPath(); path.arcMoveTo(r(5, 5.5, 14, 14), 60); path.arcTo(r(5, 5.5, 14, 14), 60, 300)
        p.drawPath(path); p.drawLine(QPointF(12, 3.5), QPointF(12, 11))
    elif name == "taskbar":
        p.drawRoundedRect(r(3, 4, 18, 16), 2, 2)
        p.drawRoundedRect(r(6, 15.5, 12, 2.2), 1, 1)
    elif name == "windows":
        p.drawRoundedRect(r(3.5, 5, 17, 14), 2, 2)
        p.drawLine(QPointF(3.5, 9), QPointF(20.5, 9))
        for x in (15, 17.5):
            p.drawPoint(QPointF(x, 7))
    elif name == "motion":                                 # ease curve
        path = QPainterPath(QPointF(3.5, 19)); path.cubicTo(11, 19, 13, 5, 20.5, 5); p.drawPath(path)
    elif name == "style":                                  # stacked layers: a diamond and two chevrons
        top = QPainterPath(QPointF(4, 8)); top.lineTo(12, 4.8); top.lineTo(20, 8); top.lineTo(12, 11.2)
        top.closeSubpath(); p.drawPath(top)
        for y in (12, 16):
            path = QPainterPath(QPointF(4, y)); path.lineTo(12, y + 3.2); path.lineTo(20, y); p.drawPath(path)
    elif name == "colors":                                 # half-filled circle
        p.drawEllipse(QPointF(12, 12), 8, 8)
        path = QPainterPath(QPointF(12, 4)); path.arcTo(r(4, 4, 16, 16), 90, 180); path.closeSubpath()
        p.save(); p.setBrush(p.pen().color()); p.drawPath(path); p.restore()
    elif name == "fonts":
        f = p.font(); f.setPixelSize(13); f.setWeight(f.Weight.DemiBold); p.setFont(f)
        p.drawText(r(2, 4, 20, 16), Qt.AlignmentFlag.AlignCenter, "Aa")
    elif name == "cursor":
        path = QPainterPath(QPointF(7, 3.5)); path.lineTo(7, 18.5); path.lineTo(10.8, 14.8); path.lineTo(13.5, 20.5)
        path.lineTo(15.6, 19.5); path.lineTo(13, 13.8); path.lineTo(18, 13.5); path.closeSubpath(); p.drawPath(path)
    elif name == "icons":
        for x in (4.5, 13.5):
            for y in (4.5, 13.5):
                p.drawRoundedRect(r(x, y, 6, 6), 1.5, 1.5)
    elif name == "terminal":
        p.drawRoundedRect(r(3, 4.5, 18, 15), 2, 2)
        path = QPainterPath(QPointF(7, 9.5)); path.lineTo(10, 12); path.lineTo(7, 14.5); p.drawPath(path)
        p.drawLine(QPointF(12, 15), QPointF(17, 15))
    elif name == "tidy":                                   # a tray with sorted rows going in
        path = QPainterPath(QPointF(3.5, 13)); path.lineTo(3.5, 19.5); path.lineTo(20.5, 19.5); path.lineTo(20.5, 13)
        p.drawPath(path)
        path = QPainterPath(QPointF(3.5, 13)); path.lineTo(8.5, 13); path.lineTo(10, 15.5); path.lineTo(14, 15.5)
        path.lineTo(15.5, 13); path.lineTo(20.5, 13); p.drawPath(path)
        for y, (a, b) in ((5, (7, 17)), (8, (8.5, 15.5)), (10.8, (10, 14))):
            p.drawLine(QPointF(a, y), QPointF(b, y))
    elif name == "store":                                  # download tray
        p.drawLine(QPointF(12, 4), QPointF(12, 14))
        path = QPainterPath(QPointF(8, 10.5)); path.lineTo(12, 14.5); path.lineTo(16, 10.5); p.drawPath(path)
        path = QPainterPath(QPointF(4.5, 15)); path.lineTo(4.5, 19.5); path.lineTo(19.5, 19.5); path.lineTo(19.5, 15)
        p.drawPath(path)


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


@lru_cache(maxsize=128)
def glyph(name: str, size: int = 20) -> QIcon:
    icon = QIcon()
    for scale in (1, 2):
        s = size * scale
        icon.addPixmap(_pixmap(name, "#8c8c8c", s), QIcon.Mode.Normal, QIcon.State.Off)
        icon.addPixmap(_pixmap(name, "#ffffff", s), QIcon.Mode.Normal, QIcon.State.On)
        icon.addPixmap(_pixmap(name, "#ffffff", s), QIcon.Mode.Active, QIcon.State.Off)
        icon.addPixmap(_pixmap(name, "#ffffff", s), QIcon.Mode.Active, QIcon.State.On)
    return icon


def clover(size: int) -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    QSvgRenderer(str(ASSETS / "clover5.svg")).render(p)
    p.end()
    return pm
