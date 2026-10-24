"""Market recap (the landing page): what traded in the latest published hours, and what
a player could look into next.

GGG publishes each hour after it ends, so nothing here is live: it's a recap of the
last 1, 2 or 3 hours, computed once per loaded hour for all three look-backs and sent
together, so the page's slider never asks the server again. Each look-back has:
- **movers**: liquid items whose price rose or fell most since the start of it, with
  how many hours running they've moved that way (what already happened: the backtest
  found buying the risers loses);
- **volatile**: liquid items with the widest traded range (high vs low) in it;
- **loops** and **cards**: every Chaos/Divine loop and card turn-in that paid, ranked
  by edge × volume traded in both markets, or margin × sets traded, summed over the
  hours that paid, with how many of them paid. Only markets with enough traded to act
  on count (MIN_LOOP_CHAOS / MIN_LOOP_ITEMS, a full set for cards): a thin market's
  one odd trade shows a huge edge nobody can repeat. Each comes with the orders the
  backtest's best option would place from the latest hour (LOOP_ORDER, CARD_ORDER) and
  its last 24 hours' price range (one grouped query for the listed items).

`analysis/backtest.py` replays these picks an hour late; the page words them as
options to check, not promises, to match what it found.

SQL here must stay Postgres-compatible.
"""

from datetime import UTC, timedelta

import duckdb
import polars as pl

from exiledbroker.normalize.exchange_loader import SOURCE as HOURLY
from exiledbroker.services import cross_market, divination
from exiledbroker.services.live import latest_hour
from exiledbroker.storage import db

LOOKBACKS = (1, 2, 3)  # hours
TREND_HOURS = 6  # how far back an hour-by-hour run is followed
TOP = 3
TICKER = 24  # movers in the page's scrolling ticker
MIN_PRICE = 5.0  # Chaos: below this, whole-number exchange ratios dominate the moves
MIN_VOLUME = 2000.0  # Chaos traded an hour: thinner markets swing on a single trade
BUFFER = 0.02  # a loop only counts if it beat this edge, as on the Arbitrage page
DIRECTIONS = ("chaos_first", "divine_first")
MIN_LOOP_CHAOS = 500.0  # Chaos traded through both markets in the hour
MIN_LOOP_ITEMS = 10.0  # items traded through both markets in the hour
MIN_CARD_SETS = 1.0  # full sets traded in the hour
# Where in the latest hour's range (0 its lowest trade, 1 its highest) the orders go:
# the backtest's best options (analysis/backtest.LIMIT_ORDERS). Loops bid halfway up the
# paying currency's range and ask three quarters up the other's; cards bid the card's
# low (only if a set still pays at the reward's low) and ask the reward's average.
LOOP_ORDER = (0.5, 0.75)
CARD_ORDER = (0.0, None)
RANGE_HOURS = 24  # the price range shown with each loop and card
# How often the orders went through recently: the same orders priced from each of the
# last CHANCE_HOURS hours, bought if the next hour traded past the bid and sold if the
# hour after traded past the ask (the backtest's "touch" fill). Fewer than MIN_TRIES
# tries is too few to say.
CHANCE_HOURS = 72
MIN_TRIES = 3
# Volatile flips (analysis/flips.py, finding 5): liquid items whose latest hour traded
# across a wide range, bid low in it and listed high, the ask cut each hour until it
# sells. Shared with the backtest. Wider ranges than FLIP_MAX_RANGE are almost always
# one odd trade nobody can repeat.
FLIP_MIN_VOLUME = 10_000.0  # Chaos traded in the hour
FLIP_MAX_RANGE = 0.5
FLIP_MIN_RANGE = 0.10  # narrower leaves too little between the bid and the ask
FLIP_ORDER = (0.1, 0.75)  # bid and ask, as a share of the hour's range
FLIP_CUT = 0.01  # the ask comes down this much each hour it doesn't sell
FLIP_SELL_HOURS = 6  # the estimate's window to sell in (at the first, uncut ask)
# Flips are priced from the Chaos market alone and placed in it: an item worth a few
# Divines trades in the Divine market at whole numbers (2:1, 3:1), which widens the
# range without being a price anyone can order at. Exchange orders are whole numbers on
# both sides (so many Chaos for so many items) and fill in whole lots, so a price is
# reached with the smallest lot of up to LOT_MAX items whose whole-Chaos total is within
# LOT_TOLERANCE of it (`whole`).
LOT_MAX = 20  # items in a lot, for an item worth a currency unit or more
UNITS_MAX = 50  # currency units in a lot, for an item worth less than one
LOT_TOLERANCE = 0.01


