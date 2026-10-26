from datetime import UTC, datetime, timedelta

import polars as pl
import pytest

from exiledbroker.normalize.exchange_loader import SOURCE as HOURLY
from exiledbroker.services import missed
from exiledbroker.storage import db

LATEST = datetime(2026, 10, 22, 8)


@pytest.fixture
def con(tmp_path):
    with db.session(tmp_path / "t.duckdb") as c:
        db.init_schema(c)
        c.execute(
            "INSERT INTO league (id, game, name, start_at, kind)"
            " VALUES ('L', 'poe1', 'L', '2026-10-20', 'challenge')"
        )
        yield c


def _item(con, item_id: str, prices: list[float], volume: float = 5000.0, spread=0.0):
    """Hourly prices ending at LATEST (the last one is the latest hour)."""
    con.execute(
        "INSERT INTO item (id, game, canonical_name, category) VALUES (?, 'poe1', ?, 'currency')",
        [item_id, item_id.split(":")[1].title()],
    )
    con.execute(
        "INSERT INTO tracked_item (item_id, group_id, group_label, sort_order)"
        " VALUES (?, 'currency', 'Currency', 1)",
        [item_id],
    )
    for i, p in enumerate(reversed(prices)):
        at = LATEST - timedelta(hours=i)
        con.execute(
            "INSERT INTO price_observation (item_id, league_id, observed_at, day_offset,"
            " chaos_value, source, chaos_volume, chaos_low, chaos_high)"
            " VALUES (?, 'L', ?, 1, ?, ?, ?, ?, ?)",
            [item_id, at, p, HOURLY, volume, p * (1 - spread), p * (1 + spread)],
        )


def test_movers_volatility_and_streaks(con):
    _item(con, "currency:climber", [10, 11, 12, 13, 15, 20])  # up 5 hours running
    _item(con, "currency:faller", [50, 50, 50, 50, 40, 30])  # down 2 hours running
    _item(con, "currency:thin", [10, 10, 10, 10, 10, 90], volume=50)  # one trade, ignored
    _item(con, "currency:dust", [1, 1, 1, 1, 1, 3])  # under MIN_PRICE, ignored
    _item(con, "currency:swingy", [20] * 6, spread=0.5)  # flat, but a wide range
    [one, two, three] = missed.missed(con, "L")
    assert (one["hours"], two["hours"], three["hours"]) == (1, 2, 3)
    assert one["latest_hour"] == LATEST.replace(tzinfo=UTC)  # sent marked as UTC

    [up] = one["rising"]
    assert up["name"] == "Climber" and up["change"] == pytest.approx(20 / 15 - 1)
    assert up["streak"] == 5
    [down] = one["falling"]
    assert down["name"] == "Faller" and down["streak"] == -2
    assert three["falling"][0]["change"] == pytest.approx(30 / 50 - 1)  # against 3 hours before
    # The ticker: every liquid mover, biggest move first (Climber +33%, Faller -25%).
    assert [m["name"] for m in one["ticker"]] == ["Climber", "Faller"]
    assert one["volatile"][0]["name"] == "Swingy"
    assert one["volatile"][0]["range"] == pytest.approx(1.0)
    # Nothing paid: no loops or cards in this data, and the counts say so.
    assert (one["loops"], one["cards"], one["loops_paid"], one["cards_paid"]) == ([], [], 0, 0)


def test_no_trades_yet(con):
    assert missed.missed(con, "L") == []


def _loop_hour(con, item_id: str, hours_ago: int, items: float, edge: float):
    """A Chaos-first loop hour at 10c an item: `items` traded in both markets, paying
    `edge` at the worst prices (Divine at 100c all round)."""
    con.execute(
        "INSERT INTO item (id, game, canonical_name, category) VALUES (?, 'poe1', ?, 'currency')"
        " ON CONFLICT DO NOTHING",
        [item_id, item_id.split(":")[1].title()],
    )
    at = LATEST - timedelta(hours=hours_ago)
    divine = 10.0 * (1 + edge) / 100.0
    con.execute(
        "INSERT INTO cross_market_hour VALUES ('L', ?, ?, 1, 10, ?, 10, 10, ?, ?, ?, ?, 100, 100, 100)",
        [item_id, at, items, divine, items, divine, divine],
    )


