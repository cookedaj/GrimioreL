# SPDX-License-Identifier: GPL-3.0-or-later
"""Self-update from the public repo: compare the installed copy's commit with GitHub's main, list what's new, and
reinstall from main's tarball.

install.sh writes INSTALLED.json into the installed copy (the commit it came from); this module reads it, asks
GitHub's API (no token: 60 requests/hour, so answers are cached and re-checked at most every few hours) and, on
"Update now", downloads codeload's tarball of that exact commit, extracts it defensively into CACHE and runs its own
install.sh, which replaces the app folder only. Settings, data and logs are never touched.

No Qt here: the hub's What's new panel (updateview.py) and `grimoire update` on the command line both use it.
"""
import fcntl
import json
import os
import shutil
import subprocess
import tarfile
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from grimoire import NAME, __version__
from grimoire.paths import CACHE, DATA, packaged

REPO = "cookedaj/grimoire-linux"   # GitHub redirects the old cookedaj/GrimioreL
BRANCH = "main"
API = f"https://api.github.com/repos/{REPO}"
TARBALL = f"https://codeload.github.com/{REPO}/tar.gz/{{sha}}"
UA = {"User-Agent": f"Grimoire-Linux/{__version__} (self-update)", "Accept": "application/vnd.github+json"}
APP = DATA / "app"                     # the installed copy (install.sh's $APP)
STATE = CACHE / "update.json"          # last check, ETag, cached comparisons
STAGING = CACHE / "update"             # download + extraction; wiped after each update
CHECK_EVERY = 6 * 3600
MAX_DOWNLOAD = 50 * 1024 * 1024        # the whole repo is under 1 MB; anything near this is wrong
MAX_EXPANDED = 200 * 1024 * 1024
TRAILERS = ("co-authored-by:", "signed-off-by:", "reviewed-by:")


class UpdateError(RuntimeError):
    """A failure worth showing as is (offline, rate-limited, a bad download)."""


@dataclass
class Change:
    sha: str
    title: str
    bullets: list = field(default_factory=list)
    date: str = ""


@dataclass
class Status:
    installed: dict                    # INSTALLED.json: {"sha", "date", ...}, sha "unknown" if not recorded
    latest: dict = field(default_factory=dict)      # {"sha", "date"} of main
    available: bool = False            # main has commits the installed copy doesn't
    changes: list = field(default_factory=list)     # Change, newest first
    total: int = 0                     # commits since the installed one (may exceed len(changes))
    note: str = ""                     # why there's no list (unknown or local build)
    checked: float = 0.0
    error: str = ""


# ---------------------------------------------------------------- what's installed
def installed() -> dict:
    """What the installed copy was built from, as install.sh recorded it."""
    try:
        info = json.loads((APP / "INSTALLED.json").read_text())
        if isinstance(info, dict) and isinstance(info.get("sha"), str):
            return info
    except (OSError, ValueError):
        pass
    return {"sha": "unknown", "date": ""}


def is_installed() -> bool:
    return (APP / "bin" / "grimoire").is_file()


def managed() -> bool:
    """A distro package (.deb, AUR) runs this copy and there's no per-user install: updates come from the package
    manager, so Grimoire never installs a second copy over it."""
    return bool(packaged()) and not is_installed()


PACKAGE_NOTE = "Installed from a distro package: updates come with your system updates (apt, pacman…)."
NOT_INSTALLED = (f"{NAME} isn't installed (run ./install.sh from a download first); "
                 "a git checkout updates with git pull.")


def _sha_ok(sha: str) -> bool:
    return len(sha) == 40 and all(c in "0123456789abcdef" for c in sha)


