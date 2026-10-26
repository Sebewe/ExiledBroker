"""Write tests/fixtures/preview_sample.json: a small pre-launch preview snapshot (every
key kind of preview/snapshot.py) for the API's and the frontend's tests, and for the
preview's streams to build against before the real snapshot exists.

    .venv/bin/python tests/fixtures/make_preview_sample.py

It replays Mirage's first 30 hours (mirage_launch.json.gz) through the live loader
with the test's fake exchange (no network), and records what the site's API answered
at three points it calls days 1, 2 and 3 (24, 28 and 30 hours in: the replay is
short, and its recap only finds trades late). Price check's items are limited to a handful (the movers and Divine Orb), and
the reveal's documents are computed from the replay's last hours. The real snapshot
(`eb preview build`) has days 1, 3, 5 and 7 and every item."""

import json
import os
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
os.environ["EB_DATA_DIR"] = tempfile.mkdtemp(prefix="eb-preview-sample-")
for name in ("EB_DATABASE_URL", "EB_BACKUP_URL", "EB_HEALTHCHECK_URL", "EB_ORIGIN_KEY"):
    os.environ[name] = ""

from fastapi.testclient import TestClient

from exiledbroker.api import deps
from exiledbroker.api.app import create_app
from exiledbroker.config import Settings
from exiledbroker.ingest import currency_exchange as cx
from exiledbroker.ingest.live import sync_live
from exiledbroker.preview import snapshot
from exiledbroker.services import cross_market, divination
from exiledbroker.services.missed import BUFFER
from exiledbroker.storage import db
from test_currency_exchange import FakeExchange, client_for
from test_live_pipeline import LAUNCH, PAGES, store_reference_data

LEAGUE = "Mirage"
# Sample day -> hours of the replay loaded. Stand-ins: the replay is 30 hours long and
# its recap only finds trades from hour 28, so "days" 2 and 3 are 28 and 30 hours in.
DAYS = {1: 24, 2: 28, 3: 30}
DEFAULT_DAY = 2
NEXT_HOURS = 24
OUT = HERE / "preview_sample.json"


def load(s: Settings, server: FakeExchange, hours_in: int) -> None:
    server.now = LAUNCH + hours_in * 3600
    now = cx.from_ts(server.now) + timedelta(minutes=10)
    with client_for(s, server) as c:
        sync_live(c, s, LEAGUE, now=now, earliest=cx.from_ts(LAUNCH - 72 * 3600))


def get(client: TestClient, path: str):
    r = client.get(path)
    assert r.status_code == 200, (path, r.text)
    return r.json()


def _hour(iso: str) -> datetime:
    return datetime.fromisoformat(iso).replace(tzinfo=None)


def _outcome(kind, item_id, paid_by_hour: dict, cutoff: datetime, known: int, direction=None):
    paid = [paid_by_hour.get(cutoff + timedelta(hours=k)) for k in range(1, known + 1)]
    return {
        "kind": kind,
        "item_id": item_id,
        "direction": direction,
        "paid": paid,
        "paid_hours": sum(1 for p in paid if p),
        "traded_hours": sum(1 for p in paid if p is not None),
        "next_hour_paid": paid[0] if paid else None,
        "still_paid": any(paid[18:]) if known >= NEXT_HOURS else None,
    }


