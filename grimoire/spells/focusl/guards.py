# SPDX-License-Identifier: GPL-3.0-or-later
"""What a focus session switches on, and how each piece is put back.

Do Not Disturb: Plasma 6's notification server (org.freedesktop.Notifications) has Inhibit/UnInhibit, the same call
video players make. While any inhibition is held Plasma shows only critical notifications and the bell in the tray
reads "Do not disturb". Plasma ties each inhibition to the D-Bus connection that asked for it and drops it when that
connection goes away, so even a SIGKILLed runner can't leave DND stuck on; UnInhibit with our cookie ends it on time
and never touches a DND you switched on yourself.

Crosshair: SightsL's overlay is stopped while you focus and started again only if it was running before.

Apps: a list of process names (yours only, never the desktop's own); a match gets a notification, then SIGTERM (the
polite quit, apps save and exit) once the grace period is over, or only the notification in "warn" mode.

Sites: /etc/hosts needs root, so FocusL's root-helper.sh adds or removes one marked block through pkexec (one password
prompt when a session starts, one when it ends).

FOCUSL_DRY=1 logs every action instead of doing it (tests), and runs the hosts helper on a sandbox copy.
"""
import os
import shutil
import signal
import subprocess
import time
from pathlib import Path

import psutil

from grimoire.paths import ASSETS, CACHE, HOME
from grimoire.spells.focusl.store import PROTECTED, log

DRY = bool(os.environ.get("FOCUSL_DRY"))
HELPER = Path(__file__).with_name("root-helper.sh")
SOUNDS = ["/usr/share/sounds/ocean/stereo/completion-success.oga", "/usr/share/sounds/freedesktop/stereo/complete.oga",
          "/usr/share/sounds/freedesktop/stereo/bell.oga"]


def _bus():
    import dbus
    return dbus.SessionBus()


# ---------------------------------------------------------------- notifications and sound
def _icon() -> str:
    share = os.environ.get("XDG_DATA_HOME") or str(HOME / ".local/share")
    return "grimoire-focusl" if os.path.exists(f"{share}/icons/hicolor/256x256/apps/grimoire-focusl.png") else \
        "grimoire" if os.path.exists(f"{share}/icons/hicolor/scalable/apps/grimoire.svg") else str(ASSETS / "clover5.svg")


def notify(title: str, body: str, urgent=False) -> bool:
    """A desktop notification from FocusL. urgent=True is "critical", the only kind Plasma shows during DND."""
    if DRY:
        log(f"dry: notify {'!' if urgent else ''}{title}: {body}")
        return True
    icon = _icon()
    try:
        import dbus
        n = _bus().get_object("org.freedesktop.Notifications", "/org/freedesktop/Notifications")
        n.Notify("FocusL", dbus.UInt32(0), icon, title, body, dbus.Array([], signature="s"),
                 {"desktop-entry": "grimoire", "urgency": dbus.Byte(2 if urgent else 1),
                  "suppress-sound": dbus.Boolean(True)}, 10000 if urgent else -1,
                 dbus_interface="org.freedesktop.Notifications", timeout=5)
        return True
    except Exception as e:
        log(f"D-Bus notify failed ({e}); trying notify-send")
    try:
        return subprocess.run(["notify-send", "-a", "FocusL", "-i", icon, "-u", "critical" if urgent else "normal",
                               "-h", "string:desktop-entry:grimoire", title, body],
                              capture_output=True, timeout=5).returncode == 0
    except (OSError, subprocess.TimeoutExpired) as e:
        log(f"notify-send failed: {e}")
        return False


def chime():
    """A soft chime (40 % volume), without waiting for it."""
    sound = next((s for s in SOUNDS if os.path.exists(s)), None)
    player = next(([p, *a] for p, a in (("paplay", ["--volume=26214"]), ("pw-play", ["--volume=0.4"]))
                   if shutil.which(p)), None)
    if DRY or not sound or not player:
        log(f"dry: chime {sound}" if DRY else "no sound player or sound file; skipping the chime")
        return
    try:
        subprocess.Popen([*player, sound], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         stdin=subprocess.DEVNULL, start_new_session=True)
    except OSError as e:
        log(f"chime failed: {e}")


# ---------------------------------------------------------------- Do Not Disturb
class Dnd:
    def __init__(self):
        self.cookie: int | None = None

    def on(self) -> bool:
        if self.cookie is not None:
            return True
        if DRY:
            log("dry: dnd on")
            self.cookie = 0
            return True
        try:
            n = _bus().get_object("org.freedesktop.Notifications", "/org/freedesktop/Notifications")
            self.cookie = int(n.Inhibit("grimoire", "Focus session (FocusL)", {},
                                        dbus_interface="org.freedesktop.Notifications", timeout=5))
            return True
        except Exception as e:
            log(f"couldn't turn on Do Not Disturb: {e}")
            return False

    def off(self):
        if self.cookie is None:
            return
        cookie, self.cookie = self.cookie, None
        if DRY:
            log("dry: dnd off")
            return
        try:
            import dbus
            n = _bus().get_object("org.freedesktop.Notifications", "/org/freedesktop/Notifications")
            n.UnInhibit(dbus.UInt32(cookie), dbus_interface="org.freedesktop.Notifications", timeout=5)
        except Exception as e:                     # Plasma restarted: our inhibition went with it
            log(f"couldn't turn off Do Not Disturb (it ends when FocusL exits anyway): {e}")


