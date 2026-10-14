"""LaunchL from the command line.

    python3 -m grimoire.spells.launchl status
    python3 -m grimoire.spells.launchl install            install or upgrade the widget package
    python3 -m grimoire.spells.launchl replace [--dry-run] put LaunchL where Kickoff is (prints the script with --dry-run)
    python3 -m grimoire.spells.launchl restore [--dry-run] put the recorded Kickoff back and take LaunchL out
    python3 -m grimoire.spells.launchl uninstall          restore Kickoff if LaunchL replaced it, then remove the package
                                                          (exit 3: kept, because LaunchL is still in a panel)
"""
import json
import sys

from grimoire.spells.launchl import panel


def main(argv: list[str]) -> int:
    cmd, dry = (argv[0] if argv else "status"), "--dry-run" in argv
    try:
        if cmd == "status":
            print(panel.status())
        elif cmd == "install":
            panel.install()
            print("LaunchL installed")
        elif cmd == "replace":
            record = panel.replace(dry_run=dry)
            if dry:
                print(json.dumps({k: v for k, v in record.items() if k != "script"}, indent=1))
                print(record["script"])
            else:
                print("LaunchL is in your panel" + (f" ({record['check']})" if record.get("check") else ""))
        elif cmd == "restore":
            record = panel.restore(dry_run=dry)
            print(record["script"] if dry else f"{record['type']} is back in your panel")
        elif cmd == "uninstall":
            # never pull the package out from under a panel: that leaves a broken placeholder in it
            if panel.can_restore():
                try:
                    panel.restore()
                    print("Your old launcher is back in the panel")
                except RuntimeError as err:
                    print(f"LaunchL kept: couldn't put your old launcher back ({err}). Run "
                          "`python3 -m grimoire.spells.launchl restore` once Plasma is running.", file=sys.stderr)
                    return 3
            elif panel.in_panel():
                print("LaunchL kept: it's in a panel and Grimoire has no record of what it replaced. Remove it in "
                      "Edit Mode (and add Kickoff back), then uninstall again.", file=sys.stderr)
                return 3
            panel.uninstall_package()
            panel.cleanup_icons()
            print("LaunchL removed")
        else:
            print(__doc__)
            return 2
    except RuntimeError as err:
        print(f"LaunchL: {err}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
