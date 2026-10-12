"""TidyL from the command line / systemd timer.

    python3 -m grimoire.spells.tidyl.cli [run|undo|enable|disable|status]
"""
import subprocess
import sys

from grimoire.paths import HOME
from grimoire.spells.tidyl import engine

UNITS = HOME / ".config/systemd/user"
SERVICE = """[Unit]
Description=Grimoire TidyL: sort ~/Downloads and clean stale installers

[Service]
Type=oneshot
ExecStart=%h/.local/bin/grimoire-tidyl run
Nice=10
IOSchedulingClass=idle
"""
TIMER = """[Unit]
Description=Run Grimoire TidyL every 10 minutes

[Timer]
OnBootSec=3min
OnUnitActiveSec=10min
Persistent=true

[Install]
WantedBy=timers.target
"""


def set_auto(on: bool):
    """Install/enable (or disable) the systemd user timer and remember the choice."""
    s = engine.Settings.load()
    s.auto = on
    s.save()
    if on:
        UNITS.mkdir(parents=True, exist_ok=True)
        (UNITS / "grimoire-tidyl.service").write_text(SERVICE)
        (UNITS / "grimoire-tidyl.timer").write_text(TIMER)
        subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
        subprocess.run(["systemctl", "--user", "enable", "--now", "grimoire-tidyl.timer"], check=True,
                       capture_output=True)
    else:
        subprocess.run(["systemctl", "--user", "disable", "--now", "grimoire-tidyl.timer"], capture_output=True)


def timer_active() -> bool:
    return subprocess.run(["systemctl", "--user", "is-active", "--quiet", "grimoire-tidyl.timer"]).returncode == 0


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "run"
    if cmd == "run":
        r = engine.run()
        print(f"moved {r['moved']}, cleaned {r['cleaned']}" + (f", errors: {r['errors']}" if r["errors"] else ""))
    elif cmd == "undo":
        print(f"moved back {engine.undo_last()} file(s)")
    elif cmd in ("enable", "disable"):
        set_auto(cmd == "enable")
        print(f"auto-tidy {'on' if cmd == 'enable' else 'off'}")
    elif cmd == "status":
        print("auto-tidy on" if timer_active() else "auto-tidy off")
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
