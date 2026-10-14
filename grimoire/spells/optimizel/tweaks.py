# SPDX-License-Identifier: GPL-3.0-or-later
"""OptimizeL's catalog: every tweak on this PC as an on/off switch, the "already good" checks, and applying a
batch of changes. The kinds of tweak (and how each one is detected, persisted and undone) live in kinds.py.

Tiers: "Safe" tweaks can't break anything and are undone with one click. "Aggressive" ones give more but each
says what can go wrong; they're never in the Recommended profile.
"""
import os
import shutil
from pathlib import Path

from grimoire import roothelper
from grimoire.fsutil import human
from grimoire.paths import CONFIG
from grimoire.spells.optimizel.kinds import (  # noqa: F401  (WHEN, has_battery, load_saved: used via tweaks.*)
    ETC, HELPER, STATE, WHEN, Autostart, Baloo, Earlyoom, GameMode, GpuPower, KdeKey, KernelArg, Modprobe,
    PowerProfile, RootFile, ShaderCache, Sysctl, Sysfs, Tweak, Udev, Units, Zram, boot_id, choice, cmdline, disks,
    gpu_count, has_battery, is_desktop, load_saved, nv_param, nvidia, read, save_saved, session_id, sh, sysctl,
    unit_active, unit_state)

GROUPS = ["CPU & power", "Memory", "Storage", "Boot", "Network", "Graphics", "Gaming", "Desktop", "Services",
          "Startup apps"]
TIERS = ("Safe", "Aggressive")


def _apt_cache() -> str:
    try:
        n = sum(e.stat().st_size for e in os.scandir("/var/cache/apt/archives") if e.name.endswith(".deb"))
    except OSError:
        return ""
    return f"package cache {human(n)}"


def _journal() -> str:
    out = sh("journalctl", "--disk-usage")
    return "logs " + out.split("take up ")[-1].split(" in")[0] if "take up" in out else ""


def _stop_timeout() -> str:
    return "stop timeout " + (sh("systemctl", "show", "-p", "DefaultTimeoutStopUSec", "--value") or "?")


def _mitigations() -> str:
    """How many CPU security mitigations are active (each costs a little on kernel entry/exit)."""
    vul = Path("/sys/devices/system/cpu/vulnerabilities")
    active = [p.name for p in sorted(vul.glob("*")) if read(p).startswith("Mitigation")]
    off = "mitigations=off" in cmdline()
    return "mitigations off" if off else f"{len(active)} active: {', '.join(active)}"


def _no_mitigations() -> str:
    vul = Path("/sys/devices/system/cpu/vulnerabilities")
    if "mitigations=off" in cmdline():
        return ""
    return "" if any(read(p).startswith("Mitigation") for p in vul.glob("*")) else \
        "Your CPU isn't affected by anything that needs a slow mitigation"


def _apst() -> str:
    v = read("/sys/module/nvme_core/parameters/default_ps_max_latency_us")
    return f"NVMe power-state latency allowed {v} µs" + (" (power saving off)" if v == "0" else "")


def _fast_link() -> bool:
    """Wired at 1 Gb/s or more: where 4 MB socket buffers start to cap single uploads."""
    for p in Path("/sys/class/net").glob("*"):
        if (p / "device").exists() and read(p / "operstate") == "up" and read(p / "speed").lstrip("-").isdigit() \
                and int(read(p / "speed")) >= 1000:
            return True
    return False


def _maint() -> str:
    on = (ETC / "systemd/system/apt-daily.service.d/grimoire-optimizel.conf").exists()
    return f"update checks at {'low' if on else 'normal'} priority"


def _thermald_skip() -> str:
    return "" if is_desktop() else "Laptops need thermald to stay cool"


def _gpumanager_skip() -> str:
    if gpu_count() != 1:
        return "This PC has more than one GPU, which is what gpu-manager is for"
    return ""


def _netdispatch_skip() -> str:
    return "systemd-networkd is in use, which this serves" if unit_active("systemd-networkd.service") else ""


def _baloo_skip() -> str:
    return "File indexing is off, so there's nothing to slim down" if Baloo.indexing() is False else ""


