"""analysis/recipes.py on a tiny made-up league: shards combined into orbs, essences
upgraded at the vendor, scarabs rerolled and Harvest changes valued at their floor."""

from datetime import datetime, timedelta
from pathlib import Path

import pytest

from exiledbroker.analysis import recipes
from exiledbroker.storage import db

START = datetime(2026, 7, 24, 22)
NAMES = {
    "currency:mirror-shard": "Mirror Shard",
    "currency:mirror-of-kalandra": "Mirror of Kalandra",
    "currency:chaos-shard": "Chaos Shard",
    "currency:chaos-orb": "Chaos Orb",
    "currency:screaming-essence-of-greed": "Screaming Essence of Greed",
    "currency:shrieking-essence-of-greed": "Shrieking Essence of Greed",
    "currency:deafening-essence-of-greed": "Deafening Essence of Greed",
    "currency:shrieking-essence-of-woe": "Shrieking Essence of Woe",
    "currency:breach-scarab": "Breach Scarab",
    "currency:breach-scarab-of-lordship": "Breach Scarab of Lordship",
    "currency:legion-scarab": "Legion Scarab",
    "currency:fine-delirium-orb": "Fine Delirium Orb",
    "currency:singular-delirium-orb": "Singular Delirium Orb",
    "currency:primal-crystallised-lifeforce": "Primal Crystallised Lifeforce",
}
CONFIG = {
    "combine": [
        {"input": "Mirror Shard", "count": 20, "output": "Mirror of Kalandra"},
        {"input": "Chaos Shard", "count": 20, "output": "Chaos Orb"},
        {"input": "Exalted Shard", "count": 20, "output": "Exalted Orb"},  # not in the league
    ],
    "tiers": {
        "essence": {
            "ratio": 3,
            "pattern": "{tier} Essence of {kind}",
            "tiers": ["Screaming", "Shrieking", "Deafening"],
        }
    },
    "reroll": {
        "scarab": {"count": 3, "like": ["%Scarab%"]},
        "harvest_delirium_orb": {
            "count": 1,
            "like": ["% Delirium Orb"],
            "lifeforce": "Primal Crystallised Lifeforce",
        },
    },
}


@pytest.fixture
def con(tmp_path):
    with db.session(tmp_path / "t.duckdb") as con:
        db.init_schema(con)
        db.execute(
            con,
            "INSERT INTO league (id, game, name, start_at) VALUES ('poe1-test', 'poe1', 'Test', ?)",
            [START],
        )
        for item_id, name in NAMES.items():
            db.execute(
                con,
                "INSERT INTO item (id, game, canonical_name, category) VALUES (?, 'poe1', ?, 'currency')",
                [item_id, name],
            )

        def hour(item_id, day, price, low, high, divine=None):
            at = START + timedelta(days=day, hours=1)
            dl, rate_low = divine if divine else (None, None)
            db.execute(
                con,
                "INSERT INTO cross_market_hour (league_id, item_id, observed_at, day_offset, "
                "chaos_price, chaos_volume, chaos_low, chaos_high, divine_low, divine_rate_low) "
                "VALUES ('poe1-test', ?, ?, ?, ?, 40, ?, ?, ?, ?)",
                [item_id, at, day + 1 / 24, price, low, high, dl, rate_low],
            )

        hour("currency:mirror-shard", 0, 1000.0, 950.0, 1100.0)
        # The Mirror sells for 25,000c, or 120 Divines at a worst rate of 200 (24,000c).
        hour("currency:mirror-of-kalandra", 0, 25000.0, 22000.0, 26000.0, (120.0, 200.0))
        hour("currency:chaos-shard", 0, 0.04, 0.03, 0.06)
        for name, price in (("screaming", 1.0), ("shrieking", 4.0), ("deafening", 10.0)):
            hour(f"currency:{name}-essence-of-greed", 0, price, price * 0.9, price * 1.1)
        hour("currency:shrieking-essence-of-woe", 0, 2.0, 1.8, 2.2)
        for item_id, price in (
            ("currency:breach-scarab", 1.0),
            ("currency:breach-scarab-of-lordship", 6.0),
            ("currency:legion-scarab", 2.0),
        ):
            hour(item_id, 0, price, price * 0.5, price * 1.5)
        hour("currency:fine-delirium-orb", 0, 3.0, 2.5, 3.5)
        hour("currency:singular-delirium-orb", 0, 8.0, 7.0, 9.0)
        hour("currency:primal-crystallised-lifeforce", 0, 0.05, 0.04, 0.06)
        yield con


