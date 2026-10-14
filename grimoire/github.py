# SPDX-License-Identifier: GPL-3.0-or-later
"""Sign in with GitHub (OAuth device flow) and settings backups in a secret gist.

Device flow: Grimoire asks GitHub for a short user code, you type it at github.com/login/device in your browser
and approve, and Grimoire polls until GitHub hands over a token. No password ever reaches Grimoire, no redirect or
local web server is involved (so there's no callback to forge), and no client secret exists. The token only gets
the "gist" scope and lives in the system keyring (keystore.py).

The token travels as a Token object whose str/repr hide it; only _auth() reveals it, to put it in a request header.
Error messages are built from status codes, never from requests, so it can't end up in a message or a log.
Every call here blocks: the UI runs them off its thread. HTTP is the one network function; tests replace it.
"""
import base64
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

from grimoire import __version__
from grimoire.github_app import client_id

DEVICE_CODE = "https://github.com/login/device/code"
ACCESS_TOKEN = "https://github.com/login/oauth/access_token"
API = "https://api.github.com"
SCOPE = "gist"
GRANT = "urn:ietf:params:oauth:grant-type:device_code"
REVOKE_PAGE = "https://github.com/settings/applications"
GIST_FILE = "grimoire-settings.grimoire-backup.b64"
GIST_DESCRIPTION = "Grimoire settings backup (made by Grimoire; keep this gist secret)"
MAX_GIST = 10 << 20                  # base64 text; settings backups are a few KB
MAX_BODY = 16 << 20
UA = f"Grimoire-Linux/{__version__} (settings sync)"


class GitHubError(RuntimeError):
    """A failure worth showing as is."""


class Token:
    """The access token. Prints as "Token(…)" so it can't leak through a log line, an f-string or a traceback."""
    __slots__ = ("_value",)

    def __init__(self, value: str):
        self._value = value

    def __repr__(self):
        return "Token(…)"

    __str__ = __repr__

    def reveal(self) -> str:
        return self._value


@dataclass
class DeviceCode:
    device_code: str
    user_code: str
    verification_uri: str
    expires_in: int
    interval: int


# ---------------------------------------------------------------- HTTP
def _urllib(method: str, url: str, headers: dict, body: bytes | None) -> tuple[int, dict, bytes]:
    req = urllib.request.Request(url, data=body, method=method, headers={"User-Agent": UA, **headers})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, dict(r.headers), r.read(MAX_BODY + 1)
    except urllib.error.HTTPError as e:
        try:
            data = e.read(MAX_BODY + 1)
        except OSError:
            data = b""
        return e.code, dict(e.headers or {}), data
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise GitHubError(f"Couldn't reach GitHub (offline?): {getattr(e, 'reason', None) or type(e).__name__}") \
            from None


HTTP = _urllib


def _call(method: str, url: str, token: Token | None = None, form: dict | None = None, payload=None,
          accept="application/vnd.github+json") -> tuple[int, dict, bytes]:
    headers, body = {"Accept": accept}, None
    if token is not None:
        headers["Authorization"] = f"Bearer {token.reveal()}"
        headers["X-GitHub-Api-Version"] = "2022-11-28"
    if form is not None:
        body = urllib.parse.urlencode(form).encode()
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    elif payload is not None:
        body = json.dumps(payload).encode()
        headers["Content-Type"] = "application/json"
    code, rh, data = HTTP(method, url, headers, body)
    if len(data) > MAX_BODY:
        raise GitHubError("GitHub sent more than expected; stopped.")
    rh = {k.lower(): v for k, v in rh.items()}
    if code in (403, 429) and (rh.get("x-ratelimit-remaining") == "0" or code == 429 or "retry-after" in rh):
        reset = rh.get("x-ratelimit-reset", "")
        when = time.strftime(" after %H:%M", time.localtime(int(reset))) if reset.isdigit() else " in a while"
        raise GitHubError(f"GitHub's rate limit is used up; try again{when}.")
    if code == 401 and token is not None:
        raise GitHubError("GitHub no longer accepts this sign-in (revoked or expired). Sign in again.")
    return code, rh, data