# ---------------------------------------------------------------- GitHub
def _get(url: str, etag: str = "", timeout=20) -> tuple[int, dict, bytes]:
    """(status, headers, body); a 304 (unchanged, and free against the rate limit) comes back as status 304."""
    headers = dict(UA)
    if etag:
        headers["If-None-Match"] = etag
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=timeout) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        if e.code == 304:
            return 304, dict(e.headers), b""
        if e.code in (403, 429) and (e.headers.get("X-RateLimit-Remaining") == "0" or e.code == 429):
            reset = e.headers.get("X-RateLimit-Reset")
            when = time.strftime(" after %H:%M", time.localtime(int(reset))) if (reset or "").isdigit() else " later"
            raise UpdateError(f"GitHub's hourly limit for update checks is used up; try again{when}.") from None
        if e.code == 404:
            return 404, dict(e.headers), b""
        raise UpdateError(f"GitHub answered {e.code} {e.reason}.") from None
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        reason = getattr(e, "reason", e)
        raise UpdateError(f"Couldn't reach GitHub (offline?): {reason}") from None


def _json(body: bytes) -> dict:
    try:
        data = json.loads(body)
    except ValueError:
        raise UpdateError("GitHub sent an answer that isn't JSON.") from None
    if not isinstance(data, dict):
        raise UpdateError("GitHub sent an unexpected answer.")
    return data


def _load_state() -> dict:
    try:
        s = json.loads(STATE.read_text())
        return s if isinstance(s, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_state(s: dict):
    STATE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(s, indent=1))
    tmp.replace(STATE)


def parse_message(message: str) -> tuple[str, list]:
    """A commit's title and its bullet lines (the repo's style: short title + bullet body), minus trailers."""
    lines = (message or "").strip().splitlines()
    title = lines[0].strip() if lines else ""
    bullets, cur = [], None
    for raw in lines[1:]:
        line = raw.strip()
        if not line or line.lower().startswith(TRAILERS):
            cur = None
            continue
        if line[:2] in ("- ", "* "):
            bullets.append(line[2:].strip())
            cur = len(bullets) - 1
        elif cur is not None:                      # a wrapped bullet continues on the next line
            bullets[cur] += " " + line
    return title, bullets


def _latest(state: dict) -> dict:
    """main's head commit; ETag-conditional, so an unchanged answer doesn't count against the limit."""
    cached = state.get("latest") or {}
    code, headers, body = _get(f"{API}/commits/{BRANCH}", etag=cached.get("etag", ""))
    if code == 304 and cached.get("sha"):
        return cached
    if code != 200:
        raise UpdateError(f"Couldn't find {REPO}'s {BRANCH} branch on GitHub.")
    d = _json(body)
    sha = d.get("sha", "")
    if not _sha_ok(sha):
        raise UpdateError("GitHub sent an unexpected answer.")
    return {"sha": sha, "date": ((d.get("commit") or {}).get("committer") or {}).get("date", ""),
            "message": (d.get("commit") or {}).get("message", ""), "etag": headers.get("ETag", "")}


def _compare(base: str, head: str, state: dict) -> dict | None:
    """Commits between two shas (cached for good: a comparison of two fixed commits never changes).
    None when the installed commit isn't on GitHub (a local build)."""
    key = f"{base}...{head}"
    cmp = state.setdefault("compare", {})
    if key in cmp:
        return cmp[key]
    code, _, body = _get(f"{API}/compare/{key}?per_page=100")
    if code == 404:
        result = None
    elif code != 200:
        raise UpdateError(f"GitHub answered {code} comparing versions.")
    else:
        d = _json(body)
        commits = []
        for c in d.get("commits") or []:
            if len(c.get("parents") or []) > 1:   # merge commits only repeat what they merge
                continue
            title, bullets = parse_message((c.get("commit") or {}).get("message", ""))
            commits.append(asdict(Change(c.get("sha", ""), title, bullets,
                                         ((c.get("commit") or {}).get("committer") or {}).get("date", ""))))
        result = {"status": d.get("status", ""), "ahead_by": int(d.get("ahead_by") or 0), "commits": commits}
    state["compare"] = {key: result}               # only the current pair is worth keeping
    return result


