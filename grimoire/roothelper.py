# SPDX-License-Identifier: GPL-3.0-or-later
"""The root helpers, run only from root-owned system copies.

Each spell that needs root (MuraL, OptimizeL, SystemL, FocusL) has a whitelisted root-helper.sh. pkexec runs it as
root, so the copy it runs must be one only root can change: the per-user app in ~/.local/share is writable by any
process running as you, and a helper edited there would get root at the next password prompt. So the helpers live in

    /usr/libexec/grimoire-linux/<spell>-root-helper.sh          distro packages (.deb, AUR)
    /usr/local/libexec/grimoire-linux/<spell>-root-helper.sh    ./install.sh (one password prompt when they change)

next to a polkit action per helper (/usr/share/polkit-1/actions), so the prompt names Grimoire Linux. Before every
run the file and each folder above it must be root-owned, not group/world-writable and not a symlink; there is no
fallback to the copy in this tree (source() is only for sandbox tests, which run it as you, without pkexec).

    python3 -I grimoire/roothelper.py status|install|uninstall [--dry]   what install.sh / uninstall.sh call
    python3 -I grimoire/roothelper.py policy DIR [local]                 print a polkit file for helpers in DIR
    python3 -I grimoire/roothelper.py stage DIR                          copy the helpers into DIR (packaging)

Tests of install/uninstall: GRIMOIRE_SYSTEM_TEST=1 GRIMOIRE_SYSTEM_PREFIX=<sandbox> puts both system folders under
the sandbox (ignored unless GRIMOIRE_SYSTEM_TEST is set; never used to find a helper to run).
This module runs as a plain script too (install.sh, stage.sh), so it imports nothing from grimoire.
"""
import base64
import hashlib
import os
import stat
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent                     # this copy's grimoire/ package
PACKAGE_DIR = Path("/usr/libexec/grimoire-linux")
LOCAL_DIR = Path("/usr/local/libexec/grimoire-linux")
POLICY_DIR = Path("/usr/share/polkit-1/actions")
ACTION = "io.github.cookedaj.grimoire-linux"
TRUSTED_UIDS = {0}                                         # tests add their own uid
# spell -> what its password prompt says it's for
SPELLS = {
    "mural": "Grimoire Linux MuraL needs your password to change the login screen or boot theme",
    "optimizel": "Grimoire Linux OptimizeL needs your password to change system settings",
    "systeml": "Grimoire Linux SystemL needs your password to manage processes, services or swap",
    "focusl": "Grimoire Linux FocusL needs your password to block or unblock sites in /etc/hosts",
}


class HelperError(RuntimeError):
    """The system helper is missing or unsafe; the message says what to do."""


def name(spell: str) -> str:
    return f"{spell}-root-helper.sh"


def source(spell: str) -> Path:
    """This tree's copy: what install.sh/packaging install, and what sandbox tests run as you (never via pkexec)."""
    return HERE / "spells" / spell / "root-helper.sh"


def packaged() -> bool:
    return (HERE.parent / "PACKAGED").is_file()


def unsafe(path: Path) -> str:
    """'' when root alone can change path (the file and every folder up to /), else why not."""
    path = Path(os.path.abspath(path))
    for p in [path, *path.parents]:
        try:
            st = os.lstat(p)
        except OSError as e:
            return f"{p}: {e.strerror or e}"
        if stat.S_ISLNK(st.st_mode):
            return f"{p} is a symlink"
        if p == path and not stat.S_ISREG(st.st_mode):
            return f"{p} isn't a regular file"
        if p != path and not stat.S_ISDIR(st.st_mode):
            return f"{p} isn't a folder"
        if st.st_uid not in TRUSTED_UIDS:
            return f"{p} isn't owned by root"
        if st.st_mode & 0o022:
            return f"{p} is writable by group or others"
    return ""


def dirs() -> list[Path]:
    """Where to look: the package's folder first for a packaged copy, the script install's first otherwise."""
    return [PACKAGE_DIR, LOCAL_DIR] if packaged() else [LOCAL_DIR, PACKAGE_DIR]


def fix_hint() -> str:
    return "reinstall the grimoire-linux package" if packaged() else "run ./install.sh again (one password prompt)"


def find(spell: str) -> Path:
    """The system copy of spell's helper, checked; raises HelperError instead of falling back to a user copy."""
    if spell not in SPELLS:
        raise HelperError(f"unknown helper {spell!r}")
    found = [d / name(spell) for d in dirs() if os.path.lexists(d / name(spell))]
    if not found:
        raise HelperError(f"System helpers aren't installed; {fix_hint()}")
    problems = []
    for p in found:
        why = unsafe(p)
        if not why:
            return p
        problems.append(why)
    raise HelperError(f"System helpers aren't safe to run ({problems[0]}); {fix_hint()}")


