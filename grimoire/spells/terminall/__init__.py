"""TerminalL: Grimoire's terminal emulator. Tabs and splits around real PTY sessions running your shell.

emulator.py keeps the screen state (pyte plus scrollback, alternate screen and a few xterm extras), session.py owns
the PTY and the shell, keys.py turns key presses into what programs expect, view.py paints one terminal, page.py is
the window (tabs, splits, search, profiles, command palette) and config.py the saved profiles and commands.
pyte comes from the distro (python3-pyte); without it the page explains how to get it instead of failing.
"""
