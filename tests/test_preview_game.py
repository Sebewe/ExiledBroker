"""The trading game's hours (preview/build.game_hours): each hour, the recap's own order
for a loop or card turn-in, filled by the Backtest's rules, with what it spent, made and
when it sold."""

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
    # Cards stand in: one card's order from hour 1 filled, and its reward "r" (3 a
    # purchase) never sold: the Backtest counted it a 5c loss when it gave up, in hour 3.
    cards = {("c", T0 + H): (True, -5.0, 105.0, T0 + 3 * H, 35.0, "r", 3.0, True)}
    monkeypatch.setattr(pb, "_card_orders", lambda *a: cards)
    reward = pl.DataFrame(
        {
            "item_id": ["r"] * 2,
            "observed_at": [T0 + H, T0 + 2 * H],
            "day_offset": [0, 0],
            "p": [40.0, 30.0],
            "lo": [38.0, 25.0],
            "hi": [42.0, 33.0],
            "units": [50.0, 60.0],
            "cv": [0.0, 0.0],
        }
    )
    monkeypatch.setattr(pb.bt, "_prices", lambda *a, **k: reward)


def _windows() -> list[dict]:
    loop = {"item_id": "a", "direction": "chaos_first"}
    cards = [{"item_id": "c", "worst_roll": False}, {"item_id": "w", "worst_roll": True}]
    return [
        {"latest_hour": f"{T0:%Y-%m-%dT%H:%M:%S}Z", "loops": [loop], "cards": cards, "flips": []},
        # A longer look-back lists the same loop again: it's judged once.
        {"latest_hour": f"{T0:%Y-%m-%dT%H:%M:%S}Z", "loops": [loop], "cards": [], "flips": []},
    ]


def test_the_game_takes_each_hours_own_order_with_what_it_spent_and_when_it_sold(market):
    recap = _windows()
    games = {
        n: {
            "latest_hour": f"{T0 + (n - 1) * H:%Y-%m-%dT%H:%M:%S}Z",
            "divine_chaos": 100.0,
            "recap": recap,
        }
        for n in (1, 2, 3)
    }
    out = pb.game_hours(None, "Mirage", games, T0 + 4 * H)
    assert sorted(out) == [1, 2, 3]
    loop = next(o for o in out[1]["orders"] if o["kind"] == "loop")
    # Hour 0's order: 88 items at the 10c bid, sold in hour 2 at the ask.
    assert loop["filled"] is True and loop["spent"] == pytest.approx(880.0)
    assert loop["pnl"] == pytest.approx(88 * (100 / 8 - 10))
    assert loop["settle_at"] == f"{T0 + 2 * H:%Y-%m-%dT%H:%M:%S}Z"
    # It buys whole lots of what one sale takes: 1 Divine for 8 items, at the 10c bid.
    assert loop["lot"] == pytest.approx(80.0)
    assert (loop["hold"], loop["units"], loop["unsold"]) == ("a", 8, False)
    # Hour 1's didn't fill: nothing spent; hour 2's wasn't placed.
    nxt = next(o for o in out[2]["orders"] if o["kind"] == "loop")
    assert (nxt["filled"], nxt["spent"], nxt["pnl"], nxt["settle_at"]) == (False, None, None, None)
    assert next(o for o in out[3]["orders"] if o["kind"] == "loop")["filled"] is None
    # The card's order from hour 1 lost 5c of the 105c it spent; random rewards aren't offered.
    card = next(o for o in out[2]["orders"] if o["kind"] == "card")
    assert (card["spent"], card["pnl"], card["lot"]) == (105.0, -5.0, 35.0)
    # Its reward never sold: the player holds 3 a purchase, priced each hour.
    assert (card["hold"], card["units"], card["unsold"]) == ("r", 3.0, True)
    assert out[2]["prices"] == {"r": [38.0, 40.0, 42.0, 50.0]}
    assert out[3]["prices"] == {"r": [25.0, 30.0, 33.0, 60.0]}
    assert all(o["item_id"] != "w" for g in out.values() for o in g["orders"])
    assert out[1]["prices"] == {}  # no flips listed, and no hour of the reward