# ---------------------------------------------------------------- the catalog
TWEAKS: list[Tweak] = [
    # ------------------------------------------------ CPU & power
    PowerProfile("performance", "CPU & power", "Performance power profile",
                 "Tells the CPU to boost sooner and stay at high clocks instead of saving watts (on Intel it sets "
                 "every core's energy preference, EPP, to performance). KDE's battery applet shows the same switch.",
                 "profile performance", power=True,
                 gain="Faster clock ramp-up: snappier apps and fewer frame dips in games; 5 to 15% in short bursts."),
    Sysctl("nmi", "CPU & power", "Turn off the NMI watchdog",
           "A kernel lockup detector that fires a timer interrupt on every core and holds one CPU performance "
           "counter per core. Desktops don't need it.", "nmi_watchdog 0", values={"kernel.nmi_watchdog": 0},
           gain="One fewer periodic interrupt per core and a free performance counter (profilers can use it)."),
    Units("thermald", "CPU & power", "Turn off thermald on a desktop",
          "thermald is Intel's laptop cooling daemon. On a desktop the CPU protects itself in hardware, and "
          "thermald can only ever cap power. It also sits on the boot path.", "thermald disabled",
          units=("thermald.service",), skip=_thermald_skip,
          gain="Takes about 2 s off reaching the desktop here (it's on the boot critical chain), and nothing "
               "software-limits the CPU's power."),
    KernelArg("mitigations", "CPU & power", "Turn off CPU security mitigations",
              "Spectre-class fixes add work on every switch into and out of the kernel. Turning them off gets "
              "that time back.", "mitigations=off", arg="mitigations=off", live=_mitigations, tier="Aggressive",
              recommended=False, in_max=False, skip=_no_mitigations,
              gain="1 to 5% in system-call-heavy work (compiling, file scans, some games); see the syscall "
                   "benchmark.",
              risk="Real security cost: malicious code (a web page's JavaScript, a game mod) could read memory it "
                   "shouldn't. Never part of a profile; only use it if you understand that trade."),

    # ------------------------------------------------ Memory
    Zram("zram", "Memory", "Compressed swap in RAM (zram)",
         "Adds up to 8 GB of zstd-compressed swap that lives in RAM, so idle tabs and apps get squeezed instead "
         "of pushed to disk.", "zram up to 8 GB, swappiness 180", root=True, installs="systemd-zram-generator",
         gain="Roughly 3x more room before anything touches the disk; the desktop stays smooth when RAM fills."),
    Earlyoom("earlyoom", "Memory", "Stay responsive when RAM runs out",
             "earlyoom closes the single biggest app when memory and swap are almost gone, instead of the whole "
             "desktop freezing for minutes.", "earlyoom running", root=True, installs="earlyoom",
             gain="Seconds instead of minutes to recover from running out of memory."),
    Sysfs("mglru", "Memory", "Never evict what you just used",
          "Multi-gen LRU's thrashing guard: pages used in the last second can't be pushed out. If that can't be "
          "kept, the out-of-memory killer acts instead of the system crawling.", "min_ttl_ms 1000",
          values={"/sys/kernel/mm/lru_gen/min_ttl_ms": 1000},
          gain="No multi-second freezes under memory pressure (the kernel docs suggest 1000 ms for desktops)."),
    Sysctl("vfscache", "Memory", "Keep folder info cached",
           "Holds directory and file metadata in RAM longer, so file browsing, searches and game launchers that "
           "scan many files stay fast.", "vfs_cache_pressure 50", values={"vm.vfs_cache_pressure": 50},
           gain="Faster repeat folder scans; costs a few hundred MB at most, cheap with 16 GB or more."),
    Sysctl("dirty", "Memory", "Smoother big file copies",
           "With lots of RAM the kernel lets gigabytes of unwritten data pile up, then stalls everything to "
           "flush it. This starts writing at 128 MB and caps it at 256 MB.", "write-back at 128 / 256 MB",
           values={"vm.dirty_bytes": 268435456, "vm.dirty_background_bytes": 134217728},
           show=("vm.dirty_ratio", "vm.dirty_background_ratio", "vm.dirty_bytes"),
           gain="No long freeze at the end of a big copy or game install; copy speed itself is unchanged."),
    Sysctl("compaction", "Memory", "Fewer memory-housekeeping stalls",
           "Stops the kernel from defragmenting RAM in the background and from boosting reclaim after every "
           "fragmentation event. Both can cause latency spikes.",
           "proactiveness 0, boost 0", values={"vm.compaction_proactiveness": 0, "vm.watermark_boost_factor": 0},
           gain="Removes a source of random millisecond stalls (the kernel docs warn of them); plenty of RAM "
                "means it isn't needed."),
    Sysfs("thp", "Memory", "Huge pages for every app",
          "Lets every app use 2 MB memory pages instead of 4 KB ones, with defragmentation done in the background "
          "only, so page faults never stall on it.", "always, defer+madvise, max_ptes_none 409",
          values={"/sys/kernel/mm/transparent_hugepage/enabled": "always",
                  "/sys/kernel/mm/transparent_hugepage/defrag": "defer+madvise",
                  "/sys/kernel/mm/transparent_hugepage/khugepaged/max_ptes_none": 409},
          tier="Aggressive", recommended=False,
          gain="Fewer TLB misses: 2 to 10% in memory-heavy games, emulators and compilers.",
          risk="Apps can use noticeably more RAM (a 2 MB page for a little data); max_ptes_none 409 limits "
               "that. A few databases (Redis, MongoDB) say to keep huge pages off."),

    # ------------------------------------------------ Storage
    Udev("iosched", "Storage", "Right I/O scheduler for each disk",
         "NVMe drives are fastest with no scheduler at all, SATA SSDs with mq-deadline, hard drives with BFQ "
         "(keeps the desktop responsive during big copies). A udev rule picks it per disk, also for new disks.",
         "per disk type", attr="scheduler", pick=lambda k: {"nvme": "none", "ssd": "mq-deadline", "hdd": "bfq"}[k],
         gain="NVMe: lowest overhead per I/O. Hard drives: no desktop freezes while copying."),
    Udev("readahead", "Storage", "Bigger read-ahead for loading",
         "Reads 1 MB ahead (4 MB on hard drives) instead of 128 KB when a program reads a file in order, so "
         "game assets, videos and big files stream in larger chunks.", "1 MB (SSD) / 4 MB (HDD)",
         attr="read_ahead_kb", pick=lambda k: "4096" if k == "hdd" else "1024", recommended=False,
         gain="Faster sequential loads when a program reads with small buffers; see the disk benchmark. Little "
              "effect on random access."),
    KernelArg("nvmeapst", "Storage", "Keep the NVMe drive awake",
              "Stops the drive from dropping into deep power-saving states between bursts, which some drives "
              "take milliseconds to wake from.", "power saving off", arg="nvme_core.default_ps_max_latency_us=0",
              live=_apst, tier="Aggressive", recommended=False, power=True,
              skip=lambda: "" if any(d.name.startswith("nvme") for d in disks()) else "No NVMe drive",
              gain="Lower first-read latency after idle (fewer hitches when a game streams in a new area).",
              risk="The drive idles 1 to 2 W higher and runs warmer; on a laptop that costs battery."),
    RootFile("aptcache", "Storage", "Don't hoard downloaded packages",
             "Deletes installer .deb files once updates are installed (apt downloads them again if ever needed).",
             "cache cleared after installs", path="/etc/apt/apt.conf.d/99grimoire-optimizel", show=_apt_cache,
             gain="Frees the package cache now and keeps it empty (often hundreds of MB to GBs)."),
    RootFile("journal", "Storage", "Cap system logs at 200 MB",
             "Keeps the system journal small, so log writes and log loading stay light.",
             "journal max 200 MB", path="/etc/systemd/journald.conf.d/99-grimoire-optimizel.conf", show=_journal,
             gain="Up to 4 GB of disk back, and faster journal searches."),

    # ------------------------------------------------ Boot
    Units("waitonline", "Boot", "Reach the login screen sooner",
          "Stops boot from waiting for the network to be fully up. Wi-Fi and Ethernet still connect right after.",
          "wait-online disabled", when="restart", units=("NetworkManager-wait-online.service",),
          gain="Often 5 to 10 s off boot on machines where something waits for the network."),
    Units("gpumanager", "Boot", "Skip Ubuntu's GPU switcher check",
          "gpu-manager sorts out laptops with two GPUs before the login screen starts. With a single graphics "
          "card it finds nothing to do, every boot.", "gpu-manager disabled", when="restart",
          units=("gpu-manager.service",), skip=_gpumanager_skip,
          gain="About 0.4 s less before the login screen (it runs right before it).",
          risk="If you later add a second GPU, turn this back off."),
    RootFile("shutdown", "Boot", "Don't wait 90 s on stuck apps at shutdown",
             "When a service or app hangs while shutting down, systemd waits 90 s before killing it (\"A stop "
             "job is running...\"). This makes it 15 s.", "stop timeout 15 s",
             path="/etc/systemd/system.conf.d/99-grimoire-optimizel.conf", show=_stop_timeout,
             gain="Up to 75 s off a stuck shutdown or restart; no change when nothing hangs."),
    RootFile("maint", "Boot", "Background jobs yield to you",
             "Update checks, firmware checks, man page indexing, log rotation and disk scrubs run at the lowest "
             "CPU (and on SATA, disk) priority.", "nice 19, low CPU weight",
             path="/etc/systemd/system/apt-daily.service.d/grimoire-optimizel.conf", show=_maint,
             gain="They never cause stutter while you play or work; they just finish a bit later."),

    # ------------------------------------------------ Network
    Sysctl("bbr", "Network", "BBR congestion control",
           "Google's BBR keeps uploads fast and latency low when the connection is busy (streaming, uploads, "
           "game downloads), paired with the fair-queue scheduler.", "bbr + fq", when="restart",
           values={"net.ipv4.tcp_congestion_control": "bbr", "net.core.default_qdisc": "fq"},
           gain="Lower ping while the line is busy (no bufferbloat from your side) and faster uploads on lossy "
                "Wi-Fi."),
    Sysctl("netbuf", "Network", "Room for fast connections",
           "Lets one upload use a 32 MB window instead of 4 MB, and keeps a connection's speed after it sits "
           "idle (no slow restart between bursts).", "32 MB buffers, no idle slow-start",
           values={"net.core.rmem_max": 33554432, "net.core.wmem_max": 33554432,
                   "net.ipv4.tcp_wmem": "4096 65536 33554432", "net.ipv4.tcp_slow_start_after_idle": 0},
           show=("net.core.wmem_max", "net.ipv4.tcp_wmem", "net.ipv4.tcp_slow_start_after_idle"),
           recommended=_fast_link(),
           gain="A 4 MB window caps one upload at about 80 MB/s to a server 50 ms away; 32 MB lifts that past "
                "1 Gb/s. Matters on gigabit lines."),

    # ------------------------------------------------ Graphics
    ShaderCache("shadercache", "Graphics", "Bigger NVIDIA shader cache",
                "Raises the driver's shader cache from 1 GB to 10 GB and stops it pruning, so games stop "
                "recompiling shaders (the stutter you get in new areas).", "10 GB, no cleanup", when="logout",
                gain="No repeat shader-compile stutter after you've played a game once."),
    GpuPower("gpupower", "Graphics", "GPU power limit at its maximum",
             "Raises the graphics card's power limit from its default to the most the card's firmware allows, "
             "re-applied at every boot.", "max power limit", root=True, tier="Aggressive", recommended=False,
             power=True,
             gain="1 to 3% in GPU-bound games when the card hits its power limit (watch it in SystemL).",
             risk="More heat, fan noise and power draw. It stays within NVIDIA's allowed range, so no damage, but "
                  "a weak power supply could shut the PC off under full load."),
    Modprobe("nvmemclear", "Graphics", "Skip zeroing GPU system memory",
             "The NVIDIA driver clears every block of system RAM it hands to a program. Turning that off makes "
             "allocations (loading screens, alt-tab, video) cheaper.", "InitializeSystemMemoryAllocations 0",
             param="InitializeSystemMemoryAllocations", value="0", tier="Aggressive", recommended=False,
             gain="Small: less CPU time on GPU allocations, so loading and alt-tab hitches shrink. CachyOS "
                  "ships this by default.",
             risk="A program could see leftover data from memory another program used before. Low risk on a "
                  "single-user PC, but it is a security trade."),

    # ------------------------------------------------ Gaming
    Sysctl("splitlock", "Gaming", "Don't throttle split-lock games",
           "Some Windows games (via Proton) trip the kernel's split-lock trap, which slows them down on "
           "purpose. Valve turns this off on the Steam Deck.", "split_lock_mitigate 0",
           values={"kernel.split_lock_mitigate": 0},
           gain="Removes 10 ms pauses per hit in the affected games (a few go from stuttering to smooth)."),
    Sysctl("maxmap", "Gaming", "Enough memory maps for big games",
           "Some games (and Proton/DXVK) create hundreds of thousands of memory mappings and crash at the old "
           "65530 limit.", "max_map_count 1048576", values={"vm.max_map_count": 1048576}, at_least=True,
           gain="Fixes crashes and hitches in games like Hogwarts Legacy, Star Citizen and CS2."),
    GameMode("gamemode", "Gaming", "Let GameMode boost games",
             "Games started with gamemoderun %command% get a higher CPU and I/O priority. That needs a gamemode "
             "group with you in it (Ubuntu's package doesn't make one) and a gamemode.ini that asks for it.", "renice 10, ioprio 0",
             root=True, when="logout",
             gain="Games win the CPU against browsers, launchers and background updates: fewer stutters when "
                  "something else is busy."),

    # ------------------------------------------------ Desktop
    KdeKey("animations", "Desktop", "Snappier animations",
           "Plays window, menu and desktop animations twice as fast, so everything feels more immediate.",
           "animation speed 2x", file="kdeglobals", kgroup="KDE", key="AnimationDurationFactor", value="0.5",
           default="1", then=("qdbus6", "org.kde.KWin", "/KWin", "reconfigure"),
           good=lambda v: v.replace(".", "", 1).isdigit() and float(v) <= 0.5,
           gain="Half the wait on every window open, close and menu."),
    KdeKey("tearing", "Desktop", "Allow tearing in fullscreen games",
           "Lets KWin show a fullscreen game's frame the moment it's ready when the game asks for it (vsync "
           "off), instead of waiting for the next refresh.", "AllowTearing true", file="kwinrc",
           kgroup="Compositing", key="AllowTearing", value="true", default="true",
           then=("qdbus6", "org.kde.KWin", "/KWin", "reconfigure"),
           gain="Up to one refresh (4 ms at 240 Hz) less input lag in games with vsync off."),
    Baloo("baloo", "Desktop", "Turn off file indexing",
          "Baloo reads every file to build a search index, which costs disk and CPU time. Name search in "
          "KRunner and VaultL still works.", "indexing off",
          gain="No background disk and CPU load from indexing (heavy after big downloads)."),
    KdeKey("balooscope", "Desktop", "Index names only, not file contents",
           "If you keep Baloo on, this stops it reading inside every document; searching by name still works.",
           "only basic indexing", file="baloofilerc", kgroup="General", key="only basic indexing", value="true",
           default="false", skip=_baloo_skip,
           gain="Most of Baloo's CPU and disk cost goes away while name search keeps working."),
    KdeKey("emptysession", "Desktop", "Start each login fresh",
           "Logs in to an empty desktop instead of reopening the apps from last time.",
           "empty session", when="logout", recommended=False, in_max=False, file="ksmserverrc", kgroup="General",
           key="loginMode", value="emptySession",
           gain="Faster login: no apps relaunching at once."),

    # ------------------------------------------------ Services
    Units("iscsi", "Services", "Turn off iSCSI network disks",
          "Server-style network storage. It also makes boot wait for the network. Nothing on a home PC uses it.",
          "iscsi disabled", units=("open-iscsi.service", "iscsid.socket", "iscsid.service"),
          gain="Less boot work and no boot wait for the network."),
    Units("cupsbrowsed", "Services", "Stop auto-adding network printers",
          "cups-browsed constantly scans the network for printers to add. Printers you've set up keep working.",
          "cups-browsed disabled", recommended=False, in_max=False, units=("cups-browsed.service",),
          gain="One less always-running daemon and less network chatter."),
    Units("rsyslog", "Services", "Log once, not twice",
          "Ubuntu writes every log message twice: to the systemd journal and again to /var/log/syslog. "
          "journalctl (and SystemL) keep everything.", "rsyslog disabled", recommended=False, in_max=False,
          units=("rsyslog.service",),
          gain="Half the log writes to disk and one less daemon.",
          risk="/var/log/syslog stops growing; use journalctl to read logs."),
    Units("netdispatch", "Services", "Unused network event daemon",
          "networkd-dispatcher only reacts to systemd-networkd, which this PC doesn't use (NetworkManager runs "
          "the network).", "networkd-dispatcher disabled", units=("networkd-dispatcher.service",),
          skip=_netdispatch_skip,
          gain="About 0.3 s of boot work and a ~20 MB Python process gone."),

    # ------------------------------------------------ Startup apps
    Autostart("discover", "Startup apps", "Discover update notifier",
              "Checks for updates in the background all session. Security updates still install automatically; "
              "open Discover when you want app updates.", "doesn't start", when="logout", in_max=True,
              entry="org.kde.discover.notifier",
              gain="About 100 MB of RAM and periodic package refreshes gone."),
    Autostart("spice", "Startup apps", "Virtual machine guest agent",
              "spice-vdagent only does something inside a virtual machine. This PC is real hardware.",
              "doesn't start", when="logout", entry="spice-vdagent", user_unit="spice-vdagent.service",
              only_on_metal=True, in_max=True, gain="One less process at login."),
    Autostart("geoclue", "Startup apps", "Location agent",
              "Shares your location with apps that ask. Unneeded on a desktop unless an app uses it.",
              "doesn't start", when="logout", entry="geoclue-demo-agent", in_max=True,
              gain="One less process at login."),
    Autostart("kup", "Startup apps", "Kup backup daemon",
              "Background backup service. Leave it on if you use Kup backups.", "doesn't start", when="logout",
              recommended=not (CONFIG.parent / "kuprc").exists(), entry="kup-daemon",
              gain="One less daemon and no surprise backup I/O."),
    Autostart("nvsettings", "Startup apps", "NVIDIA settings loader",
              "Re-applies X11 settings from nvidia-settings at login. On Wayland it does nothing.",
              "doesn't start", when="logout", entry="nvidia-settings-autostart", in_max=True,
              gain="A slightly quicker login."),
    Autostart("kdeconnect", "Startup apps", "KDE Connect",
              "Phone integration (notifications, file sharing). Leave it on if you pair your phone.",
              "doesn't start", when="logout", recommended=False, entry="org.kde.kdeconnect.daemon",
              gain="About 40 MB of RAM and its network discovery gone."),
]

