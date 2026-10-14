# SPDX-License-Identifier: GPL-3.0-or-later
"""OptimizeL's before/after benchmark: about 30 s of small, fixed tests that need no root, so a tweak's effect can
be measured instead of guessed. Results are kept with timestamps (and which tweaks were on) in
DATA/optimizel-bench.json; the page compares the latest run with a baseline run.

The tests run in a child process (python3 -m grimoire.spells.optimizel.bench), so the UI's own threads can't
skew the timings. It prints one JSON line per finished test, then {"done": ...}.

    boot        systemd-analyze, recorded once per boot (firmware / loader / kernel / userspace)
    cpu         SHA-256 throughput on one core and on every core (hashlib drops the GIL)
    syscall     cost of one cheap system call (CPU mitigations show up here)
    memory      copy bandwidth (memcpy) and random-read cost over 256 MB (numpy, when installed)
    disk        512 MB in ~/.cache: sequential write + read (page cache dropped first), 4K random reads (O_DIRECT)
    latency     how late a 1 ms sleep wakes up while every core is busy: a frame-pacing proxy (p50 / p99)
"""
import hashlib
import json
import mmap
import os
import random
import subprocess
import sys
import threading
import time
from pathlib import Path

from grimoire.paths import CACHE, DATA

FILE = DATA / "optimizel-bench.json"
TMP = CACHE / "optimizel-bench"

# key: (label, unit, higher is better, group)
METRICS = {
    "boot_total": ("Boot to desktop", "s", False, "Boot"),
    "boot_firmware": ("Firmware (BIOS/UEFI)", "s", False, "Boot"),
    "boot_loader": ("Boot loader", "s", False, "Boot"),
    "boot_kernel": ("Kernel", "s", False, "Boot"),
    "boot_userspace": ("Services to desktop", "s", False, "Boot"),
    "cpu_single": ("One core (SHA-256)", "MB/s", True, "CPU"),
    "cpu_multi": ("All cores (SHA-256)", "MB/s", True, "CPU"),
    "syscall": ("System call", "ns", False, "CPU"),
    "mem_copy": ("Memory copy", "GB/s", True, "Memory"),
    "mem_random": ("Random reads, many at once", "ns", False, "Memory"),
    "disk_write": ("Sequential write", "MB/s", True, "Disk"),
    "disk_read": ("Sequential read", "MB/s", True, "Disk"),
    "disk_iops": ("4K random read", "IOPS", True, "Disk"),
    "disk_lat": ("4K read latency", "µs", False, "Disk"),
    "wake_p50": ("Wake-up delay, typical", "µs", False, "Latency"),
    "wake_p99": ("Wake-up delay, worst 1%", "µs", False, "Latency"),
}
GROUPS = ["Boot", "CPU", "Memory", "Disk", "Latency"]


# ---------------------------------------------------------------- results file
def load() -> dict:
    try:
        d = json.loads(FILE.read_text())
        if not isinstance(d, dict):
            d = {}
    except (OSError, ValueError):
        d = {}
    d.setdefault("boots", [])
    d.setdefault("runs", [])
    d.setdefault("baseline", None)
    return d


def save(d: dict):
    tmp = FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, indent=1))
    tmp.replace(FILE)


def _seconds(text: str) -> float | None:
    """'1min 2.5s' / '850ms' / '3.194s' -> seconds."""
    total, num = 0.0, ""
    try:
        for tok in text.replace("min", "min ").split():
            for unit, mult in (("ms", 0.001), ("us", 1e-6), ("µs", 1e-6), ("min", 60), ("h", 3600), ("s", 1)):
                if tok.endswith(unit):
                    total += float(tok[: -len(unit)] or num) * mult
                    break
        return round(total, 3)
    except ValueError:
        return None


def boot_times() -> dict:
    """This boot's phases from systemd-analyze ('' while boot is still finishing)."""
    try:
        out = subprocess.run(["systemd-analyze"], capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.TimeoutExpired):
        return {}
    line = out.splitlines()[0] if out else ""
    if "Startup finished in" not in line:
        return {}
    r = {}
    for part in line.split("in", 1)[1].split("+"):
        part = part.split("=")[0].strip()
        for name in ("firmware", "loader", "kernel", "userspace", "initrd"):
            if f"({name})" in part:
                r[f"boot_{name}"] = _seconds(part.split("(")[0])
    r["boot_total"] = _seconds(line.split("=")[-1]) if "=" in line else None
    if "boot_initrd" in r:                       # fold the initrd into the kernel phase
        r["boot_kernel"] = round((r.get("boot_kernel") or 0) + (r.pop("boot_initrd") or 0), 3)
    return {k: v for k, v in r.items() if v is not None}


