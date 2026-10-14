"""MuraL community store: top items from the KDE Store (OCS API) and Wallhaven, installed on demand.

Nothing is downloaded until you press Install. Archives are extracted defensively (no absolute paths,
no "..", regular files only, size-capped) and only the recognised theme files are copied into place:

    kind        installs to                                   applied by
    plasma      ~/.local/share/plasma/desktoptheme/<dir>      MuraL Taskbar / Style
    colors      ~/.local/share/color-schemes/<name>.colors    MuraL Colors
    cursor      ~/.local/share/icons/<dir>                    MuraL Cursor
    icons       ~/.local/share/icons/<dir>                    MuraL Icons
    aurorae     ~/.local/share/aurorae/themes/<dir>           MuraL Windows
    splash      ~/.local/share/plasma/look-and-feel/<id>      MuraL Splash
    konsole     ~/.local/share/konsole/<name>.colorscheme     MuraL Terminal
    sddm        staged; copied to /usr/share/sddm/themes on Install (password prompt)
    plymouth    staged; copied to /usr/share/plymouth/themes on Install (password prompt)
    wallpaper   MuraL library (optionally converted to black & white)
"""
import hashlib
import json
import re
import shutil
import tarfile
import threading
import time
import urllib.parse
import urllib.request
import zipfile
from configparser import ConfigParser
from dataclasses import asdict, dataclass, field
from pathlib import Path

from grimoire.paths import CACHE, DATA, HOME

UA = {"User-Agent": "Grimoire-MuraL/0.1 (personal KDE customizer)"}
OCS = "https://api.kde-look.org/ocs/v1/content/data"
WALLHAVEN = "https://wallhaven.cc/api/v1/search"
STORE_CACHE = CACHE / "store"
DOWNLOADS = STORE_CACHE / "downloads"
STAGED = DATA / "mural" / "staged"
REGISTRY = DATA / "mural" / "store-installed.json"
MAX_ARCHIVE = 600 * 1024 * 1024
LIST_TTL = 6 * 3600
_lock = threading.Lock()


@dataclass(frozen=True)
class Category:
    key: str
    title: str
    kind: str
    ocs: tuple = ()               # KDE Store category ids
    wallhaven: str = ""           # Wallhaven query (wallpapers only)


CATEGORIES = {
    "plasma": Category("plasma", "Plasma styles", "plasma", (104,)),
    "colors": Category("colors", "Color schemes", "colors", (112,)),
    "cursor": Category("cursor", "Cursors", "cursor", (107,)),
    "icons": Category("icons", "Icon themes", "icons", (132,)),
    "aurorae": Category("aurorae", "Window decorations", "aurorae", (717, 114)),
    "splash": Category("splash", "Splash screens", "splash", (716,)),
    "konsole": Category("konsole", "Konsole color schemes", "konsole", (462,)),
    "sddm": Category("sddm", "Login themes (SDDM)", "sddm", (101,)),
    "plymouth": Category("plymouth", "Boot themes (Plymouth)", "plymouth", (108,)),
    "wallpaper": Category("wallpaper", "KDE wallpapers", "wallpaper", (299,)),
    "wallhaven-bw": Category("wallhaven-bw", "Wallhaven · black & white anime", "wallpaper",
                             wallhaven="anime monochrome"),
    "wallhaven-bc": Category("wallhaven-bc", "Wallhaven · Black Clover", "wallpaper", wallhaven="Black Clover"),
}


@dataclass
class Item:
    id: str
    name: str
    author: str = ""
    downloads: int = 0
    score: int = 0                # 0..100
    preview: str = ""             # image URL
    summary: str = ""
    files: list = field(default_factory=list)   # [(url, filename, size_kb)]
    page: str = ""


# ---------------------------------------------------------------- networking
def _get(url: str, timeout=30) -> bytes:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def _download(url: str, dest: Path, limit=MAX_ARCHIVE):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=60) as r, open(dest, "wb") as f:
        total = 0
        while chunk := r.read(1 << 16):
            total += len(chunk)
            if total > limit:
                raise RuntimeError("download is larger than the safety limit")
            f.write(chunk)