def command(spell: str, *args: str) -> list[str]:
    """pkexec runs the helper itself (its #!/bin/bash line), so the polkit action for its path applies."""
    return ["pkexec", str(find(spell)), *args]


def run(spell: str, *args: str, timeout: float | None = None) -> subprocess.CompletedProcess:
    """Run spell's system helper through pkexec (a password prompt). Raises HelperError when it's missing or unsafe;
    pkexec's own codes come back as usual (126: prompt dismissed, 127: not authorized / no agent)."""
    return subprocess.run(command(spell, *args), capture_output=True, text=True, timeout=timeout)


# ---------------------------------------------------------------- installing (install.sh, uninstall.sh, packaging)
def policy(directory: Path, local: bool = False) -> str:
    """A polkit action per helper in directory: the prompt names Grimoire Linux, and a second root action within a
    few minutes from the same app doesn't ask again (auth_admin_keep)."""
    base = ACTION + (".local" if local else "")
    actions = "".join(f"""
  <action id="{base}.{spell}">
    <description>Run Grimoire Linux's {spell} root helper</description>
    <message>{msg}</message>
    <icon_name>grimoire</icon_name>
    <defaults>
      <allow_any>auth_admin</allow_any>
      <allow_inactive>auth_admin</allow_inactive>
      <allow_active>auth_admin_keep</allow_active>
    </defaults>
    <annotate key="org.freedesktop.policykit.exec.path">{directory / name(spell)}</annotate>
  </action>
""" for spell, msg in SPELLS.items())
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE policyconfig PUBLIC "-//freedesktop//DTD PolicyKit Policy Configuration 1.0//EN"
 "http://www.freedesktop.org/standards/PolicyKit/1/policyconfig.dtd">
<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
<!-- Grimoire Linux's root helpers ({directory}); written by Grimoire's installer. -->
<policyconfig>
  <vendor>Grimoire Linux</vendor>
  <vendor_url>https://github.com/cookedaj/grimoire-linux</vendor_url>
{actions}</policyconfig>
"""


def policy_name(local: bool) -> str:
    return ACTION + (".local" if local else "") + ".policy"


def wanted(directory: Path, local: bool) -> dict[str, bytes]:
    """file name -> content for a system install into directory."""
    files = {name(s): _shebang(source(s).read_bytes()) for s in SPELLS}
    files[policy_name(local)] = policy(directory, local).encode()
    return files


def _shebang(data: bytes) -> bytes:
    """pkexec clears PATH to its own, so '#!/usr/bin/env bash' would work, but a fixed interpreter is plainer."""
    first, _, rest = data.partition(b"\n")
    return b"#!/bin/bash\n" + rest if first.startswith(b"#!") else data


def stage(out: Path):
    """Packaging: the helpers (0755) for /usr/libexec/grimoire-linux; stage.sh adds the policy."""
    out.mkdir(parents=True, exist_ok=True)
    for spell in SPELLS:
        p = out / name(spell)
        p.write_bytes(_shebang(source(spell).read_bytes()))
        p.chmod(0o755)


def _targets() -> tuple[Path, Path, bool]:
    """(helper folder, polkit folder, test mode) for install/uninstall."""
    prefix = os.environ.get("GRIMOIRE_SYSTEM_PREFIX", "") if os.environ.get("GRIMOIRE_SYSTEM_TEST") else ""
    if prefix:
        return Path(prefix + str(LOCAL_DIR)), Path(prefix + str(POLICY_DIR)), True
    return LOCAL_DIR, POLICY_DIR, False


def _sha(p: Path) -> str:
    try:
        return hashlib.sha256(p.read_bytes()).hexdigest()
    except OSError:
        return ""


def outdated() -> list[str]:
    """Files of the script install that are missing, different from this tree's, or unsafe."""
    directory, pol_dir, test = _targets()
    out = []
    for fname, data in wanted(LOCAL_DIR, True).items():
        dest = (pol_dir if fname.endswith(".policy") else directory) / fname
        if _sha(dest) != hashlib.sha256(data).hexdigest() or (not test and unsafe(dest)):
            out.append(fname)
    return out


# One fixed root step: decode the given files into a root-owned temp folder (so nothing can swap them under us),
# then install them root-owned. Only helper and policy names are accepted.
INSTALL_SH = r"""set -eu
umask 022
dir=$1; pol=$2; shift 2
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
while [ $# -ge 2 ]; do
    case $1 in */*|.*|'') echo "bad file name: $1" >&2; exit 2 ;; esac
    case $1 in *-root-helper.sh|*.policy) ;; *) echo "unexpected file: $1" >&2; exit 2 ;; esac
    printf '%s' "$2" | base64 -d > "$tmp/$1"
    shift 2
done
install -d -o root -g root -m 0755 "$dir"
for f in "$tmp"/*; do
    case $f in
        *-root-helper.sh) install -o root -g root -m 0755 "$f" "$dir/" ;;
        *.policy) install -d -m 0755 "$pol"; install -o root -g root -m 0644 "$f" "$pol/" ;;
    esac
done
echo installed
"""