BY_ID = {t.id: t for t in TWEAKS}
for _t in TWEAKS:                      # Aggressive is never "recommended"; every Aggressive one says its risk
    assert _t.group in GROUPS and _t.tier in TIERS, _t.id
    assert _t.tier == "Safe" or (_t.risk and not _t.recommended), _t.id


# ---------------------------------------------------------------- "already good" checks
def checks() -> dict[str, list[str]]:
    """Things the scan found already set the fast way, per group (shown so you know they were looked at)."""
    out: dict[str, list[str]] = {g: [] for g in GROUPS}
    cpu = Path("/sys/devices/system/cpu")
    drv = read(cpu / "cpu0/cpufreq/scaling_driver")
    if drv in ("intel_pstate", "amd-pstate-epp") and read(cpu / "intel_pstate/status" if drv == "intel_pstate"
                                                         else cpu / "amd_pstate/status") == "active":
        out["CPU & power"].append(f"{drv} runs in active mode: the CPU picks its own clocks (the power profile "
                                  "sets its energy preference)")
    if read(cpu / "intel_pstate/no_turbo") == "0" or read(cpu / "cpufreq/boost") == "1":
        out["CPU & power"].append("Turbo boost is on")
    if sysctl("kernel.sched_autogroup_enabled") == "1":
        out["CPU & power"].append("Autogroup scheduling keeps the desktop responsive under load")
    if read("/sys/module/zswap/parameters/enabled") in ("N", "0") and "zram" in read("/proc/swaps"):
        out["Memory"].append("zswap is off, so swap isn't compressed twice on top of zram")
    try:
        if int(read("/sys/kernel/mm/lru_gen/enabled") or "0", 16):
            out["Memory"].append("Multi-gen LRU picks what to evict from RAM smartly")
    except ValueError:
        pass
    if choice("/sys/kernel/mm/transparent_hugepage/enabled") == "madvise":
        out["Memory"].append("Huge pages for apps that ask for them (no random stalls)")
    for d in disks():
        if d.name.startswith("nvme") and choice(d / "queue/scheduler") == "none":
            out["Storage"].append(f"{d.name} uses the \"none\" I/O scheduler, the fastest for NVMe")
    if unit_state("fstrim.timer") == "enabled":
        out["Storage"].append("Weekly TRIM keeps the SSD fast")
    grub = read("/etc/default/grub")
    if "GRUB_TIMEOUT=0" in grub:
        out["Boot"].append("Boot menu is skipped (no countdown)")
    if unit_state("NetworkManager-wait-online.service") in ("disabled", "masked") and \
            not (STATE / "waitonline.units").exists():
        out["Boot"].append("Boot doesn't wait for the network")
    if sysctl("net.ipv4.tcp_fastopen") in ("1", "3"):
        out["Network"].append("TCP Fast Open is on")
    rmem = sysctl("net.ipv4.tcp_rmem").split()
    if rmem and rmem[-1].isdigit() and int(rmem[-1]) >= 16 << 20:
        out["Network"].append("Downloads can already use a big receive window")
    if nvidia():
        if nv_param("PreserveVideoMemoryAllocations") == "1":
            out["Graphics"].append("NVIDIA keeps video memory across suspend (no broken apps after sleep)")
        if nv_param("UsePageAttributeTable") in ("1", "4294967295"):
            out["Graphics"].append("The NVIDIA driver uses PAT memory types (its default since 515)")
        bar1 = sh("nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits")
        q = sh("nvidia-smi", "-q", "-d", "MEMORY")
        if "BAR1" in q and bar1.isdigit():
            try:
                total = int(q.split("BAR1")[1].split("Total")[1].split(":")[1].split()[0])
                if total >= int(bar1) * 0.9:
                    out["Graphics"].append(f"Resizable BAR is on ({total} MiB of video memory visible to the CPU)")
            except (IndexError, ValueError):
                pass
        if "modeset=1" in sh("grep", "-rh", "nvidia.drm\\|nvidia_drm", "/etc/modprobe.d", "/usr/lib/modprobe.d") \
                or "nvidia-drm.modeset=1" in cmdline():
            out["Graphics"].append("nvidia-drm modesetting is on (needed for Wayland)")
        out["Graphics"].append("Persistence mode isn't needed: with a display attached the driver stays loaded")
    if Path("/dev/ntsync").exists():
        out["Gaming"].append("ntsync is loaded: Wine and Proton builds that support it sync game threads in the kernel (faster)")
    if shutil.which("gamemoded"):
        out["Gaming"].append("GameMode is installed (launch games with gamemoderun %command%)")
    if nvidia():
        out["Gaming"].append("Proton turns on NVAPI (DLSS, Reflex) by itself on NVIDIA; no variable needed")
    if "cap_sys_nice" in sh("getcap", "/usr/bin/kwin_wayland"):
        out["Desktop"].append("KWin draws frames at real-time priority")
    return out