def record_boot() -> dict:
    """Keep this boot's times once (last 30 boots). Returns the stored file."""
    d = load()
    bid = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    if any(b.get("id") == bid for b in d["boots"]):
        return d
    times = boot_times()
    if times:
        d["boots"] = (d["boots"] + [{"id": bid, "ts": time.time(), **times}])[-30:]
        try:
            save(d)
        except OSError:
            pass
    return d


def baseline_run(d: dict) -> dict | None:
    runs = d["runs"]
    if not runs:
        return None
    for r in runs:
        if r.get("ts") == d.get("baseline"):
            return r
    return runs[0]


# run-to-run noise on an idle desktop: changes smaller than this show as "same"
NOISE = {"wake_p50": 15, "wake_p99": 25, "disk_write": 8, "disk_read": 6, "disk_iops": 6, "disk_lat": 6,
         "mem_copy": 6, "mem_random": 6, "syscall": 5}


def noise(metric: str) -> float:
    return NOISE.get(metric, 1 if metric.startswith("boot_") else 3)


def change(metric: str, old, new) -> float | None:
    """Improvement in percent (positive = better), whichever way the metric goes."""
    if not old or new is None:
        return None
    better_up = METRICS[metric][2]
    return round(((new - old) / old if better_up else (old - new) / old) * 100, 1)


# ---------------------------------------------------------------- the tests (child process)
def _timed(fn, seconds: float) -> tuple[int, float]:
    n, start = 0, time.perf_counter()
    while (el := time.perf_counter() - start) < seconds:
        fn()
        n += 1
    return n, el


def cpu() -> dict:
    block = os.urandom(16 << 20)
    n, el = _timed(lambda: hashlib.sha256(block).digest(), 2.0)
    single = n * len(block) / el / 1e6
    threads = os.cpu_count() or 1
    counts = [0] * threads
    stop = time.perf_counter() + 2.5

    def work(i):
        while time.perf_counter() < stop:
            hashlib.sha256(block).digest()
            counts[i] += 1

    ts = [threading.Thread(target=work, args=(i,)) for i in range(threads)]
    start = time.perf_counter()
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    multi = sum(counts) * len(block) / (time.perf_counter() - start) / 1e6
    # one cheap syscall minus the Python call around it; best of 5 rounds (the least disturbed one)
    loops, syscall = 100_000, float("inf")
    f = int
    for _ in range(5):
        t0 = time.perf_counter()
        for _ in range(loops):
            os.getppid()
        t1 = time.perf_counter()
        for _ in range(loops):
            f()
        t2 = time.perf_counter()
        syscall = min(syscall, max(((t1 - t0) - (t2 - t1)) / loops * 1e9, 1.0))
    return {"cpu_single": round(single), "cpu_multi": round(multi), "syscall": round(syscall, 1)}


