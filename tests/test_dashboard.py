"""Headless runs of the demo in the states a new league goes through."""

from datetime import date
from pathlib import Path

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from exiledbroker.config import Settings
from exiledbroker.ingest import currency_exchange as cx
from exiledbroker.ingest.poe_ninja_dumps import parse_index
from exiledbroker.normalize import exchange_loader
from exiledbroker.storage import db
from exiledbroker.storage import dumps as dump_store
from test_currency_exchange import (
    ALCH,
    CHAOS,
    DIVINE,
    MIRROR,
    NAMES,
    T0,
    FakeExchange,
    client_for,
    market,
)

APP = str(Path(__file__).resolve().parents[1] / "app" / "dashboard.py")
INDEX = [
    {
        "leagueName": "Mirage",
        "minDate": "2026-03-06T00:00:00",
        "maxDate": "2026-07-20T00:00:00",
        "zipName": "Mirage.zip",
    }
]


@pytest.fixture
def settings(tmp_path, monkeypatch):
    monkeypatch.setenv("EB_DATA_DIR", str(tmp_path))
    st.cache_data.clear()
    return Settings(data_dir=tmp_path, request_min_interval=0)


def run_app(page=None):
    at = AppTest.from_file(APP, default_timeout=60).run()
    if page:
        at.switch_page(page).run()
    assert not at.exception, [e.message for e in at.exception]
    return at


def register(settings):
    con = db.connect(settings.db_path)
    db.init_schema(con)
    dump_store.upsert_leagues(con, parse_index(INDEX))
    con.execute("UPDATE league SET exchange_tracked = TRUE WHERE name = 'Mirage'")
    return con


def test_no_database(settings):
    at = run_app()
    assert at.info[0].value.startswith("Run ")
    run_app("app_pages/data.py")
    run_app("app_pages/analysis.py")


def test_league_registered_before_first_hour(settings):
    register(settings).close()
    at = run_app()
    assert "no hourly trades have been published yet" in at.info[0].value
    assert not at.metric and not at.dataframe
    # No cards loaded yet: the turn-ins page says so instead of failing.
    at = run_app("app_pages/cards.py")
    assert at.info[0].value.startswith("Run ")
    # Analysis tools wait for data instead of failing.
    at = run_app("app_pages/analysis.py")
    for tool in ("Unique moves", "Launch curves", "Group timing", "Card turn-ins", "Cross-market"):
        at.get("button_group")[0].set_value(tool).run()
        assert not at.exception, [e.message for e in at.exception]
        assert "No challenge league has" in at.info[0].value


def test_first_hours_with_gaps(settings):
    # Launch hour: only Alchemy trades, so there's no Divine rate yet. Divine and
    # Mirror trades start an hour later; nothing else has traded at all.
    pages = {
        T0: [market("Mirage", ALCH, CHAOS, 50, 10)],
        T0 + 3600: [
            market("Mirage", CHAOS, DIVINE, 300, 10),
            market("Mirage", MIRROR, DIVINE, 1, 400),
        ],
    }
    con = register(settings)
    server = FakeExchange(pages, now=T0 + 2 * 3600)
    with client_for(settings, server) as client:
        result = cx.sync_league(client, settings, "Mirage", date(2026, 3, 6), days=14)
    cx.extract_league(settings, result.window)
    exchange_loader.load_league(con, settings, result.window, NAMES)
    con.close()

    at = run_app()
    assert "2 hours since launch" in at.caption[0].value
    cards = {m.label: m.value for m in at.metric}
    assert cards["Divine Orb"] == "30.0 c"
    assert cards["Mirror of Kalandra"] == "400.0 div"
    assert cards["Mirror Shard"] == "–"  # hasn't traded yet
    assert "Chaos Orb" not in cards
    # One day of data: no "vs. day 1" change yet.
    assert not any(m.delta for m in at.metric)
    for unit in ("chaos", "divine"):
        for group in ("Currency", "High-tier essences", "Scarabs"):
            at.get("button_group")[0].set_value(group).run()
            at.get("button_group")[1].set_value(unit).run()
            assert not at.exception, [e.message for e in at.exception]
    # Essences have no trades: a clear empty state instead of an empty table.
    at.get("button_group")[0].set_value("High-tier essences").run()
    assert "Nothing in high-tier essences has traded yet" in at.info[0].value
    run_app("app_pages/data.py")

    # A followed card whose reward hasn't traded in the same hour yet.
    con = db.connect(settings.db_path)
    con.execute(
        "INSERT INTO divination_card (item_id, name, stack_size, reward_kind, reward_name, "
        "reward_quantity, reward_item_id, reward_text, filter_tier, followed, reward_fixed) "
        "VALUES ('currency:orb-of-alchemy', 'Test Card', 300, 'currency', 'Mirror Shard', 1, "
        "'currency:mirror-shard', '', 't3', TRUE, TRUE)"
    )
    con.close()
    st.cache_data.clear()
    # Two hours of one league: every analysis tool still renders.
    at = run_app("app_pages/analysis.py")
    for tool in ("Unique moves", "Launch curves", "Group timing", "Card turn-ins", "Cross-market"):
        at.get("button_group")[0].set_value(tool).run()
        assert not at.exception, [e.message for e in at.exception]
    at = run_app("app_pages/cards.py")
    assert "No hour in Mirage has trades for both" in at.info[0].value
    assert {m.label: m.value for m in at.metric}["Top score"] == "–"
