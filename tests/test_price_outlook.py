"""The price outlook research (analysis/price_outlook.py, finding 9): the backtest set,
past leagues' paths, the leave-one-league-out backtest, scoring and the shipped rule.
Synthetic leagues only, no real data."""

import math

import polars as pl
import pytest

from exiledbroker.analysis import price_outlook as po
from exiledbroker.config import Settings
from exiledbroker.storage import db


def _league(
    name: str, items: dict[str, tuple[str, callable]], hours: int = 340, rate=lambda h: 100.0
) -> tuple[pl.DataFrame, pl.DataFrame]:
    """A league's traded hours and its clock: `items` maps item id to (group, Chaos price
    by hour); every item trades every hour, 1,000c an hour (thick)."""
    prices = pl.DataFrame(
        [
            (name, item, grp, h, float(price(h)), 1000.0)
            for item, (grp, price) in items.items()
            for h in range(hours)
        ],
        schema={
            "league": pl.String,
            "item_id": pl.String,
            "grp": pl.String,
            "hour": pl.Int32,
            "chaos": pl.Float64,
            "cv": pl.Float64,
        },
        orient="row",
    )
    clock = pl.DataFrame(
        {
            "league": [name] * hours,
            "hour": list(range(hours)),
            "rate": [rate(h) for h in range(hours)],
        },
        schema={"league": pl.String, "hour": pl.Int32, "rate": pl.Float64},
    )
    return prices, clock


def _flat(c: float = 10.0):
    return lambda h: c


def test_forward_change_uses_the_next_hours_not_the_price_now():
    # The price doubles at hour 100: the decision at hour 96 sees 10c now, sells over
    # hours 97–102 (median of 10, 10, 10, 20, 20, 20 = 15) and holds into 121–126 (20).
    prices, clock = _league("A", {"x": ("currency", lambda h: 10.0 if h < 100 else 20.0)})
    g = po.hourly_grid(prices, clock).filter(hour=96)
    assert g["s_chaos"][0] == pytest.approx(10.0)
    assert g["y_h24_chaos"][0] == pytest.approx(math.log(20 / 15))
    assert g["m_h24_chaos"][0] == pytest.approx(0.0)


def test_divine_price_carries_the_rate_forward():
    # No Divine rate for hours 10–19: those hours use hour 9's rate (100c).
    def rate(h):
        return None if 10 <= h < 20 else (100.0 if h < 10 else 200.0)

    prices, clock = _league("A", {"x": ("currency", _flat(50.0))}, hours=40, rate=rate)
    g = po.hourly_grid(prices, clock)
    assert g.filter(hour=15)["div"][0] == pytest.approx(0.5)
    assert g.filter(hour=25)["div"][0] == pytest.approx(0.25)


def test_rows_mark_thin_markets_and_unloaded_hours_unknown():
    prices, clock = _league("A", {"x": ("currency", _flat()), "y": ("currency", _flat())})
    # y trades one hour in four: thin.
    prices = prices.filter((pl.col("item_id") == "x") | (pl.col("hour") % 4 == 0))
    rows = po.hourly_rows(prices, clock)
    at = rows.filter(day=5.0)
    assert at.filter(item_id="x")["thick"][0] is True
    assert at.filter(item_id="y").is_empty() or at.filter(item_id="y")["thick"][0] is False
    assert set(rows["phase"]) == {"days 0-2", "days 2-7", "days 7-14", "later"}  # 340 h
    assert (rows["day"] * 24 % po.STEP_HOURS == 0).all()

    # Hours 100–199 weren't loaded: the share of hours traded counts only loaded hours.
    gap = clock.filter((pl.col("hour") < 100) | (pl.col("hour") >= 200))
    rows = po.hourly_rows(prices.filter(pl.col("hour").is_in(gap["hour"].to_list())), gap)
    assert rows.filter(item_id="x", day=210 / 24)["thick"][0] is True
    assert rows.filter((pl.col("day") * 24 >= 100) & (pl.col("day") * 24 < 200)).is_empty()


def _rows(league: str, item: str, grp: str, ys: dict[int, float]) -> pl.DataFrame:
    n = len(ys)
    return pl.DataFrame(
        {
            "league": [league] * n,
            "item_id": [item] * n,
            "grp": [grp] * n,
            "bin": list(ys),
            "y": list(ys.values()),
        }
    )


