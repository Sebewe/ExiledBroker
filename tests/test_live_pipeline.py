"""End to end on real API output: replay Mirage's first hours exactly as GGG's
exchange API published them (tests/fixtures/mirage_launch.json.gz), one hour at a
time, and after each update run every page and tool of the demo.

This is what a live league looks like: nothing at first, then hours arriving with
gaps (no Divine trades for the first two hours, items that haven't traded yet)."""

import gzip
import json
from datetime import timedelta
from pathlib import Path

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from exiledbroker.config import Settings
from exiledbroker.ingest import core_pool, item_names, loot_filter
from exiledbroker.ingest import currency_exchange as cx
from exiledbroker.ingest.files import write_json_atomic
from exiledbroker.ingest.http import meta_path_for
from exiledbroker.ingest.live import sync_live
from exiledbroker.storage import db
from test_currency_exchange import FakeExchange, client_for

with gzip.open(Path(__file__).parent / "fixtures" / "mirage_launch.json.gz", "rt") as _f:
    FIXTURE = json.load(_f)
LAUNCH = FIXTURE["launch"]
PAGES = {int(ts): page["markets"] for ts, page in FIXTURE["pages"].items()}
APP = str(Path(__file__).resolve().parents[1] / "app" / "dashboard.py")
PAGES_TO_RUN = ["live", "market", "cards", "arbitrage", "analysis", "data"]
ANALYSIS_TOOLS = ["Unique moves", "Launch curves", "Group timing", "Card turn-ins"]


@pytest.fixture
def settings(tmp_path, monkeypatch):
    monkeypatch.setenv("EB_DATA_DIR", str(tmp_path))
    st.cache_data.clear()
    s = Settings(data_dir=tmp_path, request_min_interval=0)
    # Names (RePoE) and the core pool / loot-filter snapshots, as `eb live` leaves them.
    path = item_names.base_items_path(s)
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(FIXTURE["base_items"]))
    write_json_atomic(meta_path_for(path), {"size": path.stat().st_size})
    names = {v["name"] for v in FIXTURE["base_items"].values()}
    for group in core_pool.SOURCES:
        write_json_atomic(
            core_pool.snapshot_path(s, group), {"league": "Mirage", "names": sorted(names)}
        )
    cards = sorted(
        v["name"] for v in FIXTURE["base_items"].values() if v.get("item_class") == "DivinationCard"
    )
    write_json_atomic(
        loot_filter.tiers_path(s), {"tiers": {c: "t1" for c in cards}, "shown": cards}
    )
    return s


def run_every_page() -> dict:
    """Run each page (and each analysis tool); fail on any exception."""
    st.cache_data.clear()
    seen = {}
    for page in PAGES_TO_RUN:
        at = AppTest.from_file(APP, default_timeout=120).run()
        at.switch_page(f"app_pages/{page}.py").run()
        assert not at.exception, (page, [e.message for e in at.exception])
        if page == "analysis" and at.get("button_group"):  # no switcher before any data
            for tool in ANALYSIS_TOOLS:
                at.get("button_group")[0].set_value(tool).run()
                assert not at.exception, (tool, [e.message for e in at.exception])
        seen[page] = at
    return seen


def test_live_league_hour_by_hour(settings):
    names = item_names.load_base_items(settings)
    server = FakeExchange(PAGES, now=LAUNCH)
    earliest = cx.from_ts(LAUNCH - 72 * 3600)

    def update(hours_in: int):
        server.now = LAUNCH + hours_in * 3600  # this hour is still being traded
        now = cx.from_ts(server.now) + timedelta(minutes=10)
        with client_for(settings, server) as client:
            return sync_live(client, settings, "Mirage", names, now=now, earliest=earliest)

    # Before the first hour is published, the league isn't trading anywhere yet.
    status = update(0)
    assert status.state == "not_running"
    pages = run_every_page()
    assert pages["live"].info[0].value.startswith("Start the live feed")

    for hours_in in (1, 2, 3, 6, 12, 24, 30):
        status = update(hours_in)
        latest = cx.from_ts(LAUNCH + (hours_in - 1) * 3600)
        assert status.state == "updated", status
        assert status.latest_hour == latest
        pages = run_every_page()

        live = pages["live"]
        with db.session(read_only=True) as con:
            traded = db.rows(
                con,
                "SELECT max(observed_at), count(DISTINCT observed_at) FROM price_observation "
                "WHERE source = 'ggg-exchange-hourly'",
            )[0]
        if traded[1] == 0:
            # Mirage's launch hour: published, but nothing had traded yet.
            assert "nothing has traded" in live.info[0].value
        else:
            banners = list(live.warning) + list(live.success)
            assert f"{traded[0]:%b %d, %H:00}" in banners[0].value
        assert traded[1] <= hours_in

    # After 30 hours: prices, cards and cross-market hours are all there.
    with db.session(read_only=True) as con:
        divine = db.scalar(
            con,
            "SELECT median(chaos_value) FROM price_observation "
            "WHERE item_id = 'currency:divine-orb' AND day_offset >= 1",
        )
        cross = db.scalar(con, "SELECT count(*) FROM cross_market_hour")
        cards = db.scalar(con, "SELECT count(*) FROM divination_card WHERE followed")
    assert 50 < divine < 200  # Mirage's day-2 Divine traded around 86–100c
    assert cross > 0 and cards == 2
    market = pages["market"]
    assert {m.label for m in market.metric} >= {"Divine Orb", "Mirror of Kalandra"}

    # Repeating an update with nothing new published fetches nothing and changes nothing.
    again = update(30)
    assert (again.state, again.fetched) == ("unchanged", 0)


def test_live_update_survives_an_interrupted_hour(settings):
    """A crash mid-update leaves no partial pages; the next update just carries on."""
    names = item_names.load_base_items(settings)
    server = FakeExchange(PAGES, now=LAUNCH + 6 * 3600)
    now = cx.from_ts(server.now) + timedelta(minutes=10)
    earliest = cx.from_ts(LAUNCH - 72 * 3600)
    real = server.handler
    crash_at = LAUNCH + 3 * 3600  # mid-window: hours 0–2 are on disk by then

    def flaky(request):
        if int(request.url.path.rsplit("/", 1)[-1]) == crash_at:
            raise KeyboardInterrupt
        return real(request)

    server.handler = flaky
    with client_for(settings, server) as client, pytest.raises(KeyboardInterrupt):
        sync_live(client, settings, "Mirage", names, now=now, earliest=earliest)
    assert not list(settings.exchange_raw_dir.glob("*.tmp"))
    assert cx.page_path(settings, LAUNCH + 2 * 3600).exists()
    assert not cx.page_path(settings, crash_at).exists()
    server.handler = real
    with client_for(settings, server) as client:
        status = sync_live(client, settings, "Mirage", names, now=now, earliest=earliest)
    assert status.state == "updated" and status.latest_hour == cx.from_ts(LAUNCH + 5 * 3600)