# ---------------------------------------------------------------- applying
def pending_note(t: Tweak, saved: dict) -> str:
    """'Restart to finish' / 'Log out to finish' while a change is still waiting on one."""
    w = t.waiting()
    if w is not None:
        return "Restart to finish" if w else ""
    mark = saved["pending"].get(t.id)
    if not mark:
        return ""
    if (t.when == "restart" and mark == boot_id()) or (t.when == "logout" and mark == session_id()):
        return "Restart to finish" if t.when == "restart" else "Log out to finish"
    return ""


def run_root(args: list[str]):
    """OptimizeL's system root helper through pkexec: one password prompt for the whole batch."""
    r = roothelper.run("optimizel", *args)
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
        except Exception as e:                       # reported as a problem; the page must never hang on it
            problems.append(f"{t.title}: {e}")
    root_ok = True
    if root_args:
        try:
            root_runner(root_args)
        except Exception as e:                       # e.g. FileNotFoundError when pkexec is missing
            root_ok = False
            problems.append("You cancelled the password prompt" if str(e) == "cancelled" else f"System changes: {e}")
    for tid, on in changes.items():                  # the part of a root tweak that's yours, once root went fine
        t = BY_ID[tid]
        if t.root and t.user_side and root_ok:
            try:
                (t.enable if on else t.disable)(saved)
            except Exception as e:
                problems.append(f"{t.title}: {e}")
    for tid in changes:
        t = BY_ID[tid]
        failed = not root_ok if t.root else any(p.startswith(t.title + ":") for p in problems)
        if t.when != "now" and not failed:
            saved["pending"][tid] = boot_id() if t.when == "restart" else session_id()
    try:
        save_saved(saved)
    except OSError as e:
        problems.append(f"Couldn't save OptimizeL's state: {e}")
    return problems
