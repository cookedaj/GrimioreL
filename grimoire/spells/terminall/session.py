# SPDX-License-Identifier: GPL-3.0-or-later
"""One shell on a real PTY. The shell is started through util-linux `setsid -c`, which gives it its own session with
the PTY as controlling terminal (job control works) without forking the multi-threaded Qt process in Python.
Output is read with a QSocketNotifier as it arrives; writes that don't fit go out when the PTY can take them.
"""
import fcntl
import os
import pwd
import shutil
import signal
import struct
import subprocess
import termios
import weakref
from pathlib import Path

from PySide6.QtCore import QObject, QSocketNotifier, QTimer, Signal

from grimoire.spells.terminall.emulator import Feeder, Screen

READ_BUDGET = 1 << 16          # bytes handled per wake-up, so a flood of output can't freeze the window
DROP_ENV = ("COLUMNS", "LINES", "TERMCAP", "VTE_VERSION", "WINDOWID", "TERM_PROGRAM_VERSION", "KONSOLE_VERSION",
            "KONSOLE_DBUS_SERVICE", "KONSOLE_DBUS_SESSION", "KONSOLE_DBUS_WINDOW", "SHELL_SESSION_ID", "COLORFGBG")
LIVE: "weakref.WeakSet[Session]" = weakref.WeakSet()
_reaping: list[subprocess.Popen] = []
_reaper = None


def user_shell() -> str:
    shell = os.environ.get("SHELL") or ""
    if not (shell and os.access(shell, os.X_OK)):
        try:
            shell = pwd.getpwuid(os.getuid()).pw_shell
        except KeyError:
            shell = ""
    return shell if shell and os.access(shell, os.X_OK) else "/bin/sh"


def _reap():
    """Collect closed shells once they've exited so none are left as zombies."""
    _reaping[:] = [p for p in _reaping if p.poll() is None]
    if not _reaping and _reaper:
        _reaper.stop()


class Session(QObject):
    changed = Signal()
    finished = Signal()

    def __init__(self, cwd: Path, columns: int, lines: int, scrollback: int, parent=None):
        super().__init__(parent)
        self.screen = Screen(columns, lines, scrollback, self.write_text)
        self.feeder = Feeder(self.screen)
        self.pending = bytearray()
        self.alive = True
        master, slave = os.openpty()
        self.fd = master
        self._winsize(slave, columns, lines)
        env = {k: v for k, v in os.environ.items() if k not in DROP_ENV}
        env.update(TERM="xterm-256color", COLORTERM="truecolor", TERM_PROGRAM="TerminalL")
        cwd = cwd if cwd.is_dir() else Path.home()
        env["PWD"] = str(cwd)
        shell = user_shell()
        argv = [shell, "-l"] if Path(shell).name in ("bash", "zsh", "fish", "ksh", "mksh", "sh", "dash") else [shell]
        setsid = shutil.which("setsid")
        try:
            self.proc = subprocess.Popen([setsid, "-c", *argv] if setsid else argv, stdin=slave, stdout=slave,
                                         stderr=slave, cwd=cwd, env=env, close_fds=True,
                                         start_new_session=not setsid)
        finally:
            os.close(slave)
        os.set_blocking(master, False)
        self.reader = QSocketNotifier(master, QSocketNotifier.Type.Read, self)
        self.reader.activated.connect(self._readable)
        self.writer = QSocketNotifier(master, QSocketNotifier.Type.Write, self)
        self.writer.setEnabled(False)
        self.writer.activated.connect(self._flush)
        try:                                   # the shell's exit ends the tab even if a background job keeps the PTY
            self.pidfd = os.pidfd_open(self.proc.pid)
        except (AttributeError, OSError):
            self.pidfd = -1
        else:
            self.exited = QSocketNotifier(self.pidfd, QSocketNotifier.Type.Read, self)
            self.exited.activated.connect(self._shell_exited)
        LIVE.add(self)

    @staticmethod
    def _winsize(fd: int, columns: int, lines: int):
        fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", lines, columns, 0, 0))

    def resize(self, columns: int, lines: int):
        if (columns, lines) == (self.screen.columns, self.screen.lines):
            return
        self.screen.resize(lines, columns)
        if self.alive:
            try:
                self._winsize(self.fd, columns, lines)     # the kernel sends SIGWINCH to the foreground job
            except OSError:
                pass

    # -- I/O ---------------------------------------------------------------------------------------------------
    def _readable(self):
        got = 0
        while got < READ_BUDGET:
            try:
                data = os.read(self.fd, 65536)
            except BlockingIOError:
                break
            except OSError:                    # EIO: the shell is gone
                data = b""
            if not data:
                self._ended()
                break
            self.feeder.feed(data)
            got += len(data)
        self.changed.emit()

    def write(self, data: bytes):
        if not self.alive or not data:
            return
        self.pending += data
        self._flush()

    def write_text(self, text: str):
        self.write(text.encode())

    def _flush(self):
        try:
            while self.pending:
                n = os.write(self.fd, self.pending[:65536])
                del self.pending[:n]
        except BlockingIOError:
            pass
        except OSError:
            self.pending.clear()
        self.writer.setEnabled(bool(self.pending))

    def _shell_exited(self):
        self.exited.setEnabled(False)
        if self.alive:
            self._readable()                   # what it printed last
            self._ended()

    def _ended(self):
        if not self.alive:
            return
        self.alive = False
        self.reader.setEnabled(False)
        self.writer.setEnabled(False)
        self.finished.emit()

    # -- what's running ----------------------------------------------------------------------------------------
    def cwd(self) -> Path | None:
        """The shell's folder (new tabs and splits start there)."""
        try:
            return Path(os.readlink(f"/proc/{self.proc.pid}/cwd"))
        except OSError:
            return None

    def foreground(self) -> str:
        """Name of the program in the foreground ('vim'), or '' while the shell itself waits."""
        try:
            pgrp = os.tcgetpgrp(self.fd)
            if pgrp == self.proc.pid:
                return ""
            return Path(f"/proc/{pgrp}/comm").read_text().strip()
        except OSError:
            return ""

    def close(self):
        """Hang up the shell (like closing a terminal window) and release the PTY."""
        global _reaper
        if self.fd < 0:
            return
        self.alive = False
        self.reader.setEnabled(False)
        self.writer.setEnabled(False)
        try:
            os.killpg(self.proc.pid, signal.SIGHUP)
        except OSError:
            pass
        os.close(self.fd)
        self.fd = -1
        if self.pidfd >= 0:
            self.exited.setEnabled(False)
            os.close(self.pidfd)
            self.pidfd = -1
        LIVE.discard(self)
        _reaping.append(self.proc)
        if _reaper is None:
            _reaper = QTimer()
            _reaper.setInterval(500)
            _reaper.timeout.connect(_reap)
        _reaper.start()