def recap_next(con, windows: list[dict], last_hour: datetime) -> dict:
    """Did each of the recap's trades keep paying over the next 24 hours (as far as the
    replay goes: its last loaded hour is `last_hour`)?"""
    cutoff = _hour(windows[0]["latest_hour"])
    known = max(0, min(NEXT_HOURS, int((last_hour - cutoff).total_seconds() // 3600)))
    trades: dict[tuple, dict] = {}
    for w in windows:
        for loop in w["loops"]:
            key = ("loop", loop["item_id"], loop["direction"])
            if key in trades:
                continue
            hours = cross_market.hourly(
                con, [LEAGUE], [loop["item_id"]], direction=loop["direction"], since=cutoff
            )
            by_hour = {r["observed_at"]: r["edge"] > BUFFER for r in hours.iter_rows(named=True)}
            trades[key] = _outcome(
                "loop", loop["item_id"], by_hour, cutoff, known, loop["direction"]
            )
        for card in w["cards"]:
            key = ("card", card["item_id"], None)
            if key in trades:
                continue
            hours = divination.hourly_turn_ins(con, LEAGUE, [card["item_id"]], since=cutoff)
            hours = hours.drop_nulls("margin") if hours.height else hours
            by_hour = {r["observed_at"]: r["margin"] > 0 for r in hours.iter_rows(named=True)}
            trades[key] = _outcome("card", card["item_id"], by_hour, cutoff, known)
        for flip in w["flips"]:
            key = ("flip", flip["item_id"], None)
            if key in trades:
                continue
            hours = db.frame(
                con,
                "SELECT observed_at, chaos_low, chaos_high FROM price_observation "
                "WHERE item_id = ? AND source = 'ggg-exchange-hourly' AND observed_at > ? "
                "AND chaos_low IS NOT NULL",
                [flip["item_id"], cutoff],
            )
            by_hour = {
                r["observed_at"]: r["chaos_low"] <= flip["bid"] and r["chaos_high"] >= flip["ask"]
                for r in hours.iter_rows(named=True)
            }
            trades[key] = _outcome("flip", flip["item_id"], by_hour, cutoff, known)
    return {
        "latest_hour": windows[0]["latest_hour"],
        "hours": known,
        "trades": list(trades.values()),
    }


def main() -> None:
    s = Settings(request_min_interval=0)
    store_reference_data(s)
    server = FakeExchange(PAGES, now=LAUNCH)
    docs: dict[str, object] = {}
    days, missed, items = [], {}, set()
    for day, hours_in in DAYS.items():
        load(s, server, hours_in)
        deps.reset()
        client = TestClient(create_app())
        league = next(lg for lg in get(client, "/api/status")["leagues"] if lg["name"] == LEAGUE)
        days.append({"day": day, "league": league})
        missed[day] = get(client, f"/api/missed/{LEAGUE}")
        docs[snapshot.day_key(day, "missed")] = missed[day]
        index = get(client, f"/api/price-check/{LEAGUE}")
        listed = {x["item_id"] for x in index["items"]}
        # A handful of items: the movers (up to 4) and Divine Orb (judged in Chaos).
        chosen = [*index["movers"][:4], "currency:divine-orb"]
        chosen = [i for i in dict.fromkeys(chosen) if i in listed]
        index["movers"] = [i for i in index["movers"] if i in chosen]
        index["items"] = [x for x in index["items"] if x["item_id"] in chosen]
        docs[snapshot.day_key(day, "price-check")] = index
        for item_id in chosen:
            doc = get(client, f"/api/price-check/{LEAGUE}/{item_id}")
            docs[snapshot.day_key(day, "price-check", item_id)] = doc
            items.add(item_id)
        docs[snapshot.day_key(day, "launch-picks")] = get(client, "/api/launch/picks")

    # What happened next, from the replay's end (the real snapshot loads to day 10).
    deps.reset()
    client = TestClient(create_app())
    for item_id in sorted(items):
        doc = get(client, f"/api/price-check/{LEAGUE}/{item_id}")
        docs[snapshot.next_key(item_id)] = {
            k: doc[k] for k in ("item_id", "name", "unit", "series")
        }
    end = cx.from_ts(LAUNCH + (max(DAYS.values()) - 1) * 3600).replace(tzinfo=None)
    with db.session(s.db_path, read_only=True) as con:
        for day in DAYS:
            docs[snapshot.day_key(day, "recap-next")] = recap_next(con, missed[day], end)

    launched = days[0]["league"]["launched_at"]
    docs[snapshot.MANIFEST] = {
        "league": LEAGUE,
        "launched_at": launched,
        "days": days,
        "default_day": DEFAULT_DAY,
        "next_until": f"{end:%Y-%m-%dT%H:%M:%S}Z",
        "built_at": "2026-10-27T00:00:00Z",
        "version": "sample-1",
    }
    # Every document goes through its model, as the real snapshot's do when written.
    docs = {key: snapshot.decode(snapshot.encode(key, doc)) for key, doc in docs.items()}
    OUT.write_text(json.dumps(dict(sorted(docs.items())), indent=None, separators=(",", ":")))
    print(f"{OUT.name}: {len(docs)} documents, {OUT.stat().st_size / 1024:.0f} kB")


if __name__ == "__main__":
    main()
