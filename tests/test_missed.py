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
    assert one["volatile"][0]["name"] == "Swingy"
    assert one["volatile"][0]["range"] == pytest.approx(1.0)
    # Nothing paid: no loops or cards in this data, and the totals say so.
    assert (one["loops"], one["cards"], one["loops_missed"], one["cards_missed"]) == ([], [], 0, 0)


def test_no_trades_yet(con):
    assert missed.missed(con, "L") == []
