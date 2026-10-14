# SPDX-License-Identifier: GPL-3.0-or-later
"""The kinds of tweak OptimizeL has, and the small readers they use. Every tweak is an on/off switch whose "on"
lives in persistent config (sysctl.d, tmpfiles.d, udev rules, modprobe.d, GRUB, systemd, KDE config, autostart
overrides) so it survives restarts, and whose "off" restores exactly what was there before. System tweaks are
done by root-helper.sh (one pkexec prompt per batch); the rest run as you.

A tweak reports one of four states: "on" (Grimoire's change is in place), "off", "native" (the system is
already set that way without Grimoire, so there's nothing to do) or "na" (doesn't apply to this machine).

OPTIMIZEL_ROOT=<sandbox> makes the Python side look for the helper's files there too (for tests only).
"""
import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from grimoire.fsutil import human
from grimoire.paths import CONFIG, DATA

HELPER = Path(__file__).with_name("root-helper.sh")
ROOT = os.environ.get("OPTIMIZEL_ROOT", "")
ETC = Path(ROOT + "/etc")
STATE = Path(ROOT + "/var/lib/grimoire-optimizel")   # root helper's saved originals
SAVED = DATA / "optimizel.json"                       # your-side originals + changes waiting on a restart/log out
AUTOSTART = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "autostart"
ENV_D = CONFIG.parent / "environment.d"
MARK = "Grimoire OptimizeL"

WHEN = {"now": "Instant", "restart": "After restart", "logout": "After log out"}


# ---------------------------------------------------------------- small readers
def sh(*args: str) -> str:
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=10).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return ""


def read(path) -> str:
    try:
        return Path(path).read_text(errors="replace").strip()
    except OSError:
        return ""


def choice(path) -> str:
    """A sysfs value, with the [selected] one picked out of lists like "always [madvise] never"."""
    v = read(path)
    m = re.search(r"\[([^]]+)\]", v)
    return m.group(1) if m else v


def sysctl(key: str) -> str:
    return " ".join(read(Path("/proc/sys", key.replace(".", "/"))).split())


def unit_state(unit: str, user=False) -> str:
    """enabled / disabled / static / masked / not-found."""
    return sh("systemctl", *(["--user"] if user else []), "is-enabled", unit) or "not-found"


def unit_active(unit: str) -> bool:
    return sh("systemctl", "is-active", unit) == "active"


def kread(file: str, group: str, key: str) -> str:
    return sh("kreadconfig6", "--file", file, "--group", group, "--key", key)


def boot_id() -> str:
    return read("/proc/sys/kernel/random/boot_id")


def session_id() -> str:
    return f"{boot_id()}:{os.environ.get('XDG_SESSION_ID', '')}"


def cmdline() -> list[str]:
    return read("/proc/cmdline").split()


def nv_param(name: str) -> str:
    """A loaded NVIDIA driver option, e.g. InitializeSystemMemoryAllocations -> "1"."""
    for line in read("/proc/driver/nvidia/params").splitlines():
        k, _, v = line.partition(":")
        if k.strip() == name:
            return v.strip().strip('"')
    return ""


def disks() -> list[Path]:
    """Physical block devices that have an I/O scheduler (no loop, zram or device-mapper)."""
    return sorted(d for d in Path("/sys/block").iterdir() if (d / "device").exists() and (d / "queue/scheduler").exists())


def disk_kind(d: Path) -> str:
    """nvme / ssd / hdd."""
    if d.name.startswith("nvme"):
        return "nvme"
    return "hdd" if read(d / "queue/rotational") == "1" else "ssd"


def is_desktop() -> bool:
    """SMBIOS chassis: desktop, tower, mini PC, all-in-one... (thermald and friends matter on laptops)."""
    t = read("/sys/class/dmi/id/chassis_type")
    return t.isdigit() and int(t) in (3, 4, 5, 6, 7, 13, 15, 16, 24, 35, 36)


def has_battery() -> bool:
    """A battery that powers this PC (not a wireless mouse's, which has scope Device)."""
    for p in Path("/sys/class/power_supply").glob("*"):
        if read(p / "type") == "Battery" and read(p / "scope") != "Device":
            return True
    return False


def nvidia() -> bool:
    return Path("/proc/driver/nvidia").exists()


def gpu_count() -> int:
    return len({read(p) for p in Path("/sys/class/drm").glob("card[0-9]*/device/uevent")
                if "PCI_SLOT_NAME" in read(p)})


