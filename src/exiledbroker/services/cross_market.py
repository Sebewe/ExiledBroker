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

import duckdb
import polars as pl

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
) -> pl.DataFrame:
    """Per item-hour: direct Chaos price, price via Divines, the VWAP gap, the
    worst-price loop edge, and the chaos value traded in both markets."""
    if not leagues or item_ids == []:
        return pl.DataFrame(schema=HOURLY_SCHEMA)
    params: list = list(leagues)
    where = f"l.name IN ({', '.join('?' for _ in leagues)})"
    if item_ids is not None:
        where += f" AND x.item_id IN ({', '.join('?' for _ in item_ids)})"
        params += item_ids
    rows = db.frame(
        con,
        f"""
        SELECT l.name AS league, x.item_id, i.canonical_name AS name, x.*
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
    )


def per_league(hours: pl.DataFrame, buffer: float = 0.02, min_hours: int = 24) -> pl.DataFrame:
    """Per item and league: hours in both markets, share of hours the loop beat
    `buffer`, median edge in those hours, median VWAP gap and overlap volume."""
    if hours.is_empty():
        return pl.DataFrame()
    paying = pl.col("edge") > buffer
    return (
        hours.group_by("league", "item_id", "name")
        .agg(
            pl.len().alias("hours"),
            paying.mean().alias("share"),
            pl.col("edge").filter(paying).median().alias("edge_when_paying"),
            pl.col("gap").median().alias("median_gap"),
            pl.col("chaos_price").median().alias("chaos_price"),
            pl.col("overlap_chaos").sum().alias("overlap_chaos"),
            # Upper bound: the edge on everything that traded in both markets.
            (pl.col("edge").clip(lower_bound=0) * pl.col("overlap_chaos"))
            .filter(paying)
            .sum()
            .alias("capacity_chaos"),
        )
        .filter(pl.col("hours") >= min_hours)
    )


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
