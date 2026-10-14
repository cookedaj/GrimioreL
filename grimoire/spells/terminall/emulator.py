# SPDX-License-Identifier: GPL-3.0-or-later
"""Screen state on top of pyte, plus what pyte leaves out and real programs need: scrollback, the alternate screen
(vim, less and htop give the shell back when they quit), xterm-style resizing, REP/SU/SD/DECSCUSR, answers to the
program's queries, and a filter for sequences pyte would otherwise print as text or choke on.

Importing this module raises ImportError when pyte is missing; page.py catches that.
"""
import codecs
import re
from collections import defaultdict, deque

import pyte
from pyte.screens import Margins, StaticDefaultDict

ALT = {47, 1047, 1049}
DECCKM = 1 << 5                 # application cursor keys (pyte stores private modes shifted by 5)
MOUSE = {9 << 5, 1000 << 5, 1002 << 5, 1003 << 5}
MOUSE_DRAG = {1002 << 5, 1003 << 5}
MOUSE_SGR = 1006 << 5
BRACKETED_PASTE = 2004 << 5
CURSOR_SHAPES = {0: None, 1: "block", 2: "block", 3: "underline", 4: "underline", 5: "bar", 6: "bar"}


class Screen(pyte.Screen):
    def __init__(self, columns: int, lines: int, scrollback: int, reply):
        self.history: deque = deque(maxlen=scrollback)
        self.pushed = 0                  # lines ever pushed into history (the view keeps its place with it)
        self.dropped = 0                 # lines that fell off the top of a full history
        self.alt = None                  # the main screen, kept while a program uses the alternate one
        self.reply = reply
        self.cursor_shape = None         # set by the program (DECSCUSR); None = the profile's
        self.bell_rung = False
        self.last_char = " "
        super().__init__(columns, lines)

    def _empty_buffer(self):
        return defaultdict(lambda: StaticDefaultDict(self.default_char))

    def set_scrollback(self, n: int):
        if n != self.history.maxlen:
            self.history = deque(self.history, maxlen=n)

    def _push(self, row):
        if self.history.maxlen:
            if len(self.history) == self.history.maxlen:
                self.dropped += 1
            self.history.append(row)
            self.pushed += 1

    def reset(self):
        self.alt = None
        self.cursor_shape = None
        super().reset()

    def write_process_input(self, data: str):
        self.reply(data)

    def bell(self, *args):
        self.bell_rung = True

    def draw(self, data: str):
        super().draw(data)
        if data:
            self.last_char = data[-1]

    # -- scrollback --------------------------------------------------------------------------------------------
    def index(self):
        top, bottom = self.margins or Margins(0, self.lines - 1)
        if self.cursor.y == bottom and top == 0 and self.alt is None:
            self._push(self.buffer[0])   # pyte moves rows up and drops this one, so no copy is needed
        super().index()

    def erase_in_display(self, how: int = 0, *args, **kwargs):
        if how == 3:                     # "clear" asks for the scrollback to go too
            self.history.clear()
        super().erase_in_display(how, *args, **kwargs)
        rows = range(self.cursor.y + 1, self.lines) if how == 0 else range(self.cursor.y) if how == 1 \
            else range(self.lines)
        for y in rows:                   # pyte only erases cells it has stored; a colored clear must fill the row
            line = self.buffer[y]
            for x in range(self.columns):
                line[x] = self.cursor.attrs

    def resize(self, lines=None, columns=None):
        """Like xterm: shrinking pushes the top into scrollback only as far as the cursor needs, growing pulls
        lines back out of it."""
        lines, columns = lines or self.lines, columns or self.columns
        if (lines, columns) == (self.lines, self.columns):
            return
        rows = [self.buffer[y] for y in range(self.lines)]
        if lines < self.lines:
            shift = max(0, self.cursor.y - (lines - 1))
            for row in rows[:shift]:
                if self.alt is None:
                    self._push(row)
            rows = rows[shift:shift + lines]
            self.cursor.y -= shift
        elif self.alt is None and self.history:
            pull = min(lines - self.lines, len(self.history))
            rows = [self.history.pop() for _ in range(pull)][::-1] + rows
            self.pushed -= pull
            self.cursor.y += pull
        if columns < self.columns:
            for row in rows:
                for x in range(columns, self.columns):
                    row.pop(x, None)
        self.buffer.clear()
        for y, row in enumerate(rows):
            self.buffer[y] = row
        self.lines, self.columns = lines, columns
        self.tabstops = {t for t in self.tabstops if t < columns} | set(range(8, columns, 8))
        self.cursor.x = min(self.cursor.x, columns)
        self.cursor.y = max(0, min(self.cursor.y, lines - 1))
        self.set_margins()
        self.dirty.update(range(lines))

    # -- alternate screen --------------------------------------------------------------------------------------
    def set_mode(self, *modes, **kwargs):
        if kwargs.get("private") and ALT & set(modes) and self.alt is None:
            if 1049 in modes:
                self.save_cursor()
            self.alt = self.buffer
            self.buffer = self._empty_buffer()
            self.dirty.update(range(self.lines))
        super().set_mode(*modes, **kwargs)

    def reset_mode(self, *modes, **kwargs):
        if kwargs.get("private") and ALT & set(modes) and self.alt is not None:
            self.buffer, self.alt = self.alt, None
            if 1049 in modes:
                self.restore_cursor()
            self.dirty.update(range(self.lines))
        super().reset_mode(*modes, **kwargs)

    # -- xterm extras pyte doesn't parse ------------------------------------------------------------------------
    def repeat_char(self, n=1, *args, **kwargs):         # REP: ncurses uses it with TERM=xterm-256color
        self.draw(self.last_char * max(1, min(n or 1, self.columns * self.lines)))

    def scroll_up(self, n=1, *args, **kwargs):           # SU
        top, bottom = self.margins or Margins(0, self.lines - 1)
        for _ in range(min(n or 1, self.lines)):
            if top == 0 and self.alt is None:
                self._push(self.buffer[0])
            for y in range(top, bottom):
                self.buffer[y] = self.buffer[y + 1]
            self.buffer.pop(bottom, None)
        self.dirty.update(range(self.lines))

    def scroll_down(self, n=1, *args, **kwargs):         # SD
        top, bottom = self.margins or Margins(0, self.lines - 1)
        for _ in range(min(n or 1, self.lines)):
            for y in range(bottom, top, -1):
                self.buffer[y] = self.buffer[y - 1]
            self.buffer.pop(top, None)
        self.dirty.update(range(self.lines))

    def cursor_style(self, n=0, *args, **kwargs):        # DECSCUSR, ESC [ n SP q (pyte drops the space)
        self.cursor_shape = CURSOR_SHAPES.get(n)

    def save_cursor_csi(self, *args, **kwargs):
        self.save_cursor()

    def restore_cursor_csi(self, *args, **kwargs):
        self.restore_cursor()

    def window_ops(self, *args, **kwargs):               # CSI t: resize/report requests, ignored
        pass

    def line(self, i: int):
        """Row i of history + screen (0 = the oldest line kept)."""
        h = len(self.history)
        return self.history[i] if i < h else self.buffer[i - h]


