"""Patient flips (analysis/flips.py): bought from a bid low in the entry hour's range,
listed high, the ask cut each hour until it sells."""

from datetime import datetime, timedelta

import polars as pl
import pytest

from exiledbroker.analysis import flips

T0 = datetime(2026, 3, 7)
H = timedelta(hours=1)


def _prices(hours: list[tuple]) -> pl.DataFrame:
    """(avg, low, high) per hour from T0, 1000 items traded each hour."""
    return pl.DataFrame(
        {
            "item_id": ["currency:a"] * len(hours),
            "observed_at": [T0 + i * H for i in range(len(hours))],
            "day_offset": [i / 24 for i in range(len(hours))],
            "p": [float(h[0]) for h in hours],
            "lo": [float(h[1]) for h in hours],
            "hi": [float(h[2]) for h in hours],
            "units": [1000.0] * len(hours),
            "cv": [h[0] * 1000.0 for h in hours],
        }
    ).with_columns(rng=(pl.col("hi") - pl.col("lo")) / pl.col("p"))


@pytest.fixture(autouse=True)
def short_hold(monkeypatch):
    monkeypatch.setattr(flips, "MAX_HOLD", 3)


RATE = pl.DataFrame({"observed_at": [T0 + i * H for i in range(8)], "rate": [100.0] * 8})


def test_bought_low_sold_at_the_ask_once_a_trade_reaches_it():
    # Entry hour 8–12c: bid 8.4c (10% up), ask 11c (75% up).
    px = _prices([(10, 8, 12), (10, 8, 12), (10, 9, 12), (10, 9, 12), (10, 9, 12)])
    [p] = flips.positions(px, RATE, [T0], "touch", cut=0.0).to_dicts()
    # 100 items (10% of 1000; 10 Divines buy far more), sold in hour 2 at 11c.
    assert p["held"] == 100 and p["sold_at"] == 2
    assert p["profit"] == pytest.approx(100 * (11 - 8.4) / 100)
    # Strict: hour 1's 10c average never went under the bid, so nothing is bought.
    assert flips.positions(px, RATE, [T0], "strict", cut=0.0).is_empty()


def test_the_ask_comes_down_each_hour_until_it_sells():
    # After the buy, trades top out at 10.5c: the 11c ask sells only once cut 10%.
    px = _prices([(10, 8, 12), (10, 8, 12), (10, 9, 10.5), (10, 9, 10.5), (10, 9, 10.5)])
    [p] = flips.positions(px, RATE, [T0], "touch", cut=0.10).to_dicts()
    assert p["sold_at"] == 3 and not p["dumped"]
    assert p["value"] == pytest.approx(100 * 11 * 0.9 / 100)


def test_whats_left_after_the_hold_is_dumped_at_the_low():
    px = _prices([(10, 8, 12), (10, 8, 12), (10, 9, 10), (10, 9, 10), (10, 9, 10)])
    [p] = flips.positions(px, RATE, [T0], "touch", cut=0.0).to_dicts()
    assert p["dumped"] and p["value"] == pytest.approx(100 * 9 / 100)


def test_spread_fill_models_take_only_the_share_past_the_price():
    px = _prices([(10, 8, 12), (10, 8, 12), (10, 8, 12), (10, 8, 12), (10, 8, 12)])
    held = {m: flips.positions(px, RATE, [T0], m)["held"][0] for m in ("touch", "even", "peaked")}
    # Bid 8.4c in an 8–12c hour: 10% of the even share under it (0.4 / 4), less peaked.
    assert held["touch"] == 100 and held["even"] == 10 and held["peaked"] < held["even"]


def test_whole_lots_fill_lot_by_lot_at_whole_chaos():
    px = _prices([(10, 8, 12), (10, 8, 12), (10, 9, 12), (10, 9, 12), (10, 9, 12)])
    [p] = flips.positions(px, RATE, [T0], "touch", cut=0.0, whole_lots=True).to_dicts()
    # Bid 8.4c: 25c for 3 (8.33c each), so 99 of the 100 items it could take; the 11c
    # ask is 11c each.
    assert (p["buy_lot"], p["held"]) == (3, 99)
    assert p["profit"] == pytest.approx(99 * (11 - 25 / 3) / 100)
