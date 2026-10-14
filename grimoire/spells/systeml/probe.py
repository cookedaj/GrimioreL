"""SystemL's readings: one Sampler per page takes a snapshot of the whole machine (CPU, cores, memory, swap,
disk and network rates, GPU, temperatures, processes). Snapshots run on a worker thread; rates are worked
out from the previous snapshot, so the first one reads zero.
"""
import os
import platform
import shutil
import subprocess
import time
from pathlib import Path

import psutil

CORES = psutil.cpu_count() or 1
PAGE = os.sysconf("SC_PAGE_SIZE")
KTHREADD = 2            # parent of every kernel thread
INTERPRETERS = ("python", "bash", "sh", "dash", "zsh", "node", "java", "perl", "ruby", "wine", "env")


def cpu_model() -> str:
    for line in Path("/proc/cpuinfo").read_text().splitlines():
        if line.startswith("model name"):
            return line.split(":", 1)[1].strip()
    return platform.processor() or "CPU"


def gpu() -> dict | None:
    """NVIDIA cards through nvidia-smi (one call, ~40 ms); None when there's no NVIDIA driver."""
    if not shutil.which("nvidia-smi"):
        return None
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=name,utilization.gpu,memory.used,memory.total,"
                              "temperature.gpu,power.draw,power.limit,fan.speed,clocks.gr",
                              "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=3).stdout
    except (OSError, subprocess.TimeoutExpired):
        return None
    parts = [p.strip() for p in out.splitlines()[0].split(",")] if out.strip() else []
    if len(parts) < 9:
        return None

    def num(s):
        try:
            return float(s)
        except ValueError:
            return None
    return {"name": parts[0], "util": num(parts[1]), "vram_used": (num(parts[2]) or 0) * 2**20,
            "vram_total": (num(parts[3]) or 0) * 2**20, "temp": num(parts[4]), "power": num(parts[5]),
            "power_limit": num(parts[6]), "fan": num(parts[7]), "clock": num(parts[8])}


def temps() -> dict[str, float]:
    """A short list of the temperatures worth showing: CPU package, each drive, the hottest of the rest."""
    out = {}
    try:
        sensors = psutil.sensors_temperatures()
    except (OSError, AttributeError):
        return out
    for chip, readings in sensors.items():
        if not readings:
            continue
        if chip in ("coretemp", "k10temp", "zenpower"):
            main = next((r for r in readings if r.label.startswith(("Package", "Tctl", "Tdie"))), readings[0])
            out["CPU"] = main.current
        elif chip == "nvme":
            out.setdefault("SSD", readings[0].current)
        elif chip in ("amdgpu", "nouveau"):
            out.setdefault("GPU", readings[0].current)
        elif chip not in ("acpitz",):
            out.setdefault(chip, max(r.current for r in readings))
    return out


