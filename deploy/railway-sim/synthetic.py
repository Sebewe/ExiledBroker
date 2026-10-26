"""A stand-in for the local copy, for running the Railway simulation without real data
(a fresh checkout, a cloud container): Allflame's first 3 published hours exactly as
GGG served them (tests/fixtures/allflame_start.json.gz, every Allflame market), then
`--hours` more hours made from the third: all of its 429 markets trading, each price
on its own random walk and each volume with noise. A made-up Mirage fortnight before
it stands in for the Launch history (the pipeline refuses a server without one). Both
are loaded the way `eb live sync` loads a league, from a fake exchange in this process:
nothing reaches GGG or poe.ninja.

    .venv/bin/python deploy/railway-sim/synthetic.py /tmp/eb-synthetic --hours 60
    EB_SIM_DATA=/tmp/eb-synthetic .venv/bin/python deploy/railway-sim/run.py run --users 100

What it lacks against the real copy, so the bill it gives is low on what the data adds:
about 55 % of a mature league's markets (~360 Chaos-market items an hour against ~650),
real past leagues, and the Backtest and sell helper reports (empty). The replay starts
48 hours in, as on the real copy, so `--hours` needs 48 plus the simulated hours and one
to spare."""

import argparse
import gzip
import json
import random
import sys
from datetime import timedelta
from pathlib import Path

import httpx

from exiledbroker.config import Settings
from exiledbroker.ingest import core_pool, item_names, loot_filter, reference
from exiledbroker.ingest import currency_exchange as cx
from exiledbroker.ingest.http import PoliteClient
from exiledbroker.ingest.live import sync_live
from exiledbroker.storage import db

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests" / "fixtures" / "allflame_start.json.gz"
CHAOS = "Metadata/Items/Currency/CurrencyRerollRare"
PAST, PAST_LAUNCH, PAST_HOURS = "Mirage", 1772827200, 16 * 24  # Mirage's real launch hour


def made_up_hours(template: list[dict], first: int, hours: int, seed: int = 7) -> dict:
    """`hours` pages after `first` with every market of the template trading (two thirds
    of them hadn't yet in the third hour): each at the template's price where it traded,
    else a made-up one, on a random walk (±3 % an hour), with noisy volumes."""
    rng = random.Random(seed)
    start = {}
    for m in template:
        a, b = m["market_pair"]
        x, ref = (b, a) if a == CHAOS else (a, b)  # x is priced in ref
        vol = m["volume_traded"]
        traded = vol[x] > 0 and vol[ref] > 0
        start[m["market_id"]] = (x, ref, vol[ref] / vol[x] if traded else rng.lognormvariate(0, 2))
    walk = {k: 1.0 for k in start}
    pages = {}
    for h in range(hours):
        markets = []
        for m in template:
            x, ref, price = start[m["market_id"]]
            walk[m["market_id"]] *= rng.lognormvariate(0, 0.03)
            price *= walk[m["market_id"]]
            units = max(1, round(rng.lognormvariate(3.5, 1.2)))
            m = json.loads(json.dumps(m))
            m["volume_traded"] = {x: units, ref: max(1, round(units * price))}
            m["lowest_ratio"] = {x: 1, ref: price * 0.97}
            m["highest_ratio"] = {x: 1, ref: price * 1.03}
            markets.append(m)
        pages[first + h * 3600] = markets
    return pages


def store_reference_data(s: Settings, base_items: dict, league: str) -> None:
    """RePoE's names, the core pool and the loot filter as `eb live` stores them, fresh,
    so the load fetches none of them (as tests/test_live_pipeline.py does)."""
    names = {v["name"] for v in base_items.values()}
    cards = sorted(
        v["name"] for v in base_items.values() if v.get("item_class") == "DivinationCard"
    )
    ninja = f"{s.poe_ninja_base_url}/poe1/api/economy"
    with db.session(s.db_path) as con:
        db.init_schema(con)
        reference.put(con, item_names.KEY, base_items, s.repoe_base_items_url)
        reference.put(con, core_pool.LEAGUES_KEY, [{"id": league}], f"{ninja}/leagues")
        for t in {t for types in core_pool.SOURCES.values() for t in types}:
            reference.put(
                con,
                core_pool.snapshot_key(t),
                {"league": league, "names": sorted(names)},
                f"{ninja}/exchange/current/overview?league={league}&type={t}",
            )
        reference.put(
            con,
            loot_filter.KEY,
            {"tiers": {c: "t1" for c in cards}, "shown": cards},
            s.loot_filter_url.format(strictness=s.loot_filter_strictness),
        )


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("out", type=Path, help="the stand-in data directory (EB_SIM_DATA)")
    ap.add_argument("--hours", type=int, default=80, help="hours after launch to make")
    args = ap.parse_args()
    if (args.out / "exiledbroker.duckdb").exists():
        sys.exit(f"{args.out} already has a database: remove it first")
    with gzip.open(FIXTURE, "rt") as f:
        fixture = json.load(f)
    league, launch = fixture["league"], fixture["launch"]
    pages = {int(ts): p["markets"] for ts, p in fixture["pages"].items()}
    third = pages[max(pages)]
    pages |= made_up_hours(third, max(pages) + 3600, args.hours - len(pages))

    s = Settings(data_dir=args.out, request_min_interval=0)
    store_reference_data(s, fixture["base_items"], league)
    # A finished league before it, made the same way, for the Launch history the picks
    # are ranked from (a server without one isn't seeded: the pipeline refuses it).
    past = made_up_hours(third, PAST_LAUNCH, PAST_HOURS, seed=11)
    past = {ts: [m | {"league": PAST} for m in ms] for ts, ms in past.items()}
    load(s, PAST, PAST_LAUNCH, PAST_LAUNCH + PAST_HOURS * 3600, past)
    load(s, league, launch, launch + args.hours * 3600, pages)


def load(s: Settings, league: str, launch: int, end: int, pages: dict) -> None:
    """`eb live sync` of `league` up to `end`, from these pages instead of GGG."""

    def handler(request: httpx.Request) -> httpx.Response:
        ts = int(request.url.path.rsplit("/", 1)[-1])
        if ts >= end:
            return httpx.Response(200, json={"next_change_id": ts, "markets": []})
        return httpx.Response(200, json={"next_change_id": ts + 3600, "markets": pages.get(ts, [])})

    with PoliteClient(s, transport=httpx.MockTransport(handler)) as client:
        status = sync_live(
            client,
            s,
            league,
            now=cx.from_ts(end) + timedelta(minutes=10),
            earliest=cx.from_ts(launch - 72 * 3600),
        )
    print(f"{league}: {(end - launch) // 3600} hours into {s.data_dir} ({status})")


if __name__ == "__main__":
    main()
