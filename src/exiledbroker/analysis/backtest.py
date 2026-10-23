"""The backtest behind the Backtest page: would following the site's tools have paid?

A dummy trader replays every hour we have (each league's launch fortnight, plus the
live league's latest 14 days) with a bank of BANK_DIVINES, and does only what the site
told them at the time:

- **Hourly tools (Market recap, the landing page).** Each hour the trader reads the 1-hour recap,
  as `services/missed` builds it, and acts on its top 3 picks in the *next* hour (GGG
  publishes an hour only after it ends, so that's the earliest anyone could):
  - loops: the item's Chaos/Divine loop, in its better direction;
  - cards: buy full sets, turn them in, sell the reward the hour after;
  - rising: buy the risers, sell 2 hours later (the "momentum" reading).
  Each is also tested as "steady": only what paid in each of the last 3 hours (the
  recap's "paid every hour" badge).
- **Launch picks.** Walk-forward: each league is traded with the picks ranked from the
  leagues before it only, bought in the window and sold in days 12–14.

Fills are limited the same way everywhere: at most CAPTURE of what actually traded
that hour (in whole items) and TRADE_DIVINES a trade. Every trade is priced two ways:
- **fair**: the hour's volume-weighted price, with SLIPPAGE lost on every trade;
- **harsh**: the hour's worst traded price for the trader (buy at the highest, sell at
  the lowest). For launch picks: the median hourly high to buy, the median hourly low
  to sell.
An item that doesn't trade when the trader needs to sell is counted as lost.

Card turn-ins and loops are also tested with **limit orders** priced from the recap's
own hour (`card_limit_trades`, `loop_limit_trades`): a buy order at that hour's lowest
price, placed only if the trade still pays from it at that hour's worst sale price, and
optionally a sell order at that hour's average (else sold at the worst price). Whether an order
fills can't be seen in hourly data, so two fill models bracket it: **touch** (some
trade that hour went past the order's price) and **strict** (the hour's average did).

The truth sits between the two: the hourly data has no order book, so we can't see
the spread a real trader would cross. A strategy is only worth showing as advice if it
holds up harsh. `build` runs everything on the local research database (it needs past
leagues' hourly rows, which the site doesn't hold) and `store` keeps the small result
for the site (`eb backtest run`, then `eb site seed`).
"""

import json
from datetime import UTC, datetime, timedelta

import duckdb
import polars as pl

from exiledbroker.normalize.exchange_loader import SOURCE as HOURLY
from exiledbroker.services import cross_market, launch_picks, missed
from exiledbroker.services.backtest import REPORT
from exiledbroker.storage import db

BANK_DIVINES = 100.0
TRADE_DIVINES = 10.0  # at most this much in one trade
TOP = missed.TOP  # picks acted on per hour, as the recap shows them
CAPTURE = 0.10  # share of the hour's traded volume one trader can take
SLIPPAGE = 0.01  # lost on every trade at fair prices
STEADY_HOURS = 3  # "steady": paid in each of the last this many hours
HOLD_HOURS = 2  # rising: sold this many hours after the buy
SELL_WITHIN = timedelta(hours=6)  # a sale waits at most this long for a trade
LAUNCH_STAKE = 10.0  # Divines per launch pick (TOP picks: the bank)
SCENARIOS = ("fair", "harsh")
STRATEGIES = ("loops", "cards", "rising")
RULES = {"top": 1, "steady": STEADY_HOURS}
# The orders the Backtest page compares, per strategy: (method, bid_at, ask_at); see
# card_limit_trades. "limit_mid" was picked on Mirage's and Allflame's first 14 days from
# a 5 × 5 grid of bid and ask levels, and held up in the other leagues: the only setting
# positive under both fill models in all five. For cards no setting beat "limit".
LIMIT_ORDERS = {
    "cards": {"market": ("market", 0.0, None), "limit": ("limit_both", 0.0, None)},
    "loops": {
        "market": ("market", 0.0, None),
        "limit": ("limit_both", 0.0, None),
        "limit_mid": ("limit_both", 0.5, 0.75),
    },
}
FILLS = ("touch", "strict")
H = timedelta(hours=1)
DIVINE = "currency:divine-orb"
CHAOS = "currency:chaos-orb"


# --- Segments of hours ------------------------------------------------------------


def segments(con, league: str) -> list[tuple[str, float, float]]:
    """The stretches of hours a league has: its launch fortnight, and (for the live
    league) its latest 14 days. (name, first day offset, end day offset)."""
    last = db.scalar(
        con,
        "SELECT max(day_offset) FROM cross_market_hour "
        "WHERE league_id = (SELECT id FROM league WHERE name = ?)",
        [league],
    )
    out = [("launch", 0.0, 14.0)]
    if last is not None and last >= 14:
        out.append(("late", 14.0, 1e9))
    return out


