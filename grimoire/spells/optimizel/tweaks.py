"""OptimizeL's catalog: every tweak is an on/off switch whose "on" lives in persistent config (sysctl.d, systemd,
apt.conf.d, KDE config, autostart overrides) so it survives restarts, and whose "off" restores what was there
before. System tweaks are done by root-helper.sh (one pkexec prompt per batch); the rest run as you.

A tweak reports one of four states: "on" (Grimoire's change is in place), "off", "native" (the system is
already set that way without Grimoire, so there's nothing to do) or "na" (doesn't apply to this machine).
"""
import json
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from grimoire.fsutil import human
from grimoire.paths import CONFIG, DATA

HELPER = Path(__file__).with_name("root-helper.sh")
STATE = Path("/var/lib/grimoire-optimizel")       # root helper's saved originals
SAVED = DATA / "optimizel.json"                   # your-side originals + changes waiting on a restart/log out
AUTOSTART = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "autostart"
ENV_D = CONFIG.parent / "environment.d"
MARK = "Grimoire OptimizeL"

GROUPS = ["Power", "Memory", "Storage & boot", "Network", "Services", "Startup apps", "Desktop", "Gaming"]
WHEN = {"now": "Instant", "restart": "After restart", "logout": "After log out"}


# ---------------------------------------------------------------- small readers
def sh(*args: str) -> str:
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=10).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return ""


def sysctl(key: str) -> str:
    try:
        return " ".join(Path("/proc/sys", key.replace(".", "/")).read_text().split())
    except OSError:
        return ""


def unit_state(unit: str, user=False) -> str:
    """enabled / disabled / static / masked / not-found."""
    return sh("systemctl", *(["--user"] if user else []), "is-enabled", unit) or "not-found"


def unit_active(unit: str) -> bool:
    return sh("systemctl", "is-active", unit) == "active"


def kread(file: str, group: str, key: str) -> str:
    return sh("kreadconfig6", "--file", file, "--group", group, "--key", key)


def boot_id() -> str:
    return Path("/proc/sys/kernel/random/boot_id").read_text().strip()


def session_id() -> str:
    return f"{boot_id()}:{os.environ.get('XDG_SESSION_ID', '')}"


def load_saved() -> dict:
    try:
        d = json.loads(SAVED.read_text())
    except (OSError, ValueError):
        d = {}
    for k in ("orig", "pending"):
        d.setdefault(k, {})
    return d


def save_saved(d: dict):
    SAVED.write_text(json.dumps(d, indent=1))


def has_mark(p: Path) -> bool:
    try:
        return MARK in p.read_text(errors="replace")
    except OSError:
        return False


# ---------------------------------------------------------------- tweak kinds
@dataclass
class Tweak:
    id: str
    group: str
    title: str
    why: str
    target: str                    # what "on" sets, in words
    when: str = "now"              # now / restart / logout
    recommended: bool = True
    installs: str = ""             # package the first "on" may install
    root: bool = False

    def current(self) -> str: return ""
    def is_on(self) -> bool: return False
    def native(self) -> bool: return False
    def unavailable(self) -> str: return ""
    def enable(self, saved: dict): raise NotImplementedError     # user tweaks only
    def disable(self, saved: dict): raise NotImplementedError

    def state(self) -> str:
        if self.is_on():
            return "on"
        if self.unavailable():
            return "na"
        return "native" if self.native() else "off"


@dataclass
class Sysctl(Tweak):
    values: dict = field(default_factory=dict)
    show: tuple = ()               # keys to show instead of values' keys
    root: bool = True

    @property
    def file(self) -> Path:
        return Path(f"/etc/sysctl.d/99-grimoire-optimizel-{self.id}.conf")

    def current(self):
        return "   ".join(f"{k.split('.')[-1]} {sysctl(k) or '?'}" for k in (self.show or self.values))

    def is_on(self):
        return self.file.exists()

    def native(self):
        return all(sysctl(k) == str(v) for k, v in self.values.items())

    def unavailable(self):
        return "" if all(sysctl(k) for k in self.values) else "Your kernel or CPU doesn't have this setting"


