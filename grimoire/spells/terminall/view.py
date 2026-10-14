"""One terminal on screen: paints pyte's cells with the colors the program asked for (Grimoire's black & white rule
is for its own chrome; default text is white on black), plus scrollback, selection, search hits, the cursor and
mouse reporting. Output arrives in bursts, so repaints are batched on a short timer.
"""
import math
import shlex

from PySide6.QtCore import QEvent, QPointF, QRect, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QClipboard, QColor, QFont, QFontMetricsF, QGuiApplication, QPainter, QPen
from PySide6.QtWidgets import QScrollBar, QWidget

from grimoire.spells.terminall import emulator, keys

FG, BG = "#f2f2f2", "#000000"
NAMED = {"black": "#000000", "red": "#cd3131", "green": "#0dbc79", "brown": "#e5e510", "blue": "#2472c8",
         "magenta": "#bc3fbc", "cyan": "#11a8cd", "white": "#e5e5e5", "brightblack": "#666666",
         "brightred": "#f14c4c", "brightgreen": "#23d18b", "brightbrown": "#f5f543", "brightyellow": "#f5f543",
         "brightblue": "#3b8eea", "brightmagenta": "#d670d6", "brightcyan": "#29b8db", "brightwhite": "#ffffff"}
PAD = 6
SCROLLBAR = 8
WORD = set("-_./~:@%+=?&#")
# box drawing drawn as lines so borders join across cells: char -> (up, down, left, right) weights, 2 = heavy
BOX = {"─": (0, 0, 1, 1), "━": (0, 0, 2, 2), "│": (1, 1, 0, 0), "┃": (2, 2, 0, 0), "┌": (0, 1, 0, 1),
       "┐": (0, 1, 1, 0), "└": (1, 0, 0, 1), "┘": (1, 0, 1, 0), "├": (1, 1, 0, 1), "┤": (1, 1, 1, 0),
       "┬": (0, 1, 1, 1), "┴": (1, 0, 1, 1), "┼": (1, 1, 1, 1), "╭": (0, 1, 0, 1), "╮": (0, 1, 1, 0),
       "╰": (1, 0, 0, 1), "╯": (1, 0, 1, 0), "┏": (0, 2, 0, 2), "┓": (0, 2, 2, 0), "┗": (2, 0, 0, 2),
       "┛": (2, 0, 2, 0), "╴": (0, 0, 1, 0), "╶": (0, 0, 0, 1), "╵": (1, 0, 0, 0), "╷": (0, 1, 0, 0)}
BLOCKS = {"█": (0, 0, 1, 1), "▀": (0, 0, 1, .5), "▄": (0, .5, 1, .5), "▌": (0, 0, .5, 1), "▐": (.5, 0, .5, 1)}


def _palette() -> dict:
    """pyte's 256-color table, with its first 16 swapped for the palette above so named and indexed colors match."""
    from pyte.graphics import FG_BG_256
    order = ["black", "red", "green", "brown", "blue", "magenta", "cyan", "white"]
    names = order + ["bright" + n for n in order]
    out = {h: NAMED[names[i]] for i, h in enumerate(FG_BG_256[:16])}
    return out