def whole(target: pl.Expr, side: str) -> tuple[pl.Expr, pl.Expr]:
    """(items, currency units) for an order at `target` units an item, in whole numbers
    on both sides as the exchange takes them, the smallest lot within LOT_TOLERANCE of the
    target: rounded down for a bid and up for an ask, so the order never pays more or
    asks less. An item worth a unit or more goes in lots of up to LOT_MAX items (50c for
    3); one worth less, in lots of up to UNITS_MAX units (5c for 64 Orbs of Alteration,
    1 Divine for 1926)."""
    buy = side == "buy"
    rnd = (lambda x: x.floor()) if buy else (lambda x: x.ceil())
    lot = pl.lit(LOT_MAX)
    for n in range(LOT_MAX - 1, 0, -1):
        close = (rnd(target * n) / n - target).abs() <= LOT_TOLERANCE * target
        lot = pl.when(close).then(n).otherwise(lot)
    # Under a unit an item: so many items for each whole number of units.
    items = (lambda m: (m / target).ceil()) if buy else (lambda m: (m / target).floor())
    units = pl.lit(UNITS_MAX)
    for m in range(UNITS_MAX - 1, 0, -1):
        close = (m / items(m) - target).abs() <= LOT_TOLERANCE * target
        units = pl.when(close).then(m).otherwise(units)
    cheap = target < 1
    return (
        pl.when(cheap).then(items(units)).otherwise(lot).cast(pl.Int64),
        pl.when(cheap).then(units.cast(pl.Float64)).otherwise(rnd(target * lot)),
    )


def paying_loops(loops: pl.DataFrame) -> pl.DataFrame:
    """Loop hours that beat BUFFER in a market with enough traded to act on, with the
    Chaos they could have made (`missed`). Shared with the backtest."""
    return loops.filter(
        pl.col("edge") > BUFFER,
        pl.col("overlap_chaos") >= MIN_LOOP_CHAOS,
        pl.col("overlap_chaos") / pl.col("chaos_price") >= MIN_LOOP_ITEMS,
    ).with_columns(missed=pl.col("edge") * pl.col("overlap_chaos"))


def _prices(con, league: str, since) -> pl.DataFrame:
    return db.frame(
        con,
        """
        SELECT p.item_id, i.canonical_name AS name, p.observed_at, p.chaos_value AS price,
               p.chaos_low AS low, p.chaos_high AS high, p.chaos_volume AS volume
        FROM price_observation p
        JOIN item i ON i.id = p.item_id
        WHERE p.league_id = (SELECT id FROM league WHERE name = ?) AND p.source = ?
          AND p.observed_at > ? AND p.chaos_value > 0
          AND p.item_id IN (SELECT item_id FROM tracked_item)
          AND p.item_id <> 'currency:chaos-orb'
        """,
        [league, HOURLY, since],
    )


def _streaks(prices: pl.DataFrame, latest) -> pl.DataFrame:
    """Per item traded in the latest hour: consecutive hourly rises (positive) or falls
    (negative) ending at it."""
    rows = []
    for (item_id,), g in prices.sort("observed_at").group_by("item_id"):
        ps = g["price"].to_list()
        if g["observed_at"][-1] != latest or len(ps) < 2:
            continue
        sign = 1 if ps[-1] > ps[-2] else -1 if ps[-1] < ps[-2] else 0
        run = 0
        for a, b in zip(ps[-2::-1], ps[:0:-1], strict=False):  # pairs back from the latest
            step = 1 if b > a else -1 if b < a else 0
            if step != sign or step == 0:
                break
            run += 1
        rows.append({"item_id": item_id, "streak": sign * run})
    return pl.DataFrame(rows, schema={"item_id": pl.String, "streak": pl.Int64})