# ---------------------------------------------------------------- SightsL's crosshair
def hide_crosshair() -> bool:
    """Stop the overlay; True if it was on (so it comes back after)."""
    from grimoire.spells.sightc import overlay
    if not overlay.running_pid():
        return False
    log("dry: crosshair off" if DRY else "crosshair off for focus")
    if not DRY:
        overlay.stop()
    return True


def restore_crosshair():
    from grimoire.spells.sightc import overlay
    if overlay.running_pid():
        return
    log("dry: crosshair on" if DRY else "crosshair back on")
    if not DRY:
        overlay.start()


# ---------------------------------------------------------------- apps
def _names(info: dict) -> set[str]:
    """Every name an app goes by: its process name (cut at 15 characters by the kernel), its executable's and its
    first argument's file names (Electron and wrapper scripts)."""
    out = {(info.get("name") or "").lower()}
    for path in (info.get("exe") or "", (info.get("cmdline") or [""])[0] if info.get("cmdline") else ""):
        if path:
            out.add(os.path.basename(path).lower())
    return out - {""}


def matches(entry: str, names: set[str]) -> bool:
    return entry in names or any(len(n) == 15 and entry.startswith(n) for n in names)


class AppGuard:
    """Watches for listed apps while you focus. tick() is cheap (one pass over your processes) and runs every two
    seconds; warn first, then close after the grace period, once per app per launch."""

    def __init__(self, apps: list[str], action: str, grace: int, notify=notify, kill=os.kill):
        self.apps = [a for a in apps if a and a not in PROTECTED]
        self.action, self.grace = action, grace
        self.notify, self.kill = notify, kill
        self.warned: dict[str, float] = {}          # app -> when to close it (or inf once warned in warn mode)
        self.me = {os.getpid(), os.getppid()}

    def running(self) -> dict[str, list[int]]:
        found: dict[str, list[int]] = {}
        uid = os.getuid()
        for p in psutil.process_iter(["pid", "name", "exe", "cmdline", "uids"]):
            info = p.info
            if info["pid"] in self.me or not info.get("uids") or info["uids"].real != uid:
                continue
            if (info.get("name") or "").lower() in PROTECTED:   # by its own name: launchers are often scripts
                continue
            names = _names(info)
            for app in self.apps:
                if matches(app, names):
                    found.setdefault(app, []).append(info["pid"])
        return found

    def tick(self, now: float | None = None):
        now = now or time.time()
        found = self.running() if self.apps else {}
        for app in list(self.warned):
            if app not in found:                     # closed (by you or by us): warn afresh on the next launch
                del self.warned[app]
        for app, pids in found.items():
            if app not in self.warned:
                if self.action == "close":
                    self.notify("Focus time", f"{app} closes in {self.grace} s. It's on your FocusL block list."
                                if self.grace else f"Closing {app}: it's on your FocusL block list.", urgent=True)
                    self.warned[app] = now + self.grace
                else:
                    self.notify("Focus time", f"{app} is on your FocusL block list.", urgent=True)
                    self.warned[app] = float("inf")
            if now >= self.warned[app]:
                for pid in pids:
                    try:
                        self.kill(pid, signal.SIGTERM) if not DRY else log(f"dry: SIGTERM {pid} ({app})")
                    except (ProcessLookupError, PermissionError):
                        pass
                log(f"closed {app} ({len(pids)} process{'es' if len(pids) > 1 else ''})")
                self.warned[app] = now + max(5, self.grace)     # give it time to exit before trying again

    def reset(self):
        self.warned.clear()


# ---------------------------------------------------------------- sites
def _helper(args: list[str]) -> str:
    """Run root-helper.sh through pkexec; '' when it worked, else why not."""
    if DRY:
        root = CACHE / "focusl-dry-root"
        (root / "etc").mkdir(parents=True, exist_ok=True)
        if not (root / "etc/hosts").exists():
            (root / "etc/hosts").write_text("127.0.0.1 localhost\n")
        cmd, env = ["bash", str(HELPER), *args], dict(os.environ, FOCUSL_ROOT=str(root))
    else:
        cmd, env = ["pkexec", "/usr/bin/bash", str(HELPER), *args], None
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=180)
    except (OSError, subprocess.TimeoutExpired) as e:
        return str(e)
    if r.returncode in (126, 127) and not DRY:
        return "the password prompt was cancelled"
    if r.returncode:
        msg = (r.stderr or r.stdout).strip().splitlines()
        return msg[-1] if msg else f"helper failed ({r.returncode})"
    return ""


def block_sites(sites: list[str]) -> str:
    return _helper(["block", *sites]) if sites else "no sites listed"


def unblock_sites() -> str:
    return _helper(["unblock"])
