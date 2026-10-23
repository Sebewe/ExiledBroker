from datetime import UTC, datetime, timedelta

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
