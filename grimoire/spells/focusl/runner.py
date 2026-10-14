# SPDX-License-Identifier: GPL-3.0-or-later
"""FocusL's background runner: one per user, it runs a whole session (focus rounds, short breaks, the long break) by
itself, so closing Grimoire doesn't stop the timer. It writes focusl-state.json whenever something changes (the page
counts down from the end time in it) and takes pause/resume/skip/stop from focusl-control.json.

    python3 -m grimoire.spells.focusl.runner start|stop|pause|resume|skip|status|unblock|run

run      the runner itself (start launches it in the background; a second one exits at once)
stop     ends the session: Do Not Disturb off, the crosshair back if it was on, blocked sites unblocked
unblock  removes a site block a session left behind (one that was killed before it could clean up)

Cleanup happens on SIGTERM/SIGINT/SIGHUP too. If the runner is SIGKILLed, Plasma drops its DND by itself (it's tied
to the D-Bus connection) and the next start or stop puts back the crosshair and the hosts file.
"""
import fcntl
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from grimoire.paths import CACHE
from grimoire.spells.focusl import guards, store
from grimoire.spells.focusl.store import log


def sequence(rounds: int) -> list[tuple[str, int]]:
    """[(focus, 1), (short, 1), (focus, 2), …, (focus, n), (long, n)]"""
    out = []
    for r in range(1, rounds + 1):
        out += [("focus", r), ("short" if r < rounds else "long", r)]
    return out