class TerminalView(QWidget):
    titleChanged = Signal()
    activated = Signal(object)
    shortcut = Signal(object)          # a key press the page may want (new tab, split…); sets e.accepted

    def __init__(self, session, profile: dict, parent=None):
        super().__init__(parent)
        self.session = session
        self.profile = profile
        self.zoom = 0
        self.scroll = 0                # lines scrolled back from the live screen
        self.seen_pushed = session.screen.pushed
        self.sel = None                # ((abs line, col), (abs line, col)) anchor and end
        self.selecting = False
        self.hits: list = []           # search matches (abs line, col0, col1)
        self.hit = -1
        self.query = ""
        self.show_focus = False
        self.last_title = ""
        self._mouse_cell = None
        self._mouse_btn = None
        self._click_time = 0
        self._colors = {}
        self._remap = _palette()
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
        self.setAttribute(Qt.WidgetAttribute.WA_InputMethodEnabled)
        self.setMouseTracking(True)
        self.setAcceptDrops(True)
        self.setCursor(Qt.CursorShape.IBeamCursor)
        self.bar = QScrollBar(Qt.Orientation.Vertical, self)
        self.bar.setCursor(Qt.CursorShape.ArrowCursor)
        self.bar.valueChanged.connect(self._bar_moved)
        self.paint_timer = QTimer(self, singleShot=True, interval=16)
        self.paint_timer.timeout.connect(self._refresh)
        session.changed.connect(self._changed)
        self.set_profile(profile)

    # -- font and size -----------------------------------------------------------------------------------------
    def set_profile(self, profile: dict):
        self.profile = profile
        self.session.screen.set_scrollback(profile["scrollback"])
        font = QFont(profile["font"])
        font.setStyleHint(QFont.StyleHint.TypeWriter)
        font.setPointSizeF(max(5, profile["size"] + self.zoom))
        font.setKerning(False)
        fm = QFontMetricsF(font)
        adv = fm.horizontalAdvance("M")
        self.cw = math.ceil(adv - 0.05)
        self.ch = math.ceil(fm.height())
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, self.cw - adv)   # keep runs of text on the grid
        self.ascent = round(fm.ascent() + (self.ch - fm.height()) / 2)
        self.fonts = {}
        for bold in (False, True):
            for italic in (False, True):
                f = QFont(font)
                f.setBold(bold)
                f.setItalic(italic)
                self.fonts[bold, italic] = f
        self._fit()
        self.update()

    def set_zoom(self, step: int | None):
        self.zoom = 0 if step is None else max(-6, min(30, self.zoom + step))
        self.set_profile(self.profile)

    def grid(self) -> tuple[int, int]:
        w = self.width() - 2 * PAD - SCROLLBAR
        return max(2, int(w // self.cw)), max(1, int((self.height() - 2 * PAD) // self.ch))

    def _fit(self):
        cols, rows = self.grid()
        self.session.resize(cols, rows)
        self.bar.setGeometry(self.width() - SCROLLBAR, 0, SCROLLBAR, self.height())
        self._sync_bar()

    def resizeEvent(self, e):
        self._fit()
        super().resizeEvent(e)

    # -- following output --------------------------------------------------------------------------------------
    def _changed(self):
        if not self.paint_timer.isActive():     # don't restart it: a steady stream must still repaint
            self.paint_timer.start()

    def _refresh(self):
        scr = self.session.screen
        grown = scr.pushed - self.seen_pushed
        self.seen_pushed = scr.pushed
        if self.scroll:
            self.scroll = max(0, min(self.scroll + grown, len(scr.history)))    # keep looking at the same lines
        scr.dirty.clear()
        scr.bell_rung = False
        self._sync_bar()
        title = self.title()
        if title != self.last_title:
            self.last_title = title
            self.titleChanged.emit()
        self.update()

    def title(self) -> str:
        scr = self.session.screen
        if scr.title:
            return scr.title
        fg = self.session.foreground()
        if fg:
            return fg
        cwd = self.session.cwd()
        if cwd is None:
            return "Shell"
        from grimoire.fsutil import tilde
        return tilde(cwd)

    def _sync_bar(self):
        scr = self.session.screen
        h = len(scr.history) if scr.alt is None else 0
        self.bar.blockSignals(True)
        self.bar.setRange(0, h)
        self.bar.setPageStep(scr.lines)
        self.bar.setValue(h - min(self.scroll, h))
        self.bar.blockSignals(False)
        self.bar.setVisible(h > 0)

    def _bar_moved(self, v):
        self.scroll = self.bar.maximum() - v
        self.update()

    def scroll_by(self, n: int):
        scr = self.session.screen
        self.scroll = max(0, min(self.scroll + n, len(scr.history) if scr.alt is None else 0))
        self._sync_bar()
        self.update()

    def to_bottom(self):
        if self.scroll:
            self.scroll = 0
            self._sync_bar()
            self.update()

    # -- painting ----------------------------------------------------------------------------------------------
    def _color(self, name: str, fg: bool) -> QColor:
        key = (name, fg)
        c = self._colors.get(key)
        if c is None:
            if name == "default":
                c = QColor(FG if fg else BG)
            elif name in NAMED:
                c = QColor(NAMED[name])
            else:
                c = QColor(self._remap.get(name) or ("#" + name if len(name) == 6 else FG if fg else BG))
                if not c.isValid():
                    c = QColor(FG if fg else BG)
            self._colors[key] = c
        return c

    def _top(self) -> int:
        """Index (into history + screen) of the first visible row."""
        return len(self.session.screen.history) - self.scroll

    def paintEvent(self, _):
        scr = self.session.screen
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(BG))
        top = self._top()
        cols = scr.columns
        sel = self._sel_range()
        hits = {}
        for n, (line, c0, c1) in enumerate(self.hits):
            hits.setdefault(line - scr.dropped, []).append((c0, c1, n == self.hit))
        for r in range(scr.lines):
            i = top + r
            if 0 <= i < len(scr.history) + scr.lines:
                self._paint_row(p, scr.line(i), cols, PAD + r * self.ch, i, sel, hits.get(i))
        self._paint_cursor(p, top)
        if self.show_focus and self.hasFocus():
            p.setPen(QColor("#5a5a5a"))
            p.drawRect(self.rect().adjusted(0, 0, -1, -1))
        p.end()

    def _cell_state(self, i, x, sel, hits):
        if sel and (sel[0][0], sel[0][1]) <= (i, x) < (sel[1][0], sel[1][1]):
            return 2
        for c0, c1, cur in hits or ():
            if c0 <= x < c1:
                return 2 if cur else 1
        return 0

    def _paint_row(self, p: QPainter, row, cols, y, i, sel, hits):
        runs = []                      # [x, cells, text, fg, bg, bold, italic, underline, strike, simple]
        x = 0
        while x < cols:
            c = row[x]
            data = c.data
            if data == "":             # second half of a wide character
                x += 1
                continue
            width = 2 if x + 1 < cols and row[x + 1].data == "" else 1
            fg, bg = self._color(c.fg, True), self._color(c.bg, False)
            if c.reverse:
                fg, bg = bg, fg
            state = self._cell_state(i, x, sel, hits) if (sel or hits) else 0
            if state == 2:
                fg, bg = QColor(BG), QColor("#e8e8e8")
            elif state == 1:
                fg, bg = QColor("#ffffff"), QColor("#4a4a4a")
            simple = width == 1 and " " <= data <= "~"
            last = runs[-1] if runs else None
            if simple and last and last[9] and last[3] == fg and last[4] == bg and last[5] == c.bold \
                    and last[6] == c.italics and last[7] == c.underscore and last[8] == c.strikethrough:
                last[1] += 1
                last[2] += data
            else:
                runs.append([x, width, data, fg, bg, c.bold, c.italics, c.underscore, c.strikethrough, simple])
            x += width
        black = QColor(BG)
        for run in runs:
            if run[4] != black:
                p.fillRect(QRect(PAD + run[0] * self.cw, y, run[1] * self.cw, self.ch), run[4])
        for x0, cells, text, fg, bg, bold, italic, ul, strike, simple in runs:
            if text.strip() == "" and not ul and not strike:
                continue
            px = PAD + x0 * self.cw
            if text in BOX or text in BLOCKS:
                self._paint_box(p, text, px, y, fg)
            else:
                p.setFont(self.fonts[bool(bold), bool(italic)])
                p.setPen(fg)
                if simple:
                    p.drawText(QPointF(px, y + self.ascent), text)
                else:
                    p.drawText(QRectF(px, y, cells * self.cw, self.ch),
                               Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter, text)
            if ul or strike:
                ly = y + (self.ascent + 2 if ul else self.ch // 2)
                p.fillRect(QRect(px, min(ly, y + self.ch - 1), cells * self.cw, 1), fg)

    def _paint_box(self, p: QPainter, ch: str, x, y, color: QColor):
        if ch in BLOCKS:
            fx, fy, fw, fh = BLOCKS[ch]
            p.fillRect(QRectF(x + fx * self.cw, y + fy * self.ch, fw * self.cw, fh * self.ch), color)
            return
        up, down, left, right = BOX[ch]
        cx, cy = x + self.cw // 2, y + self.ch // 2
        for weight, rect in ((up, (cx, y, 0, cy - y)), (down, (cx, cy, 0, y + self.ch - cy)),
                             (left, (x, cy, cx - x, 0)), (right, (cx, cy, x + self.cw - cx, 0))):
            if weight:
                t = 2 if weight == 2 else 1
                rx, ry, rw, rh = rect
                p.fillRect(QRect(rx - (t // 2 if not rw else 0), ry - (t // 2 if not rh else 0),
                                 rw or t, rh or t), color)
        if (up or down) and (left or right):     # fill the joint
            t = 2 if 2 in (up, down, left, right) else 1
            p.fillRect(QRect(cx - t // 2, cy - t // 2, t, t), color)

    def _paint_cursor(self, p: QPainter, top: int):
        scr = self.session.screen
        if scr.cursor.hidden or not self.session.alive:
            return
        r = len(scr.history) + scr.cursor.y - top
        if not 0 <= r < scr.lines:
            return
        x = min(scr.cursor.x, scr.columns - 1)
        rect = QRect(PAD + x * self.cw, PAD + r * self.ch, self.cw, self.ch)
        shape = scr.cursor_shape or self.profile["cursor"]
        white = QColor("#f2f2f2")
        if shape == "bar":
            p.fillRect(QRect(rect.x(), rect.y(), 2, rect.height()), white)
        elif shape == "underline":
            p.fillRect(QRect(rect.x(), rect.bottom() - 1, rect.width(), 2), white)
        elif self.hasFocus():
            p.fillRect(rect, white)
            c = scr.buffer[scr.cursor.y][x]
            if c.data.strip():
                p.setFont(self.fonts[bool(c.bold), bool(c.italics)])
                p.setPen(QColor(BG))
                p.drawText(QRectF(rect), Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter, c.data)
        else:
            p.setPen(QPen(white, 1))
            p.drawRect(rect.adjusted(0, 0, -1, -1))

    # -- text and selection ------------------------------------------------------------------------------------
    def row_text(self, i: int) -> tuple[str, list[int]]:
        """A line's text and, for each character, the column it sits in."""
        scr = self.session.screen
        row = scr.line(i)
        chars, cols = [], []
        for x in range(scr.columns):
            d = row[x].data
            if d:
                chars.append(d)
                cols.extend([x] * len(d))
        return "".join(chars), cols

    def _sel_range(self):
        """Selection as ((i, col), (i, col_end_exclusive)) in history + screen indexes."""
        if not self.sel:
            return None
        drop = self.session.screen.dropped
        a, b = sorted(self.sel)
        if a == b:
            return None
        return (a[0] - drop, a[1]), (b[0] - drop, b[1])

    def selected_text(self) -> str:
        rng = self._sel_range()
        if not rng:
            return ""
        scr = self.session.screen
        (i0, c0), (i1, c1) = rng
        out = []
        for i in range(max(0, i0), min(i1, len(scr.history) + scr.lines - 1) + 1):
            text, cols = self.row_text(i)
            lo = c0 if i == i0 else 0
            hi = c1 if i == i1 else scr.columns
            out.append("".join(ch for ch, x in zip(text, cols) if lo <= x < hi).rstrip())
        return "\n".join(out)

    def cell_at(self, pos) -> tuple[int, int]:
        """(abs line, col) under a point; col may equal the column count (end of line)."""
        scr = self.session.screen
        col = max(0, min(scr.columns, round((pos.x() - PAD) / self.cw)))
        r = max(0, min(scr.lines - 1, int((pos.y() - PAD) // self.ch)))
        return scr.dropped + self._top() + r, col

    def _word_at(self, line: int, col: int):
        i = line - self.session.screen.dropped
        text, cols = self.row_text(i)
        idx = next((k for k, x in enumerate(cols) if x >= col), None)
        if idx is None or not (text[idx].isalnum() or text[idx] in WORD):
            return (line, col), (line, col + 1)
        a = b = idx
        while a > 0 and (text[a - 1].isalnum() or text[a - 1] in WORD):
            a -= 1
        while b + 1 < len(text) and (text[b + 1].isalnum() or text[b + 1] in WORD):
            b += 1
        return (line, cols[a]), (line, cols[b] + 1)

    def copy(self, mode=QClipboard.Mode.Clipboard):
        text = self.selected_text()
        if text:
            QGuiApplication.clipboard().setText(text, mode)

    def paste(self, mode=QClipboard.Mode.Clipboard):
        text = QGuiApplication.clipboard().text(mode)
        if text:
            self.send_text(text, paste=True)

    def send_text(self, text: str, paste=False):
        text = text.replace("\r\n", "\r").replace("\n", "\r")
        if paste and emulator.BRACKETED_PASTE in self.session.screen.mode:
            text = "\x1b[200~" + text.replace("\x1b[201~", "") + "\x1b[201~"
        self.to_bottom()
        self.session.write_text(text)

    def select_all(self):
        scr = self.session.screen
        self.sel = ((scr.dropped, 0), (scr.dropped + len(scr.history) + scr.lines - 1, scr.columns))
        self.update()

    def clear_scrollback(self):
        self.session.screen.history.clear()
        self.scroll = 0
        self.sel = None
        self.hits = []
        self._sync_bar()
        self.update()

    # -- search ------------------------------------------------------------------------------------------------
    def find(self, query: str, backwards=True) -> tuple[int, int]:
        """Jump to the next match (older first, like Konsole). Returns (match number, total)."""
        scr = self.session.screen
        if query != self.query or not self.hits:
            self.query = query
            self.hits, self.hit = [], -1
            if query:
                q = query.lower()
                for i in range(len(scr.history) + scr.lines):
                    text, cols = self.row_text(i)
                    low = text.lower()
                    k = low.find(q)
                    while k >= 0 and len(self.hits) < 5000:
                        end = k + len(q) - 1
                        self.hits.append((scr.dropped + i, cols[k], cols[min(end, len(cols) - 1)] + 1))
                        k = low.find(q, k + 1)
            self.hit = len(self.hits) if backwards else -1
        if not self.hits:
            self.sel = None
            self.update()
            return 0, 0
        self.hit = (self.hit + (-1 if backwards else 1)) % len(self.hits)
        line, c0, c1 = self.hits[self.hit]
        self.sel = ((line, c0), (line, c1))
        i = line - scr.dropped
        top = self._top()
        if not top <= i < top + scr.lines:          # bring it into view, a few lines from the top
            self.scroll = max(0, min(len(scr.history), len(scr.history) - i + scr.lines // 3))
            self._sync_bar()
        self.update()
        return self.hit + 1, len(self.hits)

    def end_search(self):
        self.hits, self.hit, self.query = [], -1, ""
        self.update()

    # -- keyboard ----------------------------------------------------------------------------------------------
    def event(self, e):
        if e.type() == QEvent.Type.ShortcutOverride:
            e.accept()                               # keys belong to the terminal, not to app-wide shortcuts
            return True
        if e.type() == QEvent.Type.KeyPress and e.key() in (Qt.Key.Key_Tab, Qt.Key.Key_Backtab):
            self.keyPressEvent(e)                    # Tab is a key here, not focus navigation
            return True
        return super().event(e)

    def keyPressEvent(self, e):
        e.ignore()
        self.shortcut.emit(e)                        # the page's shortcuts first (tabs, splits, palette…)
        if e.isAccepted():
            return
        mods = e.modifiers()
        ctrl_shift = Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier
        key = e.key()
        if (mods & ctrl_shift) == ctrl_shift and key == Qt.Key.Key_C:
            return self.copy()
        if (mods & ctrl_shift) == ctrl_shift and key == Qt.Key.Key_V:
            return self.paste()
        if (mods & ctrl_shift) == ctrl_shift and key == Qt.Key.Key_A:
            return self.select_all()
        if mods & Qt.KeyboardModifier.ShiftModifier and key == Qt.Key.Key_Insert:
            return self.paste(QClipboard.Mode.Selection)
        if mods & Qt.KeyboardModifier.ControlModifier and key in (Qt.Key.Key_Equal, Qt.Key.Key_Plus):
            return self.set_zoom(1)
        if mods == Qt.KeyboardModifier.ControlModifier and key == Qt.Key.Key_Minus:
            return self.set_zoom(-1)
        if mods == Qt.KeyboardModifier.ControlModifier and key == Qt.Key.Key_0:
            return self.set_zoom(None)
        scr = self.session.screen
        if mods == Qt.KeyboardModifier.ShiftModifier and scr.alt is None:
            page = scr.lines - 1
            steps = {Qt.Key.Key_PageUp: page, Qt.Key.Key_PageDown: -page, Qt.Key.Key_Up: 1, Qt.Key.Key_Down: -1,
                     Qt.Key.Key_Home: len(scr.history), Qt.Key.Key_End: -len(scr.history)}
            if key in steps:
                return self.scroll_by(steps[key])
        data = keys.encode(key, mods, e.text(), emulator.DECCKM in scr.mode)
        if data:
            self.to_bottom()
            self.session.write(data)

    def inputMethodEvent(self, e):
        if e.commitString():
            self.send_text(e.commitString())

    def inputMethodQuery(self, q):
        if q == Qt.InputMethodQuery.ImCursorRectangle:
            scr = self.session.screen
            return QRect(PAD + scr.cursor.x * self.cw, PAD + (scr.cursor.y + self.scroll) * self.ch, self.cw, self.ch)
        return super().inputMethodQuery(q)

    def focusNextPrevChild(self, _next):
        return False

    def focusInEvent(self, e):
        self.activated.emit(self)
        self.update()
        super().focusInEvent(e)

    def focusOutEvent(self, e):
        self.update()
        super().focusOutEvent(e)

    # -- mouse -------------------------------------------------------------------------------------------------
    def _reporting(self, e) -> bool:
        """The program wants the mouse (htop, vim with mouse=a) unless Shift is held, as in other terminals."""
        return bool(emulator.MOUSE & self.session.screen.mode) \
            and not e.modifiers() & Qt.KeyboardModifier.ShiftModifier

    def _report(self, button: int, e, press=True, motion=False):
        scr = self.session.screen
        col = max(0, min(scr.columns - 1, int((e.position().x() - PAD) // self.cw)))
        row = max(0, min(scr.lines - 1, int((e.position().y() - PAD) // self.ch)))
        if motion and (col, row) == self._mouse_cell:
            return
        self._mouse_cell = (col, row)
        m = e.modifiers()
        code = button + (8 if m & Qt.KeyboardModifier.AltModifier else 0) \
            + (16 if m & Qt.KeyboardModifier.ControlModifier else 0) + (32 if motion else 0)
        if emulator.MOUSE_SGR in scr.mode:
            self.session.write_text(f"\x1b[<{code};{col + 1};{row + 1}{'M' if press else 'm'}")
        else:
            if not press:
                code = 3 + (code & ~3 & ~64)
            self.session.write(bytes([27, 91, 77, min(255, 32 + code), min(255, 33 + col), min(255, 33 + row)]))

    BUTTONS = {Qt.MouseButton.LeftButton: 0, Qt.MouseButton.MiddleButton: 1, Qt.MouseButton.RightButton: 2}

    def mousePressEvent(self, e):
        self.setFocus()
        if self._reporting(e) and e.button() in self.BUTTONS:
            self._mouse_btn = self.BUTTONS[e.button()]
            self._report(self._mouse_btn, e)
            return
        if e.button() == Qt.MouseButton.LeftButton:
            cell = self.cell_at(e.position())
            now = e.timestamp()
            if self.sel and now - self._click_time < QGuiApplication.styleHints().mouseDoubleClickInterval() \
                    and self._click_time and getattr(self, "_double", False):
                self.sel = ((cell[0], 0), (cell[0], self.session.screen.columns))     # triple click: the line
                self._double = False
                self.copy(QClipboard.Mode.Selection)
                self.update()
                return
            self._double = False
            self.sel = (cell, cell)
            self.selecting = True
            self.update()
        elif e.button() == Qt.MouseButton.MiddleButton:
            self.paste(QClipboard.Mode.Selection)
        elif e.button() == Qt.MouseButton.RightButton:
            self.shortcut.emit(e)                    # the page shows the context menu

    def mouseDoubleClickEvent(self, e):
        if self._reporting(e) or e.button() != Qt.MouseButton.LeftButton:
            return self.mousePressEvent(e)
        line, col = self.cell_at(e.position())
        self.sel = self._word_at(line, min(col, self.session.screen.columns - 1))
        self._double, self._click_time = True, e.timestamp()
        self.copy(QClipboard.Mode.Selection)
        self.update()

    def mouseMoveEvent(self, e):
        if self._mouse_btn is not None or (self._reporting(e) and 1003 << 5 in self.session.screen.mode):
            if self._mouse_btn is not None and not emulator.MOUSE_DRAG & self.session.screen.mode:
                return
            self._report(3 if self._mouse_btn is None else self._mouse_btn, e, motion=True)
            return
        if self.selecting:
            if e.position().y() < 0:
                self.scroll_by(1)
            elif e.position().y() > self.height():
                self.scroll_by(-1)
            self.sel = (self.sel[0], self.cell_at(e.position()))
            self.update()

    def mouseReleaseEvent(self, e):
        if self._mouse_btn is not None:
            self._report(self._mouse_btn, e, press=False)
            self._mouse_btn = None
            return
        if self.selecting:
            self.selecting = False
            if self._sel_range():
                self.copy(QClipboard.Mode.Selection)
            else:
                self.sel = None
                self.update()

    def wheelEvent(self, e):
        dy = e.angleDelta().y()
        if not dy:
            return
        up = dy > 0
        scr = self.session.screen
        if self._reporting(e):
            self._report(64 if up else 65, e)
        elif scr.alt is not None:                    # less, man, vim without mouse: scroll with arrows
            seq = ("\x1bO" if emulator.DECCKM in scr.mode else "\x1b[") + ("A" if up else "B")
            self.session.write_text(seq * 3)
        else:
            self.scroll_by(3 if up else -3)

    # -- drag and drop: files become quoted paths ---------------------------------------------------------------
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls() or e.mimeData().hasText():
            e.acceptProposedAction()

    def dropEvent(self, e):
        md = e.mimeData()
        if md.hasUrls():
            text = " ".join(shlex.quote(u.toLocalFile() or u.toString()) for u in md.urls()) + " "
        else:
            text = md.text()
        self.send_text(text, paste=True)
        self.setFocus()