@dataclass
class Units(Tweak):
    """Turns system units off; "off" brings back exactly the ones that were enabled."""
    units: tuple = ()
    root: bool = True

    def current(self):
        return "   ".join(f"{u.removesuffix('.service')} {unit_state(u)}" for u in self.units
                         if unit_state(u) != "not-found")

    def is_on(self):
        return (STATE / f"{self.id}.units").exists()

    def native(self):
        return all(unit_state(u) in ("disabled", "masked", "not-found", "static") for u in self.units)

    def unavailable(self):
        return "" if any(unit_state(u) != "not-found" for u in self.units) else "Not installed here"


@dataclass
class RootFile(Tweak):
    """A config file the helper writes; on = the file exists (with Grimoire's mark)."""
    path: str = ""
    show: object = None            # () -> str for current()
    root: bool = True

    def current(self):
        return self.show() if self.show else ""

    def is_on(self):
        return has_mark(Path(self.path))


class Zram(Tweak):
    def current(self):
        swaps = Path("/proc/swaps").read_text().splitlines()[1:]
        names = ", ".join(f"{Path(s.split()[0]).name} {human(int(s.split()[2]) * 1024)}" for s in swaps)
        return f"swap: {names or 'none'}   swappiness {sysctl('vm.swappiness')}"

    def is_on(self):
        p = Path("/etc/systemd/zram-generator.conf")
        return has_mark(p) and "[zram0]" in p.read_text()

    def native(self):
        p = Path("/etc/systemd/zram-generator.conf")
        return "zram" in Path("/proc/swaps").read_text() or (p.exists() and not has_mark(p))


class Earlyoom(Tweak):
    def current(self):
        on = [n for n in ("earlyoom", "systemd-oomd") if unit_active(n + ".service")]
        return f"running: {', '.join(on)}" if on else "no early out-of-memory guard running"

    def is_on(self):
        return (STATE / "earlyoom.units").exists()

    def native(self):
        return unit_active("earlyoom.service") or unit_active("systemd-oomd.service")


# ---------------------------------------------------------------- tweaks you own (no password)
class PowerProfile(Tweak):
    def current(self):
        return f"profile {sh('powerprofilesctl', 'get') or '?'}"

    def is_on(self):
        return self.id in load_saved()["orig"] and sh("powerprofilesctl", "get") == "performance"

    def native(self):
        return sh("powerprofilesctl", "get") == "performance"

    def unavailable(self):
        return "" if shutil.which("powerprofilesctl") else "power-profiles-daemon isn't installed"

    def enable(self, saved):
        saved["orig"].setdefault(self.id, sh("powerprofilesctl", "get") or "balanced")
        _check(["powerprofilesctl", "set", "performance"])

    def disable(self, saved):
        _check(["powerprofilesctl", "set", saved["orig"].pop(self.id, "balanced")])


@dataclass
class KdeKey(Tweak):
    file: str = ""
    kgroup: str = ""
    key: str = ""
    value: str = ""
    then: tuple = ()               # command to run after a change (e.g. tell KWin)
    good: object = None            # (live value) -> bool: already as good without Grimoire

    def current(self):
        return f"{self.key} {kread(self.file, self.kgroup, self.key) or 'default'}"

    def is_on(self):
        return self.id in load_saved()["orig"] and kread(self.file, self.kgroup, self.key) == self.value

    def native(self):
        live = kread(self.file, self.kgroup, self.key)
        return live == self.value or bool(self.good and self.good(live))

    def enable(self, saved):
        saved["orig"].setdefault(self.id, kread(self.file, self.kgroup, self.key))
        _check(["kwriteconfig6", "--notify", "--file", self.file, "--group", self.kgroup, "--key", self.key, self.value])
        if self.then:
            sh(*self.then)

    def disable(self, saved):
        old = saved["orig"].pop(self.id, "")
        args = ["kwriteconfig6", "--notify", "--file", self.file, "--group", self.kgroup, "--key", self.key]
        _check(args + ([old] if old else ["--delete"]))
        if self.then:
            sh(*self.then)


