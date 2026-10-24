"""Seed the simulated server's Postgres (run by run.py inside a pipeline container, as
root) the way a real deploy does with `eb site seed --hosted`: from the local copy.

For the replay, the live league (Allflame) is cut back to `--start` in a scratch copy
of the research database: its later rows are deleted, so the seeded server has only
the hours before it and the pipeline then fetches the rest from the upstream
stand-in, one hour at a time. Each complete league is reduced to its Launch history
(as `eb launch picks` does) and the picks are ranked from it, and to its Farming
history (as `eb farming history` does), so neither holds a league cut back or dropped
from the copy. Stored reference
sources are pointed at the stand-in, so their checks are conditional requests
answered 304 instead of fresh downloads (a changed URL counts as a new source).

    python seed_server.py --start 1785103200 --league Allflame
    python seed_server.py --league Mirage --drop Allflame   # just before a switch

`--drop` removes later leagues from the copy, as if they hadn't happened yet: the
league switch replay seeds a server following Mirage, before Allflame launched.
"""

import argparse
import json
import os
import shutil
from datetime import UTC, datetime
from pathlib import Path

import duckdb
import psycopg

from exiledbroker.config import Settings
from exiledbroker.services import item_history, launch_picks
from exiledbroker.storage import db, site

SRC, WORK, CACHE = Path("/src"), Path("/tmp/seed"), Path("/sim-cache")
UPSTREAM = "http://upstream:9000"


def sim_url(key: str, league: str) -> str | None:
    if key == "repoe/base_items":
        return f"{UPSTREAM}/repoe/base_items.min.json"
    if key == "neversink/divination_tiers":
        return f"{UPSTREAM}/filter/2-SEMI-STRICT.filter"
    if key == "poe_ninja/leagues":
        return f"{UPSTREAM}/ninja/poe1/api/economy/leagues"
    if key.startswith("core_pool/type/"):
        t = key.rsplit("/", 1)[1]
        return (
            f"{UPSTREAM}/ninja/poe1/api/economy/exchange/current/overview?league={league}&type={t}"
        )
    return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", type=int, help="first hour (unix) not yet loaded")
    ap.add_argument("--league", default="Allflame")
    ap.add_argument("--drop", action="append", default=[], help="a later league to remove")
    args = ap.parse_args()
    start = datetime.fromtimestamp(args.start or 2**31, UTC).replace(tzinfo=None)

    shutil.rmtree(WORK, ignore_errors=True)
    WORK.mkdir(parents=True)
    copy = WORK / "exiledbroker.duckdb"
    shutil.copy2(SRC / "exiledbroker.duckdb", copy)
    con = duckdb.connect(str(copy))
    db.init_schema(con)
    for name in args.drop:
        drop = db.scalar(con, "SELECT id FROM league WHERE name = ?", [name])
        for table in ("price_observation", "cross_market_hour", "exchange_hour_loaded"):
            con.execute(f"DELETE FROM {table} WHERE league_id = ?", [drop])
        con.execute("DELETE FROM ingest_load WHERE league_id = ?", [drop])
        con.execute("UPDATE league SET exchange_tracked = FALSE WHERE id = ?", [drop])
    lid = db.scalar(con, "SELECT id FROM league WHERE name = ?", [args.league])
    for table, col in (
        ("price_observation", "observed_at"),
        ("cross_market_hour", "observed_at"),
        ("exchange_hour_loaded", "hour"),
    ):
        con.execute(f"DELETE FROM {table} WHERE league_id = ? AND {col} >= ?", [lid, start])
    hours = db.scalar(con, "SELECT count(*) FROM exchange_hour_loaded WHERE league_id = ?", [lid])
    # `eb launch picks`: the league cut back mid-fortnight isn't a reference yet.
    con.execute("DELETE FROM launch_history")
    for league in launch_picks.complete_leagues(con):
        launch_picks.capture(con, league)
    refs = launch_picks.captured_leagues(con)[: launch_picks.REFERENCE_LEAGUES]
    launch_picks.build(con, refs)
    # `eb farming history`: the copy's item_day_history may hold the cut-back or dropped
    # leagues (their future days); recapture the same leagues as the Launch history.
    local = Settings(data_dir=SRC)
    con.execute(f"DELETE FROM {item_history.HISTORY}")
    items = item_history.basket_items(con, local)
    farmed = launch_picks.captured_leagues(con)
    for league in farmed:
        item_history.capture(con, league, items)
    reference = {}
    for key, content in db.rows(con, "SELECT key, content FROM reference_data"):
        reference[key] = json.loads(content)
        if url := sim_url(key, args.league):
            con.execute("UPDATE reference_data SET source_url = ? WHERE key = ?", [url, key])
    CACHE.mkdir(exist_ok=True)
    (CACHE / "reference.json").write_text(json.dumps(reference))

    # `eb site seed --hosted`: rows, histories and picks, and the loaded hours' pages.
    with psycopg.connect(os.environ["EB_DATABASE_URL"], autocommit=True) as pg:
        result = site.seed(con, pg, [args.league], local)
    con.close()
    shutil.rmtree(WORK)
    print(
        f"seeded: {args.league} {hours} hours before {start:%Y-%m-%d %H:%M}, "
        f"{result.rows.get('exchange_page', 0)} pages, picks from {', '.join(refs)}, "
        f"Farming history of {', '.join(farmed) or 'no league'}"
    )


if __name__ == "__main__":
    main()
