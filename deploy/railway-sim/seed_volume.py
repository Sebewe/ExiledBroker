"""Seed the simulated pipeline volume (run by run.py inside a container, as root).

What a real deploy would copy onto the Railway volume: the research database and the
raw GGG pages. For the replay, the live league (Allflame) is cut back to `--start`:
its later rows are deleted and its later pages left out, so the pipeline fetches
them from the upstream stand-in one hour at a time. Stored reference sources are
pointed at the stand-in, so their checks are conditional requests answered 304
instead of fresh downloads (a changed URL counts as a new source).

    python seed_volume.py --start 1785103200 --league Allflame
"""

import argparse
import json
import os
import pwd
import shutil
from datetime import UTC, datetime
from pathlib import Path

import duckdb

SRC, DATA, CACHE = Path("/src"), Path("/data"), Path("/sim-cache")
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
    ap.add_argument("--start", type=int, required=True, help="first hour (unix) not yet loaded")
    ap.add_argument("--league", default="Allflame")
    args = ap.parse_args()
    start = datetime.fromtimestamp(args.start, UTC).replace(tzinfo=None)

    for p in DATA.iterdir():
        shutil.rmtree(p) if p.is_dir() else p.unlink()
    shutil.copy2(SRC / "exiledbroker.duckdb", DATA / "exiledbroker.duckdb")
    pages_in, pages_out = SRC / "raw/ggg/currency_exchange", DATA / "raw/ggg/currency_exchange"
    pages_out.mkdir(parents=True)
    copied = 0
    for page in pages_in.glob("*.json.gz"):
        if int(page.name.split(".")[0]) < args.start:
            shutil.copy2(page, pages_out / page.name)
            copied += 1

    con = duckdb.connect(str(DATA / "exiledbroker.duckdb"))
    lid = con.execute("SELECT id FROM league WHERE name = ?", [args.league]).fetchall()[0][0]
    for table, col in (
        ("price_observation", "observed_at"),
        ("cross_market_hour", "observed_at"),
        ("exchange_hour_loaded", "hour"),
    ):
        con.execute(f"DELETE FROM {table} WHERE league_id = ? AND {col} >= ?", [lid, start])
    hours = con.execute(
        "SELECT count(*) FROM exchange_hour_loaded WHERE league_id = ?", [lid]
    ).fetchall()[0][0]
    reference = {}
    for key, content in con.execute("SELECT key, content FROM reference_data").fetchall():
        reference[key] = json.loads(content)
        if url := sim_url(key, args.league):
            con.execute("UPDATE reference_data SET source_url = ? WHERE key = ?", [url, key])
    con.execute("CHECKPOINT")
    con.close()
    CACHE.mkdir(exist_ok=True)
    (CACHE / "reference.json").write_text(json.dumps(reference))

    app = pwd.getpwnam("app")
    for root, dirs, files in os.walk(DATA):
        for name in [*dirs, *files]:
            os.chown(os.path.join(root, name), app.pw_uid, app.pw_gid)
    os.chown(DATA, app.pw_uid, app.pw_gid)
    print(
        f"seeded: {copied} pages before {start:%Y-%m-%d %H:%M}, {args.league} {hours} hours loaded"
    )


if __name__ == "__main__":
    main()
