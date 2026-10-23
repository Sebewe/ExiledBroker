"""Missed opportunities (the landing page): what the latest published hours of trading
offered, for someone who wasn't watching.

GGG publishes each hour after it ends, so nothing here is live: it's a recap of the
last 1, 2 or 3 hours, computed once per loaded hour for all three look-backs and sent
together, so the page's slider never asks the server again. Each look-back has:
- **movers**: liquid items whose price rose or fell most since the start of it, with
  how many hours running they've moved that way (a short-term trend to act on);
- **volatile**: liquid items with the widest traded range (high vs low) in it;
- **loops** and **cards**: the Chaos/Divine loops and card turn-ins that left the most
  Chaos on the table: edge × volume traded in both markets, or margin × sets traded,
  summed over the hours that paid. An upper bound: nobody catches every trade.

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
MIN_PRICE = 5.0  # Chaos: below this, whole-number exchange ratios dominate the moves
MIN_VOLUME = 2000.0  # Chaos traded an hour: thinner markets swing on a single trade
BUFFER = 0.02  # a loop only counts if it beat this edge, as on the Arbitrage page
DIRECTIONS = ("chaos_first", "divine_first")


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


def _movement(prices: pl.DataFrame, latest, hours: int) -> tuple[list, list, list]:
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
    return up.head(TOP).to_dicts(), down.head(TOP).to_dicts(), volatile.head(TOP).to_dicts()


def _loops(loops: pl.DataFrame, latest, hours: int) -> tuple[list, float]:
    paid = loops.filter(
        pl.col("observed_at") > latest - timedelta(hours=hours), pl.col("edge") > BUFFER
    )
    if paid.is_empty():
        return [], 0.0
    per = (
        paid.group_by("item_id", "name", "direction")
        .agg(
            missed=(pl.col("edge") * pl.col("overlap_chaos")).sum(),
            best_edge=pl.col("edge").max(),
            hours_paid=pl.len(),
            price=pl.col("chaos_price").sort_by("observed_at").last(),
        )
        .sort(["missed", "item_id"], descending=[True, False])
        .unique("item_id", keep="first", maintain_order=True)  # its better direction
    )
    return per.head(TOP).to_dicts(), float(per["missed"].sum())


def _cards(turn_ins: pl.DataFrame, latest, hours: int) -> tuple[list, float]:
    paid = turn_ins.filter(
        pl.col("observed_at") > latest - timedelta(hours=hours), pl.col("margin") > 0
    )
    if paid.is_empty():
        return [], 0.0
    per = (
        paid.with_columns(sets=pl.col("card_volume") / pl.col("stack_size"))
        .group_by("item_id", "card", "reward")
        .agg(
            missed=(pl.col("margin") * pl.col("sets")).sum(),
            margin=pl.col("margin").sort_by("observed_at").last(),
            set_cost=pl.col("set_cost").sort_by("observed_at").last(),
            sets=pl.col("sets").sum(),
            hours_paid=pl.len(),
        )
        .rename({"card": "name"})
        .sort(["missed", "item_id"], descending=[True, False])
    )
    return per.head(TOP).to_dicts(), float(per["missed"].sum())


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
        reward=pl.format("{}× {}", pl.col("reward_quantity"), pl.col("reward_name")),
    )
    turn_ins = turn_ins.join(cards, left_on="card", right_on="name")
    out = []
    for hours in LOOKBACKS:
        up, down, volatile = _movement(prices, latest, hours)
        top_loops, loops_total = _loops(loops, latest, hours)
        top_cards, cards_total = _cards(turn_ins, latest, hours)
        out.append(
            {
                "hours": hours,
                "latest_hour": latest.replace(tzinfo=UTC),  # a list, not a frame: mark UTC here
                "rising": up,
                "falling": down,
                "volatile": volatile,
                "loops": top_loops,
                "cards": top_cards,
                "loops_missed": loops_total,
                "cards_missed": cards_total,
            }
        )
    return out