def _rate(con, league: str) -> pl.DataFrame:
    """The Divine's Chaos price per hour."""
    return db.frame(
        con,
        """
        SELECT observed_at, chaos_value AS rate FROM price_observation
        WHERE league_id = (SELECT id FROM league WHERE name = ?) AND source = ?
          AND item_id = ?
        """,
        [league, HOURLY, DIVINE],
    )


def _signals(paid: pl.DataFrame, keys: list[str], hours: int, one_per: str) -> pl.DataFrame:
    """The recap's top picks each hour: what left the most on the table (`missed`), in
    that hour, or summed over `hours` hours it paid in every one of; one per `one_per`."""
    out = paid.select("observed_at", *keys, "missed")
    for k in range(1, hours):
        before = paid.select(*keys, observed_at=pl.col("observed_at") + k * H, m="missed")
        out = out.join(before, on=["observed_at", *keys]).with_columns(
            missed=pl.col("missed") + pl.col("m")
        )
        out = out.drop("m")
    return (
        out.sort(["observed_at", "missed", one_per], descending=[False, True, False])
        .unique(["observed_at", one_per], keep="first", maintain_order=True)
        .group_by("observed_at", maintain_order=True)
        .head(TOP)
    )


def _price(scenario: str, side: str, vwap: str, worst: str) -> pl.Expr:
    if scenario == "fair":
        return pl.col(vwap) * (1 + SLIPPAGE if side == "buy" else 1 - SLIPPAGE)
    return pl.col(worst)


# --- Loops ----------------------------------------------------------------------


def _loop_hours(con, league: str) -> pl.DataFrame:
    return pl.concat(
        [
            cross_market.hourly(con, [league], direction=d).with_columns(direction=pl.lit(d))
            for d in missed.DIRECTIONS
        ]
    ).with_columns(units=pl.col("overlap_chaos") / pl.col("chaos_price"))


def loop_trades(loops: pl.DataFrame, rate: pl.DataFrame, rule: str, scenario: str):
    paid = missed.paying_loops(loops)
    sig = _signals(paid, ["item_id", "direction"], RULES[rule], "item_id")
    # At fair prices the loop earns the VWAP gap, less slippage on its three trades.
    fair = pl.when(pl.col("direction") == "chaos_first").then(pl.col("gap"))
    fair = fair.otherwise(1 / (1 + pl.col("gap")) - 1)
    ret = (1 + fair) * (1 - SLIPPAGE) ** 3 - 1 if scenario == "fair" else pl.col("edge")
    buy = _price(scenario, "buy", "chaos_price", "chaos_high")
    nxt = loops.select(
        "item_id",
        "direction",
        "units",
        observed_at=pl.col("observed_at") - H,
        ret=ret,
        buy=buy,
        unit="chaos_price",
    )
    return (
        sig.join(nxt, on=["observed_at", "item_id", "direction"], how="left")
        .join(rate.select(observed_at=pl.col("observed_at") - H, rate="rate"), on="observed_at")
        .with_columns(
            k=pl.min_horizontal(
                (pl.col("units") * CAPTURE).floor(),
                (TRADE_DIVINES * pl.col("rate") / pl.col("buy")).floor(),
            ).fill_null(0)
        )
        .with_columns(
            pnl=pl.when(pl.col("k") >= 1)
            .then(pl.col("ret") * pl.col("k") * pl.col("unit") / pl.col("rate"))
            .otherwise(0.0)
        )
        .select("observed_at", "item_id", filled=pl.col("k") >= 1, pnl="pnl")
    )


# --- Cards ------------------------------------------------------------------------


def _prices(con, league: str) -> pl.DataFrame:
    return db.frame(
        con,
        """
        SELECT item_id, observed_at, day_offset, chaos_value AS p, chaos_low AS lo,
               chaos_high AS hi, volume AS units, chaos_volume AS cv
        FROM price_observation
        WHERE league_id = (SELECT id FROM league WHERE name = ?) AND source = ?
          AND chaos_value > 0
        """,
        [league, HOURLY],
    ).sort("observed_at")


def _sell(trades: pl.DataFrame, prices: pl.DataFrame, item: str, after: timedelta, scenario):
    """The first hour at or after `after` past the signal that `item` traded in
    (within SELL_WITHIN): its sale price and units traded."""
    sells = prices.select(
        sell_at="observed_at",
        sell_item="item_id",
        sell=_price(scenario, "sell", "p", "lo"),
        sell_units="units",
    ).sort("sell_at")
    return (
        trades.with_columns(sell_from=pl.col("observed_at") + after, sell_item=pl.col(item))
        .sort("sell_from")
        .join_asof(
            sells,
            left_on="sell_from",
            right_on="sell_at",
            by="sell_item",
            strategy="forward",
            tolerance=SELL_WITHIN,
            check_sortedness=False,  # sorted by time above; checked per group it can't be
        )
    )