def _json(data: bytes) -> dict:
    try:
        d = json.loads(data)
    except (ValueError, UnicodeDecodeError):
        raise GitHubError("GitHub sent an answer that isn't JSON.") from None
    if not isinstance(d, dict):
        raise GitHubError("GitHub sent an unexpected answer.")
    return d


# ---------------------------------------------------------------- device flow
def configured() -> bool:
    return bool(client_id())


def start() -> DeviceCode:
    """Step 1: get a user code to show and the page to type it on."""
    cid = client_id()
    if not cid:
        raise GitHubError("Sign-in isn't set up yet in this copy of Grimoire.")
    code, _, data = _call("POST", DEVICE_CODE, form={"client_id": cid, "scope": SCOPE}, accept="application/json")
    d = _json(data)
    if code != 200 or "error" in d:
        raise GitHubError(_flow_error(str(d.get("error", f"http {code}"))))
    try:
        dc = DeviceCode(str(d["device_code"]), str(d["user_code"]), str(d["verification_uri"]),
                        int(d["expires_in"]), max(1, int(d.get("interval", 5))))
    except (KeyError, TypeError, ValueError):
        raise GitHubError("GitHub sent an unexpected answer.") from None
    if not dc.verification_uri.startswith("https://github.com/"):       # only ever open GitHub itself
        raise GitHubError("GitHub sent an unexpected sign-in page address.")
    return dc


def _flow_error(err: str) -> str:
    return {
        "expired_token": "The code expired before it was entered. Start again.",
        "access_denied": "Sign-in was cancelled on GitHub.",
        "device_flow_disabled": "Device flow isn't enabled for Grimoire's GitHub app yet.",
        "incorrect_client_credentials": "GitHub doesn't know Grimoire's client ID; sign-in isn't set up right.",
        "incorrect_device_code": "GitHub didn't recognise the sign-in code. Start again.",
        "unsupported_grant_type": "GitHub refused the sign-in method.",
    }.get(err, f"GitHub refused the sign-in ({err[:60]}).")


def poll(dc: DeviceCode, cancelled=lambda: False, sleep=time.sleep, clock=time.monotonic) -> Token:
    """Step 2: wait for the user to approve, at GitHub's pace (interval, +5 s on every slow_down).
    Raises GitHubError when denied, expired or cancelled() turns true."""
    interval, end = dc.interval, clock() + dc.expires_in
    while True:
        sleep(interval)
        if cancelled():
            raise GitHubError("Sign-in cancelled.")
        if clock() > end:
            raise GitHubError(_flow_error("expired_token"))
        code, _, data = _call("POST", ACCESS_TOKEN, accept="application/json",
                              form={"client_id": client_id(), "device_code": dc.device_code, "grant_type": GRANT})
        d = _json(data)
        if d.get("access_token"):
            scopes = {s.strip() for s in str(d.get("scope", "")).split(",")}
            if SCOPE not in scopes:
                raise GitHubError("GitHub didn't grant access to gists, which backups need.")
            return Token(str(d["access_token"]))
        err = str(d.get("error", f"http {code}"))
        if err == "authorization_pending":
            continue
        if err == "slow_down":
            interval = max(interval + 5, int(d.get("interval") or 0))
            continue
        raise GitHubError(_flow_error(err))


# ---------------------------------------------------------------- account
def user(token: Token) -> dict:
    code, _, data = _call("GET", f"{API}/user", token)
    if code != 200:
        raise GitHubError(f"GitHub answered {code} when asked who's signed in.")
    d = _json(data)
    return {"login": str(d.get("login", ""))[:40], "name": str(d.get("name") or "")[:80],
            "avatar_url": str(d.get("avatar_url", ""))}