def _movement(prices: pl.DataFrame, latest, hours: int) -> tuple[list, list, list, list]:
    now = prices.filter(pl.col("observed_at") == latest, pl.col("volume") >= MIN_VOLUME)
    base = (
        prices.filter(pl.col("observed_at") <= latest - timedelta(hours=hours))
        .sort("observed_at")
        .group_by("item_id")
        .agg(pl.col("price").last().alias("before"))
    )
    moved = (
        now.join(base, on="item_id")
        .filter(pl.col("price") >= MIN_PRICE)
        .join(_streaks(prices, latest), on="item_id", how="left")
        .select(
            "item_id",
            "name",
            "price",
            "before",
            "volume",
            "streak",
            change=pl.col("price") / pl.col("before") - 1,
        )
    )
    up = moved.filter(pl.col("change") > 0).sort(["change", "item_id"], descending=[True, False])
    down = moved.filter(pl.col("change") < 0).sort(["change", "item_id"])
    window = prices.filter(pl.col("observed_at") > latest - timedelta(hours=hours))
    volatile = (
        window.group_by("item_id", "name")
        .agg(
            low=pl.col("low").min(),
            high=pl.col("high").max(),
            price=(pl.col("price") * pl.col("volume")).sum() / pl.col("volume").sum(),
            volume=pl.col("volume").sum() / hours,
        )
        .filter(pl.col("volume") >= MIN_VOLUME, pl.col("price") >= MIN_PRICE)
        .with_columns(range=(pl.col("high") - pl.col("low")) / pl.col("price"))
        .sort(["range", "item_id"], descending=[True, False])
    )
    # The ticker: every liquid mover, the biggest moves either way first.
    ticker = (
        moved.filter(pl.col("change") != 0)
        .with_columns(size=pl.col("change").abs())
        .sort(["size", "item_id"], descending=[True, False])
        .head(TICKER)
        .drop("size")
    )
    return (
        up.head(TOP).to_dicts(),
        down.head(TOP).to_dicts(),
        volatile.head(TOP).to_dicts(),
        ticker.to_dicts(),
    )


def _at(lo: str, hi: str, at: float) -> pl.Expr:
    return pl.col(lo) + at * (pl.col(hi) - pl.col(lo))


def _loop_orders(loops: pl.DataFrame, latest) -> pl.DataFrame:
    """Per item and direction traded in both markets in the latest hour: the bid for
    the item (in the currency it's bought with) and the ask (in the other), and whether
    the loop still beats BUFFER from the bid at that hour's worst sale and rate."""
    bid_at, ask_at = LOOP_ORDER
    chaos_first = pl.col("direction") == "chaos_first"
    return (
        loops.filter(pl.col("observed_at") == latest, pl.col("divine_low").is_not_null())
        .with_columns(
            bid=pl.when(chaos_first)
            .then(_at("chaos_low", "chaos_high", bid_at))
            .otherwise(_at("divine_low", "divine_high", bid_at)),
            ask=pl.when(chaos_first)
            .then(_at("divine_low", "divine_high", ask_at))
            .otherwise(_at("chaos_low", "chaos_high", ask_at)),
            bid_in=pl.when(chaos_first).then(pl.lit("chaos")).otherwise(pl.lit("divine")),
        )
        .with_columns(
            order_ok=pl.when(chaos_first)
            .then(pl.col("divine_low") * pl.col("divine_rate_low") / pl.col("bid"))
            .otherwise(pl.col("chaos_low") / (pl.col("bid") * pl.col("divine_rate_high")))
            - 1
            > BUFFER
        )
        .select("item_id", "direction", "bid", "ask", "bid_in", "order_ok")
    )