def top(cat: Category, sort: str = "down", search: str = "", page: int = 0) -> list[Item]:
    """Top items (sort: down = most downloaded, high = best rated, new = newest). Cached for 6 h."""
    key = hashlib.sha1(json.dumps([cat.key, sort, search, page]).encode()).hexdigest()[:16]
    cache = STORE_CACHE / f"list-{key}.json"
    if cache.exists() and time.time() - cache.stat().st_mtime < LIST_TTL:
        return [Item(**d) for d in json.loads(cache.read_text())]
    items = _wallhaven(cat, sort, search, page) if cat.wallhaven else _ocs(cat, sort, search, page)
    STORE_CACHE.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps([asdict(i) for i in items]))
    return items


def _ocs(cat, sort, search, page) -> list[Item]:
    params = {"categories": "x".join(map(str, cat.ocs)), "sortmode": sort, "pagesize": 100, "page": page,
              "format": "json"}
    if search:
        params["search"] = search
    data = json.loads(_get(OCS + "?" + urllib.parse.urlencode(params)))
    items = []
    for d in data.get("data", []):
        files = []
        for n in range(1, 30):
            link = d.get(f"downloadlink{n}")
            if not link:
                break
            files.append((link, d.get(f"downloadname{n}") or "", int(d.get(f"downloadsize{n}") or 0)))
        items.append(Item(id=f"kde-{d['id']}", name=d.get("name", "?"), author=d.get("personid", ""),
                          downloads=int(d.get("downloads") or 0), score=int(float(d.get("score") or 0)),
                          preview=d.get("smallpreviewpic1") or d.get("previewpic1") or "",
                          summary=re.sub(r"<[^>]+>", "", d.get("summary") or "")[:200], files=files,
                          page=d.get("detailpage", "")))
    return items