class Session:
    def __init__(self, clock=time.time):
        self.clock = clock
        self.s = store.load_settings()
        self.seq = sequence(self.s["rounds"])
        self.i = 0
        self.dnd = guards.Dnd()
        self.apps: guards.AppGuard | None = None
        self.quit = False
        self._control_id = None
        self._last_apps = 0.0
        now = clock()
        self.st = {"pid": os.getpid(), "started": now, "phase": "focus", "round": 1, "rounds": self.s["rounds"],
                   "status": "running", "length": 0, "ends": None, "left": 0, "auto": self.s["auto_start"],
                   "dnd": False, "crosshair_hidden": False, "sites_blocked": False, "note": ""}

    def save(self):
        store.write_state(self.st)

    # ------------------------------------------------------------ the session's shape
    def begin(self):
        """Pick up what a killed session left behind, block sites if asked, then the first focus round."""
        store.CONTROL.unlink(missing_ok=True)               # a stale command must not hit the new session
        old = store.load_state()
        if old.get("crosshair_hidden"):
            if self.s["hide_crosshair"]:
                self.st["crosshair_hidden"] = True           # still hidden from last time: it comes back at the end
            else:
                guards.restore_crosshair()
        if self.s["block_sites"] and self.s["sites"]:
            err = guards.block_sites(self.s["sites"])       # replaces an old block: one password prompt, not two
            self.st["sites_blocked"] = not err or bool(old.get("sites_blocked"))
            if err:
                self.st["note"] = f"Sites aren't blocked: {err}"
                log(f"block sites: {err}")
        elif old.get("sites_blocked"):
            err = guards.unblock_sites()
            self.st["sites_blocked"] = bool(err)
        self.start_phase(0)

    def start_phase(self, i: int):
        self.i = i
        self.s = store.load_settings()                       # changes made mid-session apply from the next phase
        kind, rnd = self.seq[i]
        length = self.s[kind] * 60
        self.st.update(phase=kind, round=rnd, status="running", length=length, ends=self.clock() + length, left=length,
                       phase_started=self.clock())
        if kind == "focus":
            self.guards_on()
        self.save()
        log(f"{kind} {rnd}/{len(self.seq) // 2} started ({self.s[kind]} min)")

    def guards_on(self):
        if self.s["dnd"]:
            self.st["dnd"] = self.dnd.on()
        if self.s["hide_crosshair"]:
            self.st["crosshair_hidden"] = guards.hide_crosshair() or self.st["crosshair_hidden"]
        if self.s["block_apps"] and self.s["apps"]:
            self.apps = guards.AppGuard(self.s["apps"], self.s["app_action"], self.s["grace"])
            self._last_apps = 0.0

    def guards_off(self):
        self.dnd.off()
        self.st["dnd"] = False
        if self.st["crosshair_hidden"]:
            guards.restore_crosshair()
            self.st["crosshair_hidden"] = False
        self.apps = None

    def focused(self) -> float:
        """Seconds of focus done in the current focus phase (pauses don't count)."""
        return max(0.0, self.st["length"] - store.left(self.st, self.clock()))

    def finish(self, full: bool):
        """The phase is over (full) or skipped: record focus, say what's next, then start it or wait for you."""
        kind = self.st["phase"]
        if kind == "focus" and self.st["status"] != "waiting":
            minutes = self.focused() / 60
            if full or minutes >= 1:
                store.record(self.st["phase_started"], self.clock(), minutes, full)
            self.guards_off()                                # before notifying: DND would hide the message
        nxt = self.i + 1
        if nxt >= len(self.seq):
            if full:
                n = len(self.seq) // 2
                guards.notify("Session complete", f"{n} focus round{'s' if n > 1 else ''} done. Well earned.")
                self.chime()
            self.quit = True
            return
        nk, nr = self.seq[nxt]
        if full:
            if kind == "focus":
                title, body = "Focus done", f"Take a {self.s[nk]} min {'long ' if nk == 'long' else ''}break."
            else:
                title, body = "Break's over", f"Round {nr} of {len(self.seq) // 2}: {self.s['focus']} min of focus."
            guards.notify(title, body + ("" if self.s["auto_start"] else " Start it in FocusL when you're ready."))
            self.chime()
        if self.s["auto_start"]:
            self.start_phase(nxt)
        else:
            self.i = nxt
            length = self.s[nk] * 60
            self.st.update(phase=nk, round=nr, status="waiting", length=length, ends=None, left=length)
            self.save()

    def chime(self):
        if self.s["sound"]:
            guards.chime()

    # ------------------------------------------------------------ commands
    def pause(self):
        if self.st["status"] != "running":
            return
        self.st.update(status="paused", left=store.left(self.st, self.clock()), ends=None)
        if self.st["phase"] == "focus":
            self.guards_off()
        self.save()

    def resume(self):
        if self.st["status"] == "waiting":
            self.start_phase(self.i)
        elif self.st["status"] == "paused":
            self.st.update(status="running", ends=self.clock() + self.st["left"])
            if self.st["phase"] == "focus":
                self.guards_on()
            self.save()

    def control(self):
        c = store._read(store.CONTROL, None)
        if not isinstance(c, dict) or c.get("id") == self._control_id:
            return
        self._control_id = c.get("id")
        store.CONTROL.unlink(missing_ok=True)
        cmd = c.get("cmd")
        log(f"command: {cmd}")
        if cmd == "pause":
            self.pause()
        elif cmd == "resume":
            self.resume()
        elif cmd == "skip":
            self.finish(full=False)
        elif cmd == "stop":
            self.quit = True

    def tick(self):
        self.control()
        now = self.clock()
        if self.st["status"] == "running" and now >= self.st["ends"]:
            self.finish(full=True)
        if self.apps and self.st["phase"] == "focus" and self.st["status"] == "running" and now - self._last_apps >= 2:
            self._last_apps = now
            try:
                self.apps.tick(now)
            except Exception as e:                           # a process vanishing mid-scan must never end focus
                log(f"app check failed: {e}")

    def loop(self):
        while not self.quit:
            self.tick()
            if not self.quit:
                time.sleep(0.5)

    def stop(self):
        """Put everything back. Runs on every exit: the end of the session, stop, skip past the end, or a signal."""
        if self.st["phase"] == "focus" and self.st["status"] in ("running", "paused"):
            minutes = self.focused() / 60
            if minutes >= 1:
                store.record(self.st["phase_started"], self.clock(), minutes, False)
        self.guards_off()
        if self.st["sites_blocked"]:
            err = guards.unblock_sites()
            if err:
                log(f"unblock sites: {err}")
                guards.notify("Sites still blocked", f"FocusL couldn't unblock them ({err}). Run "
                              "\"grimoire-focusl unblock\" or press Unblock in FocusL.")
            self.st["sites_blocked"] = bool(err)
        store.write_state({"phase": "idle", "ended": self.clock(), "crosshair_hidden": False,
                           "sites_blocked": self.st["sites_blocked"]})
        log("session ended")


