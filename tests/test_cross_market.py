from datetime import date, timedelta

import polars as pl
import pytest

from exiledbroker.config import Settings
from exiledbroker.ingest import currency_exchange as cx
from exiledbroker.normalize import exchange_loader
from exiledbroker.services import cross_market as xm
from exiledbroker.storage import db
from test_currency_exchange import (
    ALCH,
    CHAOS,
    DIVINE,
    LAUNCH,
    NAMES,
    T0,
    FakeExchange,
    client_for,
    market,
    register,
)


@pytest.fixture
def con(tmp_path):
    settings = Settings(data_dir=tmp_path, request_min_interval=0)
    # Hour 0: Divine 100c (range 90–110). Alchemy: 1c in the Chaos market (range 0.9–1.2),
    # 0.015 div in the Divine market (range 0.014–0.016) = 1.5c via Divines.
    # Hour 1: Alchemy trades against Chaos only, so it isn't a cross-market hour.
    pages = {
        T0: [
            market("Mirage", CHAOS, DIVINE, 1000, 10, lo=(90, 1), hi=(110, 1)),
            market("Mirage", ALCH, CHAOS, 100, 100, lo=(10, 9), hi=(10, 12)),
            market("Mirage", ALCH, DIVINE, 200, 3, lo=(1000, 14), hi=(1000, 16)),
        ],
        T0 + 3600: [
            market("Mirage", CHAOS, DIVINE, 1000, 10),
            market("Mirage", ALCH, CHAOS, 100, 100),
        ],
    }
    c = register(settings)
    with client_for(settings, FakeExchange(pages, now=T0 + 7200)) as client:
        r = cx.sync_league(client, settings, "Mirage", date(2026, 3, 6), days=1)
    exchange_loader.load_league(c, settings, r.window, NAMES)
    yield c
    c.close()


def test_loader_fills_cross_market_hours(con):
    rows = db.rows(
        con,
        "SELECT item_id, chaos_price, chaos_low, chaos_high, divine_price, divine_low, "
        "divine_high, divine_rate, divine_rate_low, divine_rate_high FROM cross_market_hour",
    )
    assert len(rows) == 1  # only hour 0 traded in both markets
    item, *values = rows[0]
    assert item == "currency:orb-of-alchemy"
    assert values == pytest.approx([1.0, 0.9, 1.2, 0.015, 0.014, 0.016, 100, 90, 110])


def test_loop_edges_at_worst_prices(con):
    chaos_first = xm.hourly(con, ["Mirage"]).row(0, named=True)
    # Via Divines at average prices: 0.015 × 100 = 1.5c, a 50% gap.
    assert chaos_first["via_divines"] == pytest.approx(1.5)
    assert chaos_first["gap"] == pytest.approx(0.5)
    # Buy at 1.2c, sell for 0.014 div, sell divines at 90c: 1.26 / 1.2 - 1 = 5%.
    assert chaos_first["edge"] == pytest.approx(0.014 * 90 / 1.2 - 1)
    # Reverse: buy at 0.016 div, sell at 0.9c, buy divines back at 110c.
    divine_first = xm.hourly(con, ["Mirage"], direction="divine_first").row(0, named=True)
    assert divine_first["edge"] == pytest.approx(0.9 / (0.016 * 110) - 1)
    # Overlap: min(100 bought with chaos, 200 sold for divines) × 1c.
    assert chaos_first["overlap_chaos"] == pytest.approx(100)
    assert xm.hourly(con, ["Mirage"], item_ids=[]).is_empty()
    with pytest.raises(ValueError):
        xm.hourly(con, ["Mirage"], direction="sideways")


def _cross_rows(con, edges: list[float]) -> None:
    """Replace the cross-market hours with one row per edge (Chaos-first loop):
    divine_low = rate_low = 1, so edge = 1 / chaos_high - 1."""
    con.execute("DELETE FROM cross_market_hour")
    for i, edge in enumerate(edges):
        con.execute(
            "INSERT INTO cross_market_hour VALUES ('poe1-mirage', 'currency:orb-of-alchemy', "
            "?, ?, 2.0, 100, 1.9, ?, 0.02, 50, 1, 1.1, 100, 1, 100)",
            [LAUNCH.replace(tzinfo=None) + timedelta(hours=i), i / 24, 1 / (1 + edge)],
        )


def test_summarize_buffer_and_capacity(con):
    _cross_rows(con, [0.05, 0.01, -0.2])
    row = xm.summarize(con, ["Mirage"], buffer=0.02, min_hours=1).row(0, named=True)
    assert (row["hours"], row["share"]) == (3, pytest.approx(1 / 3))
    assert row["edge_when_paying"] == pytest.approx(0.05)
    # Overlap: min(100 bought with chaos, 50 sold for divines) × 2c = 100c per hour.
    assert row["overlap_chaos"] == pytest.approx(300)
    assert row["capacity_chaos"] == pytest.approx(0.05 * 100)
    assert xm.summarize(con, ["Mirage"], min_hours=4).is_empty()
    with pytest.raises(ValueError):
        xm.summarize(con, ["Mirage"], direction="sideways")


def test_across_leagues_counts_missing_leagues_as_zero():
    per = pl.DataFrame(
        {
            "league": ["A", "B"],
            "item_id": ["x", "x"],
            "name": ["X", "X"],
            "hours": [3, 1],
            "share": [1 / 3, 1.0],
            "edge_when_paying": [0.05, 0.3],
            "median_gap": [0.1, 0.4],
            "chaos_price": [2.0, 2.0],
            "overlap_chaos": [300.0, 100.0],
            "capacity_chaos": [5.0, 30.0],
        }
    )
    both = xm.across_leagues(per, ["A", "B"], {"A": 1.0, "B": 1.0}).row(0, named=True)
    assert both["weighted_share"] == pytest.approx((1 / 3 + 1) / 2)
    assert both["worst_league_share"] == pytest.approx(1 / 3)
    # A league where the item never traded in both markets counts as 0.
    three = xm.across_leagues(per, ["A", "B", "C"], {"A": 1.0, "B": 1.0, "C": 1.0})
    assert three["worst_league_share"].item() == 0.0
    assert three["weighted_share"].item() == pytest.approx((1 / 3 + 1) / 3)
    assert xm.score(three)["score"].item() == 1.0


def test_since_limits_hours_in_sql(con):
    from datetime import timedelta

    from test_currency_exchange import LAUNCH

    hour0 = LAUNCH.replace(tzinfo=None)
    assert xm.hourly(con, ["Mirage"], since=hour0 - timedelta(hours=1)).height == 1
    assert xm.hourly(con, ["Mirage"], since=hour0).is_empty()  # exclusive
