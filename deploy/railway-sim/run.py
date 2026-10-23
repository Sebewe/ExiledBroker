"""The Railway simulation: seed it, run a day of visitors against it, report the bill.

    .venv/bin/python deploy/railway-sim/run.py run --users 100            # a day in ~24 min
    .venv/bin/python deploy/railway-sim/run.py run --users 1000 --seconds-per-hour 3600  # real time
    .venv/bin/python deploy/railway-sim/run.py spike --users 1000          # all at once
    .venv/bin/python deploy/railway-sim/run.py switch                      # Mirage → Allflame
    .venv/bin/python deploy/railway-sim/run.py down                        # remove it all

A run starts from a fresh server (`seed`): Allflame replayed from 48 hours after its
launch, Postgres seeded from the local copy as `eb site seed --hosted` does (the
rows, the Launch history and picks, and the pages so far).
Then: an idle window with no visitors (what the always-on services cost doing
nothing), then `--sim-hours` simulated hours with the visitors browsing while, a few
minutes past each simulated hour, the pipeline runs once (a Railway cron job) and
publishes the hour that just ended. Nothing reaches GGG or poe.ninja: the pipeline's
network has no route out, only to the upstream stand-in.

The report (printed, and saved to data/perf/railway-<label>.json) extrapolates to a
real day and month:
- always-on memory: the services' mean while the visitors ran, over 24 h;
- CPU: the idle rate over 24 h, plus the visitors' extra work (measured, not scaled:
  a compressed day does a day's work, just faster);
- the pipeline: its measured runs × 24 a day;
- volumes: Postgres's size (the pipeline has none); egress: the bytes the visitors
  received.
"""

import argparse
import asyncio
import json
import os
import subprocess
import sys
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
# The local copy the server is seeded from (default: this checkout's data/).
DATA = Path(os.environ.get("EB_SIM_DATA", ROOT / "data"))
sys.path.insert(0, str(HERE))
import loadgen
import meter

COMPOSE = ["docker", "compose", "-f", str(HERE / "docker-compose.yml")]
WEB = "http://localhost:8100"
UPSTREAM = "http://localhost:9100"
LEAGUE = "Allflame"
LAUNCH = 1784930400  # Allflame's first hour, 2026-07-24 22:00 UTC
START = LAUNCH + 48 * 3600  # the replay starts two days in
CRON_MINUTE = 6  # Railway cron "6 * * * *"
DAY = 24 * 3600


def sh(args: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(args, check=True, text=True, **kw)


def iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, UTC).isoformat()


def set_upstream_now(ts: float, missing_empty: bool = False) -> None:
    params = {"ts": int(ts), "missing_empty": missing_empty}
    httpx.post(f"{UPSTREAM}/_sim/now", params=params, timeout=10).raise_for_status()


def pipeline_pass(at: float, missing_empty: bool = False) -> dict:
    """One cron run of the pipeline at simulated time `at`; its wall time and output."""
    set_upstream_now(at, missing_empty)
    started = time.monotonic()
    out = subprocess.run(
        [
            *COMPOSE,
            "--profile",
            "cron",
            "run",
            "--rm",
            "--no-deps",
            "pipeline",
            "eb",
            "pipeline",
            "run",
            "--now",
            iso(at),
        ],
        capture_output=True,
        text=True,
        check=False,  # a failed pass is reported, not fatal: the next hour catches up
    )
    return {
        "at": iso(at),
        "seconds": round(time.monotonic() - started, 1),
        "ok": out.returncode == 0,
        "out": (out.stdout + out.stderr).strip()[-400:],
        # The pass's own line (stderr carries docker's "Container … Created" too).
        "result": (out.stdout.strip().splitlines() or [""])[-1],
    }


def wait_healthy(url: str, seconds: int = 120) -> None:
    for _ in range(seconds):
        try:
            if httpx.get(url, timeout=2).status_code < 500:
                return
        except httpx.HTTPError:
            pass
        time.sleep(1)
    raise RuntimeError(f"{url} didn't come up")


NEXT_ENV = HERE / ".cache" / "next.env"  # the announced league, for both services


