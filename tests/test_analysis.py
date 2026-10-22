from datetime import date

import pytest

from exiledbroker.analysis import launch_patterns as lp
from exiledbroker.storage import db

LEAGUES = [("poe1-mirage", "Mirage", "2026-03-06"), ("poe1-necropolis", "Necropolis", "2024-03-29")]
# (league, item, day, divine, confidence)
PRICES = [
    ("poe1-mirage", "ninja:1", 2, 100, "High"),
    ("poe1-mirage", "ninja:1", 14, 150, "High"),
    ("poe1-mirage", "ninja:2", 2, 10, "High"),
    ("poe1-mirage", "ninja:2", 14, 2, "High"),
    ("poe1-mirage", "ninja:3", 2, 1, "Low"),
    ("poe1-mirage", "ninja:3", 14, 5, "High"),
    ("poe1-necropolis", "ninja:2", 2, 20, "High"),
    ("poe1-necropolis", "ninja:2", 14, 8, "High"),
]


@pytest.fixture
def con(tmp_path):
    con = db.connect(tmp_path / "t.duckdb")
    db.init_schema(con)
    for lid, name, start in LEAGUES:
        con.execute(
            "INSERT INTO league (id, game, name, start_at, kind) VALUES (?, 'poe1', ?, ?, "
            "'challenge')",
            [lid, name, start],
        )
    for n in (1, 2, 3):
        con.execute(
            "INSERT INTO item (id, game, canonical_name, category) VALUES (?, 'poe1', ?, "
            "'UniqueArmour')",
            [f"ninja:{n}", f"Unique {n}"],
        )
    for lid, item, day, div, conf in PRICES:
        con.execute(
            "INSERT INTO price_observation (item_id, league_id, observed_at, day_offset, "
            "divine_value, source, confidence) VALUES (?, ?, ?, ?, ?, 'poe.ninja-dump', ?)",
            [item, lid, date(2026, 1, day), day, div, conf],
        )
    yield con
    con.close()


def test_unique_moves_filters_confidence_and_tiers(con):
    moves = lp.unique_moves(con, since=date(2024, 1, 1))
    got = {
        (r["league"], r["item_id"]): (r["tier"], r["ratio"]) for r in moves.iter_rows(named=True)
    }
    # ninja:3 has a Low-confidence base price, so it's left out.
    assert got == {
        ("Mirage", "ninja:1"): ("chase (≥50 div)", 1.5),
        ("Mirage", "ninja:2"): ("mid (5–50 div)", 0.2),
        ("Necropolis", "ninja:2"): ("mid (5–50 div)", 0.4),
    }
    assert moves.filter(exchange_era=True)["league"].unique().to_list() == ["Mirage"]
    assert lp.unique_moves(con, since=date(2024, 1, 1), confidence=None).height == 4


def test_by_tier_orders_tiers_then_newest_league(con):
    t = lp.by_tier(lp.unique_moves(con, since=date(2024, 1, 1)))
    assert t.select("tier", "league").rows() == [
        ("chase (≥50 div)", "Mirage"),
        ("mid (5–50 div)", "Mirage"),
        ("mid (5–50 div)", "Necropolis"),
    ]
    pooled = lp.by_tier(lp.unique_moves(con, since=date(2024, 1, 1)), per_league=False)
    mid = pooled.filter(tier="mid (5–50 div)").row(0, named=True)
    assert (mid["items"], mid["leagues"], mid["share_up"]) == (2, 2, 0.0)
    assert mid["median_ratio"] == pytest.approx(0.3)


def test_recency_weights_halve_every_half_life():
    w = lp.recency_weights(["Mirage", "Keepers", "Mercenaries"], half_life=1)
    assert w == {"Mirage": 1.0, "Keepers": 0.5, "Mercenaries": 0.25}


def test_weighted_curve_and_turning_points():
    import polars as pl

    curves = pl.DataFrame(
        {
            "league": ["A", "A", "B", "B"],
            "bucket_day": [0.0, 1.0, 0.0, 1.0],
            "relative": [1.0, 3.0, 1.0, 1.0],
        }
    )
    avg = lp.weighted_curve(curves, {"A": 1.0, "B": 0.5})
    assert avg["relative"].to_list() == [1.0, pytest.approx(7 / 3)]
    assert lp.turning_points(avg) == {
        "low_day": 0.0,
        "low": 1.0,
        "peak_day": 1.0,
        "peak": pytest.approx(7 / 3),
    }
    assert lp.turning_points(avg.clear())["peak"] is None


def test_launch_curve_baseline_is_day1_median(tmp_path):
    from exiledbroker.config import Settings
    from exiledbroker.ingest import currency_exchange as cx
    from exiledbroker.normalize import exchange_loader
    from test_currency_exchange import (
        ALCH,
        CHAOS,
        DIVINE,
        NAMES,
        T0,
        FakeExchange,
        client_for,
        market,
        register,
    )

    settings = Settings(data_dir=tmp_path, request_min_interval=0)
    # Divine at 30, 30, 300 (one junk hour) on day 1, then 60 on day 2.
    pages = {
        T0: [market("Mirage", CHAOS, DIVINE, 300, 10), market("Mirage", ALCH, CHAOS, 5, 1)],
        T0 + 3600: [market("Mirage", CHAOS, DIVINE, 300, 10)],
        T0 + 7200: [market("Mirage", CHAOS, DIVINE, 3000, 10)],
        T0 + 86400: [market("Mirage", CHAOS, DIVINE, 600, 10)],
    }
    con = register(settings)
    with client_for(settings, FakeExchange(pages, now=T0 + 86400 + 3600)) as client:
        r = cx.sync_league(client, settings, "Mirage", date(2026, 3, 6), days=2)
    exchange_loader.load_league(con, settings, r.window, NAMES)
    curves = lp.launch_curves(con, ["currency:divine-orb"], ["Mirage"], "chaos", bucket_hours=24)
    day2 = curves.filter(bucket_day=1.0).row(0, named=True)
    # Median of 30, 30, 300 is 30, so day 2 (60) is 2x; an average would say ~0.5x.
    assert day2["relative"] == pytest.approx(2.0) and day2["baseline_hours"] == 3
    assert lp.hourly_league_names(con) == ["Mirage"]
    con.close()