class Baloo(Tweak):
    @staticmethod
    def indexing() -> bool:
        if not shutil.which("balooctl6"):
            return False
        r = subprocess.run(["balooctl6", "status"], capture_output=True, text=True)
        return "disabled" not in (r.stdout + r.stderr)

    def current(self):
        return "indexing " + ("on" if self.indexing() else "off")

    def is_on(self):
        return self.id in load_saved()["orig"] and not self.indexing()

    def native(self):
        return not self.indexing()

    def unavailable(self):
        return "" if shutil.which("balooctl6") else "Baloo isn't installed"

    def enable(self, saved):
        saved["orig"][self.id] = "on"
        _check(["balooctl6", "disable"])

    def disable(self, saved):
        saved["orig"].pop(self.id, None)
        _check(["balooctl6", "enable"])


class ShaderCache(Tweak):
    file = ENV_D / "90-grimoire-optimizel-shadercache.conf"

    def current(self):
        size = os.environ.get("__GL_SHADER_DISK_CACHE_SIZE")
        return f"cache limit {human(int(size)) if size and size.isdigit() else 'driver default'}"

    def is_on(self):
        return has_mark(self.file)

    def unavailable(self):
        return "" if Path("/proc/driver/nvidia").exists() else "Only for NVIDIA graphics"

    def enable(self, saved):
        ENV_D.mkdir(parents=True, exist_ok=True)
        self.file.write_text(f"# {MARK}: bigger NVIDIA shader cache, turn it off in OptimizeL\n"
                             "__GL_SHADER_DISK_CACHE_SIZE=10737418240\n__GL_SHADER_DISK_CACHE_SKIP_CLEANUP=1\n")

    def disable(self, saved):
        if has_mark(self.file):
            self.file.unlink()


@dataclass
class Autostart(Tweak):
    """Stops a login app via the XDG way: a ~/.config/autostart copy with Hidden=true (yours wins over
    /etc/xdg). Off removes that copy, only if Grimoire wrote it."""
    entry: str = ""
    user_unit: str = ""            # a systemd --user unit that starts the same thing
    only_on_metal: bool = False    # pointless outside a virtual machine

    @property
    def mine(self) -> Path:
        return AUTOSTART / f"{self.entry}.desktop"

    def current(self):
        return "starts at login" if not (self.is_on() or self.native()) else "doesn't start at login"

    def is_on(self):
        return has_mark(self.mine)

    def native(self):
        if not self.mine.exists():
            return False
        text = self.mine.read_text(errors="replace")
        return "Hidden=true" in text or "X-KDE-autostart-enabled=false" in text

    def unavailable(self):
        if not Path(f"/etc/xdg/autostart/{self.entry}.desktop").exists():
            return "Not installed here"
        if self.only_on_metal and sh("systemd-detect-virt") not in ("none", ""):
            return "This is a virtual machine, so it's needed"
        if self.mine.exists() and not self.is_on() and not self.native():
            return "You've customized this entry yourself"
        return ""

    def enable(self, saved):
        AUTOSTART.mkdir(parents=True, exist_ok=True)
        self.mine.write_text(f"# {MARK}: turn this off in OptimizeL to start {self.title.lower()} again\n"
                             "[Desktop Entry]\nType=Application\nHidden=true\n")
        if self.user_unit:
            sh("systemctl", "--user", "disable", "--now", self.user_unit)

    def disable(self, saved):
        if has_mark(self.mine):
            self.mine.unlink()
        if self.user_unit and unit_state(self.user_unit, user=True) == "disabled":
            sh("systemctl", "--user", "enable", self.user_unit)