def load_saved() -> dict:
    try:
        d = json.loads(SAVED.read_text())
    except (OSError, ValueError):
        d = {}
    for k in ("orig", "pending"):
        d.setdefault(k, {})
    return d


def save_saved(d: dict):
    tmp = SAVED.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, indent=1))
    tmp.replace(SAVED)


def has_mark(p: Path) -> bool:
    try:
        return MARK in p.read_text(errors="replace")
    except OSError:
        return False


def _check(args: list[str]):
    r = subprocess.run(args, capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError((r.stderr or r.stdout).strip() or f"{args[0]} failed")


# ---------------------------------------------------------------- the base
@dataclass
class Tweak:
    id: str
    group: str
    title: str
    why: str                       # what it does, in plain words
    target: str                    # what "on" sets, in words (shown as "now → target")
    when: str = "now"              # now / restart / logout
    recommended: bool = True       # part of the "Recommended" profile (Safe tier only)
    installs: str = ""             # package the first "on" may install
    root: bool = False
    tier: str = "Safe"             # Safe / Aggressive
    gain: str = ""                 # the expected gain, on this kind of hardware
    risk: str = ""                 # what can go wrong (every Aggressive tweak has one)
    in_max: bool = True            # part of "Max performance" (False for ones that only remove features)
    power: bool = False            # costs power or heat: undone by the Battery profile
    skip: object = None            # () -> reason this doesn't apply here, or ""
    already: object = None         # () -> True when the system is already set this way without Grimoire

    def current(self) -> str: return ""
    def goal(self) -> str: return self.target
    def is_on(self) -> bool: return False
    def native(self) -> bool: return False
    def unavailable(self) -> str: return ""
    def waiting(self) -> bool | None:
        """True while it's on but not live yet (needs a restart), when the tweak can tell; None if it can't."""
        return None
    def enable(self, saved: dict): raise NotImplementedError     # user-side tweaks (and user_side root ones)
    def disable(self, saved: dict): raise NotImplementedError
    user_side = False              # a root tweak that also has a part done as you, after the helper ran

    def reason(self) -> str:
        return (self.skip() if self.skip else "") or self.unavailable()

    def state(self) -> str:
        if self.is_on():
            return "on"
        if self.reason():
            return "na"
        return "native" if self.native() or bool(self.already and self.already()) else "off"


# ---------------------------------------------------------------- system tweaks (root helper)
@dataclass
class Sysctl(Tweak):
    values: dict = field(default_factory=dict)
    show: tuple = ()               # keys to show instead of values' keys
    at_least: bool = False         # native when every live value is already >= ours
    root: bool = True

    @property
    def file(self) -> Path:
        return ETC / f"sysctl.d/99-grimoire-optimizel-{self.id}.conf"

    def current(self):
        return "   ".join(f"{k.split('.')[-1]} {sysctl(k) or '?'}" for k in (self.show or self.values))

    def is_on(self):
        return self.file.exists()

    def native(self):
        if self.at_least:
            return all(sysctl(k).isdigit() and int(sysctl(k)) >= int(v) for k, v in self.values.items())
        return all(sysctl(k) == str(v) for k, v in self.values.items())

    def unavailable(self):
        return "" if all(sysctl(k) for k in self.values) else "Your kernel or CPU doesn't have this setting"


@dataclass
class Sysfs(Tweak):
    """Kernel knobs under /sys/kernel/mm, kept across boots by a tmpfiles.d line."""
    values: dict = field(default_factory=dict)      # path -> value
    root: bool = True

    @property
    def file(self) -> Path:
        return ETC / f"tmpfiles.d/grimoire-optimizel-{self.id}.conf"

    def current(self):
        return "   ".join(f"{Path(p).name} {choice(p) or '?'}" for p in self.values)

    def is_on(self):
        return has_mark(self.file)

    def native(self):
        return all(choice(p) == str(v) for p, v in self.values.items())

    def unavailable(self):
        return "" if all(Path(p).exists() for p in self.values) else "Your kernel doesn't have this setting"


@dataclass
class Udev(Tweak):
    """A per-disk queue setting, chosen by disk type and kept by a udev rule (also for disks plugged in later)."""
    attr: str = ""                 # queue/<attr>
    pick: object = None            # (kind: nvme/ssd/hdd) -> the value we want
    root: bool = True

    @property
    def file(self) -> Path:
        return ETC / f"udev/rules.d/60-grimoire-optimizel-{self.id}.rules"

    def current(self):
        return "   ".join(f"{d.name} {choice(d / 'queue' / self.attr)}" for d in disks())

    def is_on(self):
        return has_mark(self.file)

    def native(self):
        return all(choice(d / "queue" / self.attr) == self.pick(disk_kind(d)) for d in disks())

    def unavailable(self):
        if not disks():
            return "No disks found"
        if self.attr == "scheduler":
            for d in disks():
                if self.pick(disk_kind(d)) not in read(d / "queue/scheduler") and disk_kind(d) != "hdd":
                    return f"Your kernel doesn't offer {self.pick(disk_kind(d))} for {d.name}"
        return ""

    def goal(self):
        return "   ".join(f"{d.name} {self.pick(disk_kind(d))}" for d in disks())


@dataclass
class KernelArg(Tweak):
    """A kernel boot option, added through /etc/default/grub.d and update-grub. Live once you restart."""
    arg: str = ""
    live: object = None            # () -> the live value to show
    when: str = "restart"
    root: bool = True

    @property
    def file(self) -> Path:
        return ETC / f"default/grub.d/99-grimoire-optimizel-{self.id}.cfg"

    def current(self):
        return self.live() if self.live else ("in use" if self.arg in cmdline() else "not set")

    def is_on(self):
        return has_mark(self.file)

    def native(self):
        return self.arg in cmdline()

    def waiting(self):
        return self.is_on() and self.arg not in cmdline()

    def unavailable(self):
        if not shutil.which("update-grub") or not Path("/etc/default/grub").exists():
            return "This PC doesn't boot with GRUB"
        key = self.arg.split("=")[0]
        if any(a.split("=")[0] == key for a in cmdline()) and self.arg not in cmdline():
            return f"You've set {key} yourself on the boot line"
        return ""


@dataclass
class Modprobe(Tweak):
    """A driver option in modprobe.d (and the initramfs). Live once you restart."""
    param: str = ""                # NVIDIA param name as /proc/driver/nvidia/params shows it
    value: str = ""
    when: str = "restart"
    root: bool = True

    @property
    def file(self) -> Path:
        return ETC / f"modprobe.d/99-grimoire-optimizel-{self.id}.conf"

    def current(self):
        return f"{self.param} {nv_param(self.param) or '?'}"

    def is_on(self):
        return has_mark(self.file)

    def native(self):
        return nv_param(self.param) == self.value

    def waiting(self):
        return self.is_on() and nv_param(self.param) != self.value

    def unavailable(self):
        if not nvidia():
            return "Only for NVIDIA graphics"
        return "" if nv_param(self.param) else "Your NVIDIA driver doesn't have this option"


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
        return has_mark(Path(ROOT + self.path))


class Zram(Tweak):
    def current(self):
        swaps = read("/proc/swaps").splitlines()[1:]
        names = ", ".join(f"{Path(s.split()[0]).name} {human(int(s.split()[2]) * 1024)}" for s in swaps)
        return f"swap: {names or 'none'}   swappiness {sysctl('vm.swappiness')}"

    def is_on(self):
        p = ETC / "systemd/zram-generator.conf"
        return has_mark(p) and "[zram0]" in read(p)

    def native(self):
        p = ETC / "systemd/zram-generator.conf"
        return "zram" in read("/proc/swaps") or (p.exists() and not has_mark(p))


class Earlyoom(Tweak):
    def current(self):
        on = [n for n in ("earlyoom", "systemd-oomd") if unit_active(n + ".service")]
        return f"running: {', '.join(on)}" if on else "no early out-of-memory guard running"

    def is_on(self):
        return (STATE / "earlyoom.units").exists()

    def native(self):
        return unit_active("earlyoom.service") or unit_active("systemd-oomd.service")


class GpuPower(Tweak):
    """NVIDIA board power limit at the card's maximum, re-applied at boot by a small systemd unit."""
    @staticmethod
    def limits() -> tuple[float, float, float]:
        out = sh("nvidia-smi", "--query-gpu=power.limit,power.default_limit,power.max_limit",
                 "--format=csv,noheader,nounits").splitlines()
        try:
            cur, dflt, mx = (float(x) for x in out[0].split(","))
            return cur, dflt, mx
        except (IndexError, ValueError):
            return 0.0, 0.0, 0.0

    def current(self):
        cur, dflt, mx = self.limits()
        return f"power limit {cur:.0f} W (default {dflt:.0f}, max {mx:.0f})" if mx else "power limit ?"

    def is_on(self):
        return has_mark(ETC / "systemd/system/grimoire-optimizel-gpupower.service")

    def native(self):
        cur, _, mx = self.limits()
        return bool(mx) and cur >= mx

    def unavailable(self):
        if not nvidia() or not shutil.which("nvidia-smi"):
            return "Only for NVIDIA graphics"
        cur, dflt, mx = self.limits()
        if not mx:
            return "The driver doesn't report a power limit"
        return "" if mx > dflt else "Your card's maximum is its default; nothing to raise"


class GameMode(Tweak):
    """Lets GameMode renice games: you join the gamemode group (root), and ~/.config/gamemode.ini asks for it."""
    user_side = True
    ini = CONFIG.parent / "gamemode.ini"

    @staticmethod
    def in_group() -> bool:
        return "gamemode" in sh("id", "-nG").split()

    def renice(self) -> str:
        m = re.search(r"^\s*renice\s*=\s*(\d+)", read(self.ini), re.M)
        return m.group(1) if m else "0"

    def current(self):
        return f"renice {self.renice()}   gamemode group {'yes' if self.in_group() else 'no'}"

    def is_on(self):
        return (STATE / "gamemode.group").exists()

    def native(self):
        return self.in_group() and self.renice() != "0"

    def unavailable(self):
        if not shutil.which("gamemoded"):
            return "GameMode isn't installed (sudo apt install gamemode)"
        if not Path("/etc/security/limits.d/10-gamemode.conf").exists():
            return "This GameMode doesn't allow renicing (no limits.d entry)"
        if self.ini.exists() and not has_mark(self.ini) and not self.is_on():
            return "You have your own gamemode.ini; set renice there"
        return ""

    def enable(self, saved):
        if self.ini.exists() and not has_mark(self.ini):
            return                                   # yours: leave it
        self.ini.write_text(f"; {MARK}: turn this off in OptimizeL\n[general]\nrenice=10\nioprio=0\n"
                            "softrealtime=off\ninhibit_screensaver=1\ndisable_splitlock=1\n")

    def disable(self, saved):
        if has_mark(self.ini):
            self.ini.unlink()


# ---------------------------------------------------------------- tweaks you own (no password)
class PowerProfile(Tweak):
    def current(self):
        epp = read("/sys/devices/system/cpu/cpu0/cpufreq/energy_performance_preference")
        return f"profile {sh('powerprofilesctl', 'get') or '?'}" + (f"   EPP {epp}" if epp else "")

    def is_on(self):
        return self.id in load_saved()["orig"] and sh("powerprofilesctl", "get") == "performance"

    def native(self):
        return sh("powerprofilesctl", "get") == "performance"

    def unavailable(self):
        if not shutil.which("powerprofilesctl"):
            return "power-profiles-daemon isn't installed"
        return "" if "performance" in sh("powerprofilesctl", "list") else "This PC has no performance profile"

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
    default: str = ""              # what KDE uses when the key isn't set
    then: tuple = ()               # command to run after a change (e.g. tell KWin)
    good: object = None            # (live value) -> bool: already as good without Grimoire

    def live(self) -> str:
        return kread(self.file, self.kgroup, self.key) or self.default

    def current(self):
        return f"{self.key} {self.live() or 'default'}"

    def is_on(self):
        return self.id in load_saved()["orig"] and kread(self.file, self.kgroup, self.key) == self.value

    def native(self):
        live = self.live()
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
        return f"cache limit {human(int(size)) if size and size.isdigit() else 'driver default (1 GB)'}"

    def is_on(self):
        return has_mark(self.file)

    def unavailable(self):
        return "" if nvidia() else "Only for NVIDIA graphics"

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
    in_max: bool = False

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
            saved["orig"].setdefault(self.id, unit_state(self.user_unit, user=True))
            sh("systemctl", "--user", "disable", "--now", self.user_unit)

    def disable(self, saved):
        if has_mark(self.mine):
            self.mine.unlink()
        # only re-enable a unit that was enabled before (turned on before this was saved: assume it was)
        was = saved["orig"].pop(self.id, "enabled")
        if self.user_unit and was == "enabled" and unit_state(self.user_unit, user=True) == "disabled":
            sh("systemctl", "--user", "enable", self.user_unit)