def test_loops_need_enough_traded_and_the_steadiest_come_first(con):
    _item(con, "currency:anchor", [10, 10, 10])  # the latest hour comes from the prices
    _loop_hour(con, "currency:thin", 0, items=2, edge=40.0)  # one odd trade: ignored
    _loop_hour(con, "currency:once", 0, items=500, edge=0.5)  # pays most, but only now
    for h in range(3):
        _loop_hour(con, "currency:steady", h, items=100, edge=0.05)
    [one, _, three] = missed.missed(con, "L")
    assert [lp["name"] for lp in one["loops"]] == ["Once", "Steady"] and one["loops_paid"] == 2
    # Over 3 hours, the one that paid every hour leads, with its volume per paying hour.
    assert [lp["name"] for lp in three["loops"]] == ["Steady", "Once"]
    assert three["loops"][0]["hours_paid"] == 3 and three["loops"][0]["volume"] == 1000
    # This hour's orders: bid halfway up the Chaos range (flat at 10c here), ask three
    # quarters up the Divine one, and it still pays from the bid at the worst sale.
    steady = three["loops"][0]
    assert (steady["bid"], steady["bid_in"], steady["order_ok"]) == (10, "chaos", True)
    assert steady["ask"] == pytest.approx(10 * 1.05 / 100)
    # Its last 24 hours, from one grouped query: 3 hours traded at 10c.
    assert (steady["range_low"], steady["range_avg"], steady["range_high"]) == (10, 10, 10)
    assert steady["range_hours"] == 3
    # How often the orders went through: only the hour 2 back has its outcome known, and
    # flat prices never trade past the bid. One try is too few to give a share.
    assert (steady["tries"], steady["through"], steady["chance"]) == (1, 0, None)


def _chaos_market(con, item_id: str, hours: int, low: float, high: float, items: float):
    """An item's Chaos-market hours ending at LATEST (cross_market_hour, no Divine leg),
    averaging midway between `low` and `high`."""
    _item(con, item_id, [(low + high) / 2] * hours)  # the item row, and the latest hour
    for h in range(hours):
        con.execute(
            "INSERT INTO cross_market_hour (league_id, item_id, observed_at, day_offset,"
            " chaos_price, chaos_volume, chaos_low, chaos_high) VALUES ('L', ?, ?, 1, ?, ?, ?, ?)",
            [item_id, LATEST - timedelta(hours=h), (low + high) / 2, items, low, high],
        )


def test_volatile_flips_are_liquid_wide_but_not_wild(con):
    _chaos_market(con, "currency:flip", 8, 16, 24, items=1000)  # 20c, a 40% range
    _chaos_market(con, "currency:wild", 8, 10, 30, items=1000)  # 100%: one odd trade
    _chaos_market(con, "currency:flat", 8, 19.5, 20.5, items=1000)  # 5%: nothing to gain
    _chaos_market(con, "currency:quiet", 8, 16, 24, items=100)  # 2k Chaos traded: too little
    [one, _, three] = missed.missed(con, "L")
    [flip] = one["flips"]
    assert flip["name"] == "Flip" and flip["range"] == pytest.approx(0.4)
    # Bid 10% up the hour's range (16.8c), list 75% up (22c), cut 1% an hour, in whole
    # Chaos: the smallest lot within 1% is 50c for 3 (16.67c each); 22c each.
    assert (flip["bid_total"], flip["bid_lot"], flip["bid"]) == pytest.approx((50, 3, 50 / 3))
    assert (flip["ask_total"], flip["ask_lot"]) == (22, 1) and flip["cut"] == 0.01
    # The same flip from each earlier hour: bought (the next low, 16c, is under 16.8c),
    # then sold at 22c within 6 hours (highs of 24c). Hours with the outcome known: 1.
    assert (flip["tries"], flip["through"], flip["chance"]) == (1, 1, None)
    assert three["flips"] == []  # the latest hour's, so sent once, with the 1-hour look-back


def test_orders_are_whole_chaos_for_whole_lots():
    """The smallest lot whose whole-Chaos total is within 1% of the target: a bid never
    pays more than the target, an ask never asks less."""
    target = pl.DataFrame({"x": [16.8, 5.5, 662.4, 4.27, 0.0783, 0.000519]})
    want = {
        # 16.67c, 5.5c, 662c, 4.25c each; 5c for 64 (0.0781c); 1 Divine for 1927.
        "buy": [(3, 50), (2, 11), (1, 662), (4, 17), (64, 5), (1927, 1)],
        # 16.8c, 5.5c, 663c, 4.29c each; 3c for 38 (0.0789c); 1 Divine for 1926.
        "sell": [(5, 84), (2, 11), (1, 663), (7, 30), (38, 3), (1926, 1)],
    }
    for side, rows in want.items():
        lot, total = missed.whole(pl.col("x"), side)
        assert target.select(lot=lot, total=total).rows() == [(n, float(c)) for n, c in rows], side