def card_trades(con, prices: pl.DataFrame, rate: pl.DataFrame, rule: str, scenario: str):
    cards = db.frame(
        con,
        """
        SELECT item_id, reward_item_id AS reward_id, stack_size AS n, reward_quantity AS q
        FROM divination_card WHERE followed AND reward_item_id IS NOT NULL
        """,
    )
    c = prices.join(cards, on="item_id")
    r = prices.select("observed_at", reward_id="item_id", rp="p")
    paid = (
        c.join(r, on=["observed_at", "reward_id"])
        .with_columns(margin=pl.col("q") * pl.col("rp") - pl.col("n") * pl.col("p"))
        .with_columns(sets=pl.col("units") / pl.col("n"))
        .filter(pl.col("margin") > 0, pl.col("sets") >= missed.MIN_CARD_SETS)
        .with_columns(missed=pl.col("margin") * pl.col("sets"))
    )
    sig = _signals(paid, ["item_id"], RULES[rule], "item_id").join(cards, on="item_id")
    buys = c.select(
        "item_id",
        observed_at=pl.col("observed_at") - H,
        buy=_price(scenario, "buy", "p", "hi"),
        buy_units="units",
    )
    t = sig.join(buys, on=["observed_at", "item_id"], how="left").join(
        rate.select(observed_at=pl.col("observed_at") - H, rate="rate"), on="observed_at"
    )
    t = _sell(t, prices, "reward_id", 2 * H, scenario).with_columns(
        k=pl.min_horizontal(
            (pl.col("buy_units") * CAPTURE / pl.col("n")).floor(),
            (TRADE_DIVINES * pl.col("rate") / (pl.col("n") * pl.col("buy"))).floor(),
            (pl.col("sell_units").fill_null(1e12) * CAPTURE / pl.col("q")).floor(),
        ).fill_null(0)
    )
    cost = pl.col("k") * pl.col("n") * pl.col("buy")
    value = (pl.col("k") * pl.col("q") * pl.col("sell")).fill_null(0)  # never sold: lost
    return t.with_columns(
        pnl=pl.when(pl.col("k") >= 1).then((value - cost) / pl.col("rate")).otherwise(0.0)
    ).select("observed_at", "item_id", filled=pl.col("k") >= 1, pnl="pnl")


def _level(lo: str, hi: str, at: float) -> pl.Expr:
    """A price `at` of the way from the hour's lowest (0) to its highest (1) trade."""
    return pl.col(lo) + at * (pl.col(hi) - pl.col(lo))


