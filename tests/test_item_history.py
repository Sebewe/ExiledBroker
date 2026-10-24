"""The Farming page's reduced history (services/item_history.py): each finished league's
fortnight as one row per basket item and day, the same on DuckDB, on Postgres and
through the hosted writer (DuckDB with Postgres attached)."""

import ctypes
import math
import os
from datetime import datetime, timedelta

import pytest

from exiledbroker.config import Settings
from exiledbroker.normalize.tracked import currency_item_id
from exiledbroker.services import item_history as ih
from exiledbroker.services import launch_picks
from exiledbroker.storage import db

PG_URL = os.environ.get("EB_TEST_POSTGRES_URL")
START = datetime(2026, 3, 6, 20)
ALPHA, BETA = currency_item_id("Alpha Orb"), currency_item_id("Beta Orb")
# (item, hours after launch, chaos price, items traded, divine rate)
HOURS = [
    (ALPHA, 0, 10.0, 1.0, 100.0),
    (ALPHA, 1, 20.0, 1.0, None),  # no Divine leg that hour
    (ALPHA, 2, 40.0, 1.0, 200.0),
    (ALPHA, 3, 0.0, 1.0, 100.0),  # no price: left out
    (BETA, 5, 3.0, 2.0, 100.0),
    (BETA, 30, 6.0, 1.0, 100.0),
    (BETA, 14 * 24 + 2, 9.0, 1.0, 100.0),  # day 14: past the fortnight
]


@pytest.fixture
def settings(tmp_path):
    s = Settings(data_dir=tmp_path, mechanics_file=tmp_path / "mechanics.toml")
    s.mechanics_file.write_text(
        '[[mechanic]]\nid = "test"\nname = "Test"\noutputs = ["Alpha Orb", "Beta Orb"]\n'
    )
    return s


def _fill(con, chaos_day: float = 13.5) -> None:
    """A league with the hours above and a Chaos price `chaos_day` days in, so it
    counts as complete (launch_picks.complete_leagues)."""
    db.execute(
        con,
        "INSERT INTO league (id, game, name, start_at, launched_at, kind, exchange_tracked) "
        "VALUES ('poe1-mirage', 'poe1', 'Mirage', ?, ?, 'challenge', TRUE)",
        [START, START],
    )
    for item_id, name in [
        (ALPHA, "Alpha Orb"),
        (BETA, "Beta Orb"),
        (launch_picks.CHAOS, "Chaos Orb"),
    ]:
        db.execute(
            con,
            "INSERT INTO item (id, game, canonical_name, category) VALUES (?, 'poe1', ?, 'currency')",
            [item_id, name],
        )
    for item_id, hour, price, volume, rate in HOURS:
        db.execute(
            con,
            "INSERT INTO cross_market_hour (league_id, item_id, observed_at, day_offset, "
            "chaos_price, chaos_volume, divine_rate) VALUES ('poe1-mirage', ?, ?, ?, ?, ?, ?)",
            [item_id, START + timedelta(hours=hour), hour / 24, price, volume, rate],
        )
    at = START + timedelta(days=chaos_day)
    db.execute(
        con,
        "INSERT INTO price_observation (item_id, league_id, observed_at, day_offset, "
        "chaos_value, source) VALUES (?, 'poe1-mirage', ?, ?, 1.0, ?)",
        [launch_picks.CHAOS, at, chaos_day, launch_picks.HOURLY],
    )


def _check(con) -> None:
    rows = {(r["item_id"], r["day"]): r for r in ih.history(con).iter_rows(named=True)}
    assert set(rows) == {(ALPHA, 0), (BETA, 0), (BETA, 1)}
    alpha = rows[(ALPHA, 0)]
    assert alpha["chaos"] == pytest.approx(20.0)
    assert alpha["divine"] == pytest.approx(0.15)  # 0.1 and 0.2; the hour without a rate is out
    assert alpha["chaos_volume"] == pytest.approx(70.0)
    assert alpha["hours"] == 3
    assert alpha["absret"] == pytest.approx(math.log(2))
    assert alpha["day_hours"] == 5  # hours 0–3 and 5 traded something (hour 3's 0c counts)
    assert rows[(BETA, 0)]["chaos_volume"] == pytest.approx(6.0)
    assert rows[(BETA, 0)]["absret"] is None  # its first traded hour has nothing before it
    assert rows[(BETA, 1)]["day_hours"] == 1
    assert {r["league_start"] for r in rows.values()} == {START}


@pytest.fixture
def con(tmp_path):
    with db.session(tmp_path / "eb.duckdb") as con:
        db.init_schema(con)
        yield con


def test_capture_reduces_the_fortnight(con, settings):
    _fill(con)
    items = ih.basket_items(con, settings)
    assert items == sorted([ALPHA, BETA])
    assert ih.capture(con, "Mirage", items) == 3
    _check(con)
    assert ih.capture(con, "Mirage", items) == 3  # replaced, not added
    assert ih.captured_leagues(con) == ["Mirage"]
    assert ih.history(con, []).is_empty()
    assert ih.capture(con, "Mirage", []) == 0
    assert ih.captured_leagues(con) == []


def test_refresh_captures_a_live_league_only_once_its_fortnight_is_over(con, settings):
    _fill(con)
    assert ih.refresh(con, settings, live="Mirage") == []  # day 13.5: still running
    assert ih.refresh(con, settings) == ["Mirage"]  # a past league: complete
    assert ih.refresh(con, settings) == []  # already captured
    db.execute(con, "DELETE FROM item_day_history")
    db.execute(con, "DELETE FROM price_observation")
    _fill_chaos(con, 14.2)
    assert ih.refresh(con, settings, live="Mirage") == ["Mirage"]
    _check(con)


def _fill_chaos(con, day: float) -> None:
    db.execute(
        con,
        "INSERT INTO price_observation (item_id, league_id, observed_at, day_offset, "
        "chaos_value, source) VALUES (?, 'poe1-mirage', ?, ?, 1.0, ?)",
        [launch_picks.CHAOS, START + timedelta(days=day), day, launch_picks.HOURLY],
    )


@pytest.fixture
def pg():
    if not PG_URL:
        pytest.skip("EB_TEST_POSTGRES_URL is not set")
    import psycopg

    pg = psycopg.connect(PG_URL, autocommit=True)
    pg.execute("DROP SCHEMA public CASCADE")
    pg.execute("CREATE SCHEMA public")
    db.init_schema(pg)
    _fill(pg)
    yield pg
    pg.close()


def test_capture_on_postgres(pg, settings):
    assert ih.capture(pg, "Mirage", ih.basket_items(pg, settings)) == 3
    _check(pg)


def test_capture_through_the_hosted_writer(pg, settings, monkeypatch, capfd):
    """Hosted, the capture runs on Postgres itself (`db.pushdown`): DuckDB never copies
    the league's hours out (see test_pipeline's whole-table check)."""
    hosted = settings.model_copy(update={"database_url": PG_URL})
    monkeypatch.setattr(db, "SHOW_PG_QUERIES", True)
    capfd.readouterr()
    with db.site_writer(hosted) as con:
        assert ih.refresh(con, hosted) == ["Mirage"]
    ctypes.CDLL(None).fflush(None)  # DuckDB prints from C, to stderr
    sent = capfd.readouterr().err
    copies = [q for q in sent.split("\n\n") if q.lstrip().startswith("COPY (SELECT")]
    assert "percentile_cont" in sent  # the aggregate itself ran on Postgres
    assert not [q for q in copies if '"cross_market_hour"' in q or '"price_observation"' in q]
    _check(pg)
