"""`eb preview build` (preview/build.py) on the recorded Mirage replay: every key of the
snapshot, no requests, the history rewound, and a missing page refused."""

from datetime import datetime, timedelta

import pytest

from exiledbroker.config import Settings
from exiledbroker.ingest import currency_exchange as cx
from exiledbroker.ingest.live import sync_live
from exiledbroker.preview import build as pb
from exiledbroker.preview import snapshot
from exiledbroker.storage import db
from test_currency_exchange import FakeExchange, client_for
from test_live_pipeline import LAUNCH, PAGES, store_reference_data

LEAGUE = "Mirage"
# The replay is 30 hours long: "days" of 6 hours (1, 3 and 5 are 6, 18 and 30 hours in).
SHORT = {"days": (1, 3, 5), "default_day": 3, "next_day": 5, "day_hours": 6, "game": False}


@pytest.fixture(scope="module")
def research(tmp_path_factory):
    """A research database with Mirage's 30 hours loaded and its pages on disk, plus a
    Launch history and Price check paths that include Mirage and a later league."""
    s = Settings(data_dir=tmp_path_factory.mktemp("preview"), request_min_interval=0)
    store_reference_data(s)
    server = FakeExchange(PAGES, now=LAUNCH + 30 * 3600)
    with client_for(s, server) as client:
        now = cx.from_ts(server.now) + timedelta(minutes=10)
        sync_live(client, s, LEAGUE, now=now, earliest=cx.from_ts(LAUNCH - 72 * 3600))
    launch = cx.from_ts(LAUNCH).replace(tzinfo=None)
    leagues = {
        "Old": launch - timedelta(days=120),
        LEAGUE: launch,
        "Later": launch + timedelta(days=120),
    }
    with db.session(s.db_path) as con:
        for name, start in leagues.items():
            con.execute(
                "INSERT INTO launch_history VALUES (?, ?, 'currency:chaos-orb', 'day1', 0.01, 5)",
                [name, start],
            )
            con.execute(
                "INSERT INTO price_path_league VALUES (?, ?, 'currency:chaos-orb', '[0.1]', '[0.2]')",
                [name, start],
            )
    return s


def test_build_writes_every_key_offline(research):
    result = pb.build(research, LEAGUE, **{**SHORT, "game": True})
    assert result.requests == 0
    with db.session(research.db_path, read_only=True) as con:
        keys = snapshot.keys(con)
        manifest = snapshot.read(con, snapshot.MANIFEST)
        docs = {k: snapshot.read(con, k) for k in keys}
    assert len(keys) == result.documents
    assert all(snapshot.model_for(k) is not None for k in keys)  # every key is a known kind
    assert [d["day"] for d in manifest["days"]] == [1, 3, 5]
    assert manifest["default_day"] == 3 and manifest["league"] == LEAGUE
    latest = [datetime.fromisoformat(d["league"]["latest_hour"]) for d in manifest["days"]]
    assert [(t - latest[0]).total_seconds() / 3600 for t in latest] == [0, 12, 24]
    for day in (1, 3, 5):
        for what in ("missed", "price-check", "launch-picks"):
            assert snapshot.day_key(day, what) in keys
        index = docs[snapshot.day_key(day, "price-check")]
        assert index["items"]
        for x in index["items"]:  # every listed item, and its reveal series
            assert snapshot.day_key(day, "price-check", x["item_id"]) in keys
            assert snapshot.next_key(x["item_id"]) in keys
    # The trading game: every hour from day 1's end to the reveal's last, each with
    # its recap, the orders it'd take and the flip items' prices.
    assert manifest["game"] == {"first": 6, "last": 29}
    games = [docs[snapshot.game_key(n)] for n in range(6, 30)]
    flipped_ever = {x["item_id"] for g in games for w in g["recap"] for x in w["flips"]}
    hours = [datetime.fromisoformat(g["latest_hour"]) for g in games]
    assert [(h - hours[0]).total_seconds() / 3600 for h in hours] == list(range(24))
    assert hours[0] == latest[0]
    for g in games:
        for o in g["orders"]:
            assert o["kind"] in ("loop", "card")
            assert (o["spent"] is not None) == bool(o["filled"])
            if o["settle_at"]:
                assert o["settle_at"] > g["latest_hour"]
        assert set(g["prices"]) <= flipped_ever
    # The recap finds trades only late in the replay: day 5's are judged on 0 known hours.
    recaps = [k for k in keys if k.endswith("/recap-next")]
    assert recaps
    for key in recaps:
        assert docs[key]["hours"] <= pb.NEXT_HOURS
        for t in docs[key]["trades"]:  # the Backtest's fills, one per known hour
            n = docs[key]["hours"]
            assert len(t["paid"]) == len(t["filled"]) == len(t["pnl"]) == len(t["spent"]) == n
            assert t["paid_hours"] <= t["traded_hours"] <= t["orders"]
            assert t["fills"] <= t["orders"]
    # The reveal's series run to the last loaded hour.
    series = docs[snapshot.next_key("currency:divine-orb")]["series"]
    assert series[-1][0] == manifest["next_until"]
    # The replay's database is gone.
    assert not (research.data_dir / "preview-build.duckdb").exists()


def test_each_build_gets_a_new_version(research):
    first = pb.build(research, LEAGUE, **SHORT)
    second = pb.build(research, LEAGUE, **SHORT)
    assert first.version != second.version
    with db.session(research.db_path, read_only=True) as con:
        assert snapshot.read(con, snapshot.MANIFEST)["version"] == second.version


def test_history_is_rewound(research):
    """The replay's Launch history and paths hold only leagues before the replayed one."""
    replay = research.model_copy(update={"db_filename": "rewind-check.duckdb"})
    pb._prepare(research, replay, LEAGUE, cx.from_ts(LAUNCH).replace(tzinfo=None))
    with db.session(replay.db_path, read_only=True) as con:
        for table in pb.REWOUND:
            assert [r[0] for r in db.rows(con, f"SELECT DISTINCT league FROM {table}")] == ["Old"]
        assert db.rows(con, "SELECT name, exchange_tracked FROM league") == [(LEAGUE, True)]


def test_a_missing_page_is_refused_not_fetched(research):
    with db.session(research.db_path, read_only=True) as con:
        before = snapshot.read(con, snapshot.MANIFEST)
    page = cx.page_path(research, LAUNCH + 20 * 3600)
    hidden = page.with_suffix(".hidden")
    page.rename(hidden)
    try:
        with pytest.raises(pb.OfflineError, match="isn't on disk"):
            pb.build(research, LEAGUE, **SHORT)
    finally:
        hidden.rename(page)
    with db.session(research.db_path, read_only=True) as con:
        assert snapshot.read(con, snapshot.MANIFEST) == before  # the last snapshot stands
    assert not (research.data_dir / "preview-build.duckdb").exists()


def test_bad_days_are_rejected(research):
    with pytest.raises(ValueError):
        pb.build(research, LEAGUE, days=(1, 3), default_day=5)
    with pytest.raises(ValueError):
        pb.build(research, LEAGUE, days=(1, 7), default_day=1, next_day=5)
    with pytest.raises(LookupError):
        pb.build(research, "Nowhere")