def _wallhaven(cat, sort, search, page) -> list[Item]:
    sorting = {"down": "favorites", "high": "toplist", "new": "date_added"}.get(sort, "favorites")
    params = {"q": search or cat.wallhaven, "categories": "010", "purity": "100", "atleast": "1920x1080",
              "sorting": sorting, "page": page + 1}
    items = []
    for p in (params["page"], params["page"] + 1, params["page"] + 2, params["page"] + 3):   # 24/page → ~96
        data = json.loads(_get(WALLHAVEN + "?" + urllib.parse.urlencode({**params, "page": p})))
        for d in data.get("data", []):
            items.append(Item(id=f"wh-{d['id']}", name=f"{d['id']} · {d['resolution']}", author="wallhaven",
                              downloads=int(d.get("favorites") or 0), preview=d["thumbs"]["small"],
                              summary=f"{d['resolution']} · {int(d.get('file_size', 0)) // 1024} KB",
                              files=[(d["path"], d["path"].rsplit("/", 1)[-1], int(d.get("file_size", 0)) // 1024)],
                              page=d.get("url", "")))
        if data.get("meta", {}).get("last_page", 1) <= p:
            break
    return items


def thumbnail(url: str) -> Path | None:
    """Cached preview image for a store item."""
    if not url:
        return None
    path = STORE_CACHE / "thumbs" / (hashlib.sha1(url.encode()).hexdigest() + Path(urllib.parse.urlparse(url).path).suffix[:5])
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            path.write_bytes(_get(url, timeout=20))
        except OSError:
            return None
    return path


# ---------------------------------------------------------------- registry
def registry() -> dict:
    try:
        return json.loads(REGISTRY.read_text())
    except (OSError, ValueError):
        return {}


def installed(cat_kind: str) -> list[dict]:
    """[{item, name, ident, path, preview}] for this kind, newest first."""
    return [e for e in registry().values() if e["kind"] == cat_kind][::-1]


def _record(entry: dict):
    with _lock:
        reg = registry()
        reg[entry["key"]] = entry
        REGISTRY.parent.mkdir(parents=True, exist_ok=True)
        REGISTRY.write_text(json.dumps(reg, indent=2))


def is_installed(item_id: str) -> bool:
    return any(e["item"] == item_id for e in registry().values())


def uninstall(key: str):
    with _lock:
        reg = registry()
        entry = reg.pop(key, None)
        REGISTRY.write_text(json.dumps(reg, indent=2))
    if entry:
        p = Path(entry["path"])
        if p.is_dir():
            shutil.rmtree(p, ignore_errors=True)
        else:
            p.unlink(missing_ok=True)


# ---------------------------------------------------------------- safe extraction
def _extract(archive: Path, dest: Path) -> Path:
    """Extract into dest (fresh dir). Rejects absolute paths, '..', links and huge expansions."""
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    if zipfile.is_zipfile(archive):
        with zipfile.ZipFile(archive) as z:
            total = 0
            for info in z.infolist():
                parts = Path(info.filename).parts
                if info.filename.startswith("/") or ".." in parts:
                    raise RuntimeError(f"unsafe path in archive: {info.filename}")
                total += info.file_size
                if total > MAX_ARCHIVE * 3:
                    raise RuntimeError("archive expands too large")
                if info.is_dir():
                    continue
                target = dest / info.filename
                target.parent.mkdir(parents=True, exist_ok=True)
                with z.open(info) as src, open(target, "wb") as out:
                    shutil.copyfileobj(src, out)
    elif tarfile.is_tarfile(archive):
        with tarfile.open(archive) as t:
            if sum(m.size for m in t.getmembers()) > MAX_ARCHIVE * 3:
                raise RuntimeError("archive expands too large")
            t.extractall(dest, filter="data")      # Python's safe filter: no links out, no abs paths, no devices
    else:                                          # a plain file (.colors, .colorscheme, an image…)
        shutil.copy(archive, dest / archive.name)
    return dest


def _pick_file(item: Item) -> tuple[str, str]:
    """Choose which of an item's files to download (prefer archives / matching extensions)."""
    if not item.files:
        raise RuntimeError("this item has no downloadable file")
    prefs = (".tar.gz", ".tgz", ".tar.xz", ".tar.bz2", ".tar", ".zip", ".colors", ".colorscheme",
             ".plasmoid", ".knsrc", ".png", ".jpg", ".jpeg", ".webp")
    for ext in prefs:
        for url, fname, _ in item.files:
            if fname.lower().endswith(ext):
                return url, fname
    return item.files[0][0], item.files[0][1] or "download"


# ---------------------------------------------------------------- install per kind
def _dirs_with(root: Path, predicate) -> list[Path]:
    return [d for d in [root, *sorted(p for p in root.rglob("*") if p.is_dir())] if predicate(d)]


def _ini(path: Path) -> ConfigParser:
    c = ConfigParser(interpolation=None, strict=False)
    c.optionxform = str
    try:
        c.read(path, encoding="utf-8")
    except Exception:
        pass
    return c


def _claim(dst: Path, item: str):
    """Refuse to replace something Grimoire didn't install for this item (your own theme with the same folder
    name, or another store item's)."""
    if dst.exists() or dst.is_symlink():
        owners = {e.get("item") for e in registry().values() if e["path"] == str(dst)}
        if item not in owners:
            raise RuntimeError(f"you already have “{dst.name}” in {dst.parent}; Grimoire won't replace it")


def _slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", str(text)).strip("._")[:80]


def _copyfile(src: Path, dst: Path, item: str):
    _claim(dst, item)
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(src, dst)


def _copytree(src: Path, dst: Path, item: str):
    if dst.resolve().parent != dst.parent.resolve():
        raise RuntimeError(f"unsafe theme name: {dst.name}")
    _claim(dst, item)
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst, symlinks=False, ignore=shutil.ignore_patterns("*.sh", "*.py", "install*"))


def install(cat: Category, item: Item, to_bw: bool = False) -> list[dict]:
    """Download + install one store item. Returns the registry entries created."""
    url, fname = _pick_file(item)
    work = DOWNLOADS / item.id
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    safe_name = re.sub(r"[^A-Za-z0-9._-]", "_", fname)[:120] or "download"
    archive = work / safe_name
    _download(url, archive)
    root = _extract(archive, work / "x")
    preview = str(thumbnail(item.preview) or "")
    entries = []

    def add(name, ident, path):
        e = {"key": f"{cat.kind}:{ident}", "item": item.id, "kind": cat.kind, "name": name, "ident": ident,
             "path": str(path), "preview": preview, "author": item.author}
        _record(e)
        entries.append(e)

    k = cat.kind

    def folder(d: Path) -> str:               # a flat archive's root is the work folder, not a theme name
        return d.name if d != root else (_slug(item.name) or item.id)
    if k == "colors":
        for f in root.rglob("*.colors"):
            dst = HOME / ".local/share/color-schemes" / f.name
            _copyfile(f, dst, item.id)
            add(_ini(f).get("General", "Name", fallback=f.stem), f.stem, dst)
    elif k == "konsole":
        for f in root.rglob("*.colorscheme"):
            dst = HOME / ".local/share/konsole" / f.name
            _copyfile(f, dst, item.id)
            add(_ini(f).get("General", "Description", fallback=f.stem), f.stem, dst)
    elif k == "cursor":
        for d in _dirs_with(root, lambda d: (d / "cursors").is_dir()):
            dst = HOME / ".local/share/icons" / folder(d)
            _copytree(d, dst, item.id)
            add(_ini(d / "index.theme").get("Icon Theme", "Name", fallback=folder(d)), folder(d), dst)
    elif k == "icons":
        for d in _dirs_with(root, lambda d: (d / "index.theme").is_file()
                            and _ini(d / "index.theme").has_option("Icon Theme", "Directories")):
            dst = HOME / ".local/share/icons" / folder(d)
            _copytree(d, dst, item.id)
            add(_ini(d / "index.theme").get("Icon Theme", "Name", fallback=folder(d)), folder(d), dst)
    elif k == "plasma":
        for d in _dirs_with(root, lambda d: ((d / "metadata.json").is_file() or (d / "metadata.desktop").is_file())
                            and ((d / "widgets").is_dir() or (d / "colors").is_file() or (d / "dialogs").is_dir())):
            dst = HOME / ".local/share/plasma/desktoptheme" / folder(d)
            _copytree(d, dst, item.id)
            add(item.name if d == root else d.name, folder(d), dst)
    elif k == "aurorae":
        for d in _dirs_with(root, lambda d: any(d.glob("decoration.svg*"))):
            dst = HOME / ".local/share/aurorae/themes" / folder(d)
            _copytree(d, dst, item.id)
            add(folder(d), folder(d), dst)
    elif k == "splash":
        for d in _dirs_with(root, lambda d: (d / "contents/splash").is_dir()):
            meta = d / "metadata.json"
            ident = folder(d)
            if meta.is_file():
                try:
                    ident = _slug(json.loads(meta.read_text())["KPlugin"]["Id"]) or ident   # never a path
                except (ValueError, KeyError, TypeError):
                    pass
            dst = HOME / ".local/share/plasma/look-and-feel" / ident
            _copytree(d, dst, item.id)
            add(item.name, ident, dst)
    elif k == "sddm":
        for d in _dirs_with(root, lambda d: (d / "metadata.desktop").is_file() and (d / "Main.qml").is_file()):
            ident = _slug(folder(d)) or item.id
            dst = STAGED / "sddm" / ident
            _copytree(d, dst, item.id)
            add(_ini(d / "metadata.desktop").get("SddmGreeterTheme", "Name", fallback=d.name), ident, dst)
    elif k == "plymouth":
        for d in _dirs_with(root, lambda d: any(d.glob("*.plymouth"))):
            ident = re.sub(r"[^A-Za-z0-9._-]", "_", next(d.glob("*.plymouth")).stem)
            dst = STAGED / "plymouth" / ident
            _copytree(d, dst, item.id)
            add(_ini(next(d.glob("*.plymouth"))).get("Plymouth Theme", "Name", fallback=ident), ident, dst)
    elif k == "wallpaper":
        from grimoire.spells.mural import library
        images = [p for p in root.rglob("*") if p.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp")
                  and p.stat().st_size > 50_000]
        images.sort(key=lambda p: p.stat().st_size, reverse=True)
        for p in images[:1]:                       # the largest image = the actual wallpaper
            dst = library.LIBRARY / f"{item.id}{p.suffix.lower()}"
            if to_bw:
                from PIL import Image, ImageOps
                ImageOps.autocontrast(Image.open(p).convert("L"), cutoff=1).save(dst.with_suffix(".png"))
                dst = dst.with_suffix(".png")
            else:
                shutil.copy(p, dst)
            add(item.name, dst.name, dst)
    shutil.rmtree(work, ignore_errors=True)
    if not entries:
        raise RuntimeError("didn't find a usable theme inside this download")
    return entries