def card_limit_trades(
    con,
    prices: pl.DataFrame,
    rate: pl.DataFrame,
    method: str,
    fill: str,
    bid_at: float = 0.0,
    ask_at: float | None = None,
) -> pl.DataFrame:
    """The recap's top card turn-ins, bought and sold with prices set from its hour:
    - market: buy at the next hour's highest card price, sell at the worst (harsh);
    - limit_buy: a buy order at the recap hour's lowest card price, placed only if the
      set still pays at that hour's lowest reward price; the reward sold at the worst;
    - limit_both: the same, with a sell order at the recap hour's average reward price,
      sold at the worst instead if it doesn't fill.
    Every order placed is a signal; one the next hour doesn't reach buys nothing (it's
    cancelled), so `filled` over signals is the share of orders that filled.
    `bid_at` / `ask_at` move the orders within the recap hour's range (0 its lowest
    trade, 1 its highest; `ask_at` None asks the average)."""
    cards = db.frame(
        con,
        """
        SELECT item_id, reward_item_id AS reward_id, stack_size AS n, reward_quantity AS q
        FROM divination_card WHERE followed AND reward_item_id IS NOT NULL
        """,
    )
    c = prices.join(cards, on="item_id")
    r = prices.select("observed_at", reward_id="item_id", rp="p", rlo="lo", rhi="hi")
    paid = (
        c.join(r, on=["observed_at", "reward_id"])
        .with_columns(
            margin=pl.col("q") * pl.col("rp") - pl.col("n") * pl.col("p"),
            sets=pl.col("units") / pl.col("n"),
        )
        .filter(pl.col("margin") > 0, pl.col("sets") >= missed.MIN_CARD_SETS)
        .with_columns(missed=pl.col("margin") * pl.col("sets"))
    )
    # The recap hour's own prices, which the orders are priced from.
    sig = (
        _signals(paid, ["item_id"], 1, "item_id")
        .join(cards, on="item_id")
        .join(
            c.select("observed_at", "item_id", card_lo="lo", card_hi="hi"),
            on=["observed_at", "item_id"],
        )
        .join(r.rename({"rlo": "reward_lo"}), on=["observed_at", "reward_id"])
        .with_columns(
            bid=_level("card_lo", "card_hi", bid_at),
            ask=pl.col("rp") if ask_at is None else _level("reward_lo", "rhi", ask_at),
        )
    )
    nxt = c.select(
        "item_id",
        observed_at=pl.col("observed_at") - H,
        next_p="p",
        next_lo="lo",
        next_hi="hi",
        buy_units="units",
    )
    t = sig.join(nxt, on=["observed_at", "item_id"], how="left").join(
        rate.select(observed_at=pl.col("observed_at") - H, rate="rate"), on="observed_at"
    )
    if method == "market":
        t = t.with_columns(buy=pl.col("next_hi"), placed=True, hit=pl.col("next_p").is_not_null())
    else:
        crossed = pl.col("next_p") if fill == "strict" else pl.col("next_lo")
        guard = pl.col("q") * pl.col("reward_lo") > pl.col("n") * pl.col("bid")
        t = t.with_columns(buy=pl.col("bid"), placed=guard, hit=crossed < pl.col("bid"))
    t = t.filter(pl.col("placed").fill_null(False))
    sells = prices.select(
        sell_at="observed_at",
        sell_item="item_id",
        sell_p="p",
        sell_lo="lo",
        sell_hi="hi",
        sell_units="units",
    ).sort("sell_at")
    t = (
        t.with_columns(sell_from=pl.col("observed_at") + 2 * H, sell_item=pl.col("reward_id"))
        .sort("sell_from")
        .join_asof(
            sells,
            left_on="sell_from",
            right_on="sell_at",
            by="sell_item",
            strategy="forward",
            tolerance=SELL_WITHIN,
            check_sortedness=False,  # sorted by time above; checked per group it can't be
        )
    )
    sell = pl.col("sell_lo")
    if method == "limit_both":
        crossed = pl.col("sell_p") if fill == "strict" else pl.col("sell_hi")
        sell = pl.when(crossed > pl.col("ask")).then(pl.col("ask")).otherwise(sell)
    t = t.with_columns(
        sell=sell,
        k=pl.when(pl.col("hit").fill_null(False))
        .then(
            pl.min_horizontal(
                (pl.col("buy_units") * CAPTURE / pl.col("n")).floor(),
                (TRADE_DIVINES * pl.col("rate") / (pl.col("n") * pl.col("buy"))).floor(),
                (pl.col("sell_units").fill_null(1e12) * CAPTURE / pl.col("q")).floor(),
            )
        )
        .otherwise(0)
        .fill_null(0),
    )
    cost = pl.col("k") * pl.col("n") * pl.col("buy")
    value = (pl.col("k") * pl.col("q") * pl.col("sell")).fill_null(0)  # never sold: lost
    return t.with_columns(
        pnl=pl.when(pl.col("k") >= 1).then((value - cost) / pl.col("rate")).otherwise(0.0)
    ).select("observed_at", "item_id", filled=pl.col("k") >= 1, pnl="pnl")


def _cross_hours(con, league: str) -> pl.DataFrame:
    """Every item-hour traded in both markets, with both markets' ranges and the hour's
    Divine rate range (what the loop's limit orders are priced from)."""
    return db.frame(
        con,
        f"""
        SELECT x.item_id, x.observed_at, x.chaos_price AS cp, x.chaos_low AS clo,
               x.chaos_high AS chi, x.chaos_volume AS cu, x.divine_price AS dp,
               x.divine_low AS dlo, x.divine_high AS dhi, x.divine_volume AS du,
               x.divine_rate_low AS rlo, x.divine_rate_high AS rhi
        FROM cross_market_hour x
        WHERE x.league_id = (SELECT id FROM league WHERE name = ?) AND {cross_market.BOTH_LEGS}
        """,
        [league],
    ).sort("observed_at")