def test_paths_take_each_leagues_median_then_the_median_over_leagues():
    past = pl.concat(
        [
            _rows("A", "x", "g", {0: -0.2}),
            _rows("A", "x", "g", {0: -0.4}).with_columns(bin=pl.lit(0, pl.Int64)),
            _rows("B", "x", "g", {0: 0.1}),
            _rows("C", "x", "g", {0: 0.0}),
            _rows("B", "z", "g", {1: 0.5}),
        ]
    )
    item, grp, drift = po.paths(past, "y")
    x = item.filter(item_id="x", bin=0)
    # A's median is −0.3; the median of (−0.3, 0.1, 0.0) is 0.0.
    assert x["item"][0] == pytest.approx(0.0)
    assert x["item_n"][0] == 3
    assert grp.filter(bin=0)["group"][0] == pytest.approx(0.0)
    assert drift.filter(bin=1)["drift"][0] == pytest.approx(0.5)


def test_an_item_with_one_past_league_falls_back_to_its_group():
    past = pl.concat(
        [
            _rows("A", "x", "g", {0: 0.3}),
            _rows("A", "w", "g", {0: -0.1}),
            _rows("B", "w", "g", {0: -0.1}),
        ]
    )
    now = _rows("T", "x", "g", {0: 0.0})
    out = po.with_paths(now, past, "y")
    assert out["basis"][0] == "group"
    # Group g: A's median (0.3, −0.1) = 0.1, B's −0.1; median over leagues 0.0.
    assert out["item"][0] == pytest.approx(0.0)


def _backtest_rows(leagues: list[str], drop: float) -> pl.DataFrame:
    """Every league: item "x" loses `drop` (log) in Divines over every 24 hours of days
    0–2 and is flat after; "y" is flat throughout."""
    frames = []
    for lg in leagues:
        f = {
            "x": ("currency", lambda h: 100.0 * math.exp(-drop * min(h, 48) / 24)),
            "y": ("currency", _flat(100.0)),
        }
        prices, clock = _league(lg, f)
        frames.append(po.hourly_rows(prices, clock))
    return pl.concat(frames)


def test_backtest_finds_a_path_that_repeats_and_beats_no_change():
    rows = _backtest_rows(["A", "B", "C"], drop=0.3)
    bt = po.backtest(rows, "div", "h24")
    assert set(bt["league"]) == {"A", "B", "C"}
    s = po.score(bt.filter(phase="days 0-2"), ["model"], (0.05,))
    item = s.filter(model="item")
    assert item["skill"][0] > 0.5
    assert item["hit_5"][0] == pytest.approx(1.0)
    assert s.filter(model="zero")["skill"][0] == pytest.approx(0.0)
    # The flat item never gets a verdict.
    flat = bt.filter(model="shrunk", item_id="y")
    assert (flat["pred"].abs() < 0.05).all()


def test_backtest_never_sees_the_target_league():
    # A, B and C rise; T falls. Predicting T from the others says hold, and is wrong.
    up = _backtest_rows(["A", "B", "C"], drop=-0.3)
    down = _backtest_rows(["T"], drop=0.3)
    bt = po.backtest(pl.concat([up, down]), "div", "h24", targets=["T"])
    x = bt.filter(model="item", item_id="x", phase="days 0-2")
    assert set(bt["league"]) == {"T"}
    assert (x["pred"] > 0).all()
    assert (x["y"] < 0).all()


def test_score_payoff_and_coverage():
    bt = pl.DataFrame(
        {
            "league": ["A"] * 4,
            "model": ["m"] * 4,
            "y": [0.1, -0.2, 0.05, 0.0],
            "pred": [0.1, -0.1, -0.06, 0.0],
            "swing": [0.01] * 4,
            "lo": [-1.0, -1.0, 0.1, -1.0],
            "hi": [1.0, 1.0, 1.0, 1.0],
            "zlo": [-1.0] * 4,
            "zhi": [1.0] * 4,
        }
    )
    s = po.score(bt, ["model"], (0.05,))
    assert s["called_5"][0] == pytest.approx(0.75)
    assert s["hit_5"][0] == pytest.approx(2 / 3)
    # Hold +0.1, sell avoided −0.2 (+0.2), sell missed +0.05 (−0.05).
    assert s["gain_5"][0] == pytest.approx(0.25 / 3)
    assert s["cover"][0] == pytest.approx(0.75)
    no_change = (0.1 + 0.2 + 0.05) / 4
    assert s["skill"][0] == pytest.approx(1 - ((0.0 + 0.1 + 0.11 + 0.0) / 4) / no_change)


