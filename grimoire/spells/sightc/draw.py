# SPDX-License-Identifier: GPL-3.0-or-later
"""Crosshair drawing, shared by the Grimoire preview and the in-game overlay.

Lines are placed on whole pixels: with an odd thickness the center moves to the middle of a pixel, so a 1 px
cross is one sharp pixel wide instead of two blurry half pixels. Callers pass an integer center.
"""
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPainterPathStroker, QPen, QTransform

from grimoire.spells.sightc.config import Crosshair


def shape(c: Crosshair, cx: float, cy: float) -> QPainterPath:
    """The whole crosshair as one filled path, centred at (cx, cy) plus the offset."""
    fill, lines = QPainterPath(), QPainterPath()
    s, g, t = c.size, c.gap, c.thickness
    h = 0.5 if t % 2 else 0.0                     # odd lines: center on a pixel middle (see module doc)
    cx, cy = cx + c.offset_x + h, cy + c.offset_y + h
    g += h if c.rotation == 0 else 0

    def arm(x0, y0, x1, y1):
        lines.moveTo(x0, y0)
        lines.lineTo(x1, y1)

    style = c.style
    if style in ("Cross", "Cross + dot", "T", "Circle + cross"):
        if style != "T":
            arm(cx, cy - g, cx, cy - g - s)                  # top
        arm(cx, cy + g, cx, cy + g + s)                      # bottom
        arm(cx - g, cy, cx - g - s, cy)                      # left
        arm(cx + g, cy, cx + g + s, cy)                      # right
    if style in ("Circle", "Circle + dot"):
        lines.addEllipse(QPointF(cx, cy), s, s)
    if style == "Circle + cross":                            # ring sits on the outer end of the arms
        lines.addEllipse(QPointF(cx, cy), g + s * 0.6, g + s * 0.6)
    if style == "Square":
        lines.addRect(QRectF(cx - s, cy - s, 2 * s, 2 * s))
    if style == "Chevron":
        lines.moveTo(cx - s, cy + s * 0.8)
        lines.lineTo(cx, cy)
        lines.lineTo(cx + s, cy + s * 0.8)
    if style in ("Dot", "Cross + dot", "Circle + dot"):
        d = round(2 * (c.dot if style != "Dot" else max(c.dot, t / 2, 1)))     # diameter in whole pixels
        if d > 0:
            # a dot sits on the pixel grid by its own size: tiny ones are sharp squares, bigger ones round
            dx, dy = cx - h + (d % 2) / 2, cy - h + (d % 2) / 2
            box = QRectF(dx - d / 2, dy - d / 2, d, d)
            fill.addRect(box) if d <= 4 else fill.addEllipse(box)

    stroker = QPainterPathStroker()                          # line work -> filled outline: one fill, one outline
    stroker.setWidth(t)
    rounded = c.round_caps or style == "Chevron"
    stroker.setCapStyle(Qt.PenCapStyle.RoundCap if rounded else Qt.PenCapStyle.FlatCap)
    stroker.setJoinStyle(Qt.PenJoinStyle.RoundJoin if rounded else Qt.PenJoinStyle.MiterJoin)
    path = stroker.createStroke(lines).united(fill).simplified()
    if c.rotation:
        path = QTransform().translate(cx, cy).rotate(c.rotation).translate(-cx, -cy).map(path)
    return path


def paint(p: QPainter, c: Crosshair, cx: float, cy: float):
    path = shape(c, cx, cy)
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setOpacity(max(0.05, min(1.0, c.opacity)))
    if c.outline and c.outline_width > 0:
        pen = QPen(QColor(c.outline_color), c.outline_width * 2)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin if c.round_caps else Qt.PenJoinStyle.MiterJoin)
        p.strokePath(path, pen)                 # outline sits half outside the shape
    p.fillPath(path, QColor(c.color))
    p.restore()


def extent(c: Crosshair) -> int:
    """Half-size of the square that fully contains the crosshair (for sizing the overlay)."""
    reach = (c.gap + c.size) * 1.42 + c.thickness + c.outline_width * 2 + 4     # 1.42: room for rotation
    return int(reach + max(abs(c.offset_x), abs(c.offset_y)))