def loop_limit_trades(
    loops: pl.DataFrame,
    cross: pl.DataFrame,
    rate: pl.DataFrame,
    method: str,
    fill: str,
    bid_at: float = 0.0,
    ask_at: float | None = None,
) -> pl.DataFrame:
    """The recap's top loops, the item bought in the next hour and sold the hour after
    (the first hour within SELL_WITHIN it traded in both markets), Divines converted at
    the worst rate that hour:
    - market: the item bought at the next hour's highest price, sold at the lowest;
    - limit_buy: a buy order at the recap hour's lowest price in the paying currency,
      placed only if the loop still beats BUFFER from it at the recap hour's worst sale;
    - limit_both: the same, with a sell order at the recap hour's average price in the
      other currency, sold at the lowest instead if it doesn't fill.
    Chaos first buys with Chaos and sells for Divines; Divines first the other way.
    `bid_at` / `ask_at` move the orders within the recap hour's range, as for cards."""
    sig = (
        _signals(missed.paying_loops(loops), ["item_id", "direction"], 1, "item_id")
        .select("observed_at", "item_id", "direction")
        .join(cross, on=["observed_at", "item_id"])
    )
    chaos_first = pl.col("direction") == "chaos_first"
    # Per direction: the buy leg's (avg, low, high, units) and the sell leg's.
    buy_cols = {"p": ("cp", "dp"), "lo": ("clo", "dlo"), "hi": ("chi", "dhi"), "u": ("cu", "du")}
    pick = {
        k: pl.when(chaos_first).then(pl.col(a)).otherwise(pl.col(b))
        for k, (a, b) in buy_cols.items()
    }
    other = {
        k: pl.when(chaos_first).then(pl.col(b)).otherwise(pl.col(a))
        for k, (a, b) in buy_cols.items()
    }
    sig = sig.with_columns(
        bid=pick["lo"] + bid_at * (pick["hi"] - pick["lo"]),
        ask=other["p"] if ask_at is None else other["lo"] + ask_at * (other["hi"] - other["lo"]),
    )
    sig = sig.with_columns(
        # The loop from the bid, at the recap hour's worst sale and conversion.
        guard_ret=pl.when(chaos_first)
        .then(pl.col("dlo") * pl.col("rlo") / pl.col("bid"))
        .otherwise(pl.col("clo") / (pl.col("bid") * pl.col("rhi")))
        - 1,
    ).select("observed_at", "item_id", "direction", "bid", "ask", "guard_ret")
    # The next hour's prices, renamed so the buy leg can be picked per direction.
    nxt = cross.select(
        "item_id",
        observed_at=pl.col("observed_at") - H,
        **{c: c for c in ("cp", "clo", "chi", "cu", "dp", "dlo", "dhi", "du")},
    )
    t = (
        sig.join(nxt, on=["observed_at", "item_id"], how="left")
        .join(rate.select(observed_at=pl.col("observed_at") - H, rate="rate"), on="observed_at")
        .with_columns(**{f"b_{k}": v for k, v in pick.items()})
    )
    if method == "market":
        t = t.with_columns(buy=pl.col("b_hi"), placed=True, hit=pl.col("b_p").is_not_null())
    else:
        crossed = pl.col("b_p") if fill == "strict" else pl.col("b_lo")
        guard = pl.col("guard_ret") > missed.BUFFER
        t = t.with_columns(buy=pl.col("bid"), placed=guard, hit=crossed < pl.col("bid"))
    t = t.filter(pl.col("placed").fill_null(False))
    sells = cross.select(
        "item_id",
        sell_at="observed_at",
        s_cp="cp",
        s_clo="clo",
        s_chi="chi",
        s_cu="cu",
        s_dp="dp",
        s_dlo="dlo",
        s_dhi="dhi",
        s_du="du",
        s_rlo="rlo",
        s_rhi="rhi",
    ).sort("sell_at")
    t = (
        t.with_columns(sell_from=pl.col("observed_at") + 2 * H)
        .sort("sell_from")
        .join_asof(
            sells,
            left_on="sell_from",
            right_on="sell_at",
            by="item_id",
            strategy="forward",
            tolerance=SELL_WITHIN,
            check_sortedness=False,  # sorted by time above; checked per group it can't be
        )
    )
    s_p = pl.when(chaos_first).then(pl.col("s_dp")).otherwise(pl.col("s_cp"))
    s_lo = pl.when(chaos_first).then(pl.col("s_dlo")).otherwise(pl.col("s_clo"))
    s_hi = pl.when(chaos_first).then(pl.col("s_dhi")).otherwise(pl.col("s_chi"))
    s_u = pl.when(chaos_first).then(pl.col("s_du")).otherwise(pl.col("s_cu"))
    sell = s_lo
    if method == "limit_both":
        crossed = s_p if fill == "strict" else s_hi
        sell = pl.when(crossed > pl.col("ask")).then(pl.col("ask")).otherwise(s_lo)
    # In Chaos per item: Chaos first spends `buy` Chaos and gets `sell` Divines, sold at
    # the worst rate; Divines first spends `buy` Divines (bought back at the worst rate)
    # and gets `sell` Chaos.
    cost = pl.when(chaos_first).then(pl.col("buy")).otherwise(pl.col("buy") * pl.col("s_rhi"))
    value = pl.when(chaos_first).then(sell * pl.col("s_rlo")).otherwise(sell)
    t = t.with_columns(
        cost=cost,
        value=value.fill_null(0),  # never sold: lost
        k=pl.when(pl.col("hit").fill_null(False))
        .then(
            pl.min_horizontal(
                (pl.col("b_u") * CAPTURE).floor(),
                (s_u.fill_null(1e12) * CAPTURE).floor(),
                (TRADE_DIVINES * pl.col("rate") / pl.col("chi")).floor(),
            )
        )
        .otherwise(0)
        .fill_null(0),
    )
    return t.with_columns(
        pnl=pl.when(pl.col("k") >= 1)
        .then(pl.col("k") * (pl.col("value") - pl.col("cost").fill_null(0)) / pl.col("rate"))
        .otherwise(0.0)
    ).select("observed_at", "item_id", filled=pl.col("k") >= 1, pnl="pnl")