def check(force: bool = False) -> Status:
    """Is there something newer on main? Without force, answers from the cache if it's recent."""
    inst = installed()
    state = _load_state()
    fresh = time.time() - state.get("checked", 0) < CHECK_EVERY
    if force or not fresh or "latest" not in state:
        state["latest"] = _latest(state)
        state["checked"] = time.time()
        _save_state(state)
    latest = state["latest"]
    st = Status(installed=inst, latest={"sha": latest["sha"], "date": latest.get("date", "")},
                checked=state.get("checked", 0))
    base = inst.get("sha", "unknown")
    if base == latest["sha"]:
        return st
    if not _sha_ok(base):
        st.available = True
        st.note = "This copy didn't record which version it is, so only the newest change is listed."
        title, bullets = parse_message(latest.get("message", ""))
        if title:
            st.changes = [Change(latest["sha"], title, bullets, latest.get("date", ""))]
            st.total = 1
        return st
    cmp = _compare(base, latest["sha"], state)
    _save_state(state)
    if cmp is None:
        st.note = ("This copy was installed from a commit that isn't on GitHub (a local build), so there's "
                   "nothing to compare it with.")
        return st
    st.available = cmp["status"] in ("ahead", "diverged") and cmp["ahead_by"] > 0
    st.changes = [Change(**c) for c in reversed(cmp["commits"])]
    st.total = cmp["ahead_by"]
    return st


# ---------------------------------------------------------------- install
def _download(url: str, dest: Path, limit=MAX_DOWNLOAD):
    req = urllib.request.Request(url, headers={"User-Agent": UA["User-Agent"]})
    try:
        with urllib.request.urlopen(req, timeout=60) as r, open(dest, "wb") as f:
            total = 0
            while chunk := r.read(1 << 16):
                total += len(chunk)
                if total > limit:
                    raise UpdateError("The download is larger than the safety limit; not installing it.")
                f.write(chunk)
    except urllib.error.HTTPError as e:
        raise UpdateError(f"The download failed: {e.code} {e.reason}.") from None
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise UpdateError(f"The download failed (offline?): {getattr(e, 'reason', e)}") from None


def _extract(archive: Path, dest: Path) -> Path:
    """Extract the tarball into a fresh dest and return its one top folder. Only plain files and folders with
    relative paths inside it; size-capped; then Python's "data" filter as a second guard."""
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    try:
        with tarfile.open(archive, "r:gz") as t:
            members = t.getmembers()
            tops, total = set(), 0
            for m in members:
                if m.isfile() or m.isdir():
                    pass
                elif m.type == tarfile.XGLTYPE or m.type == tarfile.XHDTYPE:
                    continue
                else:
                    raise UpdateError(f"The download contains a link or special file ({m.name}); not installing it.")
                parts = Path(m.name).parts
                if m.name.startswith("/") or ".." in parts or not parts:
                    raise UpdateError(f"The download contains an unsafe path ({m.name}); not installing it.")
                tops.add(parts[0])
                total += m.size
            if total > MAX_EXPANDED:
                raise UpdateError("The download expands too large; not installing it.")
            if len(tops) != 1:
                raise UpdateError("The download isn't laid out like Grimoire; not installing it.")
            t.extractall(dest, members=[m for m in members if m.isfile() or m.isdir()], filter="data")
    except (tarfile.TarError, EOFError, OSError) as e:
        raise UpdateError(f"The download is damaged: {e}") from None
    root = dest / tops.pop()
    if not ((root / "install.sh").is_file() and (root / "grimoire" / "__init__.py").is_file()):
        raise UpdateError("The download isn't laid out like Grimoire; not installing it.")
    return root