def test_shipped_verdicts():
    assert po.ship_verdict("days 2-7", True, "h24", -0.06) == "sell"
    assert po.ship_verdict("days 2-7", True, "h24", 0.06) == "hold"
    assert po.ship_verdict("days 2-7", True, "h24", 0.01) == "none"
    # Thin, days 2–7, 24 hours: sell only past −8%, never hold.
    assert po.ship_verdict("days 2-7", False, "h24", -0.06) == "none"
    assert po.ship_verdict("days 2-7", False, "h24", -0.09) == "sell"
    assert po.ship_verdict("days 2-7", False, "h24", 0.5) == "none"
    # No verdict after the launch fortnight, or without a path.
    assert po.ship_verdict("later", True, "d3", -0.5) == "none"
    assert po.ship_verdict("days 0-2", True, "h24", None) == "none"


def test_build_gives_paths_for_items_with_two_leagues_and_the_constants():
    rows = _backtest_rows(["A", "B", "C"], drop=0.3)
    rows = pl.concat([rows, _backtest_rows(["D"], drop=0.3).with_columns(item_id=pl.lit("solo"))])
    paths, consts = po.build(rows)
    assert set(paths["item_id"]) == {"x", "y"}
    assert set(paths["horizon"]) == {"h24", "d3"}
    assert (paths["leagues"] >= po.MIN_LEAGUES).all()
    x0 = paths.filter(item_id="x", horizon="h24", bin=0)["path"][0]
    assert x0 == pytest.approx(-0.3, abs=0.02)
    cell = consts.filter(phase="days 0-2", thick=True, horizon="h24")
    assert cell["weight"][0] == pytest.approx(1.0, abs=0.1)
    assert cell["sell_below"][0] == 0.05


def test_daily_rows_drop_rounded_prices_and_know_only_yesterday():
    daily = pl.DataFrame(
        {
            "league": ["A"] * 6,
            "item_id": ["x"] * 6,
            "grp": ["currency"] * 6,
            "day": [0, 1, 2, 3, 4, 5],
            "chaos": [5.0, 20.0, 20.0, 40.0, 40.0, 40.0],
            "div": [0.05, 0.2, 0.2, 0.4, 0.4, 0.4],
        }
    )
    rows = po.daily_rows(daily)
    assert rows["day"].to_list() == [1.0, 2.0, 3.0, 4.0, 5.0]  # day 0 is under 10c
    d2 = rows.filter(day=2.0)
    assert d2["y_h24_div"][0] == pytest.approx(math.log(2))
    assert d2["m_h24_div"][0] is None  # day 0 was dropped, so day 1's move is unknown
    d4 = rows.filter(day=4.0)
    assert d4["m_h24_div"][0] == pytest.approx(math.log(2))  # day 3 over day 2
    assert d4["thick"][0] is False


def test_load_hourly_and_dump_coverage_read_the_database(tmp_path):
    settings = Settings(data_dir=tmp_path)
    con = db.connect(settings.db_path)
    db.init_schema(con)
    con.execute(
        "INSERT INTO league (id, game, name, start_at, kind) "
        "VALUES ('poe1-a', 'poe1', 'A', '2026-01-01', 'challenge')"
    )
    for item, cat in (("currency:x", "currency"), ("currency:y", "essence")):
        con.execute(
            "INSERT INTO item (id, game, canonical_name, category) VALUES (?, 'poe1', ?, ?)",
            [item, item, cat],
        )
    for h in range(3):
        con.execute(
            "INSERT INTO cross_market_hour (league_id, item_id, observed_at, day_offset, "
            "chaos_price, chaos_volume, divine_rate) VALUES ('poe1-a', 'currency:x', "
            "TIMESTAMP '2026-01-01' + to_hours(?), ?, 10, 5, ?)",
            [h, h / 24, 100.0 if h else None],
        )
    con.execute(
        "INSERT INTO cross_market_hour (league_id, item_id, observed_at, day_offset, "
        "chaos_price, chaos_volume) VALUES ('poe1-a', 'currency:y', '2026-01-01', 0, 1, 1)"
    )
    con.execute(
        "INSERT INTO price_observation (item_id, league_id, observed_at, day_offset, "
        "chaos_value, divine_value, source) VALUES ('currency:x', 'poe1-a', '2026-01-01', "
        "0, 12, 0.12, 'poe.ninja-dump')"
    )
    prices, hours = po.load_hourly(con, "A")
    assert prices.height == 4
    assert prices.filter(item_id="currency:y")["grp"][0] == "essence"
    assert hours.sort("hour")["rate"].to_list() == [None, 100.0, 100.0]
    assert po.exchange_leagues(con) == ["A"]
    cov = po.dump_coverage(con, "A", None)
    assert cov["exchange_items"] == 2
    assert cov["usable"] == 1
    assert cov["cv_usable"] == pytest.approx(150 / 151)
    con.close()
