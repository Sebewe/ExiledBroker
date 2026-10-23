"""The backtest behind the Backtest page (analysis/backtest.py): a trader acting on the
recap an hour late, with small whole-item fills, priced fair and harsh."""

from datetime import datetime, timedelta

import polars as pl
import pytest

from exiledbroker.analysis import backtest as bt
from exiledbroker.api.models import BacktestReport
from exiledbroker.services import backtest as services
from exiledbroker.storage import db
from test_currency_exchange import FakeExchange
from test_live_pipeline import LAUNCH, PAGES, settings  # noqa: F401

T0 = datetime(2026, 3, 7)
H = timedelta(hours=1)


def _loop(hour: int, item: str, edge: float, gap: float, units: float = 1000.0) -> dict:
    return {
        "observed_at": T0 + hour * H,
        "day_offset": hour / 24,
        "item_id": item,
        "direction": "chaos_first",
        "edge": edge,
        "gap": gap,
        "units": units,
        "overlap_chaos": units * 10.0,
        "chaos_price": 10.0,
        "chaos_high": 10.5,
    }


RATE = pl.DataFrame({"observed_at": [T0 + h * H for h in range(6)], "rate": [100.0] * 6})


def test_a_pick_is_traded_at_the_next_hours_prices():
    # Hour 0's loop paid 50%; by hour 1, when the trader can act, it loses 10%.
    loops = pl.DataFrame([_loop(0, "a", 0.5, 0.6), _loop(1, "a", -0.1, 0.0)])
    [trade] = bt.loop_trades(loops, RATE, "top", "harsh").to_dicts()
    assert trade["observed_at"] == T0 and trade["filled"]
    # 10% of 1000 traded = 100 items, capped at 10 Divines (1000c) = 95 items at 10.5c.
    assert trade["pnl"] == pytest.approx(-0.1 * 95 * 10.0 / 100.0)


def test_fair_prices_lose_slippage_on_each_of_the_loops_three_trades():
    loops = pl.DataFrame([_loop(0, "a", 0.5, 0.6), _loop(1, "a", -0.1, 0.03)])
    [trade] = bt.loop_trades(loops, RATE, "top", "fair").to_dicts()  # hour 1 didn't pay
    ret = 1.03 * (1 - bt.SLIPPAGE) ** 3 - 1
    # Bought at 10c + 1%: 99 items fit in 10 Divines.
    assert trade["pnl"] == pytest.approx(ret * 99 * 10.0 / 100.0)


def test_nothing_is_filled_when_the_next_hour_is_too_thin():
    # 5 items traded next hour: 10% of it is less than one whole item.
    loops = pl.DataFrame([_loop(0, "a", 0.5, 0.6), _loop(1, "a", -0.5, 0.6, units=5.0)])
    [trade] = bt.loop_trades(loops, RATE, "top", "harsh").to_dicts()
    assert not trade["filled"] and trade["pnl"] == 0


def test_steady_needs_every_hour_of_the_look_back():
    loops = pl.DataFrame(
        [_loop(0, "a", 0.1, 0.1), _loop(1, "a", 0.1, 0.1), _loop(2, "a", 0.1, 0.1)]
        + [_loop(1, "b", 0.9, 0.9), _loop(2, "b", 0.9, 0.9)]
        + [_loop(3, "a", -0.05, 0.05), _loop(3, "b", -0.05, 0.05)]  # traded, didn't pay
    )
    trades = bt.loop_trades(loops, RATE, "steady", "harsh")
    # Only "a" paid 3 hours running (hours 0–2); "b" paid only 2.
    assert trades.select("observed_at", "item_id").rows() == [(T0 + 2 * H, "a")]


