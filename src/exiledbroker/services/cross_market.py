"""Cross-market loops: the same item priced in Chaos and in Divines.

For each item-hour traded in both markets (table cross_market_hour), two loops are
priced at the *worst* prices seen that hour on every leg:

    Chaos → item → Divines → Chaos
        buy the item at the hour's highest Chaos price, sell it at the lowest Divine
        price, sell the Divines at the lowest Divine rate:
        edge = divine_low × rate_low / chaos_high − 1
    Divines → item → Chaos → Divines
        buy at the highest Divine price, sell at the lowest Chaos price, buy Divines
        back at the highest rate:
        edge = chaos_low / (divine_high × rate_high) − 1

An hour counts as profitable when the edge beats `buffer` (gold fees, rounding to
whole-number trade ratios). These are hourly summaries, not an order book: a positive
edge says trades happened at those prices within the hour, not that one player could
have caught both sides, so treat results as candidates to check live.

SQL here must stay Postgres-compatible: Supabase will serve the same queries.
"""

from datetime import datetime

import duckdb
import polars as pl

from exiledbroker.services import leagues as league_ids
from exiledbroker.services.scoring import rank_score
from exiledbroker.storage import db

DIRECTIONS = {
    "chaos_first": "Chaos → item → Divines → Chaos",
    "divine_first": "Divines → item → Chaos → Divines",
}
SCORE_FACTORS = {
    "edge": ("weighted_edge", True),
    "consistency": ("weighted_share", True),
    "worst_league": ("worst_league_share", True),
    "volume": ("overlap_chaos", True),
}
DEFAULT_WEIGHTS = {"edge": 3.0, "consistency": 4.0, "worst_league": 2.0, "volume": 3.0}

HOURLY_SCHEMA = {
    "league": pl.String,
    "item_id": pl.String,
    "name": pl.String,
    "observed_at": pl.Datetime,
    "day_offset": pl.Float64,
    "chaos_price": pl.Float64,
    "via_divines": pl.Float64,
    "gap": pl.Float64,
    "edge": pl.Float64,
    "overlap_chaos": pl.Float64,
}


def _edge(direction: str) -> pl.Expr:
    if direction == "chaos_first":
        return pl.col("divine_low") * pl.col("divine_rate_low") / pl.col("chaos_high") - 1
    if direction == "divine_first":
        return pl.col("chaos_low") / (pl.col("divine_high") * pl.col("divine_rate_high")) - 1
    raise ValueError(f"direction must be one of {', '.join(DIRECTIONS)}")


def hourly(
    con: duckdb.DuckDBPyConnection,
    leagues: list[str],
    item_ids: list[str] | None = None,
    direction: str = "chaos_first",
    since: datetime | None = None,
) -> pl.DataFrame:
    """Per item-hour: direct Chaos price, price via Divines, the VWAP gap, the
    worst-price loop edge, and the chaos value traded in both markets.

    `since` (exclusive) limits it to recent hours in SQL, so the live view doesn't
    pull a league's whole history."""
    if not leagues or item_ids == []:
        return pl.DataFrame(schema=HOURLY_SCHEMA)
    params: list = league_ids.ids(con, leagues)
    if not params:
        return pl.DataFrame(schema=HOURLY_SCHEMA)
    where = f"x.league_id IN ({league_ids.marks(params)})"
    if item_ids is not None:
        where += f" AND x.item_id IN ({', '.join('?' for _ in item_ids)})"
        params += item_ids
    if since is not None:
        where += " AND x.observed_at > ?"
        params.append(since)
    rows = db.frame(
        con,
        f"""
        SELECT l.name AS league, x.item_id, i.canonical_name AS name, x.observed_at,
               x.day_offset, x.chaos_price, x.chaos_volume, x.chaos_low, x.chaos_high,
               x.divine_price, x.divine_volume, x.divine_low, x.divine_high,
               x.divine_rate, x.divine_rate_low, x.divine_rate_high
        FROM cross_market_hour x
        JOIN league l ON l.id = x.league_id
        JOIN item i ON i.id = x.item_id
        WHERE {where}
        """,
        params,
    )
    if rows.is_empty():
        return pl.DataFrame(schema=HOURLY_SCHEMA)
    return (
        rows.with_columns(
            via_divines=pl.col("divine_price") * pl.col("divine_rate"),
            edge=_edge(direction),
            # The smaller side bounds how much could have gone through both markets.
            overlap_chaos=pl.min_horizontal("chaos_volume", "divine_volume")
            * pl.col("chaos_price"),
        )
        .with_columns(gap=pl.col("via_divines") / pl.col("chaos_price") - 1)
        .select(list(HOURLY_SCHEMA))
        # Sorted here, not in SQL: Postgres orders text by locale, DuckDB bytewise.
        .sort("observed_at", "league", "item_id")
    )


