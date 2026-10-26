"""A league switch, replayed on the exchange's real pages (tests/fixtures/
league_switch.json.gz): the 2 hours before Allflame launched, when the previous
league (Mirage) had already ended and only Standard and an event league traded, then
Allflame's first 4 hours, every market as GGG served it.

What the real switches on disk show (docs/go-live.md): the old league stops trading
3–4 days before the next launches; the new league trades in its launch hour; the
response's shape doesn't change, but pages grow tenfold in the first hours and
items RePoE doesn't know yet trade from the start. So:
- the hosted pipeline keeps following the old league through the gap, switches to
  the announced one at its first published hour, then drops the old one;
- the loader's results don't depend on the order, size or extra fields of a page;
- items RePoE doesn't know yet are rechecked daily and, once named, the league is
  rebuilt from its stored pages, so an item never splits in two."""

import copy
import gzip
import json
import random
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from exiledbroker.api import app as app_module
from exiledbroker.api import deps
from exiledbroker.config import Settings
from exiledbroker.ingest import currency_exchange as cx
from exiledbroker.ingest import item_names, pipeline, reference
from exiledbroker.ingest.live import sync_live
from exiledbroker.storage import db
from test_api import endpoints
from test_currency_exchange import FakeExchange, client_for
from test_live_pipeline import FIXTURE as MIRAGE
from test_live_pipeline import store_reference_data

with gzip.open(Path(__file__).parent / "fixtures" / "league_switch.json.gz", "rt") as _f:
    SWITCH = json.load(_f)
LEAGUE, LAUNCH = SWITCH["league"], SWITCH["launch"]
PAGES = {int(ts): page["markets"] for ts, page in SWITCH["pages"].items()}
NEW_IDS = set(SWITCH["new_ids"])
H = 3600


def at(hours_in: int):
    """Six minutes past hour `hours_in` from Allflame's launch: the cron's moment."""
    return cx.from_ts(LAUNCH + hours_in * H) + timedelta(minutes=6)


def _settings(path: Path, base_items: dict | None = None) -> Settings:
    s = Settings(data_dir=path, request_min_interval=0)
    fixture = {**SWITCH, "base_items": base_items or SWITCH["base_items"]}
    store_reference_data(s, fixture)
    return s


def update(s, server, hours_in: int):
    server.now = LAUNCH + hours_in * H
    with client_for(s, server) as c:
        return sync_live(c, s, LEAGUE, now=at(hours_in), earliest=cx.from_ts(LAUNCH - 24 * H))


def _rows(s) -> dict:
    with db.session(s.db_path, read_only=True) as con:
        return {
            t: sorted(map(repr, db.rows(con, f"SELECT * FROM {t} ORDER BY ALL")))
            for t in ("price_observation", "cross_market_hour", "item")
        }


# --- The page's shape doesn't matter ----------------------------------------------


def _reshaped(markets: list[dict], seed: int) -> list[dict]:
    """The same trades, served differently: shuffled, each pair listed the other way
    round, numbers as floats, unknown fields, and padded with other leagues' markets
    (pages grow tenfold in a launch's first hours)."""
    rng = random.Random(seed)
    out = []
    for m in copy.deepcopy(markets):
        m["market_pair"] = m["market_pair"][::-1]
        for field in ("volume_traded", "lowest_stock", "highest_stock"):
            m[field] = {k: float(v) for k, v in (m.get(field) or {}).items()}
        m["new_field"] = {"anything": [1, 2]}
        out.append(m)
    padding = [
        {**copy.deepcopy(m), "league": f"Padding {i}"} for i in range(5) for m in markets[:50]
    ]
    out += padding
    rng.shuffle(out)
    return out


def test_the_loaders_results_dont_depend_on_the_pages_shape(tmp_path):
    plain = _settings(tmp_path / "plain")
    reshaped = _settings(tmp_path / "reshaped")
    served = {ts: _reshaped(markets, ts) for ts, markets in PAGES.items()}
    for s, pages in ((plain, PAGES), (reshaped, served)):
        server = FakeExchange(pages, now=LAUNCH)
        for h in range(1, 5):
            assert update(s, server, h).state == "updated"
    assert _rows(plain) == _rows(reshaped)