def _ranges(con, league: str, latest, table: str, item_ids: list[str]) -> pl.DataFrame:
    """Each item's Chaos price range over the last RANGE_HOURS: lowest and highest
    trade, volume-weighted average and hours traded. One grouped row per item."""
    if not item_ids:
        return pl.DataFrame(
            schema={
                "item_id": pl.String,
                "range_low": pl.Float64,
                "range_avg": pl.Float64,
                "range_high": pl.Float64,
                "range_hours": pl.Int64,
            }
        )
    # Chaos value traded over items traded: cross_market_hour counts items, the price
    # table both.
    value, units = (
        ("chaos_price * chaos_volume", "chaos_volume")
        if table == "cross_market_hour"
        else ("chaos_volume", "volume")
    )
    source = "" if table == "cross_market_hour" else " AND source = ?"
    out = db.frame(
        con,
        f"""
        SELECT item_id, min(chaos_low) AS range_low,
               sum({value}) / nullif(sum({units}), 0) AS range_avg,
               max(chaos_high) AS range_high, count(*) AS range_hours
        FROM {table}
        WHERE league_id = (SELECT id FROM league WHERE name = ?){source}
          AND observed_at > ? AND item_id IN ({", ".join("?" for _ in item_ids)})
        GROUP BY item_id
        """,
        [league, *([HOURLY] if source else []), latest - timedelta(hours=RANGE_HOURS), *item_ids],
    )
    return out.cast({"range_hours": pl.Int64})


_NO_CHANCE = {"tries": pl.Int64, "through": pl.Int64}


def _chance_frame(rows: list, keys: dict) -> pl.DataFrame:
    return pl.DataFrame(rows, schema={**keys, **_NO_CHANCE}, orient="row")


def _loop_chances(con, league: str, latest, item_ids: list[str]) -> pl.DataFrame:
    """Per listed item and direction: tries (hours its orders could be placed from, with
    the outcome known) and how many went through, buy and sale. Counted in SQL: one row
    back per item and direction."""
    keys = {"item_id": pl.String, "direction": pl.String}
    if not item_ids:
        return _chance_frame([], keys)
    bid_at, ask_at = LOOP_ORDER
    marks = ", ".join("?" for _ in item_ids)
    rows = db.rows(
        con,
        f"""
        WITH h AS (
            SELECT item_id, observed_at, chaos_low AS clo, chaos_high AS chi,
                   divine_low AS dlo, divine_high AS dhi
            FROM cross_market_hour
            WHERE league_id = (SELECT id FROM league WHERE name = ?)
              AND divine_price IS NOT NULL AND divine_rate IS NOT NULL
              AND observed_at > ? AND item_id IN ({marks})
        )
        SELECT h.item_id, count(*) AS tries,
               sum(CASE WHEN n.clo < h.clo + ? * (h.chi - h.clo)
                         AND s.dhi > h.dlo + ? * (h.dhi - h.dlo) THEN 1 ELSE 0 END),
               sum(CASE WHEN n.dlo < h.dlo + ? * (h.dhi - h.dlo)
                         AND s.chi > h.clo + ? * (h.chi - h.clo) THEN 1 ELSE 0 END)
        FROM h
        LEFT JOIN h n ON n.item_id = h.item_id AND n.observed_at = h.observed_at + INTERVAL '1 hour'
        LEFT JOIN h s ON s.item_id = h.item_id AND s.observed_at = h.observed_at + INTERVAL '2 hours'
        WHERE h.observed_at <= ?
        GROUP BY h.item_id
        """,
        [
            league,
            latest - timedelta(hours=CHANCE_HOURS),
            *item_ids,
            bid_at,
            ask_at,
            bid_at,
            ask_at,
            latest - timedelta(hours=2),
        ],
    )
    out = []
    for item_id, tries, chaos_first, divine_first in rows:
        out.append((item_id, "chaos_first", tries, chaos_first or 0))
        out.append((item_id, "divine_first", tries, divine_first or 0))
    return _chance_frame(out, keys)