def test_the_committed_config_parses():
    config = recipes.load(Path(__file__).parents[1] / "config" / "recipes.toml")
    assert config["combine"] and config["tiers"] and config["reroll"]
    for c in config["combine"]:
        assert {"input", "count", "output"} <= set(c)


def test_tiers_expand_to_every_name_at_both_tiers():
    names = set(NAMES.values())
    got = recipes.expand_tiers(names, CONFIG["tiers"])
    assert [(r["input"], r["output"]) for r in got] == [
        ("Screaming Essence of Greed", "Shrieking Essence of Greed"),
        ("Shrieking Essence of Greed", "Deafening Essence of Greed"),
    ]  # Woe has no Screaming or Deafening tier here


def test_combines_are_priced_fair_and_harsh(con):
    rs, missing = recipes.combines(con, CONFIG)
    assert missing == ["Exalted Orb", "Exalted Shard"]
    hours = recipes.combine_hours(con, "Test", rs)
    by = {r["recipe"]: r for r in hours.iter_rows(named=True)}
    mirror = by["20 Mirror Shard -> Mirror of Kalandra"]
    assert mirror["cost"] == pytest.approx(20_000)
    assert mirror["margin"] == pytest.approx(0.25)
    # Harsh: shards at the high (22,000c); the Mirror at its better worst sale (24,000c
    # via Divines beats 22,000c in Chaos).
    assert mirror["harsh_margin"] == pytest.approx(24_000 / 22_000 - 1)
    assert mirror["sets_traded"] == pytest.approx(2.0)
    chaos = by["20 Chaos Shard -> Chaos Orb"]
    assert chaos["margin"] == pytest.approx(1 / 0.8 - 1)  # 20 shards at 0.04c make 1c
    ess = by["3 Screaming Essence of Greed -> Shrieking Essence of Greed"]
    assert ess["margin"] == pytest.approx(4 / 3 - 1)
    s = recipes.combine_summary(hours)
    assert set(s["recipe"]) == set(by)
    assert s.filter(recipe="3 Shrieking Essence of Greed -> Deafening Essence of Greed")[
        "pays"
    ].item() == pytest.approx(0.0)


def test_a_scarab_reroll_is_valued_at_the_cheapest_other_scarab(con):
    v = recipes.reroll_days(con, "Test", "scarab", CONFIG["reroll"]["scarab"])
    by = {r["input"]: r for r in v.iter_rows(named=True)}
    # Three Breach Scarabs (3c) roll at worst a Legion Scarab (2c): the floor leaves the
    # input out, since the vendor gives a different scarab.
    assert by["Breach Scarab"]["floor"] == pytest.approx(2.0)
    assert by["Breach Scarab"]["margin"] == pytest.approx(2 / 3 - 1)
    assert by["Legion Scarab"]["floor"] == pytest.approx(1.0)
    # Harsh: three at the high (3 x 1.5) against the cheapest other's low (1.0).
    assert by["Breach Scarab"]["harsh_margin"] == pytest.approx(1.0 / 4.5 - 1)


def test_a_harvest_change_reports_the_lifeforce_its_gain_pays_for(con):
    spec = CONFIG["reroll"]["harvest_delirium_orb"]
    v = recipes.reroll_days(con, "Test", "harvest_delirium_orb", spec)
    by = {r["input"]: r for r in v.iter_rows(named=True)}
    fine = by["Fine Delirium Orb"]
    assert fine["gain"] == pytest.approx(5.0)  # 3c into at worst an 8c orb
    assert fine["lifeforce_units"] == pytest.approx(100.0)  # at 0.05c a unit
    assert by["Singular Delirium Orb"]["gain"] == pytest.approx(-5.0)
    s = recipes.reroll_summary(v)
    assert "lifeforce_units" in s.columns
    across = recipes.across_leagues(s, "input")
    assert across.row(0, named=True)["input"] == "Fine Delirium Orb"


def test_a_thin_day_doesnt_price_a_reroll(con):
    # Only one of three scarabs trades on day 1: under MIN_COVERAGE, so no floor.
    db.execute(
        con,
        "INSERT INTO cross_market_hour (league_id, item_id, observed_at, day_offset, "
        "chaos_price, chaos_volume, chaos_low, chaos_high) "
        "VALUES ('poe1-test', 'currency:breach-scarab', ?, 1.05, 1, 10, 1, 1)",
        [START + timedelta(days=1, hours=1)],
    )
    v = recipes.reroll_days(con, "Test", "scarab", CONFIG["reroll"]["scarab"])
    assert set(v["day"]) == {0}