# ---------------------------------------------------------------- running it
def _lock():
    """The single-instance lock, held for the runner's whole life; None if another runner has it."""
    fd = os.open(store.LOCK, os.O_RDWR | os.O_CREAT, 0o600)
    for _ in range(10):                                      # a client may hold a shared lock for a moment
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return fd
        except BlockingIOError:
            time.sleep(0.1)
    os.close(fd)
    return None


def run() -> int:
    fd = _lock()
    if fd is None:
        print("FocusL is already running")
        return 0
    sess = Session()

    def bye(*_):
        sess.quit = True
    for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        signal.signal(sig, bye)
    try:
        sess.begin()
        sess.loop()
    except Exception as e:
        log(f"runner crashed: {e!r}")
        raise
    finally:
        for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
            signal.signal(sig, signal.SIG_IGN)                # a second Ctrl+C must not cut the cleanup short
        sess.stop()
        os.close(fd)
    return 0


def runner_pid() -> int | None:
    try:
        pid = int(store.load_state().get("pid"))
        cmd = Path(f"/proc/{pid}/cmdline").read_bytes()
    except (OSError, ValueError, TypeError):
        return None
    return pid if b"grimoire.spells.focusl.runner" in cmd and store.running() else None


def start() -> bool:
    """Launch a session in the background; False if one is already running."""
    if store.running():
        return False
    repo = Path(__file__).resolve().parents[3]
    env = dict(os.environ, PYTHONPATH=f"{repo}:{os.environ.get('PYTHONPATH', '')}".rstrip(":"))
    with open(CACHE / "focusl.out", "w") as out:
        subprocess.Popen([sys.executable, "-m", "grimoire.spells.focusl.runner", "run"], env=env, stdout=out,
                         stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, start_new_session=True)
    return True


def stop(wait: float = 0) -> bool:
    """End the session (the runner cleans up), or clean up after a dead one. True if a session was running."""
    pid = runner_pid()
    if pid:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pid = None
    if not pid:
        recover()
        return False
    end = time.time() + wait
    while time.time() < end and store.running():
        time.sleep(0.1)
    return True


def recover(sites: bool = False) -> str:
    """After a runner that died without cleaning up: the crosshair back on, and (asked for, since it needs the
    password) the hosts block removed. '' when all is back, else what's left."""
    if store.running():
        return ""
    st = store.load_state()
    if st.get("crosshair_hidden"):
        guards.restore_crosshair()
        st["crosshair_hidden"] = False
    err = ""
    if sites and st.get("sites_blocked"):
        err = guards.unblock_sites()
        st["sites_blocked"] = bool(err)
    if st.get("phase", "idle") != "idle":
        st = {"phase": "idle", "ended": time.time(), "crosshair_hidden": False,
              "sites_blocked": bool(st.get("sites_blocked"))}
    store.write_state(st)
    return err or ("sites are still blocked" if st.get("sites_blocked") else "")


def status_text() -> str:
    s = store.live_state()
    line = store.status_line()
    if s["phase"] != "idle":
        line += f" · round {s.get('round')} of {s.get('rounds')}"
    if s.get("sites_blocked") and s["phase"] == "idle":
        line += " · sites still blocked (grimoire-focusl unblock)"
    return line


def main(argv: list[str]):
    cmd = argv[0] if argv else "status"
    if cmd == "run":
        sys.exit(run())
    elif cmd == "start":
        print("started" if start() else "already running")
    elif cmd == "stop":
        print("stopped" if stop(wait=5) else "not running")
    elif cmd in ("pause", "resume", "skip"):
        if not store.running():
            sys.exit("FocusL isn't running")
        store.send(cmd)
    elif cmd == "status":
        print(status_text())
    elif cmd == "unblock":
        err = recover(sites=True)
        print(f"couldn't: {err}" if err else "nothing blocked now")
        sys.exit(1 if err else 0)
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