def _card_chances(con, league: str, latest, card_ids: list[str]) -> pl.DataFrame:
    """Per listed card: tries (hours a set still paid from the bid at the reward's low,
    with the outcome known) and how many went through: cards bought the next hour, the
    reward sold at its ask the hour after. One row back per card."""
    keys = {"item_id": pl.String}
    if not card_ids:
        return _chance_frame([], keys)
    marks = ", ".join("?" for _ in card_ids)
    rows = db.rows(
        con,
        f"""
        WITH d AS (
            SELECT item_id, reward_item_id, stack_size, reward_quantity FROM divination_card
            WHERE item_id IN ({marks})
        ),
        p AS (
            SELECT item_id, observed_at, chaos_value AS avg, chaos_low AS lo,
                   chaos_high AS hi
            FROM price_observation
            WHERE league_id = (SELECT id FROM league WHERE name = ?) AND source = ?
              AND observed_at > ? AND chaos_value > 0
              AND (item_id IN ({marks})
                   OR item_id IN (SELECT reward_item_id FROM d))
        )
        SELECT c.item_id, count(*) AS tries,
               sum(CASE WHEN n.lo < c.lo AND s.hi > r.avg THEN 1 ELSE 0 END)
        FROM p c
        JOIN d ON d.item_id = c.item_id
        JOIN p r ON r.item_id = d.reward_item_id AND r.observed_at = c.observed_at
        LEFT JOIN p n ON n.item_id = c.item_id AND n.observed_at = c.observed_at + INTERVAL '1 hour'
        LEFT JOIN p s ON s.item_id = d.reward_item_id
             AND s.observed_at = c.observed_at + INTERVAL '2 hours'
        WHERE c.observed_at <= ? AND d.reward_quantity * r.lo > d.stack_size * c.lo
        GROUP BY c.item_id
        """,
        [
            *card_ids,
            league,
            HOURLY,
            latest - timedelta(hours=CHANCE_HOURS),
            *card_ids,
            latest - timedelta(hours=2),
        ],
    )
    return _chance_frame([(i, n, k or 0) for i, n, k in rows], keys)


def _flips(con, league: str, latest) -> pl.DataFrame:
    """The latest hour's flip candidates in the Chaos market, widest range first, with
    their orders as placed: whole Chaos for whole lots."""
    market = db.frame(
        con,
        """
        SELECT x.item_id, i.canonical_name AS name, x.chaos_price AS price,
               x.chaos_low AS low, x.chaos_high AS high,
               x.chaos_price * x.chaos_volume AS volume
        FROM cross_market_hour x
        JOIN item i ON i.id = x.item_id
        WHERE x.league_id = (SELECT id FROM league WHERE name = ?) AND x.observed_at = ?
          AND x.chaos_price >= ? AND x.chaos_price * x.chaos_volume >= ?
          AND x.chaos_high > x.chaos_low
          AND x.item_id IN (SELECT item_id FROM tracked_item)
        """,
        [league, latest, MIN_PRICE, FLIP_MIN_VOLUME],
    ).cast(  # typed even when empty (Postgres gives an empty result no types)
        {"item_id": pl.String, "name": pl.String}
        | {c: pl.Float64 for c in ("price", "low", "high", "volume")}
    )
    bid_at, ask_at = FLIP_ORDER
    bid_lot, bid_total = whole(pl.col("low") + bid_at * (pl.col("high") - pl.col("low")), "buy")
    ask_lot, ask_total = whole(pl.col("low") + ask_at * (pl.col("high") - pl.col("low")), "sell")
    return (
        market.with_columns(range=(pl.col("high") - pl.col("low")) / pl.col("price"))
        .filter(pl.col("range") >= FLIP_MIN_RANGE, pl.col("range") <= FLIP_MAX_RANGE)
        .with_columns(
            bid_lot=bid_lot,
            bid_total=bid_total,
            ask_lot=ask_lot,
            ask_total=ask_total,
            cut=pl.lit(FLIP_CUT),
        )
        .with_columns(
            bid=pl.col("bid_total") / pl.col("bid_lot"),
            ask=pl.col("ask_total") / pl.col("ask_lot"),
        )
        .cast({"bid_lot": pl.Int64, "ask_lot": pl.Int64})
        .sort(["range", "item_id"], descending=[True, False])
    )