def reset_and_seed(
    seed: list[str] | None = None, first_at: float | None = None, next_league: str = ""
) -> None:
    """A fresh simulation: rebuilt image, an empty Postgres seeded from the local copy
    (by default Allflame cut back to START), then a first pipeline pass."""
    sh([*COMPOSE, "--profile", "cron", "down", "-v", "--remove-orphans"], capture_output=True)
    (HERE / ".cache").mkdir(exist_ok=True)
    NEXT_ENV.write_text(next_league)
    sh([*COMPOSE, "build", "web"])
    sh([*COMPOSE, "up", "-d", "--wait", "postgres", "backup"])
    sh(
        [
            *COMPOSE,
            "--profile",
            "cron",
            "run",
            "--rm",
            "--user",
            "root",
            "-v",
            f"{DATA}:/src:ro",
            "-v",
            f"{HERE}:/sim:ro",
            "-v",
            f"{HERE / '.cache'}:/sim-cache",
            "--entrypoint",
            "python",
            "pipeline",
            "/sim/seed_server.py",
            *(seed or ["--start", str(START), "--league", LEAGUE]),
        ]
    )
    sh([*COMPOSE, "up", "-d", "upstream"])
    wait_healthy(f"{UPSTREAM}/_sim/stats")
    # Nothing new yet: checks it's caught up.
    first = pipeline_pass(first_at or START + CRON_MINUTE * 60, missing_empty=bool(seed))
    if not first["ok"]:
        raise RuntimeError(f"the first pipeline pass failed: {first['out']}")
    print(f"first pass: {first['out']}")
    sh([*COMPOSE, "up", "-d", "web"])
    wait_healthy(f"{WEB}/api/health")
    httpx.post(f"{UPSTREAM}/_sim/reset", timeout=10)


# What the backup must match: the site's leagues, hours, rows, pages and data version.
BACKUP_CHECK = """SELECT json_build_object(
    'leagues', (SELECT string_agg(league_id || ':' || fingerprint, ',' ORDER BY league_id)
                FROM ingest_load),
    'loaded_at', (SELECT max(loaded_at)::text FROM ingest_load),
    'hours', (SELECT count(*) FROM exchange_hour_loaded),
    'latest_hour', (SELECT max(hour)::text FROM exchange_hour_loaded),
    'prices', (SELECT count(*) FROM price_observation),
    'loops', (SELECT count(*) FROM cross_market_hour),
    'pages', (SELECT count(*) FROM exchange_page),
    'items', (SELECT count(*) FROM item),
    'history', (SELECT count(*) FROM launch_history))"""


def backup_check() -> dict:
    """The site's database against its backup, after the pipeline's last sync."""

    def summary(service: str, database: str) -> dict:
        out = sh(
            [
                *COMPOSE,
                "exec",
                "-T",
                service,
                "psql",
                "-U",
                "eb",
                "-d",
                database,
                "-At",
                "-c",
                BACKUP_CHECK,
            ],
            capture_output=True,
        )
        return json.loads(out.stdout)

    site, copy = summary("postgres", "railway"), summary("backup", "backup")
    return {"same": site == copy, "site": site, "backup": copy}


def diff(a: dict[str, meter.Usage], b: dict[str, meter.Usage]) -> dict[str, meter.Usage]:
    out = {}
    for s, now in b.items():
        u = meter.Usage(
            **{k: getattr(now, k) - getattr(a[s], k) for k in ("gb_s", "vcpu_s", "seconds")}
        )
        u.peak_gb, u.peak_vcpu = now.peak_gb, now.peak_vcpu
        out[s] = u
    return out


def report(
    label: str,
    users: int,
    sim_hours: float,
    idle: dict,
    load: dict,
    traffic: dict,
    passes: list[dict],
    volumes: dict,
    upstream: dict,
    load_seconds: float,
) -> dict:
    day_scale = 24 / sim_hours  # visitor work in the run → a day's work
    services = {}
    for s in ("web", "postgres"):
        idle_vcpu = idle[s].vcpu_s / idle[s].seconds if idle[s].seconds else 0.0
        extra = max(load[s].vcpu_s - idle_vcpu * load_seconds, 0.0) * day_scale
        services[s] = {
            "mean_gb": round(load[s].mean_gb, 4),
            "peak_gb": round(load[s].peak_gb, 4),
            "idle_vcpu": round(idle_vcpu, 5),
            "gb_s_day": load[s].mean_gb * DAY,
            "vcpu_s_day": idle_vcpu * DAY + extra,
            "peak_vcpu": round(load[s].peak_vcpu, 3),
        }
    # A cron run lasts seconds, shorter than docker stats samples well, so each run is
    # billed at the larger of what was sampled and its wall time × its peak (a bound).
    runs = max(len(passes), 1)
    wall = sum(p["seconds"] for p in passes)
    p = load["pipeline"]
    services["pipeline"] = {
        "runs": len(passes),
        "wall_seconds_per_run": round(wall / runs, 1),
        "peak_gb": round(p.peak_gb, 4),
        "peak_vcpu": round(p.peak_vcpu, 3),
        "gb_s_day": max(p.gb_s, wall * p.peak_gb) / runs * 24,
        "vcpu_s_day": max(p.vcpu_s, wall * p.peak_vcpu) / runs * 24,
    }
    egress_gb_day = traffic["total_bytes"] / 1e9 * day_scale
    volume_gb = sum(volumes.values())

    def month(cpu_band: float) -> dict:
        gb = sum(v["gb_s_day"] for v in services.values()) * 30 / meter.MONTH_S
        vcpu = sum(v["vcpu_s_day"] for v in services.values()) * 30 / meter.MONTH_S * cpu_band
        return meter.monthly_cost(gb=gb, vcpu=vcpu, volume=volume_gb, egress_gb=egress_gb_day * 30)

    cost, cost_slow = month(1.0), month(meter.CPU_BAND)
    out = {
        "label": label,
        "measured_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "users": users,
        "sim_hours": sim_hours,
        "services": services,
        "volumes_gb": volumes,
        "egress_gb_day": round(egress_gb_day, 4),
        "traffic": traffic,
        "upstream": upstream,
        "pipeline_passes": passes,
        "monthly": {k: round(v, 3) for k, v in cost.items()},
        "monthly_slow_cpu": {k: round(v, 3) for k, v in cost_slow.items()},
        "hobby_bill": round(meter.hobby_bill(cost["total"]), 2),
        "hobby_bill_slow_cpu": round(meter.hobby_bill(cost_slow["total"]), 2),
        "rates": meter.RATES,
    }
    perf = DATA / "perf"
    perf.mkdir(parents=True, exist_ok=True)
    (perf / f"railway-{label}.json").write_text(json.dumps(out, indent=2, default=str))
    return out