def _check(args: list[str]):
    r = subprocess.run(args, capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError((r.stderr or r.stdout).strip() or f"{args[0]} failed")


def _apt_cache() -> str:
    try:
        n = sum(e.stat().st_size for e in os.scandir("/var/cache/apt/archives") if e.name.endswith(".deb"))
    except OSError:
        return ""
    return f"package cache {human(n)}"


def _journal() -> str:
    out = sh("journalctl", "--disk-usage")
    return "logs " + out.split("take up ")[-1].split(" in")[0] if "take up" in out else ""


# ---------------------------------------------------------------- the catalog
TWEAKS: list[Tweak] = [
    PowerProfile("performance", "Power", "Performance power profile",
                 "Tells the CPU to boost sooner and stay at high clocks instead of saving watts. The biggest single "
                 "win on a desktop; KDE's battery applet shows the same switch.", "profile performance"),
    Sysctl("nmi", "Power", "Turn off the NMI watchdog",
           "A kernel lockup detector that fires a timer interrupt on every core and holds a CPU performance "
           "counter. Desktops don't need it.", "nmi_watchdog 0", values={"kernel.nmi_watchdog": 0}),

    Zram("zram", "Memory", "Compressed swap in RAM (zram)",
         "Adds up to 8 GB of zstd-compressed swap that lives in RAM, so idle tabs and apps get squeezed instead "
         "of pushed to disk. Keeps games and the desktop smooth when memory fills up.",
         "zram up to 8 GB, swappiness 180", root=True, installs="systemd-zram-generator"),
    Earlyoom("earlyoom", "Memory", "Stay responsive when RAM runs out",
             "earlyoom closes the single biggest app when memory and swap are almost gone, instead of the whole "
             "desktop freezing for minutes.", "earlyoom running", root=True, installs="earlyoom"),
    Sysctl("vfscache", "Memory", "Keep folder info cached",
           "Holds directory and file metadata in RAM longer, so file browsing and searches stay fast. Cheap "
           "with 16 GB or more.", "vfs_cache_pressure 50", values={"vm.vfs_cache_pressure": 50}),
    Sysctl("dirty", "Memory", "Smoother big file copies",
           "Starts writing to disk after 128 MB instead of letting gigabytes pile up in RAM, which avoids the "
           "long stall at the end of a big copy.", "write-back at 128 / 256 MB",
           values={"vm.dirty_bytes": 268435456, "vm.dirty_background_bytes": 134217728},
           show=("vm.dirty_ratio", "vm.dirty_background_ratio")),

    Units("waitonline", "Storage & boot", "Reach the login screen sooner",
          "Stops boot from waiting for the network to be fully up (often 5 to 10 s). Wi-Fi and Ethernet "
          "still connect right after.", "wait-online disabled", when="restart",
          units=("NetworkManager-wait-online.service",)),
    RootFile("aptcache", "Storage & boot", "Don't hoard downloaded packages",
             "Deletes installer .deb files once updates are installed (apt downloads them again if ever needed). "
             "Frees the cache now and keeps it empty.", "cache cleared after installs",
             path="/etc/apt/apt.conf.d/99grimoire-optimizel", show=_apt_cache),
    RootFile("journal", "Storage & boot", "Cap system logs at 200 MB",
             "Keeps the system journal small, so log writes and boot-time log loading stay light.",
             "journal max 200 MB", path="/etc/systemd/journald.conf.d/99-grimoire-optimizel.conf", show=_journal),
    RootFile("maint", "Storage & boot", "Background jobs yield to you",
             "Update checks, firmware checks, log rotation and disk scrubs run at the lowest CPU priority, so "
             "they never cause stutter while you play or work.", "nice 19, low CPU weight",
             path="/etc/systemd/system/apt-daily.service.d/grimoire-optimizel.conf",
             show=lambda: "update checks at " + ("low" if Path("/etc/systemd/system/apt-daily.service.d/"
                                                               "grimoire-optimizel.conf").exists() else "normal")
             + " priority"),

    Sysctl("bbr", "Network", "BBR congestion control",
           "Google's BBR keeps uploads fast and latency low when the connection is busy (streaming, uploads, "
           "game downloads), paired with the fair-queue scheduler.", "bbr + fq", when="restart",
           values={"net.ipv4.tcp_congestion_control": "bbr", "net.core.default_qdisc": "fq"}),

    Units("iscsi", "Services", "Turn off iSCSI network disks",
          "Server-style network storage. It also makes boot wait for the network. Nothing on a home PC uses it.",
          "iscsi disabled", units=("open-iscsi.service", "iscsid.socket", "iscsid.service")),
    Units("cupsbrowsed", "Services", "Stop auto-adding network printers",
          "cups-browsed constantly scans the network for printers to add. Printers you've set up keep working.",
          "cups-browsed disabled", recommended=False, units=("cups-browsed.service",)),

    Autostart("discover", "Startup apps", "Discover update notifier",
              "Checks for updates in the background all session. Security updates still install automatically; "
              "open Discover when you want app updates.", "doesn't start", when="logout",
              entry="org.kde.discover.notifier"),
    Autostart("spice", "Startup apps", "Virtual machine guest agent",
              "spice-vdagent only does something inside a virtual machine. This PC is real hardware.",
              "doesn't start", when="logout", entry="spice-vdagent", user_unit="spice-vdagent.service",
              only_on_metal=True),
    Autostart("geoclue", "Startup apps", "Location agent",
              "Shares your location with apps that ask. Unneeded on a desktop unless an app uses it.",
              "doesn't start", when="logout", entry="geoclue-demo-agent"),
    Autostart("kup", "Startup apps", "Kup backup daemon",
              "Background backup service. Leave it on if you use Kup backups.", "doesn't start", when="logout",
              recommended=not (CONFIG.parent / "kuprc").exists(), entry="kup-daemon"),
    Autostart("nvsettings", "Startup apps", "NVIDIA settings loader",
              "Re-applies X11 settings from nvidia-settings at login. On Wayland it does nothing.",
              "doesn't start", when="logout", entry="nvidia-settings-autostart"),
    Autostart("kdeconnect", "Startup apps", "KDE Connect",
              "Phone integration (notifications, file sharing). Leave it on if you pair your phone.",
              "doesn't start", when="logout", recommended=False, entry="org.kde.kdeconnect.daemon"),

    KdeKey("animations", "Desktop", "Snappier animations",
           "Plays window, menu and desktop animations twice as fast, so everything feels more immediate.",
           "animation speed 2x", file="kdeglobals", kgroup="KDE", key="AnimationDurationFactor", value="0.5",
           then=("qdbus6", "org.kde.KWin", "/KWin", "reconfigure"),
           good=lambda v: v.replace(".", "", 1).isdigit() and float(v) <= 0.5),
    KdeKey("emptysession", "Desktop", "Start each login fresh",
           "Logs in to an empty desktop instead of reopening the apps from last time, so login is quicker.",
           "empty session", when="logout", recommended=False, file="ksmserverrc", kgroup="General",
           key="loginMode", value="emptySession"),
    Baloo("baloo", "Desktop", "Turn off file indexing",
          "Baloo reads every file to build a search index, which costs disk and CPU time. Name search in "
          "KRunner and FileL still works.", "indexing off"),

    Sysctl("splitlock", "Gaming", "Don't throttle split-lock games",
           "Some Windows games (via Proton) trip the kernel's split-lock trap, which slows them down on "
           "purpose. Valve turns this off on the Steam Deck.", "split_lock_mitigate 0",
           values={"kernel.split_lock_mitigate": 0}),
    ShaderCache("shadercache", "Gaming", "Bigger NVIDIA shader cache",
                "Raises the driver's shader cache to 10 GB and stops it pruning, so games stop recompiling "
                "shaders (the stutter you get in new areas).", "10 GB, no cleanup", when="logout"),
]

BY_ID = {t.id: t for t in TWEAKS}


# ---------------------------------------------------------------- "already good" checks
def checks() -> dict[str, list[str]]:
    """Things the scan found already set the fast way, per group (shown so you know they were looked at)."""
    out: dict[str, list[str]] = {g: [] for g in GROUPS}
    for dev in Path("/sys/block").glob("nvme*"):
        if "[none]" in (dev / "queue/scheduler").read_text():
            out["Storage & boot"].append(f"{dev.name} uses the \"none\" I/O scheduler, the fastest for NVMe")
    if unit_state("fstrim.timer") == "enabled":
        out["Storage & boot"].append("Weekly TRIM keeps the SSD fast")
    grub = Path("/etc/default/grub").read_text() if Path("/etc/default/grub").exists() else ""
    if "GRUB_TIMEOUT=0" in grub:
        out["Storage & boot"].append("Boot menu is skipped (no countdown)")
    try:
        if int(Path("/sys/kernel/mm/lru_gen/enabled").read_text(), 16):
            out["Memory"].append("Multi-gen LRU picks what to evict from RAM smartly")
    except (OSError, ValueError):
        pass
    if "[madvise]" in Path("/sys/kernel/mm/transparent_hugepage/enabled").read_text():
        out["Memory"].append("Huge pages only for apps that ask (no random stalls)")
    if sysctl("kernel.sched_autogroup_enabled") == "1":
        out["Power"].append("Autogroup scheduling keeps the desktop responsive under load")
    if unit_active("thermald.service"):
        out["Power"].append("thermald manages CPU temperature")
    if (sysctl("vm.max_map_count") or "0").isdigit() and int(sysctl("vm.max_map_count") or 0) >= 1048576:
        out["Gaming"].append("vm.max_map_count is high enough for big games")
    if shutil.which("gamemoded"):
        out["Gaming"].append("GameMode is installed (launch games with gamemoderun %command%)")
    if "cap_sys_nice" in sh("getcap", "/usr/bin/kwin_wayland"):
        out["Desktop"].append("KWin draws frames at real-time priority")
    if sysctl("net.ipv4.tcp_fastopen") in ("1", "3"):
        out["Network"].append("TCP Fast Open is on")
    return out


# ---------------------------------------------------------------- applying
def pending_note(t: Tweak, saved: dict) -> str:
    """'After restart' / 'After log out' while a change is still waiting on one."""
    mark = saved["pending"].get(t.id)
    if not mark:
        return ""
    if (t.when == "restart" and mark == boot_id()) or (t.when == "logout" and mark == session_id()):
        return "Restart to finish" if t.when == "restart" else "Log out to finish"
    return ""


def run_root(args: list[str]):
    """root-helper.sh through pkexec: one password prompt for the whole batch."""
    r = subprocess.run(["pkexec", "/usr/bin/bash", str(HELPER), *args], capture_output=True, text=True)
    if r.returncode == 126:
        raise RuntimeError("cancelled")
    if r.returncode:
        msg = (r.stderr or r.stdout).strip().splitlines()
        raise RuntimeError(msg[-1] if msg else f"helper failed ({r.returncode})")


def apply(changes: dict[str, bool], root_runner=run_root) -> list[str]:
    """Turn tweaks on (True) or off (False). Root ones go to root_runner(args) in one batch. Returns problems."""
    saved = load_saved()
    problems = []
    root_args = []
    for tid, on in changes.items():
        t = BY_ID[tid]
        if t.root:
            root_args += ["on" if on else "off", tid]
            continue
        try:
            (t.enable if on else t.disable)(saved)
        except (RuntimeError, OSError) as e:
            problems.append(f"{t.title}: {e}")
    root_ok = True
    if root_args:
        try:
            root_runner(root_args)
        except RuntimeError as e:
            root_ok = False
            problems.append("You cancelled the password prompt" if str(e) == "cancelled" else f"System changes: {e}")
    for tid in changes:
        t = BY_ID[tid]
        failed = not root_ok if t.root else any(p.startswith(t.title + ":") for p in problems)
        if t.when != "now" and not failed:
            saved["pending"][tid] = boot_id() if t.when == "restart" else session_id()
    save_saved(saved)
    return problems
