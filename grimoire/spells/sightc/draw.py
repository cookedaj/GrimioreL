"""Crosshair drawing, shared by the Grimoire preview and the in-game overlay."""
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPainterPathStroker, QPen

from grimoire.spells.sightc.config import Crosshair


def shape(c: Crosshair, cx: float, cy: float) -> tuple[QPainterPath, QPainterPath]:
    """Return (filled shapes, stroked shapes) for the crosshair centred at (cx, cy)."""
    fill, lines = QPainterPath(), QPainterPath()
    cx, cy = cx + c.offset_x, cy + c.offset_y
    s, g, t = c.size, c.gap, c.thickness

    def arm(x0, y0, x1, y1):
        lines.moveTo(x0, y0)
        lines.lineTo(x1, y1)

    style = c.style
    if style in ("Cross", "Cross + dot", "T"):
        if style != "T":
            arm(cx, cy - g, cx, cy - g - s)                  # top
        arm(cx, cy + g, cx, cy + g + s)                      # bottom
        arm(cx - g, cy, cx - g - s, cy)                      # left
        arm(cx + g, cy, cx + g + s, cy)                      # right
    if style in ("Circle", "Circle + dot"):
        lines.addEllipse(QPointF(cx, cy), s, s)
    if style == "Chevron":
        lines.moveTo(cx - s, cy + s * 0.8)
        lines.lineTo(cx, cy)
        lines.lineTo(cx + s, cy + s * 0.8)
    if style in ("Dot", "Cross + dot", "Circle + dot"):
        r = max(0.5, c.dot if style != "Dot" else max(c.dot, t))
        fill.addEllipse(QPointF(cx, cy), r, r)

    # turn the line work into a filled outline so everything shares one fill + outline pass
    stroker = QPainterPathStroker()
    stroker.setWidth(t)
    stroker.setCapStyle(Qt.PenCapStyle.FlatCap if style != "Chevron" else Qt.PenCapStyle.RoundCap)
    stroker.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
    return fill, stroker.createStroke(lines)


def paint(p: QPainter, c: Crosshair, cx: float, cy: float):
    fill, stroked = shape(c, cx, cy)
    path = stroked.united(fill)
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setOpacity(max(0.05, min(1.0, c.opacity)))
    if c.outline and c.outline_width > 0:
        pen = QPen(QColor(c.outline_color), c.outline_width * 2)
        pen.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
        p.strokePath(path, pen)                 # outline sits half outside the shape
    p.fillPath(path, QColor(c.color))
    p.restore()


def extent(c: Crosshair) -> int:
    """Half-size of the square that fully contains the crosshair (for sizing the overlay)."""
    reach = c.gap + c.size + c.thickness + c.outline_width * 2 + 4
    return int(reach + max(abs(c.offset_x), abs(c.offset_y)))

