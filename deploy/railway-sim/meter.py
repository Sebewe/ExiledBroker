"""Meter the simulated Railway services the way Railway bills them: memory used
(GB-seconds), CPU used (vCPU-seconds), volume size (GB-seconds) and public egress (GB).

Usage is read from `docker stats` (streamed, about once a second) for the containers
of the `ebsim` compose project, by service: web, postgres, pipeline (each cron run is
its own short-lived container). The load generator counts egress exactly (the bytes
it received), since Railway bills only public egress, not the private network.

Assumptions, stated in the report:
- Docker's memory figure is the container's usage without the page cache; Railway's
  container memory metric is taken to be the same.
- CPU is measured on this machine's cores; Railway's vCPUs are slower, so CPU is
  also reported doubled as a conservative band.
"""

import json
import re
import subprocess
import threading
import time
from dataclasses import dataclass, field

# Railway Hobby, from https://railway.com/pricing and
# https://docs.railway.com/reference/pricing/plans (read 2026-10-23).
RATES = {
    "memory_gb_month": 10.0,
    "vcpu_month": 20.0,
    "volume_gb_month": 0.15,
    "egress_gb": 0.05,
}
HOBBY_FEE = 5.0  # a month, including this much usage
MONTH_S = 30 * 24 * 3600  # Railway's monthly figures are per-second rates × 30 days
SERVICES = ("web", "postgres", "pipeline")
CPU_BAND = 2.0  # Railway vCPU vs this machine's cores (conservative)

_UNITS = {"b": 1, "kib": 2**10, "mib": 2**20, "gib": 2**30, "kb": 1e3, "mb": 1e6, "gb": 1e9}


def parse_bytes(text: str) -> float:
    m = re.match(r"\s*([\d.]+)\s*([a-zA-Z]+)", text)
    if not m:
        return 0.0
    return float(m.group(1)) * _UNITS.get(m.group(2).lower(), 1)


def service_of(container: str) -> str | None:
    """ebsim-web-1 → web; ebsim-pipeline-run-3f2a… → pipeline."""
    if not container.startswith("ebsim-"):
        return None
    name = container[len("ebsim-") :]
    for s in SERVICES:
        if name.startswith(s + "-"):
            return s
    return None


@dataclass
class Usage:
    gb_s: float = 0.0  # memory, GB-seconds
    vcpu_s: float = 0.0  # CPU, vCPU-seconds
    seconds: float = 0.0  # time running
    peak_gb: float = 0.0
    peak_vcpu: float = 0.0

    def add(self, mem_gb: float, vcpu: float, dt: float) -> None:
        self.gb_s += mem_gb * dt
        self.vcpu_s += vcpu * dt
        self.seconds += dt
        self.peak_gb = max(self.peak_gb, mem_gb)
        self.peak_vcpu = max(self.peak_vcpu, vcpu)

    @property
    def mean_gb(self) -> float:
        return self.gb_s / self.seconds if self.seconds else 0.0

    def as_dict(self) -> dict:
        return {k: round(v, 6) for k, v in self.__dict__.items()} | {
            "mean_gb": round(self.mean_gb, 6)
        }


@dataclass
class Meter:
    """Streams `docker stats` in a thread and integrates usage per service."""

    usage: dict[str, Usage] = field(default_factory=lambda: {s: Usage() for s in SERVICES})
    samples: list[dict] = field(default_factory=list)
    _last: dict[str, float] = field(default_factory=dict)
    _proc: subprocess.Popen | None = None
    _thread: threading.Thread | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def start(self) -> "Meter":
        self._proc = subprocess.Popen(
            ["docker", "stats", "--format", "{{json .}}"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        self._thread = threading.Thread(target=self._read, daemon=True)
        self._thread.start()
        return self

    def _read(self) -> None:
        assert self._proc and self._proc.stdout
        for line in self._proc.stdout:
            # docker stats redraws the screen between rounds with escape codes.
            line = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", line).strip()
            if not line.startswith("{"):
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            self.record(row, time.monotonic())

    def record(self, row: dict, now: float) -> None:
        name = row.get("Name", "")
        service = service_of(name)
        if service is None:
            return
        mem_gb = parse_bytes(row.get("MemUsage", "0B").split("/")[0]) / 1e9
        vcpu = float(row.get("CPUPerc", "0%").rstrip("%") or 0) / 100
        with self._lock:
            last = self._last.get(name)
            self._last[name] = now
            if last is None:
                return  # the first sample of a container only starts its clock
            dt = min(now - last, 10.0)  # a gap (container stopped) isn't billed
            self.usage[service].add(mem_gb, vcpu, dt)
            self.samples.append({"t": now, "service": service, "mem_gb": mem_gb, "vcpu": vcpu})

    def snapshot(self) -> dict[str, Usage]:
        with self._lock:
            return {s: Usage(**u.__dict__) for s, u in self.usage.items()}

    def stop(self) -> None:
        if self._proc:
            self._proc.terminate()
            self._proc.wait(timeout=10)


def volume_gb(volume: str, image: str = "ebsim-app") -> float:
    """A named volume's size, measured inside a container (du)."""
    out = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "--user",
            "root",
            "-v",
            f"{volume}:/v",
            "--entrypoint",
            "du",
            image,
            "-sb",
            "/v",
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return int(out.split()[0]) / 1e9


def monthly_cost(
    gb: float = 0.0, vcpu: float = 0.0, volume: float = 0.0, egress_gb: float = 0.0
) -> dict:
    """Dollars a month for an average memory (GB), CPU (vCPU), volume (GB) and egress
    (GB a month)."""
    out = {
        "memory": gb * RATES["memory_gb_month"],
        "cpu": vcpu * RATES["vcpu_month"],
        "volume": volume * RATES["volume_gb_month"],
        "egress": egress_gb * RATES["egress_gb"],
    }
    out["total"] = sum(out.values())
    return out


def hobby_bill(usage: float) -> float:
    """The month's Hobby bill: the fee covers the first $5 of usage."""
    return HOBBY_FEE + max(0.0, usage - HOBBY_FEE)