# --- Rising -------------------------------------------------------------------------


def rising_trades(con, prices: pl.DataFrame, rate: pl.DataFrame, rule: str, scenario: str):
    tracked = [r[0] for r in db.rows(con, "SELECT DISTINCT item_id FROM tracked_item")]
    p = prices.filter(pl.col("item_id").is_in(tracked), pl.col("item_id") != CHAOS)
    before = p.select("item_id", before_at="observed_at", before="p").sort("before_at")
    rose = (
        p.with_columns(before_from=pl.col("observed_at") - H)
        .sort("before_from")
        .join_asof(
            before,
            left_on="before_from",
            right_on="before_at",
            by="item_id",
            strategy="backward",
            tolerance=SELL_WITHIN,
            check_sortedness=False,  # sorted by time above; checked per group it can't be
        )
        .with_columns(change=pl.col("p") / pl.col("before") - 1)
        .filter(
            pl.col("cv") >= missed.MIN_VOLUME,
            pl.col("p") >= missed.MIN_PRICE,
            pl.col("change") > 0,
        )
        .with_columns(missed=pl.col("change"))
    )
    sig = _signals(rose, ["item_id"], RULES[rule], "item_id")
    buys = p.select(
        "item_id",
        observed_at=pl.col("observed_at") - H,
        buy=_price(scenario, "buy", "p", "hi"),
        buy_units="units",
    )
    t = sig.join(buys, on=["observed_at", "item_id"], how="left").join(
        rate.select(observed_at=pl.col("observed_at") - H, rate="rate"), on="observed_at"
    )
    t = _sell(t, p, "item_id", (1 + HOLD_HOURS) * H, scenario).with_columns(
        k=pl.min_horizontal(
            (pl.col("buy_units") * CAPTURE).floor(),
            (TRADE_DIVINES * pl.col("rate") / pl.col("buy")).floor(),
            (pl.col("sell_units").fill_null(1e12) * CAPTURE).floor(),
        ).fill_null(0)
    )
    value = (pl.col("k") * pl.col("sell")).fill_null(0)
    return t.with_columns(
        pnl=pl.when(pl.col("k") >= 1)
        .then((value - pl.col("k") * pl.col("buy")) / pl.col("rate"))
        .otherwise(0.0)
    ).select("observed_at", "item_id", filled=pl.col("k") >= 1, pnl="pnl")


# --- Hourly results ---------------------------------------------------------------


def _summary(trades: pl.DataFrame, hours: pl.DataFrame) -> dict:
    """Totals over a segment's hours, and the running total at the end of each day."""
    per_hour = hours.join(
        trades.group_by("observed_at").agg(pl.col("pnl").sum()), on="observed_at", how="left"
    ).with_columns(pl.col("pnl").fill_null(0.0))
    filled = trades.filter("filled")
    day = ((pl.col("observed_at") - pl.col("observed_at").min()).dt.total_hours() // 24).alias(
        "day"
    )
    daily = per_hour.group_by(day).agg(pl.col("pnl").sum()).sort("day")
    return {
        "hours": hours.height,
        "signals": trades.height,
        "filled": filled.height,
        "won": int((filled["pnl"] > 0).sum()),
        "total": float(per_hour["pnl"].sum()),
        "per_hour": float(per_hour["pnl"].mean()) if hours.height else 0.0,
        "best_hour": float(per_hour["pnl"].max()) if hours.height else 0.0,
        "worst_hour": float(per_hour["pnl"].min()) if hours.height else 0.0,
        "daily": [round(v, 2) for v in daily["pnl"].cum_sum().to_list()],
    }


def _persistence(loops: pl.DataFrame, hours: pl.DataFrame) -> dict:
    """How often a loop the recap flags pays again the next hour, against every other
    loop that traded enough that hour to show on it."""
    paid = missed.paying_loops(loops)
    flagged = _signals(paid, ["item_id", "direction"], 1, "item_id").select(
        "observed_at", "item_id", "direction", flagged=pl.lit(True)
    )
    nxt = loops.select(
        "item_id",
        "direction",
        observed_at=pl.col("observed_at") - H,
        again=pl.col("edge") > missed.BUFFER,
    )
    liquid = loops.filter(
        pl.col("overlap_chaos") >= missed.MIN_LOOP_CHAOS,
        pl.col("overlap_chaos") / pl.col("chaos_price") >= missed.MIN_LOOP_ITEMS,
    )
    j = (
        liquid.join(hours, on="observed_at")
        .join(flagged, on=["observed_at", "item_id", "direction"], how="left")
        .join(nxt, on=["observed_at", "item_id", "direction"])
        .with_columns(pl.col("flagged").fill_null(False))
    )
    share = j.group_by("flagged").agg(pl.col("again").mean())
    get = dict(zip(share["flagged"].to_list(), share["again"].to_list(), strict=True))
    return {"flagged": get.get(True), "others": get.get(False)}


