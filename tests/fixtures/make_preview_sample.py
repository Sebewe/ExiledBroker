"""Write web/src/test/preview_sample.json: a small pre-launch preview snapshot (every
key kind of preview/snapshot.py) for the API's and the frontend's tests, and for the
preview's streams to build against before the real snapshot exists.

    .venv/bin/python tests/fixtures/make_preview_sample.py

It replays Mirage's first 30 hours (mirage_launch.json.gz) through the live loader
with the test's fake exchange (no network), and records what the site's API answered
at three points it calls days 1, 2 and 3 (24, 28 and 30 hours in: the replay is
short, and its recap only finds trades late), and every hour from 24 to 29 for the
trading game. Price check's items are limited to a handful (the movers and Divine Orb), and
the reveal's documents are computed from the replay's last hours. The real snapshot
(`eb preview build`) has days 1, 3, 5 and 7 and every item."""

import json
import os
import sys
import tempfile
from datetime import timedelta
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
from exiledbroker.preview.build import game_hours  # the snapshot's own
from exiledbroker.storage import db
from test_currency_exchange import FakeExchange, client_for
from test_live_pipeline import LAUNCH, PAGES, store_reference_data

LEAGUE = "Mirage"
# Sample day -> hours of the replay loaded. Stand-ins: the replay is 30 hours long and
# its recap only finds trades from hour 28, so "days" 2 and 3 are 28 and 30 hours in.
DAYS = {1: 24, 2: 28, 3: 30}
DEFAULT_DAY = 2
OUT = HERE.parents[1] / "web" / "src" / "test" / "preview_sample.json"  # the frontend reads it too


def load(s: Settings, server: FakeExchange, hours_in: int) -> None:
    server.now = LAUNCH + hours_in * 3600
    now = cx.from_ts(server.now) + timedelta(minutes=10)
    with client_for(s, server) as c:
        sync_live(c, s, LEAGUE, now=now, earliest=cx.from_ts(LAUNCH - 72 * 3600))


def get(client: TestClient, path: str):
    r = client.get(path)
    assert r.status_code == 200, (path, r.text)
    return r.json()


def main() -> None:
    s = Settings(request_min_interval=0)
    store_reference_data(s)
    server = FakeExchange(PAGES, now=LAUNCH)
    docs: dict[str, object] = {}
    days, items, games = [], set(), {}
    at_day = {h: d for d, h in DAYS.items()}
    for hours_in in range(min(DAYS.values()), max(DAYS.values()) + 1):
        load(s, server, hours_in)
        deps.reset()
        client = TestClient(create_app())
        league = next(lg for lg in get(client, "/api/status")["leagues"] if lg["name"] == LEAGUE)
        if hours_in < max(DAYS.values()):  # the trading game's hours: those with one after
            games[hours_in] = {
                "latest_hour": league["latest_hour"],
                "divine_chaos": league["divine_chaos"],
                "recap": get(client, f"/api/missed/{LEAGUE}"),
            }
        if (day := at_day.get(hours_in)) is None:
            continue
        days.append({"day": day, "league": league})
        docs[snapshot.day_key(day, "missed")] = get(client, f"/api/missed/{LEAGUE}")
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
        for n, doc in game_hours(con, LEAGUE, games, end).items():
            docs[snapshot.game_key(n)] = doc

    launched = days[0]["league"]["launched_at"]
    docs[snapshot.MANIFEST] = {
        "league": LEAGUE,
        "launched_at": launched,
        "days": days,
        "game": {"first": min(games), "last": max(games)},
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