def test_the_report_is_built_stored_and_served(settings):  # noqa: F811
    from test_api import update

    update(settings, FakeExchange(PAGES, now=LAUNCH), 12)
    with db.session(settings.db_path) as con:
        report = bt.build(con)
        bt.store(con, report)
        bt.store(con, report)  # replaced, not added
        stored = services.report(con)
    assert stored == [report]
    checked = BacktestReport.model_validate(report)  # what the API sends
    assert checked.leagues == ["Mirage"] and checked.launch == []  # no earlier league
    rows = {(h.strategy, h.rule, h.scenario): h for h in checked.hourly}
    assert len(rows) == len(bt.STRATEGIES) * len(bt.RULES) * len(bt.SCENARIOS)
    for key, h in rows.items():
        # Hours with both markets of a loop (the first have no Divine rate yet).
        assert 0 < h.hours <= 12 and h.filled <= h.signals, key
        assert h.per_hour == pytest.approx(h.total / h.hours), key
    for strategy, orders in bt.LIMIT_ORDERS.items():
        methods = {(c.method, c.fill) for c in checked.limits if c.strategy == strategy}
        limited = {(m, f) for m in orders if m != "market" for f in bt.FILLS}
        assert methods == {("market", "touch"), *limited}, strategy
    # The worst traded price is never better than the average less slippage.
    for strategy in bt.STRATEGIES:
        harsh, fair = rows[strategy, "top", "harsh"], rows[strategy, "top", "fair"]
        assert harsh.total <= fair.total + 1e-9, strategy


def test_no_report_before_a_run(settings):  # noqa: F811
    with db.session(settings.db_path) as con:
        db.init_schema(con)
        assert services.report(con) == []


def test_launch_picks_are_ranked_from_earlier_leagues_only(monkeypatch):
    seen = []
    real = bt.launch_picks.rank

    def rank(prices, leagues, min_leagues=3):
        seen.append((leagues, sorted(prices["league"].unique().to_list())))
        return real(prices, leagues, min_leagues)

    monkeypatch.setattr(bt.launch_picks, "rank", rank)
    monkeypatch.setattr(bt.launch_picks, "league_windows", lambda con, lg: _windows())
    monkeypatch.setattr(bt, "_launch_prices", lambda con, lg: _launch_px())
    monkeypatch.setattr(bt.db, "rows", lambda con, q, params=None: [("x", "X")])
    bt.launch_results(None, ["A", "B", "C"])
    assert seen == [(["A"], ["A"]), (["B", "A"], ["A", "B"])]


def _windows() -> pl.DataFrame:
    return pl.DataFrame(
        {"item_id": ["x"], "window_id": ["day1"], "divine": [1.0], "divine_volume": [100.0]}
    )


def _launch_px() -> pl.DataFrame:
    return pl.DataFrame(
        {"item_id": ["x"], "day_offset": [0.5], "d": [1.0], "lo": [0.9], "hi": [1.1], "dv": [50.0]}
    )


def _card_prices(card: list[tuple], reward: list[tuple]) -> pl.DataFrame:
    """(hour, avg, low, high, units) for a 5-card set worth 1 reward."""
    rows = [("c", *r) for r in card] + [("r", *r) for r in reward]
    return pl.DataFrame(
        {
            "item_id": [r[0] for r in rows],
            "observed_at": [T0 + r[1] * H for r in rows],
            "day_offset": [r[1] / 24 for r in rows],
            "p": [r[2] for r in rows],
            "lo": [r[3] for r in rows],
            "hi": [r[4] for r in rows],
            "units": [r[5] for r in rows],
            "cv": [r[2] * r[5] for r in rows],
        }
    ).sort("observed_at")


def _from_hour_0(trades: pl.DataFrame) -> list[dict]:
    """The order placed from hour 0's recap (later hours place their own)."""
    return trades.filter(pl.col("observed_at") == T0).to_dicts()


@pytest.fixture
def one_card(monkeypatch):
    cards = pl.DataFrame({"item_id": ["c"], "reward_id": ["r"], "n": [5], "q": [1]})
    monkeypatch.setattr(bt.db, "frame", lambda con, q, params=None: cards)