EDGE_SQL = {
    "chaos_first": "x.divine_low * x.divine_rate_low / x.chaos_high - 1",
    "divine_first": "x.chaos_low / (x.divine_high * x.divine_rate_high) - 1",
}


def summarize(
    con: duckdb.DuckDBPyConnection,
    leagues: list[str],
    direction: str = "chaos_first",
    buffer: float = 0.02,
    min_hours: int = 24,
) -> pl.DataFrame:
    """Per item and league, computed in the database: hours in both markets, share of
    hours the loop beat `buffer`, median edge in those hours, median VWAP gap, median
    price, overlap volume and the upper-bound profit. Returns ~one row per item and
    league instead of every item-hour (cost issue #4)."""
    if direction not in EDGE_SQL:
        raise ValueError(f"direction must be one of {', '.join(DIRECTIONS)}")
    if not leagues:
        return pl.DataFrame()
    ids = league_ids.ids(con, leagues)
    if not ids:
        return pl.DataFrame()
    out = db.frame(
        con,
        f"""
        WITH h AS (
            SELECT l.name AS league, x.item_id, i.canonical_name AS name,
                   {EDGE_SQL[direction]} AS edge,
                   x.divine_price * x.divine_rate / x.chaos_price - 1 AS gap,
                   x.chaos_price,
                   least(x.chaos_volume, x.divine_volume) * x.chaos_price AS overlap_chaos
            FROM cross_market_hour x
            JOIN league l ON l.id = x.league_id
            JOIN item i ON i.id = x.item_id
            WHERE x.league_id IN ({league_ids.marks(ids)})
        )
        SELECT league, item_id, name,
               count(*) AS hours,
               avg(CASE WHEN edge IS NULL THEN NULL WHEN edge > ? THEN 1.0 ELSE 0.0 END)
                   AS share,
               percentile_cont(0.5) WITHIN GROUP (ORDER BY edge) FILTER (WHERE edge > ?)
                   AS edge_when_paying,
               percentile_cont(0.5) WITHIN GROUP (ORDER BY gap) AS median_gap,
               percentile_cont(0.5) WITHIN GROUP (ORDER BY chaos_price) AS chaos_price,
               sum(overlap_chaos) AS overlap_chaos,
               -- Upper bound: the edge on everything that traded in both markets.
               coalesce(sum(greatest(edge, 0) * overlap_chaos) FILTER (WHERE edge > ?), 0)
                   AS capacity_chaos
        FROM h
        GROUP BY league, item_id, name
        HAVING count(*) >= ?
        """,
        [*ids, buffer, buffer, buffer, min_hours],
    )
    return out.with_columns(pl.col("hours").cast(pl.UInt32))


def across_leagues(
    per: pl.DataFrame, leagues: list[str], weights: dict[str, float]
) -> pl.DataFrame:
    """One row per item: recency-weighted share and edge, the worst league's share,
    and totals. An item missing from a league counts as 0 there (it didn't pay)."""
    if per.is_empty():
        return pl.DataFrame()
    w = per.with_columns(weight=pl.col("league").replace_strict(weights, default=0.0))
    total_weight = sum(weights.get(name, 0.0) for name in leagues)
    out = w.group_by("item_id", "name").agg(
        pl.col("league").n_unique().alias("leagues"),
        ((pl.col("share") * pl.col("weight")).sum() / total_weight).alias("weighted_share"),
        (
            (pl.col("edge_when_paying").fill_null(0) * pl.col("weight")).sum()
            / pl.col("weight").filter(pl.col("edge_when_paying").is_not_null()).sum()
        ).alias("weighted_edge"),
        pl.col("share").min().alias("worst_seen_share"),
        pl.col("median_gap").median().alias("median_gap"),
        pl.col("chaos_price").median().alias("chaos_price"),
        pl.col("overlap_chaos").sum().alias("overlap_chaos"),
        pl.col("capacity_chaos").sum().alias("capacity_chaos"),
        pl.col("hours").sum().alias("hours"),
    )
    # Worst league over *all* selected leagues: missing leagues count as 0.
    return out.with_columns(
        worst_league_share=pl.when(pl.col("leagues") == len(leagues))
        .then(pl.col("worst_seen_share"))
        .otherwise(0.0)
    ).drop("worst_seen_share")


def score(summary: pl.DataFrame, weights: dict[str, float] | None = None) -> pl.DataFrame:
    """Rank items by the tunable opportunity score (see services/scoring.py)."""
    if summary.is_empty():
        return summary
    return rank_score(
        summary.filter(pl.col("weighted_share") > 0), SCORE_FACTORS, weights or DEFAULT_WEIGHTS
    )
