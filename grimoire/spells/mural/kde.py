# SPDX-License-Identifier: GPL-3.0-or-later
"""Thin wrappers around KDE's command-line tools, shared by the MuraL tabs. Failures raise RuntimeError,
which a tab's Apply shows as "Couldn't apply: …"."""
import subprocess
from pathlib import Path

ROOT_HELPER = Path(__file__).with_name("root-helper.sh")


def kwrite(file: str, groups: str | list[str], key: str, value, type_: str | None = None, notify=False):
    """kwriteconfig6 one key. groups is one group name or a nested path of them."""
    args = ["kwriteconfig6"] + (["--notify"] if notify else []) + ["--file", file]
    for g in [groups] if isinstance(groups, str) else groups:
        args += ["--group", g]
    args += ["--key", key] + (["--type", type_] if type_ else []) + [str(value)]
    r = subprocess.run(args, capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(r.stderr.strip() or "kwriteconfig6 failed")


def kread(file: str, groups: str | list[str], key: str, default: str | None = None) -> str:
    """kreadconfig6 one key ("" or default when it isn't set)."""
    args = ["kreadconfig6", "--file", file]
    for g in [groups] if isinstance(groups, str) else groups:
        args += ["--group", g]
    args += ["--key", key] + (["--default", default] if default is not None else [])
    return subprocess.run(args, capture_output=True, text=True).stdout.strip()


def kwin_reconfigure():
    subprocess.run(["qdbus6", "org.kde.KWin", "/KWin", "reconfigure"], capture_output=True)


def plasma_script(script: str) -> subprocess.CompletedProcess:
    """Run a plasmashell desktop script; returns the finished process (stdout = what the script printed)."""
    return subprocess.run(["qdbus6", "org.kde.plasmashell", "/PlasmaShell", "org.kde.PlasmaShell.evaluateScript",
                           script], capture_output=True, text=True)


def run_tool(args: list[str], ok_if_already=False):
    """Run a plasma-apply-* style tool; raise its message on failure ("already set" counts as success
    when ok_if_already)."""
    r = subprocess.run(args, capture_output=True, text=True)
    if r.returncode and not (ok_if_already and "already" in (r.stdout + r.stderr)):
        raise RuntimeError((r.stderr or r.stdout).strip() or f"{Path(args[0]).name} failed")


def run_root(*args: str):
    """Run root-helper.sh through pkexec (asks for the password). Raises RuntimeError("cancelled") if the
    prompt is dismissed, or the helper's last message on failure."""
    r = subprocess.run(["pkexec", "/usr/bin/bash", str(ROOT_HELPER), *args], capture_output=True, text=True)
    if r.returncode == 126:
        raise RuntimeError("cancelled")
    if r.returncode:
        msg = (r.stderr or r.stdout).strip().splitlines()
        raise RuntimeError(msg[-1] if msg else f"helper failed ({r.returncode})")
