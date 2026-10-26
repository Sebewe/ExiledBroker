"""The preview's "did it pay the next hour?" (preview/build.recap_next): each hour after
the chosen day, the recap's own order for a trade, filled by the Backtest's rules."""

from datetime import datetime, timedelta

import polars as pl
import pytest

from exiledbroker.preview import build as pb

T0 = datetime(2026, 3, 7)  # the chosen day's last hour
H = timedelta(hours=1)


def _cross(rows: dict[int, tuple]) -> pl.DataFrame:
    """Hour -> (chaos avg/low/high, divine avg/low/high), 1000 items in each market, the
    Divine at 100c."""
    cols = ["cp", "clo", "chi", "dp", "dlo", "dhi"]
    return pl.DataFrame(
        {
            "item_id": ["a"] * len(rows),
            "observed_at": [T0 + h * H for h in rows],
            **{c: [float(r[i]) for r in rows.values()] for i, c in enumerate(cols)},
            "cu": [1000.0] * len(rows),
            "du": [1000.0] * len(rows),
            "rate": [100.0] * len(rows),
            "rlo": [100.0] * len(rows),
            "rhi": [100.0] * len(rows),
        }
    ).sort("observed_at")


@pytest.fixture
def market(monkeypatch):
    """Item "a" loops Chaos first, and the replay ends at hour 4. Each hour's order bids
    halfway up its Chaos range and asks 3/4 up its Divine one, placed if the loop still
    beats 2% from the bid at the hour's worst sale."""
    cross = _cross(
        {
            0: (10, 9, 11, 0.12, 0.11, 0.13),  # bid 10c: 10% from it
            1: (10, 9, 11, 0.12, 0.11, 0.13),  # traded under hour 0's bid
            2: (10.5, 10.2, 11, 0.12, 0.10, 0.13),  # never under hour 1's; no loop from 10.6c
            3: (10, 9, 11, 0.12, 0.11, 0.13),
            4: (10, 9, 11, 0.12, 0.11, 0.13),  # fills hour 3's order; its sale is after
        }
    )
    rate = pl.DataFrame({"observed_at": [T0 + h * H for h in range(8)], "rate": [100.0] * 8})
    monkeypatch.setattr(pb.bt, "_cross_hours", lambda *a, **k: cross)
    monkeypatch.setattr(pb.bt, "_rate", lambda *a, **k: rate)
    # Cards and flips stand in: one card's order from hour 1 filled at a 5c loss.
    cards = {("c", T0 + H): (True, -5.0)}
    monkeypatch.setattr(pb, "_card_orders", lambda *a: cards)
    monkeypatch.setattr(pb, "_flip_orders", lambda *a: {})


def _windows() -> list[dict]:
    loop = {"item_id": "a", "direction": "chaos_first"}
    cards = [{"item_id": "c", "worst_roll": False}, {"item_id": "w", "worst_roll": True}]
    return [
        {"latest_hour": f"{T0:%Y-%m-%dT%H:%M:%S}Z", "loops": [loop], "cards": cards, "flips": []},
        # A longer look-back lists the same loop again: it's judged once.
        {"latest_hour": f"{T0:%Y-%m-%dT%H:%M:%S}Z", "loops": [loop], "cards": [], "flips": []},
    ]


def test_each_hour_places_the_recaps_order_and_fills_it_by_the_backtests_rules(market):
    doc = pb.recap_next(None, "Mirage", _windows(), T0 + 4 * H)
    assert doc["hours"] == 4
    loop, card = doc["trades"]  # the random-reward card isn't replayed
    assert (loop["kind"], loop["direction"], card["item_id"]) == ("loop", "chaos_first", "c")
    # Hour 0's order (the one the recap showed) filled in hour 1 and sold in hour 2 at
    # its ask; hour 1's didn't fill; hour 2's wouldn't pay from its bid, so it wasn't
    # placed; hour 3's filled in hour 4, but its sale is past the replay's end.
    assert loop["filled"] == [True, False, None, True]
    assert loop["paid"] == [True, False, None, None]
    assert loop["next_hour_paid"] is True and loop["still_paid"] is None  # 4 hours known
    assert loop["pnl"][0] > 0 and loop["pnl"][1:] == [None, None, None]
    assert loop["profit"] == pytest.approx(loop["pnl"][0])
    assert (loop["orders"], loop["fills"], loop["traded_hours"], loop["paid_hours"]) == (3, 2, 2, 1)
    # The card's order from hour 1 filled and lost: it didn't pay.
    assert card["paid"] == [None, False, None, None] and card["pnl"][1] == -5.0
    assert card["next_hour_paid"] is None  # no order from the recap's own hour


def test_the_order_is_bought_with_10_divines_at_most_and_sold_at_the_ask(market):
    loop = pb.recap_next(None, "Mirage", _windows(), T0 + 4 * H)["trades"][0]
    # Bid 10c (whole Chaos), ask 0.125 div: the exchange takes 1 Divine for 8 items.
    # 90 items for 10 Divines at the buy hour's 11c high, sold at 100c a Divine.
    assert loop["pnl"][0] == pytest.approx(88 * (100 / 8 - 10))


def test_nothing_is_judged_without_hours_after(market):
    doc = pb.recap_next(None, "Mirage", _windows(), T0)
    assert doc["hours"] == 0
    assert all(t["paid"] == [] and t["next_hour_paid"] is None for t in doc["trades"])
    assert pb.recap_next(None, "Mirage", [], T0) is None
