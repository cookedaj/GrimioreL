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
    elif name == "looks":                                  # two framed pictures, one behind the other
        back = QPainterPath(QPointF(7, 9)); back.lineTo(7, 5.5); back.quadTo(7, 3.5, 9, 3.5); back.lineTo(18.5, 3.5)
        back.quadTo(20.5, 3.5, 20.5, 5.5); back.lineTo(20.5, 12.5); back.quadTo(20.5, 14.5, 18.5, 14.5)
        back.lineTo(17, 14.5); p.drawPath(back)
        p.drawRoundedRect(r(3.5, 9, 13.5, 11), 2, 2)
        path = QPainterPath(QPointF(5.5, 18)); path.lineTo(9, 14); path.lineTo(11.5, 16.5); path.lineTo(15, 13)
        p.drawPath(path)
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
    elif name == "folder":
        path = QPainterPath(QPointF(3.5, 7)); path.lineTo(3.5, 18.5); path.lineTo(20.5, 18.5); path.lineTo(20.5, 8.5)
        path.lineTo(11.5, 8.5); path.lineTo(9.5, 5.5); path.lineTo(3.5, 5.5); path.closeSubpath(); p.drawPath(path)
    elif name == "vault":                                  # a safe: door, dial and feet
        p.drawRoundedRect(r(3.5, 4, 17, 15.5), 2, 2)
        p.drawEllipse(QPointF(12.5, 11.75), 3.6, 3.6)
        p.drawEllipse(QPointF(12.5, 11.75), 1, 1)
        for a, b in (((12.5, 8.15), (12.5, 9.4)), ((12.5, 14.1), (12.5, 15.35)), ((8.9, 11.75), (10.15, 11.75)),
                     ((14.85, 11.75), (16.1, 11.75))):
            p.drawLine(QPointF(*a), QPointF(*b))
        p.drawLine(QPointF(6.2, 8), QPointF(6.2, 9.5)); p.drawLine(QPointF(6.2, 14), QPointF(6.2, 15.5))
        p.drawLine(QPointF(6.5, 19.5), QPointF(6.5, 21)); p.drawLine(QPointF(17.5, 19.5), QPointF(17.5, 21))
    elif name == "clock":
        p.drawEllipse(QPointF(12, 12), 8, 8)
        path = QPainterPath(QPointF(12, 7.5)); path.lineTo(12, 12); path.lineTo(15.5, 14); p.drawPath(path)
    elif name == "bigfile":                                # a document with a filled-in block
        path = QPainterPath(QPointF(6, 3.5)); path.lineTo(14, 3.5); path.lineTo(18.5, 8); path.lineTo(18.5, 20.5)
        path.lineTo(6, 20.5); path.closeSubpath(); p.drawPath(path)
        p.drawRect(r(9, 12.5, 6.5, 5))
    elif name == "copies":                                 # two overlapping documents
        p.drawRoundedRect(r(8, 3.5, 11.5, 14), 1.5, 1.5)
        path = QPainterPath(QPointF(8, 7)); path.lineTo(4.5, 7); path.lineTo(4.5, 20.5); path.lineTo(16, 20.5)
        path.lineTo(16, 17.5); p.drawPath(path)
    elif name == "files":                                  # two stacked folders
        path = QPainterPath(QPointF(5.5, 9)); path.lineTo(5.5, 19.5); path.lineTo(20.5, 19.5); path.lineTo(20.5, 10.5)
        path.lineTo(12.5, 10.5); path.lineTo(11, 8); path.lineTo(5.5, 8); path.closeSubpath(); p.drawPath(path)
        path = QPainterPath(QPointF(3, 16.5)); path.lineTo(3, 5); path.lineTo(8.5, 5); path.lineTo(10, 7)
        p.drawPath(path)
    elif name == "document":
        path = QPainterPath(QPointF(6, 3.5)); path.lineTo(14, 3.5); path.lineTo(18.5, 8); path.lineTo(18.5, 20.5)
        path.lineTo(6, 20.5); path.closeSubpath(); p.drawPath(path)
        for y in (11, 14, 17):
            p.drawLine(QPointF(8.5, y), QPointF(16, y))
    elif name == "video":
        p.drawRoundedRect(r(3, 6, 13, 12), 2, 2)
        path = QPainterPath(QPointF(16, 10.5)); path.lineTo(21, 7.5); path.lineTo(21, 16.5); path.lineTo(16, 13.5)
        p.drawPath(path)
    elif name == "music":
        p.drawLine(QPointF(9.5, 17), QPointF(9.5, 5)); p.drawLine(QPointF(9.5, 5), QPointF(18.5, 3.5))
        p.drawLine(QPointF(18.5, 3.5), QPointF(18.5, 15.5))
        p.drawEllipse(QPointF(7, 17.5), 2.5, 2.2); p.drawEllipse(QPointF(16, 16), 2.5, 2.2)
    elif name == "trash":
        p.drawLine(QPointF(4, 6.5), QPointF(20, 6.5))
        path = QPainterPath(QPointF(9, 6.5)); path.lineTo(9.5, 4); path.lineTo(14.5, 4); path.lineTo(15, 6.5); p.drawPath(path)
        path = QPainterPath(QPointF(6, 6.5)); path.lineTo(7, 20.5); path.lineTo(17, 20.5); path.lineTo(18, 6.5); p.drawPath(path)
        p.drawLine(QPointF(10, 10), QPointF(10.3, 17)); p.drawLine(QPointF(14, 10), QPointF(13.7, 17))
    elif name == "drive":
        p.drawRoundedRect(r(3, 7, 18, 10), 2, 2)
        p.drawLine(QPointF(6, 12), QPointF(12, 12)); p.drawPoint(QPointF(17.5, 12))
    elif name in ("back", "forward"):
        d = -1 if name == "back" else 1
        path = QPainterPath(QPointF(12 - 3.5 * d, 6)); path.lineTo(12 + 3.5 * d, 12); path.lineTo(12 - 3.5 * d, 18)
        p.drawPath(path)
    elif name == "up":
        path = QPainterPath(QPointF(6, 14.5)); path.lineTo(12, 8.5); path.lineTo(18, 14.5); p.drawPath(path)
    elif name == "grid":
        for x in (4.5, 13.5):
            for y in (4.5, 13.5):
                p.drawRect(r(x, y, 6, 6))
    elif name == "list":
        for y in (6.5, 12, 17.5):
            p.drawLine(QPointF(8.5, y), QPointF(20, y)); p.drawPoint(QPointF(4.5, y))
    elif name == "search":
        p.drawEllipse(QPointF(10.5, 10.5), 6, 6); p.drawLine(QPointF(15, 15), QPointF(20, 20))
    elif name == "hidden":                                 # an eye
        path = QPainterPath(QPointF(3, 12)); path.quadTo(12, 3.5, 21, 12); path.quadTo(12, 20.5, 3, 12); p.drawPath(path)
        p.drawEllipse(QPointF(12, 12), 2.8, 2.8)
    elif name == "preview":                                # panel on the right
        p.drawRoundedRect(r(3, 4.5, 18, 15), 2, 2); p.drawLine(QPointF(14, 4.5), QPointF(14, 19.5))
    elif name == "newfolder":
        path = QPainterPath(QPointF(3.5, 7)); path.lineTo(3.5, 18.5); path.lineTo(20.5, 18.5); path.lineTo(20.5, 8.5)
        path.lineTo(11.5, 8.5); path.lineTo(9.5, 5.5); path.lineTo(3.5, 5.5); path.closeSubpath(); p.drawPath(path)
        p.drawLine(QPointF(12, 11), QPointF(12, 16.5)); p.drawLine(QPointF(9.25, 13.75), QPointF(14.75, 13.75))
    elif name == "store":                                  # download tray
        p.drawLine(QPointF(12, 4), QPointF(12, 14))
        path = QPainterPath(QPointF(8, 10.5)); path.lineTo(12, 14.5); path.lineTo(16, 10.5); p.drawPath(path)
        path = QPainterPath(QPointF(4.5, 15)); path.lineTo(4.5, 19.5); path.lineTo(19.5, 19.5); path.lineTo(19.5, 15)
        p.drawPath(path)
    elif name == "optimize":                               # speedometer: an open dial with the needle up high
        path = QPainterPath(); path.arcMoveTo(r(3.5, 5, 17, 17), 200); path.arcTo(r(3.5, 5, 17, 17), 200, -220)
        p.drawPath(path)
        p.drawLine(QPointF(12, 13.5), QPointF(16.2, 8.6)); p.drawEllipse(QPointF(12, 13.5), 1.3, 1.3)
    elif name == "system":                                 # a screen with a pulse line across it
        p.drawRoundedRect(r(3, 4.5, 18, 13), 2, 2)
        p.drawLine(QPointF(9, 20.5), QPointF(15, 20.5))
        path = QPainterPath(QPointF(5.5, 11.5)); path.lineTo(9, 11.5); path.lineTo(10.8, 8); path.lineTo(13.2, 15)
        path.lineTo(15, 11.5); path.lineTo(18.5, 11.5); p.drawPath(path)
    elif name == "update":                                 # an arrow rising out of a circle: a newer version
        p.drawEllipse(QPointF(12, 12), 8.5, 8.5)
        p.drawLine(QPointF(12, 16.5), QPointF(12, 7.8))
        path = QPainterPath(QPointF(8.6, 11.2)); path.lineTo(12, 7.8); path.lineTo(15.4, 11.2); p.drawPath(path)
    elif name == "check":
        path = QPainterPath(QPointF(5, 12.5)); path.lineTo(10, 17.5); path.lineTo(19, 7); p.drawPath(path)
    elif name == "bell":                                   # a bell with its clapper
        path = QPainterPath(QPointF(5, 17)); path.lineTo(6.5, 15); path.lineTo(6.5, 10.5)
        path.cubicTo(6.5, 3.5, 17.5, 3.5, 17.5, 10.5); path.lineTo(17.5, 15); path.lineTo(19, 17)
        path.closeSubpath(); p.drawPath(path)
        path = QPainterPath(QPointF(10, 19.5)); path.quadTo(12, 21.5, 14, 19.5); p.drawPath(path)
        p.drawLine(QPointF(12, 3), QPointF(12, 4.6))
    elif name == "terminall":                              # a terminal window with a tab strip and a prompt
        p.drawRoundedRect(r(3, 4.5, 18, 15), 2, 2); p.drawLine(QPointF(3, 8.5), QPointF(21, 8.5))
        path = QPainterPath(QPointF(7, 11.5)); path.lineTo(9.5, 13.75); path.lineTo(7, 16); p.drawPath(path)
        p.drawLine(QPointF(11.5, 16), QPointF(16, 16))
    elif name == "plus":
        p.drawLine(QPointF(12, 5.5), QPointF(12, 18.5)); p.drawLine(QPointF(5.5, 12), QPointF(18.5, 12))
    elif name == "down":
        path = QPainterPath(QPointF(6, 9.5)); path.lineTo(12, 15.5); path.lineTo(18, 9.5); p.drawPath(path)
    elif name == "close":
        p.drawLine(QPointF(7, 7), QPointF(17, 17)); p.drawLine(QPointF(17, 7), QPointF(7, 17))
    elif name in ("splith", "splitv"):                     # a pane split side by side / top and bottom
        p.drawRoundedRect(r(3.5, 5, 17, 14), 2, 2)
        if name == "splith":
            p.drawLine(QPointF(12, 5), QPointF(12, 19))
        else:
            p.drawLine(QPointF(3.5, 12), QPointF(20.5, 12))
    elif name == "palette":                                # a bolt: quick commands
        path = QPainterPath(QPointF(13.5, 3.5)); path.lineTo(6.5, 13.5); path.lineTo(11.5, 13.5); path.lineTo(10.5, 20.5)
        path.lineTo(17.5, 10.5); path.lineTo(12.5, 10.5); path.closeSubpath(); p.drawPath(path)
    elif name == "focus":                                  # a stopwatch: crown, open ring and one hand
        path = QPainterPath(); path.arcMoveTo(r(4.5, 6, 15, 15), 75); path.arcTo(r(4.5, 6, 15, 15), 75, 330)
        p.drawPath(path)
        p.drawLine(QPointF(10, 3), QPointF(14, 3)); p.drawLine(QPointF(12, 3), QPointF(12, 6))
        p.drawLine(QPointF(12, 13.5), QPointF(14.8, 10.7))
    elif name == "net":                                    # traffic: an arrow down beside an arrow up
        p.drawLine(QPointF(8, 4), QPointF(8, 19.5))
        path = QPainterPath(QPointF(4.5, 16)); path.lineTo(8, 19.5); path.lineTo(11.5, 16); p.drawPath(path)
        p.drawLine(QPointF(16, 20), QPointF(16, 4.5))
        path = QPainterPath(QPointF(12.5, 8)); path.lineTo(16, 4.5); path.lineTo(19.5, 8); p.drawPath(path)
    elif name == "wifi":                                   # three arcs over a dot
        for rad in (3.6, 7.4, 11.2):
            path = QPainterPath(); path.arcMoveTo(r(12 - rad, 18.5 - rad, rad * 2, rad * 2), 45)
            path.arcTo(r(12 - rad, 18.5 - rad, rad * 2, rad * 2), 45, 90); p.drawPath(path)
        p.drawEllipse(QPointF(12, 18.5), 0.9, 0.9)
    elif name == "link":                                   # two chain links: connections
        p.drawRoundedRect(r(2.8, 9.2, 10.5, 5.6), 2.8, 2.8)
        p.drawRoundedRect(r(10.7, 9.2, 10.5, 5.6), 2.8, 2.8)


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


def meter(cpu: float, ram: float, size: int = 64, color: str = "#ffffff") -> QPixmap:
    """The tray icon: two gauges, CPU on the left and RAM on the right, filled solid from the bottom (0..100)."""
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.scale(size / S, size / S)
    pen = QPen(QColor(color), 1.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
    for x, value in ((3.5, cpu), (13.5, ram)):
        box = QRectF(x, 2.5, 7, 19)
        path = QPainterPath()
        path.addRoundedRect(box, 1.8, 1.8)
        h = box.height() * max(0.0, min(100.0, value)) / 100
        p.save()
        p.setClipRect(QRectF(x - 1, box.bottom() - h, 9, h + 1))
        p.fillPath(path, QColor(color))                    # solid, so it still reads at 22 px
        p.restore()
        p.strokePath(path, pen)
    p.end()
    return pm


def clover(size: int) -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    QSvgRenderer(str(ASSETS / "clover5.svg")).render(p)
    p.end()
    return pm