def _flip_chances(con, league: str, latest, item_ids: list[str]) -> pl.DataFrame:
    """Per listed item: how often the same flip went through in the last CHANCE_HOURS,
    priced from each hour: bought if the next hour traded under the bid, sold if any of
    the FLIP_SELL_HOURS after traded over the (uncut) ask. One row back per item."""
    keys = {"item_id": pl.String}
    if not item_ids:
        return _chance_frame([], keys)
    bid_at, ask_at = FLIP_ORDER
    rows = db.rows(
        con,
        f"""
        WITH h AS (
            SELECT item_id, observed_at, chaos_low AS lo, chaos_high AS hi
            FROM cross_market_hour
            WHERE league_id = (SELECT id FROM league WHERE name = ?)
              AND observed_at > ? AND chaos_price > 0
              AND item_id IN ({", ".join("?" for _ in item_ids)})
        )
        SELECT h.item_id, count(*) AS tries,
               sum(CASE WHEN n.lo < h.lo + ? * (h.hi - h.lo) AND EXISTS (
                       SELECT 1 FROM h s
                       WHERE s.item_id = h.item_id
                         AND s.observed_at >= h.observed_at + INTERVAL '2 hours'
                         AND s.observed_at <= h.observed_at + INTERVAL '{1 + FLIP_SELL_HOURS} hours'
                         AND s.hi > h.lo + ? * (h.hi - h.lo)
                   ) THEN 1 ELSE 0 END)
        FROM h
        LEFT JOIN h n ON n.item_id = h.item_id AND n.observed_at = h.observed_at + INTERVAL '1 hour'
        WHERE h.observed_at <= ?
        GROUP BY h.item_id
        """,
        [
            league,
            latest - timedelta(hours=CHANCE_HOURS),
            *item_ids,
            bid_at,
            ask_at,
            latest - timedelta(hours=1 + FLIP_SELL_HOURS),
        ],
    )
    return _chance_frame([(i, n, k or 0) for i, n, k in rows], keys)


def _likeliest_first(rows: pl.DataFrame) -> pl.DataFrame:
    """The backtest's lesson as an order: orders that still pay from the bid first, then
    those most likely to go through, then the steadiest and what paid most."""
    return rows.with_columns(
        chance=pl.when(pl.col("tries") >= MIN_TRIES).then(pl.col("through") / pl.col("tries"))
    ).sort(
        ["order_ok", "chance", "hours_paid", "missed", "item_id"],
        descending=[True, True, True, True, False],
        nulls_last=True,
    )


def _loops(loops: pl.DataFrame, latest, hours: int) -> tuple[pl.DataFrame | list, int]:
    paid = paying_loops(loops.filter(pl.col("observed_at") > latest - timedelta(hours=hours)))
    if paid.is_empty():
        return [], 0
    per = (
        paid.group_by("item_id", "name", "direction")
        .agg(
            missed=pl.col("missed").sum(),
            best_edge=pl.col("edge").max(),
            hours_paid=pl.len(),
            price=pl.col("chaos_price").sort_by("observed_at").last(),
            volume=pl.col("overlap_chaos").mean(),
        )
        # Steadiest first (paid in more of the hours), then what paid the most.
        .sort(["hours_paid", "missed", "item_id"], descending=[True, True, False])
        .unique("item_id", keep="first", maintain_order=True)  # its better direction
    )
    return per, per.height


def paying_cards(turn_ins: pl.DataFrame) -> pl.DataFrame:
    """Card hours whose full set was worth less than its reward, with at least a full
    set traded (`sets`, and the Chaos they could have made as `missed`)."""
    return (
        turn_ins.with_columns(sets=pl.col("card_volume") / pl.col("stack_size"))
        .filter(pl.col("margin") > 0, pl.col("sets") >= MIN_CARD_SETS)
        .with_columns(missed=pl.col("margin") * pl.col("sets"))
    )


def _card_orders(turn_ins: pl.DataFrame, latest) -> pl.DataFrame:
    """Per card traded with its reward in the latest hour: the bid for each card (its
    low that hour), the ask for each reward (its average) and whether a set still pays
    from the bid at the reward's low."""
    bid_at, ask_at = CARD_ORDER
    return (
        turn_ins.filter(pl.col("observed_at") == latest)
        .with_columns(
            bid=_at("card_low", "card_high", bid_at),
            ask=pl.col("reward_price") if ask_at is None else None,
        )
        .with_columns(
            bid_in=pl.lit("chaos"),
            order_ok=pl.col("reward_quantity") * pl.col("reward_low")
            > pl.col("stack_size") * pl.col("bid"),
        )
        .select("item_id", "bid", "ask", "bid_in", "order_ok")
    )


