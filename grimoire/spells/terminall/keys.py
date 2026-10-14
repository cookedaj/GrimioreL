# SPDX-License-Identifier: GPL-3.0-or-later
"""Key presses → the bytes an xterm-256color program expects (arrows, Home/End, PgUp/PgDn, F-keys, Ctrl and Alt
combinations, with xterm's modifier parameter when Shift/Alt/Ctrl are held)."""
from PySide6.QtCore import Qt

K = Qt.Key
CURSOR = {K.Key_Up: "A", K.Key_Down: "B", K.Key_Right: "C", K.Key_Left: "D", K.Key_Home: "H", K.Key_End: "F"}
TILDE = {K.Key_Insert: 2, K.Key_Delete: 3, K.Key_PageUp: 5, K.Key_PageDown: 6, K.Key_F5: 15, K.Key_F6: 17,
         K.Key_F7: 18, K.Key_F8: 19, K.Key_F9: 20, K.Key_F10: 21, K.Key_F11: 23, K.Key_F12: 24}
SS3 = {K.Key_F1: "P", K.Key_F2: "Q", K.Key_F3: "R", K.Key_F4: "S"}
CTRL_PUNCT = {K.Key_Space: 0, K.Key_At: 0, K.Key_2: 0, K.Key_BracketLeft: 27, K.Key_3: 27, K.Key_Backslash: 28,
              K.Key_4: 28, K.Key_BracketRight: 29, K.Key_5: 29, K.Key_AsciiCircum: 30, K.Key_6: 30,
              K.Key_Underscore: 31, K.Key_7: 31, K.Key_Slash: 31, K.Key_Question: 127, K.Key_8: 127}


def encode(key: int, mods, text: str, app_cursor: bool = False) -> bytes | None:
    """None when the key means nothing to a terminal (a lone Shift, say)."""
    shift = bool(mods & Qt.KeyboardModifier.ShiftModifier)
    alt = bool(mods & Qt.KeyboardModifier.AltModifier)
    ctrl = bool(mods & Qt.KeyboardModifier.ControlModifier)
    m = 1 + shift + 2 * alt + 4 * ctrl                   # xterm's modifier parameter
    esc = "\x1b" if alt else ""

    if key in CURSOR:
        if m > 1:
            return f"\x1b[1;{m}{CURSOR[key]}".encode()
        return (("\x1bO" if app_cursor else "\x1b[") + CURSOR[key]).encode()
    if key in TILDE:
        return (f"\x1b[{TILDE[key]};{m}~" if m > 1 else f"\x1b[{TILDE[key]}~").encode()
    if key in SS3:
        return (f"\x1b[1;{m}{SS3[key]}" if m > 1 else f"\x1bO{SS3[key]}").encode()
    if key == K.Key_Backtab:
        return b"\x1b[Z"
    if key == K.Key_Tab:
        return b"\x1b[Z" if shift else (esc + "\t").encode()
    if key == K.Key_Backspace:
        return (esc + ("\x08" if ctrl else "\x7f")).encode()
    if key in (K.Key_Return, K.Key_Enter):
        return (esc + "\r").encode()
    if key == K.Key_Escape:
        return b"\x1b"
    if ctrl:
        if K.Key_A <= key <= K.Key_Z:
            return (esc + chr(key - K.Key_A + 1)).encode()
        if key in CTRL_PUNCT:
            return (esc + chr(CTRL_PUNCT[key])).encode()
    if text and text.isprintable():
        return (esc + text).encode()
    if text and len(text) == 1 and ord(text) < 32:      # a control char the layout already produced
        return (esc + text).encode()
    if alt and 0x20 < key < 0x7f:                       # Alt+key where the platform gave no text
        ch = chr(key)
        return (esc + (ch if shift else ch.lower())).encode()
    return None
