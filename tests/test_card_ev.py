"""analysis/card_ev.py on a tiny made-up league: a card whose random reward rolls one of
three orbs, valued at the floor, the median and the mean, at fair and harsh prices."""

from datetime import datetime, timedelta
from pathlib import Path

import pytest

from exiledbroker.analysis import card_ev
from exiledbroker.storage import db

START = datetime(2026, 7, 24, 22)
POOLS = {"Delirium Orb": ["% Delirium Orb"]}
ORBS = {
    "currency:fine-delirium-orb": 2.0,
    "currency:singular-delirium-orb": 4.0,
    "currency:diviners-delirium-orb": 9.0,
}
CARD = "currency:disdain"


@pytest.fixture
def con(tmp_path):
    with db.session(tmp_path / "t.duckdb") as con:
        db.init_schema(con)
        db.execute(
            con,
            "INSERT INTO league (id, game, name, start_at) VALUES ('poe1-test', 'poe1', 'Test', ?)",
            [START],
        )
        names = {
            "currency:fine-delirium-orb": "Fine Delirium Orb",
            "currency:singular-delirium-orb": "Singular Delirium Orb",
            "currency:diviners-delirium-orb": "Diviner's Delirium Orb",
            "currency:legacy-delirium-orb": "Legacy Delirium Orb",  # never trades
            CARD: "Disdain",
        }
        for item_id, name in names.items():
            db.execute(
                con,
                "INSERT INTO item (id, game, canonical_name, category) VALUES (?, 'poe1', ?, 'currency')",
                [item_id, name],
            )
        db.execute(
            con,
            "INSERT INTO divination_card (item_id, name, stack_size, reward_kind, reward_name, "
            "reward_quantity, reward_fixed, followed) VALUES (?, 'Disdain', 5, 'currency', "
            "'Delirium Orb', 1, false, true)",
            [CARD],
        )

        def hour(item_id, day, price, low, high):
            at = START + timedelta(days=day, hours=1)
            db.execute(
                con,
                "INSERT INTO cross_market_hour (league_id, item_id, observed_at, day_offset, "
                "chaos_price, chaos_volume, chaos_low, chaos_high) VALUES ('poe1-test', ?, ?, ?, ?, 10, ?, ?)",
                [item_id, at, day + 1 / 24, price, low, high],
            )

        for day in (0, 1):
            hour(CARD, day, 0.3, 0.25, 0.4)  # a set: 1.5c fair, 2.0c harsh
            for item_id, price in ORBS.items():
                hour(item_id, day, price, price * 0.5, price * 1.2)
        hour(CARD, 2, 0.3, 0.25, 0.4)  # day 2: only the dearest orb traded
        hour("currency:diviners-delirium-orb", 2, 9.0, 8.0, 10.0)
        yield con


def test_a_set_is_valued_at_the_floor_median_and_mean(con):
    v = card_ev.daily_values(con, "Test", POOLS)
    day0 = v.filter(day=0).row(0, named=True)
    assert day0["cost"] == pytest.approx(1.5)
    assert (day0["floor"], day0["median"]) == (pytest.approx(2.0), pytest.approx(4.0))
    assert day0["mean"] == pytest.approx(5.0)
    assert day0["floor_margin"] == pytest.approx(2.0 / 1.5 - 1)
    # Harsh: the set bought at the hours' high (5 x 0.4), the floor sold at the low (2 x 0.5).
    assert day0["harsh_floor_margin"] == pytest.approx(1.0 / 2.0 - 1)


def test_a_day_with_most_of_the_pool_missing_is_skipped(con):
    """Day 2 has only the dearest orb: its 'floor' would be 9c, so the day isn't counted.
    The legacy orb never traded, so it doesn't count against coverage on days 0 and 1."""
    v = card_ev.daily_values(con, "Test", POOLS)
    assert sorted(v["day"].to_list()) == [0, 1]


def test_the_summary_and_the_committed_pools(con):
    s = card_ev.summary(card_ev.daily_values(con, "Test", POOLS)).row(0, named=True)
    assert s["days"] == 2 and s["floor_pays"] == 1.0
    pools = card_ev.load_pools(Path(__file__).resolve().parents[1] / "config/card_rewards.toml")
    assert "Delirium Orb" in pools and all(pools.values())
