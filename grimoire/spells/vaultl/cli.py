"""VaultL's auto-tidy from the command line and the systemd timer.

    grimoire-vaultl tidy [run|undo|enable|disable|status]     (grimoire-tidyl <cmd> still works)

The timer keeps TidyL's unit name and calls grimoire-tidyl, so an already-enabled timer keeps running untouched.
"""
import subprocess
import sys

from grimoire.paths import HOME
from grimoire.spells.vaultl import tidy

UNITS = HOME / ".config/systemd/user"
SERVICE = """[Unit]
Description=Grimoire VaultL: sort ~/Downloads and clean stale installers

[Service]
Type=oneshot
ExecStart=%h/.local/bin/grimoire-tidyl run
Nice=10
IOSchedulingClass=idle
"""
TIMER = """[Unit]
Description=Run Grimoire VaultL's auto-tidy every 10 minutes

[Timer]
OnBootSec=3min
OnUnitActiveSec=10min
Persistent=true

[Install]
WantedBy=timers.target
"""


def set_auto(on: bool):
    """Install/enable (or disable) the systemd user timer and remember the choice."""
    s = tidy.Settings.load()
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


def main(argv: list[str]):
    cmd = argv[0] if argv else "run"
    if cmd == "run":
        r = tidy.run()
        print(f"moved {r['moved']}, cleaned {r['cleaned']}" + (f", errors: {r['errors']}" if r["errors"] else ""))
    elif cmd == "undo":
        print(f"moved back {tidy.undo_last()} file(s)")
    elif cmd in ("enable", "disable"):
        set_auto(cmd == "enable")
        print(f"auto-tidy {'on' if cmd == 'enable' else 'off'}")
    elif cmd == "status":
        print("auto-tidy on" if timer_active() else "auto-tidy off")
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