def avatar(url: str) -> bytes:
    """The profile picture (small), only from GitHub's avatar host."""
    p = urllib.parse.urlparse(url)
    if p.scheme != "https" or p.hostname != "avatars.githubusercontent.com":
        return b""
    q = urllib.parse.parse_qs(p.query) | {"s": ["96"]}
    code, _, data = _call("GET", p._replace(query=urllib.parse.urlencode(q, doseq=True)).geturl(), accept="image/*")
    return data if code == 200 and len(data) < (1 << 20) else b""


# ---------------------------------------------------------------- backups in a secret gist
def find_backup(token: Token) -> str:
    """The id of the gist Grimoire backed up to before (say, from another PC), or ""."""
    for page in range(1, 11):
        code, _, data = _call("GET", f"{API}/gists?per_page=100&page={page}", token)
        if code != 200:
            raise GitHubError(f"GitHub answered {code} listing your gists.")
        try:
            gists = json.loads(data)
        except ValueError:
            raise GitHubError("GitHub sent an answer that isn't JSON.") from None
        if not isinstance(gists, list):
            raise GitHubError("GitHub sent an unexpected answer.")
        for g in gists:
            if isinstance(g, dict) and GIST_FILE in (g.get("files") or {}) and not g.get("public"):
                return str(g.get("id", ""))
        if len(gists) < 100:
            break
    return ""


def _gist_id_ok(gid: str) -> bool:
    return bool(gid) and gid.isalnum() and gid.isascii() and len(gid) <= 64


def upload(token: Token, backup: bytes, gist_id: str = "") -> str:
    """Put a backup into the secret gist (made on first use). Returns the gist id."""
    text = base64.b64encode(backup).decode()
    if len(text) > MAX_GIST:
        raise GitHubError("This backup is too large for a gist (leave the wallpaper library out).")
    files = {GIST_FILE: {"content": text}}
    if _gist_id_ok(gist_id):
        code, _, data = _call("PATCH", f"{API}/gists/{gist_id}", token, payload={"files": files})
        if code == 200:
            return gist_id
        if code != 404:                                  # 404: deleted on GitHub meanwhile, so make a new one
            raise GitHubError(f"GitHub answered {code} updating the backup gist.")
    code, _, data = _call("POST", f"{API}/gists", token,
                          payload={"description": GIST_DESCRIPTION, "public": False, "files": files})
    if code != 201:
        raise GitHubError(f"GitHub answered {code} creating the backup gist.")
    gid = str(_json(data).get("id", ""))
    if not _gist_id_ok(gid):
        raise GitHubError("GitHub sent an unexpected answer.")
    return gid


def download(token: Token, gist_id: str) -> bytes:
    """The backup bytes from the gist (to be checked by backup.inspect like any other file)."""
    if not _gist_id_ok(gist_id):
        raise GitHubError("No backup on GitHub yet.")
    code, _, data = _call("GET", f"{API}/gists/{gist_id}", token)
    if code == 404:
        raise GitHubError("The backup gist is gone from GitHub.")
    if code != 200:
        raise GitHubError(f"GitHub answered {code} fetching the backup.")
    f = (_json(data).get("files") or {}).get(GIST_FILE)
    if not isinstance(f, dict):
        raise GitHubError("That gist doesn't hold a Grimoire backup.")
    text = f.get("content") if not f.get("truncated") else None
    if not isinstance(text, str):                        # big files come truncated; fetch the raw one
        raw = urllib.parse.urlparse(str(f.get("raw_url", "")))
        if raw.scheme != "https" or raw.hostname != "gist.githubusercontent.com":
            raise GitHubError("GitHub sent an unexpected backup address.")
        code, _, body = _call("GET", raw.geturl(), accept="text/plain")
        if code != 200:
            raise GitHubError(f"GitHub answered {code} fetching the backup.")
        text = body.decode("ascii", "replace")
    if len(text) > MAX_GIST:
        raise GitHubError("The backup on GitHub is larger than the safety limit.")
    try:
        return base64.b64decode(text.strip(), validate=True)
    except ValueError:
        raise GitHubError("The backup on GitHub is damaged (not base64).") from None