def apply(sha: str, date: str = "", progress=lambda text: None) -> dict:
    """Download main at sha and install it over the installed copy with its own install.sh.
    Returns the new INSTALLED.json. Only one update runs at a time."""
    if managed():
        raise UpdateError(PACKAGE_NOTE)
    if not is_installed():                         # a checkout updates with git pull, not by installing a copy
        raise UpdateError(NOT_INSTALLED)
    if not _sha_ok(sha):
        raise UpdateError("No valid version to update to; check for updates first.")
    STAGING.mkdir(parents=True, exist_ok=True)
    with open(STAGING.parent / "update.lock", "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise UpdateError("Another update is already running.") from None
        work = STAGING / sha
        try:
            if work.exists():
                shutil.rmtree(work)
            work.mkdir(parents=True)
            progress("Downloading…")
            archive = work / "grimoire.tar.gz"
            _download(TARBALL.format(sha=sha), archive)
            progress("Unpacking…")
            root = _extract(archive, work / "x")
            progress("Installing…")
            env = os.environ | {"GRIMOIRE_SOURCE_SHA": sha, "GRIMOIRE_SOURCE_DATE": date}
            env.pop("PYTHONPATH", None)            # install.sh runs the new code, not the running copy's
            try:
                r = subprocess.run(["bash", str(root / "install.sh")], cwd=root, env=env, capture_output=True,
                                   text=True, timeout=300)
            except (OSError, subprocess.TimeoutExpired) as e:
                raise UpdateError(f"The installer didn't finish: {e}") from None
            if r.returncode != 0:
                tail = (r.stdout + r.stderr).strip().splitlines()[-3:]
                raise UpdateError("The installer failed: " + (" ".join(tail) or f"exit {r.returncode}"))
        finally:
            shutil.rmtree(work, ignore_errors=True)  # Grimoire's own staging folder, never user files
    new = installed()
    if new.get("sha") != sha:
        raise UpdateError("The installer ran, but the installed copy doesn't report the new version.")
    state = _load_state()
    state.pop("compare", None)
    _save_state(state)
    return new


def snooze(sha: str):
    """'Later' on the home banner: hide it until a newer version than sha shows up."""
    state = _load_state()
    state["snoozed"] = sha
    _save_state(state)


def snoozed(sha: str) -> bool:
    return _load_state().get("snoozed") == sha


def short(sha: str) -> str:
    return sha[:7] if _sha_ok(sha) else sha


def day(iso: str) -> str:
    """'2026-10-14T01:04:00Z' -> 'Oct 13, 2026' (in local time, like the dates git writes)."""
    try:
        return datetime.fromisoformat(iso).astimezone().strftime("%b %-d, %Y")
    except (ValueError, TypeError):
        return ""


# ---------------------------------------------------------------- command line
def cli(argv: list[str]) -> int:
    """grimoire update [--check]: show what's new on main and install it (or only show it with --check)."""
    if argv and argv[0] not in ("--check", "-n"):
        print("usage: grimoire update [--check]")
        return 2
    if managed():
        print(PACKAGE_NOTE)
        return 0
    if not is_installed():
        print(NOT_INSTALLED)
        return 1
    try:
        st = check(force=True)
    except UpdateError as e:
        print(e)
        return 1
    inst = st.installed
    print(f"Installed: {short(inst.get('sha', 'unknown'))} {day(inst.get('date', ''))}".rstrip())
    print(f"Latest:    {short(st.latest['sha'])} {day(st.latest.get('date', ''))}".rstrip())
    if st.note:
        print(st.note)
    if not st.available:
        print(f"{NAME} is up to date." if not st.note else "Nothing to update automatically.")
        return 0
    print(f"\nWhat's new ({st.total} change{'s' if st.total != 1 else ''}):")
    for c in st.changes:
        print(f"  {c.title}")
        for b in c.bullets:
            print(f"    - {b}")
    if argv:
        return 0
    try:
        new = apply(st.latest["sha"], st.latest.get("date", ""), progress=lambda t: print(t))
    except UpdateError as e:
        print(e)
        return 1
    print(f"Updated to {short(new['sha'])}. Restart {NAME} (and any open spell windows) to use it.")
    return 0