class Stream(pyte.Stream):
    """pyte's stream with the CSI finals it lacks."""
    csi = dict(pyte.Stream.csi, b="repeat_char", S="scroll_up", T="scroll_down", q="cursor_style",
               s="save_cursor_csi", u="restore_cursor_csi", t="window_ops")


# sequences handled (or dropped) before pyte sees them; pyte would print most of them as text
_SEQ = re.compile(
    r"\x1b\[([<=>])([0-9;:]*)[ -/]*([@-~])"               # CSI with < = > prefix (secondary DA, modifyOtherKeys…)
    r"|\x1b\[\?[0-9;:]*[ -/]*([^hlJKc0-9;:\x20-/])"       # private CSI pyte's handlers can't take (?u, ?n, ?m…)
    r"|\x1b\[([0-9;:]*:[0-9;:]*)m"                        # SGR with colon sub-parameters
    r"|\x1b[P_^X][^\x1b\x07]*(?:\x1b\\|\x07)",            # DCS / APC / PM / SOS strings
)
_TAIL = re.compile(r"\x1b(?:\[[0-9;:<=>?\x20-/]*|[P_^X][^\x1b\x07]*\x1b?)?\Z")
MAX_HOLD = 1 << 16


def _colon_sgr(params: str) -> str:
    """38:2::r:g:b → 38;2;r;g;b, 4:3 → 4: what pyte understands."""
    out = []
    for group in params.split(";"):
        parts = group.split(":")
        if parts[0] in ("38", "48", "58") and len(parts) > 1:
            if parts[1] == "2":
                rgb = [p or "0" for p in parts[2:]][-3:]
                out.append(";".join([parts[0], "2"] + rgb) if parts[0] != "58" else "")
            elif parts[1] == "5" and len(parts) > 2 and parts[0] != "58":
                out.append(f"{parts[0]};5;{parts[2] or 0}")
        else:
            out.append(parts[0])
    return "\x1b[" + ";".join(o for o in out if o) + "m"


class Feeder:
    """Bytes from the PTY → filtered text → pyte. Holds back an escape sequence cut off at a chunk boundary."""

    def __init__(self, screen: Screen):
        self.screen = screen
        self.stream = Stream(screen)
        self.decoder = codecs.getincrementaldecoder("utf-8")("replace")
        self.hold = ""

    def _sub(self, m: re.Match) -> str:
        if m.group(1) == ">" and m.group(3) == "c" and m.group(2) in ("", "0"):
            self.screen.reply("\x1b[>0;10;1c")                 # secondary DA: a plain VT220-ish answer
        elif m.group(5) is not None:
            return _colon_sgr(m.group(5))
        return ""

    def feed(self, data: bytes):
        text = self.hold + self.decoder.decode(data)
        tail = _TAIL.search(text)
        if tail and len(tail.group()) < MAX_HOLD:
            text, self.hold = text[:tail.start()], tail.group()
        else:
            self.hold = ""
        text = _SEQ.sub(self._sub, text)
        try:
            self.stream.feed(text)
        except Exception:      # a sequence pyte can't handle must never take the terminal down; it resets itself
            pass