def show(r: dict) -> None:
    m, ms = r["monthly"], r["monthly_slow_cpu"]
    print(f"\n== {r['label']}: {r['users']} users, {r['sim_hours']} simulated hours")
    for s, v in r["services"].items():
        print(
            f"  {s:<9} {json.dumps({k: (round(x, 2) if isinstance(x, float) else x) for k, x in v.items()})}"
        )
    t = r["traffic"]
    print(
        f"  traffic  {t['total_requests']} requests ({t.get('requests_per_user_day')}/user/day), {t['total_bytes'] / 1e6:.1f} MB, p50 {t['p50_ms']} ms, p95 {t['p95_ms']} ms, errors {sum(t['errors'].values())}"
    )
    print(f"  upstream {r['upstream'].get('counts')}")
    print(f"  volumes  {r['volumes_gb']}")
    print(
        f"  monthly  memory ${m['memory']:.2f}  cpu ${m['cpu']:.2f} (slow-vCPU ${ms['cpu']:.2f})  volume ${m['volume']:.2f}  egress ${m['egress']:.2f}  = usage ${m['total']:.2f} (≤ ${ms['total']:.2f})"
    )
    print(
        f"  Hobby bill ${r['hobby_bill']:.2f} a month (≤ ${r['hobby_bill_slow_cpu']:.2f} with slower vCPUs)"
    )


def run(args) -> dict:
    reset_and_seed()
    m = meter.Meter().start()
    time.sleep(3)
    print(f"idle window: {args.idle_minutes} min")
    s0 = m.snapshot()
    time.sleep(args.idle_minutes * 60)
    s1 = m.snapshot()
    sim_start = START + CRON_MINUTE * 60
    passes: list[dict] = []

    def cron() -> None:
        # A few minutes past each simulated hour, the pipeline publishes the hour that ended.
        clock = loadgen.Clock(sim_start, args.seconds_per_hour, real_start=load_t0)
        for h in range(1, int(args.sim_hours) + 1):
            at = START + h * 3600 + CRON_MINUTE * 60
            delay = (at - clock.now()) / clock.scale
            if delay > 0:
                time.sleep(delay)
            passes.append(pipeline_pass(at))
            print(
                f"  pipeline {passes[-1]['at']}: {passes[-1]['seconds']} s, ok={passes[-1]['ok']}"
            )

    load_t0 = time.monotonic()
    worker = threading.Thread(target=cron, daemon=True)
    worker.start()
    traffic = asyncio.run(
        loadgen.run(
            WEB,
            args.users,
            datetime.fromtimestamp(sim_start, UTC),
            args.sim_hours,
            args.seconds_per_hour,
            immutable_assets=args.immutable_assets,
            real_start=load_t0,
        )
    )
    worker.join()
    load_seconds = time.monotonic() - load_t0
    s2 = m.snapshot()
    m.stop()
    upstream = httpx.get(f"{UPSTREAM}/_sim/stats", timeout=10).json()
    volumes = {"pgdata": round(meter.volume_gb("ebsim_pgdata"), 3)}
    r = report(
        args.label or f"{args.users}u",
        args.users,
        args.sim_hours,
        diff(s0, s1),
        diff(s1, s2),
        traffic,
        passes,
        volumes,
        {"counts": upstream["counts"]},
        load_seconds,
    )
    r["backup"] = backup_check()
    show(r)
    print(f"  backup matches the site: {r['backup']['same']}")
    return r