UNINSTALL_SH = r"""set -eu
dir=$1; pol=$2; shift 2
for f in "$@"; do
    case $f in "$dir"/*-root-helper.sh|"$pol"/*.local.policy) rm -f -- "$f" ;; *) echo "refusing $f" >&2; exit 2 ;; esac
done
rmdir -- "$dir" 2>/dev/null || true
echo removed
"""


def install(dry: bool = False) -> int:
    """Bring the script install's system helpers up to date with this tree: one pkexec prompt, only when needed.
    Never fails install.sh: without them only the root features are unavailable."""
    directory, pol_dir, _ = _targets()
    if not all(source(s).is_file() for s in SPELLS):     # a package's tree: its helpers are in /usr/libexec
        print("This copy carries no root helpers (a distro package installs them in /usr/libexec/grimoire-linux).")
        return 0
    todo = outdated()
    if not todo:
        print(f"System helpers are up to date in {directory}.")
        return 0
    files = wanted(LOCAL_DIR, True)
    print("Grimoire Linux's root helpers run as root, so they're kept where only root can change them:")
    for f in todo:
        print(f"  {(pol_dir if f.endswith('.policy') else directory) / f}")
    print("Installing them asks for your password once (pkexec).")
    later = "Root features (MuraL login/boot themes, OptimizeL system tweaks, SystemL root actions, FocusL sites) " \
            "stay unavailable until you run ./install.sh again."
    if dry:
        print("[dry] pkexec /bin/sh -c <install step> …")
        return 0
    args = []
    for f in todo:
        args += [f, base64.b64encode(files[f]).decode()]
    try:
        r = subprocess.run(["pkexec", "/bin/sh", "-c", INSTALL_SH, "grimoire-install", str(directory), str(pol_dir),
                            *args], text=True, capture_output=True, timeout=600)
    except (OSError, subprocess.TimeoutExpired) as e:
        print(f"Couldn't run pkexec ({e}). {later}")
        return 1
    if r.returncode in (126, 127):
        print(f"The password prompt was cancelled or isn't available. {later}")
        return 1
    if r.returncode:
        print(f"Installing the system helpers failed: {(r.stderr or r.stdout).strip()}. {later}")
        return 1
    left = outdated()
    if left:
        print(f"The system helpers still don't match ({', '.join(left)}). {later}")
        return 1
    print(f"System helpers installed in {directory}.")
    return 0


def uninstall(dry: bool = False) -> int:
    """Remove the script install's system helpers and policy (never a package's) with one pkexec prompt."""
    directory, pol_dir, _ = _targets()
    present = [directory / name(s) for s in SPELLS if os.path.lexists(directory / name(s))]
    pol = pol_dir / policy_name(True)
    if os.path.lexists(pol):
        present.append(pol)
    if not present:
        return 0
    cmd = ["pkexec", "/bin/sh", "-c", UNINSTALL_SH, "grimoire-uninstall", str(directory), str(pol_dir),
           *map(str, present)]
    print("Removing Grimoire Linux's system helpers (asks for your password once):")
    for p in present:
        print(f"  {p}")
    manual = f"sudo rm -f {' '.join(map(str, present))} && sudo rmdir {directory}"
    if dry:
        print(f"[dry] pkexec /bin/sh -c <remove step> {directory} {pol_dir} …")
        return 0
    try:
        r = subprocess.run(cmd, text=True, capture_output=True, timeout=600)
    except (OSError, subprocess.TimeoutExpired) as e:
        r = None
        print(f"Couldn't run pkexec ({e}).")
    if r is None or r.returncode:
        if r is not None:
            print("They weren't removed (" + ("prompt cancelled" if r.returncode in (126, 127)
                                              else (r.stderr or r.stdout).strip()) + ").")
        print(f"Remove them later with:\n  {manual}")
        return 1
    print("System helpers removed.")
    return 0


def cli(argv: list[str]) -> int:
    dry = "--dry" in argv
    argv = [a for a in argv if a != "--dry"]
    match argv:
        case ["status"]:
            todo = outdated()
            print("up to date" if not todo else "outdated: " + " ".join(todo))
            return 1 if todo else 0
        case ["install"]:
            return install(dry)
        case ["uninstall"]:
            return uninstall(dry)
        case ["policy", directory, *rest]:
            sys.stdout.write(policy(Path(directory), rest == ["local"]))
            return 0
        case ["stage", out]:
            stage(Path(out))
            return 0
    print(__doc__.split("\n\n")[2], file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(cli(sys.argv[1:]))