# --- RePoE lagging behind the launch ------------------------------------------------


def _hours(con, item_id: str) -> int:
    """Hours an item traded in (the arbitrage universe keeps every traded item)."""
    q = "SELECT count(DISTINCT observed_at) FROM cross_market_hour WHERE item_id = ?"
    return db.scalar(con, q, [item_id])


def test_items_repoe_doesnt_know_yet_are_reloaded_once_named(tmp_path, monkeypatch):
    lagging = {k: v for k, v in SWITCH["base_items"].items() if k not in NEW_IDS}
    s = _settings(tmp_path, lagging)
    server = FakeExchange(PAGES, now=LAUNCH)
    ages = []
    real = item_names.ensure_base_items

    def ensure(client, settings, con, max_age=item_names.MAX_AGE):
        ages.append(max_age)
        return real(client, settings, con, max_age)

    monkeypatch.setattr(item_names, "ensure_base_items", ensure)
    for h in range(1, 4):
        update(s, server, h)
    assert ages[-1] == item_names.UNKNOWN_MAX_AGE  # rechecked daily while unknown
    with db.session(s.db_path, read_only=True) as con:
        placeholders = db.rows(
            con,
            "SELECT id FROM item WHERE metadata_id = 'Metadata/Items/Currency/CurrencyDeepwater'",
        )
        placeholder_hours = _hours(con, "currency:currencydeepwater")
    assert placeholders == [("currency:currencydeepwater",)] and placeholder_hours >= 2

    # RePoE catches up: the next check downloads the new names.
    def caught_up(client, settings, con, max_age=item_names.MAX_AGE):
        ages.append(max_age)
        reference.put(con, item_names.KEY, SWITCH["base_items"], settings.repoe_base_items_url)
        return "downloaded"

    monkeypatch.setattr(item_names, "ensure_base_items", caught_up)
    before = len(server.requests)
    status = update(s, server, 4)
    # Rebuilt from the pages already stored: only the new hour was fetched.
    assert status.hours_added == 4 and server.requests[before:].count(LAUNCH + 3 * H) == 1
    assert set(server.requests[before:]) == {LAUNCH + 3 * H}
    with db.session(s.db_path, read_only=True) as con:
        assert _hours(con, "currency:currencydeepwater") == 0
        # One item, every hour it traded (the new one too), under its real name.
        assert _hours(con, "currency:dead-man-s-sulphur") == placeholder_hours + 1
    ages.clear()
    update(s, server, 4)
    assert ages == [item_names.MAX_AGE]  # all known again: weekly


# --- The hosted pipeline through a switch ---------------------------------------------


