"""Demand research (analysis/demand.py, finding 11) on synthetic frames: readings use
hours <= t only, outcomes start after t, excess, labels, leave one league out, and the
stock features. No database file, no data/, no requests."""

import math

import polars as pl
import pytest

from exiledbroker.analysis import demand as dm

HOURS = 24 * 8


def _rows(item="currency:a", growth=0.01, volume=100.0, rate=100.0, spike_at=None):
    """An item traded every hour in the Chaos market, its Chaos price growing by `growth`
    a log-hour (so its Divine price does too at a constant rate), and a busy spell."""
    out = []
    for h in range(HOURS):
        p = rate * math.exp(growth * h)
        v = volume * (5 if spike_at is not None and spike_at <= h < spike_at + 6 else 1)
        out.append(
            {
                "item_id": item,
                "grp": "currency",
                "hour": h,
                "chaos_price": p,
                "chaos_volume": v,
                "chaos_low": p * 0.9,
                "chaos_high": p * 1.1,
                "divine_price": None,
                "divine_volume": None,
            }
        )
    return pl.DataFrame(
        out, schema_overrides={"divine_price": pl.Float64, "divine_volume": pl.Float64}
    )


def _hours(rate=100.0):
    return pl.DataFrame({"hour": list(range(HOURS)), "rate": [rate] * HOURS})


def test_readings_use_only_past_hours_and_outcomes_start_after():
    rows = _rows(spike_at=100)
    full = dm.readings("L", rows, _hours())
    cut = dm.readings(
        "L", rows.filter(pl.col("hour") <= 120), _hours().filter(pl.col("hour") <= 120)
    )
    feats = ["s6", "m6", "m24", "m72", "v6", "u6", "base", "ratio", "uratio", "liquid"]
    j = full.join(cut, on=["item_id", "hour"], suffix="_cut").filter(pl.col("hour") <= 120)
    for c in feats:
        assert j[c].to_list() == j[f"{c}_cut"].to_list(), c
    at = full.filter(pl.col("hour") == 50).row(0, named=True)
    # Price ×e^0.01 an hour: 6-hour and 3-day moves, and the outcome from the medians of
    # hours t+1..t+3 to t+25..t+27 (harsh: buy at the high, sell at the low).
    assert at["m6"] == pytest.approx(0.06)
    assert at["m72"] is None  # needs 72 hours of history
    assert at["y24"] == pytest.approx(0.24)
    assert at["yh24"] == pytest.approx(0.24 + math.log(0.9 / 1.1))
    # No outcome once the exit hours aren't loaded.
    assert full.filter(pl.col("hour") == HOURS - 10)["y24"][0] is None


def test_volume_ratio_against_previous_days_and_liquidity():
    rd = dm.readings("L", _rows(growth=0.0, spike_at=100), _hours())
    row = rd.filter(pl.col("hour") == 105).row(0, named=True)
    # The busy 6 hours against the same hours on earlier days, in value and in units.
    assert row["ratio"] == pytest.approx(5.0) and row["uratio"] == pytest.approx(5.0)
    assert rd.filter(pl.col("hour") == 20)["ratio"][0] is None  # no earlier day yet
    assert row["liquid"]  # >= 2000c traded an hour and >= 5c
    thin = dm.readings("L", _rows(volume=1.0), _hours())
    assert not thin["liquid"].any()


def test_excess_labels_and_leave_one_league_out():
    frames = []
    for lg in ("A", "B", "C"):
        rows = pl.concat([_rows("x:up", 0.01, spike_at=100), _rows("x:flat", 0.0)])
        frames.append(dm.readings(lg, rows, _hours()))
    df = dm.with_excess(pl.concat(frames))
    # Excess is against the hour's median over liquid items (two here: the mean of both).
    r = df.filter(pl.col("item_id") == "x:up", pl.col("hour") == 105, pl.col("league") == "A")
    assert r["x24"][0] == pytest.approx(0.12)
    lab = dm.labels(df.with_columns(m6=pl.lit(0.2)))
    assert lab.filter("rising")["hour"].is_between(100, 110).all()
    sig = dm.lolo(df.with_columns(m6=pl.lit(0.2)), dm.rising_expr, [("ratio", 3.0, 0.1)], 1)
    assert set(sig["league"]) == set()  # 6 signals a league: under MIN_TRAIN_N
    old = dm.MIN_TRAIN_N
    try:
        dm.MIN_TRAIN_N = 1
        sig = dm.lolo(df.with_columns(m6=pl.lit(0.2)), dm.rising_expr, [("ratio", 3.0, 0.1)], 1)
    finally:
        dm.MIN_TRAIN_N = old
    assert set(sig["league"]) == {"A", "B", "C"}
    s = dm.summary(sig, "24", 1)
    assert s["n"] == sig.height and s["leagues"] == 3 and s["excess"] > 0


def test_stock_features_drain_and_imbalance():
    hours = _hours()
    mk = pl.DataFrame(
        [
            {
                "item_id": "currency:a",
                "hour": h,
                "market": "chaos",
                "stock_x_lo": 50 if h >= 96 else 100,
                "stock_x_hi": 100,
                "stock_ref_lo": 1000,
                "stock_ref_hi": 2000,
            }
            for h in range(HOURS)
        ]
    )
    st = dm.stock_per_hour(mk, hours)
    assert st.filter(pl.col("hour") == 0)["buy_hi"][0] == pytest.approx(20.0)  # 2000c at 100c
    rd = dm.stock_features(st, dm.readings("L", _rows(growth=0.0), hours))
    at = rd.filter(pl.col("hour") == 120).row(0, named=True)
    assert at["drain6"] == pytest.approx(0.5)  # half the sellers' book traded through
    assert at["S6"] == pytest.approx(100.0) and at["B6"] == pytest.approx(20.0)
    assert at["dI"] == pytest.approx(0.0)  # same balance as the earlier days
    assert rd.filter(pl.col("hour") == 30)["drain6"][0] == pytest.approx(0.0)