def memory() -> dict:
    size = 256 << 20
    src = bytearray(os.urandom(1 << 20)) * 256
    dst = bytearray(size)
    best = 0.0
    for _ in range(5):
        t = time.perf_counter()
        dst[:] = src
        best = max(best, size / (time.perf_counter() - t) / 1e9)
    r = {"mem_copy": round(best, 2)}
    del src, dst
    try:
        import numpy as np
    except ImportError:
        return r
    arr = np.arange(size // 8, dtype=np.int64)
    idx = np.random.default_rng(1).integers(0, arr.size, 8_000_000)
    arr[idx[:1000]].sum()
    t = time.perf_counter()
    arr[idx].sum()
    r["mem_random"] = round((time.perf_counter() - t) / idx.size * 1e9, 2)
    return r


def disk(size=512 << 20) -> dict:
    TMP.mkdir(parents=True, exist_ok=True)
    st = os.statvfs(TMP)
    if st.f_bavail * st.f_frsize < size * 4:
        return {}
    path = TMP / f"bench-{os.getpid()}.bin"
    chunk = os.urandom(4 << 20)
    r = {}
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        t = time.perf_counter()
        for _ in range(size // len(chunk)):
            os.write(fd, chunk)
        os.fsync(fd)
        r["disk_write"] = round(size / (time.perf_counter() - t) / 1e6)
        os.posix_fadvise(fd, 0, 0, os.POSIX_FADV_DONTNEED)     # clean pages leave the cache: reads hit the disk
        os.close(fd)
        # sequential read in 128 KB requests, the way most programs read: read-ahead decides the speed
        fd = os.open(path, os.O_RDONLY)
        os.posix_fadvise(fd, 0, 0, os.POSIX_FADV_DONTNEED)
        buf = bytearray(128 << 10)
        t = time.perf_counter()
        with os.fdopen(fd, "rb", buffering=0) as f:
            while f.readinto(buf):
                pass
        r["disk_read"] = round(size / (time.perf_counter() - t) / 1e6)
        # 4K random reads straight from the disk, one at a time
        try:
            fd = os.open(path, os.O_RDONLY | os.O_DIRECT)
        except OSError:
            return r
        page = mmap.mmap(-1, 4096)
        blocks = size // 4096
        rnd = random.Random(7)
        lats = []
        stop = time.perf_counter() + 3.0
        try:
            while (now := time.perf_counter()) < stop:
                os.preadv(fd, [page], rnd.randrange(blocks) * 4096)
                lats.append(time.perf_counter() - now)
        except OSError:
            pass
        finally:
            os.close(fd)
        if lats:
            r["disk_iops"] = round(len(lats) / sum(lats))
            r["disk_lat"] = round(sorted(lats)[len(lats) // 2] * 1e6, 1)
    finally:
        try:
            path.unlink()                                   # our own scratch file
        except OSError:
            pass
    return r


def latency() -> dict:
    """1 ms sleeps while `yes` keeps every core busy: how late does the scheduler wake us?"""
    hogs = []
    try:
        for _ in range(os.cpu_count() or 1):
            hogs.append(subprocess.Popen(["yes"], stdout=subprocess.DEVNULL))
        time.sleep(0.3)
        rounds = []                              # 3 rounds; the middle one's numbers (one stray spike can't win)
        for _ in range(3):
            late = []
            for _ in range(1000):
                t = time.perf_counter()
                time.sleep(0.001)
                late.append(time.perf_counter() - t - 0.001)
            late.sort()
            rounds.append((late[len(late) // 2], late[int(len(late) * 0.99)]))
    finally:
        for h in hogs:
            h.kill()
        for h in hogs:
            h.wait()
    p50 = sorted(r[0] for r in rounds)[1]
    p99 = sorted(r[1] for r in rounds)[1]
    return {"wake_p50": round(p50 * 1e6, 1), "wake_p99": round(p99 * 1e6, 1)}


TESTS = [("CPU", cpu), ("Memory", memory), ("Disk", disk), ("Latency", latency)]


def main():
    out = {}
    for name, fn in TESTS:
        print(json.dumps({"step": name}), flush=True)
        try:
            out.update(fn())
        except Exception as e:                       # one failing test mustn't lose the rest
            print(json.dumps({"error": f"{name}: {e}"}), flush=True)
    print(json.dumps({"done": out}), flush=True)


# ---------------------------------------------------------------- running it (from the page)
def run(progress=lambda step: None) -> dict:
    """Run the tests in a child process, store the run, return it. Slow (~30 s): call off the UI thread."""
    from grimoire.spells.optimizel import tweaks
    root = Path(__file__).resolve().parents[3]
    env = dict(os.environ, PYTHONPATH=str(root) + os.pathsep + os.environ.get("PYTHONPATH", ""))
    p = subprocess.Popen([sys.executable, "-m", "grimoire.spells.optimizel.bench"], stdout=subprocess.PIPE,
                         stderr=subprocess.DEVNULL, text=True, env=env, cwd=root)
    results, errors = {}, []
    for line in p.stdout:
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        if "step" in msg:
            progress(msg["step"])
        elif "error" in msg:
            errors.append(msg["error"])
        elif "done" in msg:
            results = msg["done"]
    p.wait()
    d = record_boot()
    boots = d["boots"]
    if boots:
        results.update({k: v for k, v in boots[-1].items() if k.startswith("boot_")})
    on = [t.id for t in tweaks.TWEAKS if _safe_on(t)]
    entry = {"ts": time.time(), "on": on, "r": results, "errors": errors}
    d["runs"] = (d["runs"] + [entry])[-50:]
    if d["baseline"] is None:
        d["baseline"] = entry["ts"]
    save(d)
    return entry


def _safe_on(t) -> bool:
    try:
        return t.is_on()
    except Exception:
        return False


if __name__ == "__main__":
    main()