@pytest.fixture
def server_db(tmp_path, monkeypatch):
    """A server following Mirage (ended; its first hours loaded), seeded, with Allflame
    announced for its real launch hour."""
    monkeypatch.setenv("EB_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("EB_NEXT_LEAGUE", LEAGUE)
    monkeypatch.setenv("EB_NEXT_LEAGUE_START", cx.from_ts(LAUNCH).isoformat())
    base_items = {**MIRAGE["base_items"], **SWITCH["base_items"]}
    s = Settings(data_dir=tmp_path, request_min_interval=0)
    store_reference_data(s, {**SWITCH, "base_items": base_items})
    mirage = {int(ts): p["markets"] for ts, p in MIRAGE["pages"].items()}
    old = FakeExchange(mirage, now=MIRAGE["launch"] + 6 * H)
    with client_for(s, old) as c:
        sync_live(
            c,
            s,
            "Mirage",
            now=cx.from_ts(old.now) + timedelta(minutes=6),
            earliest=cx.from_ts(MIRAGE["launch"] - 24 * H),
        )
    with db.session(s.db_path) as con:
        con.execute(
            "INSERT INTO launch_history VALUES ('Keepers', '2025-10-31', 'currency:chaos-orb', "
            "'day1', 0.01, 5)"
        )
    return s


def run(s, server, hours_in: int):
    server.now = LAUNCH + hours_in * H
    before = len(server.requests)
    with client_for(s, server) as c:
        result = pipeline.run(c, s, now=at(hours_in))
    return result, server.requests[before:]


def api() -> TestClient:
    deps.reset()
    return TestClient(app_module.create_app())


def test_the_pipeline_follows_a_league_switch(server_db):
    s = server_db
    server = FakeExchange(PAGES, now=LAUNCH)
    # In the gap: Mirage has stopped trading; it stays the site's league, untouched.
    for h in (-2, -1):
        result, requests = run(s, server, h)
        assert (result.league, result.live.state) == ("Mirage", "not_running")
        assert len(requests) <= 2 and not result.dropped  # just the latest-hour check
    status = api().get("/api/status").json()
    assert [lg["name"] for lg in status["leagues"]] == ["Mirage"]
    assert status["upcoming"]["name"] == LEAGUE

    # Launch: Allflame trades from 22:00, published after 23:00. Mirage stays until then.
    result, _ = run(s, server, 0)
    assert (result.league, result.live.state, result.dropped) == (LEAGUE, "not_running", [])
    result, requests = run(s, server, 1)
    assert result.live.state == "updated" and result.live.hours_added == 1
    assert result.dropped == ["Mirage"]
    # The launch search started a day before the announcement, not in 2024.
    assert min(requests) >= LAUNCH - 24 * H and len(requests) <= 8
    status = api().get("/api/status").json()
    assert [lg["name"] for lg in status["leagues"]] == [LEAGUE] and status["upcoming"] is None

    for h in (2, 3, 4):
        result, requests = run(s, server, h)
        assert result.live.hours_added == 1 and requests == [LAUNCH + (h - 1) * H]
        client = api()
        for path in endpoints(LEAGUE):
            r = client.get(path)
            assert r.status_code == 200, (h, path, r.text)

    with db.session(s.db_path, read_only=True) as con:
        pages = [r[0] for r in db.rows(con, "SELECT hour FROM exchange_page ORDER BY hour")]
        leagues = db.rows(con, "SELECT DISTINCT league_id FROM exchange_hour_loaded")
        history = db.rows(con, "SELECT DISTINCT league FROM launch_history")
    assert pages == [LAUNCH + h * H for h in range(4)]  # only Allflame's window is kept
    assert leagues == [("poe1-allflame",)]
    assert history == [("Keepers",)]  # Mirage's fortnight wasn't complete: not a reference


def test_a_switch_keeps_the_reports_and_captures_the_old_league_first(server_db):
    """What was built from past leagues stays through a switch: the sell helper report (the
    sell helper's constants), like the Launch history. A followed league whose fortnight
    is complete but not captured yet goes into the Launch history before the switch
    drops its hours."""
    s = server_db
    with db.session(s.db_path) as con:
        con.execute("INSERT INTO sell_helper_report VALUES ('report', '2026-10-24 09:00:00', '{}')")
        # Mirage's fortnight, as complete (a Chaos price 14 days in): not captured yet.
        start = db.scalar(con, "SELECT start_at FROM league WHERE name = 'Mirage'")
        con.execute(
            "INSERT INTO price_observation (item_id, league_id, observed_at, day_offset, "
            "chaos_value, source) VALUES ('currency:chaos-orb', 'poe1-mirage', ?, 14.2, 1.0, "
            "'ggg-exchange-hourly')",
            [start + timedelta(days=14.2)],
        )
    server = FakeExchange(PAGES, now=LAUNCH)
    for h in (-1, 0, 1, 2):
        result, _ = run(s, server, h)
        if h == 1:
            assert result.dropped == ["Mirage"]
    with db.session(s.db_path, read_only=True) as con:
        history = db.rows(con, "SELECT DISTINCT league FROM launch_history")
        report = db.rows(con, "SELECT id FROM sell_helper_report")
        hours = db.scalar(
            con, "SELECT count(*) FROM cross_market_hour WHERE league_id = 'poe1-mirage'"
        )
    assert ("Mirage",) in history
    assert report == [("report",)] and hours == 0
