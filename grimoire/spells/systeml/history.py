# SPDX-License-Identifier: GPL-3.0-or-later
"""Per-app history: while SystemL is open, each snapshot's processes are summed per app; once a minute the
averages and peaks go into a small file, kept for a week, so "what was eating my CPU an hour ago" has an
answer. Only the busiest apps of each minute are kept, so the file stays small.
"""
import json
import time
from collections import defaultdict

from grimoire.paths import DATA
from grimoire.spells.systeml.probe import app_name

FILE = DATA / "systeml-history.json"
KEEP = 7 * 24 * 60          # minutes
PER_MINUTE = 25             # apps kept per minute


def per_app(procs: list[dict]) -> dict[str, tuple[float, int, int]]:
    """{app: (cpu %, memory bytes, process count)} for one snapshot; kernel threads are left out."""
    apps = defaultdict(lambda: [0.0, 0, 0])
    for p in procs:
        if p["kernel"]:
            continue
        a = apps[app_name(p)]
        a[0] += p["cpu"]
        a[1] += p["mem"]
        a[2] += 1
    return {k: tuple(v) for k, v in apps.items()}


class History:
    def __init__(self):
        self.minutes: list[dict] = self._load()
        self._acc: dict[str, list] = {}         # app -> [cpu sum, cpu peak, mem sum, mem peak, samples]
        self._samples = 0
        self._minute = int(time.time() // 60)

    def _load(self) -> list[dict]:
        try:
            data = json.loads(FILE.read_text())
            return data["minutes"] if isinstance(data.get("minutes"), list) else []
        except (OSError, ValueError, AttributeError):
            return []

    def add(self, procs: list[dict]):
        """Feed one snapshot; closes the minute when the clock moves on (called on the worker thread)."""
        minute = int(time.time() // 60)
        if minute != self._minute and self._samples:
            self._close()
        self._minute = minute
        self._samples += 1
        for app, (cpu, mem, _) in per_app(procs).items():
            a = self._acc.setdefault(app, [0.0, 0.0, 0, 0, 0])
            a[0] += cpu
            a[1] = max(a[1], cpu)
            a[2] += mem
            a[3] = max(a[3], mem)
            a[4] += 1

    def _close(self):
        n = self._samples
        apps = {app: [round(a[0] / n, 2), round(a[1], 1), int(a[2] / n), a[3]] for app, a in self._acc.items()}
        busiest = sorted(apps, key=lambda k: (apps[k][0], apps[k][2]), reverse=True)[:PER_MINUTE]
        by_mem = sorted(apps, key=lambda k: apps[k][2], reverse=True)[:PER_MINUTE // 2]
        self.minutes.append({"t": self._minute * 60, "apps": {k: apps[k] for k in {*busiest, *by_mem}}})
        self.minutes = self.minutes[-KEEP:]
        self._acc, self._samples = {}, 0
        self.save()

    def save(self):
        tmp = FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps({"minutes": self.minutes}, separators=(",", ":")))
        tmp.replace(FILE)

    def summary(self, since_minutes: int) -> list[dict]:
        """Apps over the last N minutes: average and peak CPU, average and peak memory, minutes seen."""
        cutoff = time.time() - since_minutes * 60
        rows = [m for m in self.minutes if m["t"] >= cutoff]
        out = defaultdict(lambda: {"cpu": 0.0, "cpu_peak": 0.0, "mem": 0, "mem_peak": 0, "minutes": 0})
        for m in rows:
            for app, (cpu, peak, mem, mpeak) in m["apps"].items():
                o = out[app]
                o["cpu"] += cpu
                o["cpu_peak"] = max(o["cpu_peak"], peak)
                o["mem"] += mem
                o["mem_peak"] = max(o["mem_peak"], mpeak)
                o["minutes"] += 1
        total = max(1, len(rows))
        for app, o in out.items():
            o["app"] = app
            o["cpu"] /= total                   # averaged over the whole window, so short bursts rank low
            o["mem"] = o["mem"] / max(1, o["minutes"])
        return sorted(out.values(), key=lambda o: o["cpu"], reverse=True)

    def series(self, app: str, since_minutes: int) -> list[tuple[float, float, float]]:
        """(time, cpu, memory) per recorded minute for one app; 0 where it wasn't among the busiest."""
        cutoff = time.time() - since_minutes * 60
        out = []
        for m in self.minutes:
            if m["t"] >= cutoff:
                v = m["apps"].get(app)
                out.append((m["t"], v[0] if v else 0.0, v[2] if v else 0))
        return out

    def span(self) -> float:
        """Minutes of history recorded so far."""
        return len(self.minutes)