class Sampler:
    """Keeps the previous counters so each sample() can report rates. Not thread-safe: the page runs one
    sample at a time."""

    def __init__(self):
        self.procs: dict[int, psutil.Process] = {}
        self.prev = None
        self.users: dict[int, str] = {}
        psutil.cpu_percent(percpu=True)        # prime the CPU counters

    def _user(self, uid: int) -> str:
        if uid not in self.users:
            try:
                import pwd
                self.users[uid] = pwd.getpwuid(uid).pw_name
            except KeyError:
                self.users[uid] = str(uid)
        return self.users[uid]

    def sample(self, with_procs=True, with_gpu=True) -> dict:
        now = time.monotonic()
        cores = psutil.cpu_percent(percpu=True)
        mem, swap = psutil.virtual_memory(), psutil.swap_memory()
        disk = psutil.disk_io_counters()
        net = psutil.net_io_counters()
        prev, self.prev = self.prev, (now, disk, net)
        dt = now - prev[0] if prev else 0
        rate = lambda a, b: max(0.0, (a - b) / dt) if dt else 0.0
        freq = psutil.cpu_freq()
        snap = {
            "time": time.time(),
            "cpu": sum(cores) / len(cores) if cores else 0.0,
            "cores": cores,
            "freq": freq.current if freq else None,
            "load": os.getloadavg(),
            "mem_used": mem.total - mem.available, "mem_total": mem.total, "mem_cache": mem.cached + mem.buffers,
            "swap_used": swap.used, "swap_total": swap.total,
            "disk_read": rate(disk.read_bytes, prev[1].read_bytes) if prev and disk else 0.0,
            "disk_write": rate(disk.write_bytes, prev[1].write_bytes) if prev and disk else 0.0,
            "net_down": rate(net.bytes_recv, prev[2].bytes_recv) if prev else 0.0,
            "net_up": rate(net.bytes_sent, prev[2].bytes_sent) if prev else 0.0,
            "temps": temps(),
            "gpu": gpu() if with_gpu else None,
            "uptime": time.time() - psutil.boot_time(),
        }
        if snap["gpu"] and snap["gpu"]["temp"] is not None:
            snap["temps"]["GPU"] = snap["gpu"]["temp"]
        if with_procs:
            snap["procs"] = self._procs(dt)
        return snap

    def _procs(self, dt: float) -> list[dict]:
        rows, alive = [], {}
        me = os.getpid()
        for p in psutil.process_iter():
            pid = p.pid
            proc = self.procs.get(pid)
            try:
                if proc is None or proc.create_time() != p.create_time():
                    proc = p
                    proc.cpu_percent()              # prime; reads 0 this round
                with proc.oneshot():
                    ppid = proc.ppid()
                    kernel = ppid == KTHREADD or pid == KTHREADD
                    info = {"pid": pid, "ppid": ppid, "name": proc.name(), "cpu": proc.cpu_percent() / CORES,
                            "mem": proc.memory_info().rss, "nice": proc.nice(), "status": proc.status(),
                            "threads": proc.num_threads(), "user": self._user(proc.uids().real),
                            "started": proc.create_time(), "kernel": kernel, "self": pid == me}
                    try:
                        io = proc.io_counters()
                        last = getattr(proc, "_grimoire_io", None)
                        proc._grimoire_io = io
                        info["io"] = ((io.read_bytes + io.write_bytes) - (last.read_bytes + last.write_bytes)) / dt \
                            if last and dt else 0.0
                    except (psutil.AccessDenied, AttributeError):
                        info["io"] = None
                    if not kernel:
                        try:
                            info["cmd"] = " ".join(proc.cmdline())
                            info["exe"] = proc.exe()
                        except (psutil.AccessDenied, psutil.ZombieProcess):
                            info["cmd"], info["exe"] = "", ""
                    else:
                        info["cmd"], info["exe"] = "", ""
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue
            alive[pid] = proc
            rows.append(info)
        self.procs = alive
        return rows


def app_name(row: dict) -> str:
    """The name a process is grouped under in Apps view and history: its executable's file name, so browser
    helpers ("Isolated Web Co", "Web Content") count towards the browser."""
    exe = Path(row.get("exe") or "").name
    return exe if exe and not exe.startswith(INTERPRETERS) else row["name"]


def system_info() -> list[tuple[str, str]]:
    mem = psutil.virtual_memory().total
    rel = {}
    try:
        for line in Path("/etc/os-release").read_text().splitlines():
            k, _, v = line.partition("=")
            rel[k] = v.strip('"')
    except OSError:
        pass
    g = gpu()
    return [("System", rel.get("PRETTY_NAME", platform.system())), ("Kernel", platform.release()),
            ("Desktop", f"KDE Plasma {os.environ.get('KDE_SESSION_VERSION', '')} "
                        f"({os.environ.get('XDG_SESSION_TYPE', '').title()})".replace("  ", " ")),
            ("CPU", f"{cpu_model()} · {psutil.cpu_count(logical=False)} cores, {CORES} threads"),
            ("Memory", f"{mem / 2**30:.0f} GB"), ("GPU", g["name"] if g else "—")]


def uptime_text(seconds: float) -> str:
    d, rest = divmod(int(seconds), 86400)
    h, m = rest // 3600, rest % 3600 // 60
    return (f"{d} d " if d else "") + (f"{h} h " if h or d else "") + f"{m} min"