def _cards(turn_ins: pl.DataFrame, latest, hours: int) -> tuple[pl.DataFrame | list, int]:
    paid = paying_cards(turn_ins.filter(pl.col("observed_at") > latest - timedelta(hours=hours)))
    if paid.is_empty():
        return [], 0
    per = (
        paid.group_by("item_id", "card", "reward")
        .agg(
            missed=pl.col("missed").sum(),
            margin=pl.col("margin").sort_by("observed_at").last(),
            set_cost=pl.col("set_cost").sort_by("observed_at").last(),
            sets=pl.col("sets").sum(),
            hours_paid=pl.len(),
        )
        .rename({"card": "name"})
        .sort(["hours_paid", "missed", "item_id"], descending=[True, True, False])
    )
    return per, per.height


def missed(con: duckdb.DuckDBPyConnection, league: str) -> list[dict]:
    """One summary per look-back in LOOKBACKS (empty before the league's first trade)."""
    latest = latest_hour(con, league)
    if latest is None:
        return []
    longest = max(LOOKBACKS)
    since = latest - timedelta(hours=longest)
    prices = _prices(con, league, latest - timedelta(hours=TREND_HOURS + 1))
    loops = pl.concat(
        [
            cross_market.hourly(con, [league], direction=d, since=since).with_columns(
                direction=pl.lit(d)
            )
            for d in DIRECTIONS
        ]
    )
    turn_ins = divination.hourly_turn_ins(con, league, since=since).drop_nulls("margin")
    cards = divination.followed_cards(con, turn_ins["card"].unique().sort().to_list()).select(
        "name",
        "item_id",
        "stack_size",
        "reward_quantity",
        reward=pl.format("{}× {}", pl.col("reward_quantity"), pl.col("reward_name")),
    )
    turn_ins = turn_ins.join(cards, left_on="card", right_on="name")
    windows = {h: (_loops(loops, latest, h), _cards(turn_ins, latest, h)) for h in LOOKBACKS}
    # The orders and 24-hour ranges, once for every item any look-back lists.
    listed = {
        kind: sorted(
            {i for w in windows.values() if len(w[k][0]) for i in w[k][0]["item_id"].to_list()}
        )
        for k, kind in enumerate(("loops", "cards"))
    }
    loop_orders = _loop_orders(loops, latest)
    card_orders = _card_orders(turn_ins, latest)
    loop_ranges = _ranges(con, league, latest, "cross_market_hour", listed["loops"])
    card_ranges = _ranges(con, league, latest, "price_observation", listed["cards"])
    loop_chances = _loop_chances(con, league, latest, listed["loops"])
    card_chances = _card_chances(con, league, latest, listed["cards"])
    flips = _flips(con, league, latest)
    flips = (
        flips.join(
            _flip_chances(con, league, latest, flips["item_id"].to_list()), on="item_id", how="left"
        )
        .with_columns(
            chance=pl.when(pl.col("tries") >= MIN_TRIES).then(pl.col("through") / pl.col("tries"))
        )
        .sort(["chance", "range", "item_id"], descending=[True, True, False], nulls_last=True)
        .to_dicts()
    )
    out = []
    for hours in LOOKBACKS:
        up, down, volatile, ticker = _movement(prices, latest, hours)
        (loop_rows, loops_paid), (card_rows, cards_paid) = windows[hours]
        all_loops = (
            loop_rows.join(loop_orders, on=["item_id", "direction"], how="left")
            .join(loop_ranges, on="item_id", how="left")
            .join(loop_chances, on=["item_id", "direction"], how="left")
            .pipe(_likeliest_first)
            .to_dicts()
            if len(loop_rows)
            else []
        )
        all_cards = (
            card_rows.join(card_orders, on="item_id", how="left")
            .join(card_ranges, on="item_id", how="left")
            .join(card_chances, on="item_id", how="left")
            .pipe(_likeliest_first)
            .to_dicts()
            if len(card_rows)
            else []
        )
        out.append(
            {
                "hours": hours,
                "latest_hour": latest.replace(tzinfo=UTC),  # a list, not a frame: mark UTC here
                "rising": up,
                "falling": down,
                "volatile": volatile,
                "ticker": ticker,
                "loops": all_loops,
                "cards": all_cards,
                "loops_paid": loops_paid,
                "cards_paid": cards_paid,
                # The latest hour's, so the same for every look-back: sent once, with the
                # 1-hour one (it's the biggest list in the response).
                "flips": flips if hours == min(LOOKBACKS) else [],
            }
        )
    return out