def hourly_results(con, league: str) -> tuple[list[dict], list[dict], list[dict]]:
    rate = _rate(con, league)
    loops = _loop_hours(con, league)
    prices = _prices(con, league)
    all_hours = loops.select("observed_at", "day_offset").unique("observed_at")
    out, persistence, limit_rows = [], [], []
    trades = {}
    cross = _cross_hours(con, league)
    limits = {}
    for strategy, orders in LIMIT_ORDERS.items():
        for name, (method, bid_at, ask_at) in orders.items():
            for fill in FILLS if method != "market" else FILLS[:1]:
                if strategy == "cards":
                    t = card_limit_trades(con, prices, rate, method, fill, bid_at, ask_at)
                else:
                    t = loop_limit_trades(loops, cross, rate, method, fill, bid_at, ask_at)
                limits[strategy, name, fill] = t
    for rule in RULES:
        for scenario in SCENARIOS:
            trades["loops", rule, scenario] = loop_trades(loops, rate, rule, scenario)
            trades["cards", rule, scenario] = card_trades(con, prices, rate, rule, scenario)
            trades["rising", rule, scenario] = rising_trades(con, prices, rate, rule, scenario)
    for segment, first, end in segments(con, league):
        hours = all_hours.filter(pl.col("day_offset") >= first, pl.col("day_offset") < end).select(
            "observed_at"
        )
        for (strategy, rule, scenario), t in trades.items():
            out.append(
                {
                    "league": league,
                    "segment": segment,
                    "strategy": strategy,
                    "rule": rule,
                    "scenario": scenario,
                    **_summary(t.join(hours, on="observed_at"), hours),
                }
            )
        persistence.append({"league": league, "segment": segment, **_persistence(loops, hours)})
        for (strategy, method, fill), t in limits.items():
            limit_rows.append(
                {
                    "league": league,
                    "segment": segment,
                    "strategy": strategy,
                    "method": method,
                    "fill": fill,
                    **_summary(t.join(hours, on="observed_at"), hours),
                }
            )
    return out, persistence, limit_rows


# --- Launch picks, walk-forward ------------------------------------------------------


def _launch_prices(con, league: str) -> pl.DataFrame:
    """Hourly Divine prices of every item in a league's first 14 days: VWAP, the
    hour's high and low (via that hour's Divine rate), and Divines traded."""
    return db.frame(
        con,
        """
        SELECT p.item_id, p.day_offset, p.divine_value AS d,
               p.chaos_low / r.chaos_value AS lo, p.chaos_high / r.chaos_value AS hi,
               p.chaos_volume / r.chaos_value AS dv
        FROM price_observation p
        JOIN price_observation r ON r.league_id = p.league_id AND r.source = p.source
             AND r.observed_at = p.observed_at AND r.item_id = ?
        WHERE p.league_id = (SELECT id FROM league WHERE name = ?) AND p.source = ?
          AND p.day_offset >= 0 AND p.day_offset < ? AND p.divine_value > 0
        """,
        [DIVINE, league, HOURLY, launch_picks.SELL[1]],
    )


def _window_stats(px: pl.DataFrame, first: int, last: int, prefix: str) -> pl.DataFrame:
    days = last - first + 1
    return (
        px.filter(pl.col("day_offset") >= first - 1, pl.col("day_offset") < last)
        .group_by("item_id")
        .agg(
            pl.col("d").median().alias(f"{prefix}_fair"),
            pl.col("hi" if prefix == "buy" else "lo").median().alias(f"{prefix}_harsh"),
            (pl.col("dv").sum() / days).alias(f"{prefix}_per_day"),
            pl.lit(days).alias(f"{prefix}_days"),
        )
    )


def _multiple(t: pl.DataFrame, scenario: str) -> pl.Expr:
    buy, sell = pl.col(f"buy_{scenario}"), pl.col(f"sell_{scenario}")
    if scenario == "fair":
        buy, sell = buy * (1 + SLIPPAGE), sell * (1 - SLIPPAGE)
    return (sell / buy).fill_null(0.0)  # never sold: lost