def test_a_limit_buy_fills_only_if_the_next_hour_trades_below_it(one_card):
    # Hour 0: sets at 5 × 10c (low 8c) against a 100c reward (low 90c). Buy order: 8c.
    reward = [(h, 100, 90, 110, 100) for h in range(4)]
    dipped = _card_prices([(0, 10, 8, 12, 500), (1, 10, 7, 12, 500)], reward)
    [trade] = _from_hour_0(bt.card_limit_trades(None, dipped, RATE, "limit_buy", "touch"))
    # 10 sets (10% of 500 cards / 5) bought at 8c, the rewards sold at hour 2's low, 90c.
    assert trade["pnl"] == pytest.approx(10 * (90 - 5 * 8) / 100)
    # The next hour never went under 8c: no fill, nothing spent.
    held = _card_prices([(0, 10, 8, 12, 500), (1, 10, 8, 12, 500)], reward)
    [unfilled] = _from_hour_0(bt.card_limit_trades(None, held, RATE, "limit_buy", "touch"))
    assert not unfilled["filled"] and unfilled["pnl"] == 0  # placed, cancelled
    # Strict: the hour's average must go under it too.
    [strict] = _from_hour_0(bt.card_limit_trades(None, dipped, RATE, "limit_buy", "strict"))
    assert not strict["filled"]


def test_a_limit_sell_asks_the_recap_hours_average(one_card):
    reward = [(0, 100, 90, 110, 100), (1, 100, 90, 110, 100), (2, 95, 80, 105, 100)]
    prices = _card_prices([(0, 10, 8, 12, 500), (1, 10, 7, 12, 500)], reward)
    [trade] = _from_hour_0(bt.card_limit_trades(None, prices, RATE, "limit_both", "touch"))
    assert trade["pnl"] == pytest.approx(10 * (100 - 40) / 100)  # hour 2 traded up to 105
    # Hour 2 never traded above the 100c ask: the reward is sold at its low instead.
    reward[2] = (2, 95, 80, 99, 100)
    prices = _card_prices([(0, 10, 8, 12, 500), (1, 10, 7, 12, 500)], reward)
    [trade] = _from_hour_0(bt.card_limit_trades(None, prices, RATE, "limit_both", "touch"))
    assert trade["pnl"] == pytest.approx(10 * (80 - 40) / 100)


def _cross(rows: list[tuple]) -> pl.DataFrame:
    """(hour, chaos avg/low/high/units, divine avg/low/high/units, rate low/high)."""
    cols = ["cp", "clo", "chi", "cu", "dp", "dlo", "dhi", "du", "rlo", "rhi"]
    return pl.DataFrame(
        {
            "item_id": ["a"] * len(rows),
            "observed_at": [T0 + r[0] * H for r in rows],
            **{c: [float(r[i + 1]) for r in rows] for i, c in enumerate(cols)},
        }
    ).sort("observed_at")


def test_a_loop_limit_buys_at_the_recap_hours_low_and_sells_the_hour_after():
    # Hour 0 paid: bought at 10c (low 9c), sold for 0.12 div (low 0.11) at 100c a Divine.
    loops = pl.DataFrame([_loop(0, "a", 0.1, 0.2)])
    cross = _cross(
        [
            (0, 10, 9, 11, 1000, 0.12, 0.11, 0.13, 1000, 100, 100),
            (1, 10, 8, 11, 1000, 0.12, 0.11, 0.13, 1000, 100, 100),  # traded under the 9c bid
            (2, 10, 9, 11, 1000, 0.12, 0.10, 0.125, 1000, 98, 100),  # up to 0.125 div
        ]
    )
    [buy] = bt.loop_limit_trades(loops, cross, RATE, "limit_buy", "touch").to_dicts()
    # 90 items (10 Divines at the next hour's 11c high): bought at 9c, sold at hour 2's
    # low (0.10 div at 98c).
    assert buy["pnl"] == pytest.approx(90 * (0.10 * 98 - 9) / 100)
    [both] = bt.loop_limit_trades(loops, cross, RATE, "limit_both", "touch").to_dicts()
    # The ask, the recap hour's 0.12 div average, filled (a trade went to 0.125).
    assert both["pnl"] == pytest.approx(90 * (0.12 * 98 - 9) / 100)
    # Strict: hour 1's 10c average never went under the bid.
    [strict] = bt.loop_limit_trades(loops, cross, RATE, "limit_buy", "strict").to_dicts()
    assert not strict["filled"] and strict["pnl"] == 0