def _orb_hours(con, item_id: str, name: str, hours: int, price: float, spread: float = 0.1):
    """A reward-pool item's Chaos-market hours ending at LATEST (cross_market_hour only:
    pool items needn't have price rows)."""
    con.execute(
        "INSERT INTO item (id, game, canonical_name, category) VALUES (?, 'poe1', ?, 'currency')",
        [item_id, name],
    )
    con.execute("INSERT INTO card_reward_pool VALUES ('Delirium Orb', ?)", [item_id])
    for h in range(hours):
        con.execute(
            "INSERT INTO cross_market_hour (league_id, item_id, observed_at, day_offset,"
            " chaos_price, chaos_volume, chaos_low, chaos_high) VALUES ('L', ?, ?, 1, ?, 50, ?, ?)",
            [
                item_id,
                LATEST - timedelta(hours=h),
                price,
                price * (1 - spread),
                price * (1 + spread),
            ],
        )


def test_random_rewards_are_valued_at_the_cheapest_roll(con):
    """Disdain (5 cards → 1 Delirium Orb) at 0.3c a card: a set costs 1.5c and pays
    if even the cheapest orb (2c) beats it. The dear orb (9c) never counts."""
    _item(con, "currency:disdain", [0.3] * 6, spread=0.1)
    con.execute("UPDATE price_observation SET volume = 50 WHERE item_id = 'currency:disdain'")
    con.execute(
        "INSERT INTO divination_card (item_id, name, stack_size, reward_kind, reward_name,"
        " reward_quantity, reward_fixed, followed) VALUES ('currency:disdain', 'Disdain', 5,"
        " 'currency', 'Delirium Orb', 1, false, true)"
    )
    _orb_hours(con, "currency:fine-delirium-orb", "Fine Delirium Orb", 6, 2.0)
    _orb_hours(con, "currency:diviners-delirium-orb", "Diviner's Delirium Orb", 6, 9.0)
    [one, _, three] = missed.missed(con, "L")
    [card] = one["cards"]
    assert (card["name"], card["reward"], card["worst_roll"]) == (
        "Disdain",
        "1× Delirium Orb",
        True,
    )
    assert card["margin"] == pytest.approx(2.0 - 1.5) and card["set_cost"] == pytest.approx(1.5)
    assert three["cards"][0]["hours_paid"] == 3
    # Orders: bid the card's low (0.27c), ask the cheapest orb's average (2c); a set still
    # pays at the cheapest orb's low (1.8c vs 1.35c).
    assert (card["bid"], card["ask"], card["order_ok"]) == pytest.approx((0.27, 2.0, True))
    # From each hour with the outcome known (4 of the 6): flat cards never trade under the
    # bid, so nothing went through.
    assert (card["tries"], card["through"], card["chance"]) == (4, 0, 0.0)


def test_a_random_reward_needs_most_of_its_pool_traded(con):
    """The cheap orb traded only hours ago: in the latest hours only the dear one did, so
    a 'floor' of 9c would be a guess. Those hours don't count."""
    _item(con, "currency:disdain", [0.3] * 6)
    con.execute("UPDATE price_observation SET volume = 50 WHERE item_id = 'currency:disdain'")
    con.execute(
        "INSERT INTO divination_card (item_id, name, stack_size, reward_kind, reward_name,"
        " reward_quantity, reward_fixed, followed) VALUES ('currency:disdain', 'Disdain', 5,"
        " 'currency', 'Delirium Orb', 1, false, true)"
    )
    _orb_hours(con, "currency:diviners-delirium-orb", "Diviner's Delirium Orb", 6, 9.0)
    _orb_hours(con, "currency:fine-delirium-orb", "Fine Delirium Orb", 6, 2.0)
    con.execute(
        "DELETE FROM cross_market_hour WHERE item_id = 'currency:fine-delirium-orb'"
        " AND observed_at > ?",
        [LATEST - timedelta(hours=3)],
    )
    [_, _, three] = missed.missed(con, "L")
    assert three["cards"] == []