def launch_results(con, leagues: list[str]) -> list[dict]:
    """Each league with an earlier one, traded with the picks ranked from the leagues
    before it only (oldest first in `leagues`)."""
    history = {
        lg: launch_picks.league_windows(con, lg).with_columns(league=pl.lit(lg)) for lg in leagues
    }
    tracked = [r[0] for r in db.rows(con, "SELECT DISTINCT item_id FROM tracked_item")]
    days = {
        w: b - a + 1 for w, (a, b) in [*launch_picks.WINDOWS.items(), ("sell", launch_picks.SELL)]
    }
    out = []
    for i, league in enumerate(leagues[1:], 1):
        prior = leagues[:i][::-1][: launch_picks.REFERENCE_LEAGUES]
        prices = pl.concat([history[p] for p in prior]).filter(pl.col("item_id").is_in(tracked))
        prices = prices.with_columns(
            per_day=pl.col("divine_volume") / pl.col("window_id").replace_strict(days)
        )
        ranked = launch_picks.rank(
            prices, prior, min_leagues=min(launch_picks.MIN_LEAGUES, len(prior))
        )
        px = _launch_prices(con, league)
        sell = _window_stats(px, *launch_picks.SELL, "sell")
        names = dict(db.rows(con, "SELECT id, canonical_name FROM item"))
        for wid, (first, last) in launch_picks.WINDOWS.items():
            picks = ranked["picks"].filter(window_id=wid).select("item_id", "rank")
            both = _window_stats(px, first, last, "buy").join(sell, on="item_id", how="left")
            t = picks.join(both, on="item_id", how="left").with_columns(
                # At most CAPTURE of what traded in the window and in the sale.
                stake=pl.min_horizontal(
                    pl.lit(LAUNCH_STAKE),
                    pl.col("buy_per_day") * pl.col("buy_days") * CAPTURE,
                    pl.col("sell_per_day").fill_null(0)
                    * pl.col("sell_days").fill_null(0)
                    * CAPTURE,
                ).fill_null(0.0),
                fair=_multiple(both, "fair"),
                harsh=_multiple(both, "harsh"),
            )
            typical = both.filter(
                ~pl.col("item_id").is_in(launch_picks.BENCHMARKS),
                pl.col("buy_fair") <= launch_picks.BUDGET_DIVINES,
                pl.col("buy_per_day") >= launch_picks.MIN_LIQUIDITY,
                pl.col("sell_per_day") >= launch_picks.MIN_LIQUIDITY,
            ).with_columns(fair=_multiple(both, "fair"), harsh=_multiple(both, "harsh"))
            staked = float(t["stake"].sum())
            row = {
                "league": league,
                "window_id": wid,
                "references": prior,
                "staked": staked,
                "typical_fair": typical["fair"].median(),
                "typical_harsh": typical["harsh"].median(),
                "picks": [
                    {
                        "name": names.get(r["item_id"], r["item_id"]),
                        "rank": r["rank"],
                        "stake": r["stake"],
                        "fair": r["fair"],
                        "harsh": r["harsh"],
                    }
                    for r in t.sort("rank").iter_rows(named=True)
                ],
            }
            for s in SCENARIOS:
                # Stake-weighted: what the bank put in each pick came back this many times.
                back = float((t["stake"] * t[s]).sum())
                row[s] = back / staked if staked else None
                row[f"{s}_profit"] = back - staked
            out.append(row)
    return out


# --- The report -----------------------------------------------------------------------


def hourly_leagues(con) -> list[str]:
    """Challenge leagues with hourly exchange data, oldest first."""
    q = """
        SELECT l.name FROM league l
        WHERE l.kind = 'challenge'
          AND EXISTS (SELECT 1 FROM cross_market_hour x WHERE x.league_id = l.id)
        ORDER BY l.start_at
    """
    return [r[0] for r in db.rows(con, q)]


def build(con: duckdb.DuckDBPyConnection) -> dict:
    leagues = hourly_leagues(con)
    hourly, persistence, limit_rows = [], [], []
    for league in leagues:
        rows, persist, limits = hourly_results(con, league)
        hourly += rows
        persistence += persist
        limit_rows += limits
    complete = [lg for lg in leagues if lg in launch_picks.complete_leagues(con)]
    return {
        "built_at": datetime.now(UTC).isoformat(),
        "leagues": leagues,
        "assumptions": {
            "bank_divines": BANK_DIVINES,
            "trade_divines": TRADE_DIVINES,
            "top": TOP,
            "capture": CAPTURE,
            "slippage": SLIPPAGE,
            "steady_hours": STEADY_HOURS,
            "hold_hours": HOLD_HOURS,
            "launch_stake": LAUNCH_STAKE,
        },
        "hourly": hourly,
        "persistence": persistence,
        "limits": limit_rows,
        "launch": launch_results(con, complete),
    }


def store(con, report: dict) -> None:
    db.execute(con, f"DELETE FROM {REPORT}")
    db.execute(
        con,
        f"INSERT INTO {REPORT} (id, built_at, body) VALUES ('latest', ?, ?)",
        [datetime.now(UTC).replace(tzinfo=None), json.dumps(report)],
    )