def spike(args) -> dict:
    """Every user arrives cold within `--minutes` real minutes, just after an hour lands."""
    reset_and_seed()
    m = meter.Meter().start()
    time.sleep(3)
    s0 = m.snapshot()
    traffic = asyncio.run(
        loadgen.run(
            WEB,
            args.users,
            datetime.fromtimestamp(START + CRON_MINUTE * 60, UTC),
            1,
            3600,
            spike_minutes=args.minutes,
        )
    )
    s1 = m.snapshot()
    m.stop()
    d = diff(s0, s1)
    out = {
        "label": args.label or f"spike-{args.users}u",
        "users": args.users,
        "minutes": args.minutes,
        "traffic": traffic,
        "web": d["web"].as_dict(),
        "postgres": d["postgres"].as_dict(),
    }
    (DATA / "perf" / f"railway-{args.label or f'spike-{args.users}u'}.json").write_text(
        json.dumps(out, indent=2)
    )
    t = traffic
    print(
        f"spike: {t['total_requests']} requests, p50 {t['p50_ms']} ms, p95 {t['p95_ms']} ms, errors {sum(t['errors'].values())}; web peak {d['web'].peak_gb:.3f} GB / {d['web'].peak_vcpu:.2f} vCPU, postgres peak {d['postgres'].peak_gb:.3f} GB / {d['postgres'].peak_vcpu:.2f} vCPU"
    )
    return out


def switch(args) -> dict:
    """A league switch on the real pages: a server following Mirage (which had ended four
    days earlier) with Allflame announced for its real launch, passes hourly from two
    hours before the launch to four after. After each pass, what the site shows."""
    launch = LAUNCH
    announced = f"EB_NEXT_LEAGUE={LEAGUE}\nEB_NEXT_LEAGUE_START={iso(launch)}\n"
    first = launch - 2 * 3600 + CRON_MINUTE * 60
    reset_and_seed(["--league", "Mirage", "--drop", LEAGUE], first, announced)
    steps = []
    for h in range(-1, 5):
        at = launch + h * 3600 + CRON_MINUTE * 60
        p = pipeline_pass(at, missing_empty=True)
        time.sleep(16)  # the web trusts its data version for 15 s
        status = httpx.get(f"{WEB}/api/status", timeout=10).json()
        names = [lg["name"] for lg in status["leagues"]]
        missed = httpx.get(f"{WEB}/api/missed/{names[0]}", timeout=30) if names else None
        steps.append(
            {
                "at": iso(at),
                "ok": p["ok"],
                "seconds": p["seconds"],
                "pipeline": p["result"],
                "site_leagues": names,
                "latest_hour": status["leagues"][0]["latest_hour"] if names else None,
                "upcoming": (status.get("upcoming") or {}).get("name"),
                "missed_status": missed.status_code if missed else None,
            }
        )
        print(json.dumps(steps[-1]))
    upstream = httpx.get(f"{UPSTREAM}/_sim/stats", timeout=10).json()["counts"]
    backed_up = backup_check()
    print(f"backup matches the site: {backed_up['same']}")
    out = {"label": "switch", "steps": steps, "upstream": upstream, "backup": backed_up}
    (DATA / "perf" / "railway-switch.json").write_text(json.dumps(out, indent=2))
    print(f"upstream requests: {upstream}")
    NEXT_ENV.write_text("")
    return out


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="a simulated day of visitors")
    r.add_argument("--users", type=int, default=100)
    r.add_argument("--sim-hours", type=float, default=24)
    r.add_argument(
        "--seconds-per-hour",
        type=float,
        default=60,
        help="real seconds per simulated hour (3600 = real time)",
    )
    r.add_argument("--idle-minutes", type=float, default=10)
    r.add_argument(
        "--immutable-assets",
        action="store_true",
        help="visitors treat /assets/* as cached for a year",
    )
    r.add_argument("--label")
    s = sub.add_parser("spike", help="all users at once, cold caches")
    s.add_argument("--users", type=int, default=1000)
    s.add_argument("--minutes", type=float, default=5)
    s.add_argument("--label")
    sub.add_parser("switch", help="a league switch, Mirage to Allflame, on the real pages")
    sub.add_parser("down", help="remove the simulation's containers and volumes")
    args = ap.parse_args()
    if args.cmd == "run":
        run(args)
    elif args.cmd == "spike":
        spike(args)
    elif args.cmd == "switch":
        switch(args)
    else:
        sh([*COMPOSE, "--profile", "cron", "down", "-v", "--remove-orphans"])


if __name__ == "__main__":
    main()
