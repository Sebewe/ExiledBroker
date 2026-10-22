"""Hourly launch-market queries over the tracked price mappings.

SQL here must stay Postgres-compatible: Supabase will serve the same queries.
"""

import duckdb
import polars as pl

from exiledbroker.normalize.exchange_loader import SOURCE as HOURLY
from exiledbroker.storage import db

UNIT_COLUMN = {"chaos": "chaos_value", "divine": "divine_value"}
SUMMARY_DAYS = (1, 3, 7, 14)  # 1-based: "day 1" is the first 24 hours after launch
SUMMARY_SCHEMA = {
    "item_id": pl.String,
    "name": pl.String,
    "group_id": pl.String,
    **{f"day_{n}": pl.Float64 for n in SUMMARY_DAYS},
    "latest": pl.Float64,
    "average": pl.Float64,
    "peak": pl.Float64,
    "peak_day": pl.Int32,
    "volume": pl.Float64,
    "chaos_volume": pl.Float64,
    "trend": pl.List(pl.Float64),
    "days": pl.Int32,
    "change": pl.Float64,
}


HOURLY_SCHEMA = {
    "observed_at": pl.Datetime,
    "day_offset": pl.Float64,
    "name": pl.String,
    "value": pl.Float64,
    "low": pl.Float64,
    "high": pl.Float64,
    "volume": pl.Float64,
}


def _unit(unit: str) -> str:
    if unit not in UNIT_COLUMN:
        raise ValueError(f"unit must be one of {', '.join(UNIT_COLUMN)}")
    return UNIT_COLUMN[unit]


def hourly_leagues(con: duckdb.DuckDBPyConnection) -> pl.DataFrame:
    """Leagues followed on the hourly exchange, newest first, including ones with no
    trades yet (a new league is registered before its first hour is published).

    Columns: name, start_at (announced), launched_at (first hour seen, or null),
    row_count and hours_covered (0 until data arrives).
    """
    return db.frame(
        con,
        """
        SELECT l.name, l.start_at, l.launched_at,
               coalesce(il.row_count, 0) AS row_count,
               coalesce((SELECT CAST(round(max(p.day_offset) * 24) AS INTEGER) + 1
                         FROM price_observation p
                         WHERE p.league_id = l.id AND p.source = ?), 0) AS hours_covered
        FROM league l
        LEFT JOIN ingest_load il ON il.league_id = l.id AND il.source = ?
        WHERE l.exchange_tracked OR il.league_id IS NOT NULL
        ORDER BY l.start_at DESC
        """,
        [HOURLY, HOURLY],
    )


def tracked_groups(con: duckdb.DuckDBPyConnection) -> pl.DataFrame:
    return db.frame(
        con,
        """
        SELECT group_id, group_label, min(sort_order) AS sort_order, count(*) AS items
        FROM tracked_item GROUP BY group_id, group_label ORDER BY 3
        """,
    )


LAUNCH_WINDOW_DAYS = 14


def daily(
    con: duckdb.DuckDBPyConnection,
    league: str,
    group_ids: list[str],
    unit: str = "chaos",
    max_day: float = LAUNCH_WINDOW_DAYS,
) -> pl.DataFrame:
    """Volume-weighted price per tracked item per launch day (day 1 = first 24 hours),
    within the first `max_day` days (a live league may have later hours loaded)."""
    col = _unit(unit)
    marks = ", ".join("?" for _ in group_ids)
    return db.frame(
        con,
        f"""
        SELECT i.id AS item_id, i.canonical_name AS name, t.group_id,
               CAST(floor(p.day_offset) AS INTEGER) + 1 AS day,
               -- Hours with no price in this unit (e.g. before the first Divine trade)
               -- are left out of both sides of the weighted average.
               sum(p.{col} * p.volume)
                   / nullif(sum(CASE WHEN p.{col} IS NOT NULL THEN p.volume END), 0) AS value,
               sum(p.volume) AS volume, sum(p.chaos_volume) AS chaos_volume
        FROM price_observation p
        JOIN item i ON i.id = p.item_id
        JOIN tracked_item t ON t.item_id = i.id
        JOIN league l ON l.id = p.league_id
        WHERE l.name = ? AND t.group_id IN ({marks}) AND p.source = ?
          AND p.day_offset >= 0 AND p.day_offset < ?
        GROUP BY i.id, i.canonical_name, t.group_id, CAST(floor(p.day_offset) AS INTEGER)
        ORDER BY name, day
        """,
        [league, *group_ids, HOURLY, max_day],
    )


def summary(
    con: duckdb.DuckDBPyConnection, league: str, group_ids: list[str], unit: str = "chaos"
) -> pl.DataFrame:
    """One row per item: average and key-day prices, change, peak, volume and a daily trend.

    Sorted by `average`, the item's volume-weighted price over the whole window.
    """
    d = daily(con, league, group_ids, unit)
    if d.is_empty():
        return pl.DataFrame(schema=SUMMARY_SCHEMA)
    priced_volume = pl.col("volume").filter(pl.col("value").is_not_null()).sum()
    out = (
        d.sort("day")
        .group_by("item_id", "name", "group_id", maintain_order=True)
        .agg(
            *[
                pl.col("value").filter(pl.col("day") == n).first().alias(f"day_{n}")
                for n in SUMMARY_DAYS
            ],
            # The item's own last traded day; thin items may not trade every day.
            pl.col("value").drop_nulls().last().alias("latest"),
            pl.when(priced_volume > 0)
            .then((pl.col("value") * pl.col("volume")).sum() / priced_volume)
            .alias("average"),
            pl.col("value").max().alias("peak"),
            pl.col("day").sort_by("value").last().alias("peak_day"),
            pl.col("volume").sum().alias("volume"),
            pl.col("chaos_volume").sum().alias("chaos_volume"),
            pl.col("day").n_unique().cast(pl.Int32).alias("days"),
            pl.col("value").drop_nulls().alias("trend"),
        )
        .with_columns(change=pl.col("latest") / pl.col("day_1") - 1)
        .sort("average", descending=True, nulls_last=True)
    )
    return out


def hourly(
    con: duckdb.DuckDBPyConnection, league: str, item_ids: list[str], unit: str = "chaos"
) -> pl.DataFrame:
    """Hourly price, traded range and volume for the given items."""
    if not item_ids:
        return pl.DataFrame(schema=HOURLY_SCHEMA)
    col = _unit(unit)
    marks = ", ".join("?" for _ in item_ids)
    return db.frame(
        con,
        f"""
        SELECT p.observed_at, p.day_offset, i.canonical_name AS name,
               p.{col} AS value,
               p.chaos_low * p.{col} / p.chaos_value AS low,
               p.chaos_high * p.{col} / p.chaos_value AS high,
               p.volume
        FROM price_observation p
        JOIN item i ON i.id = p.item_id
        JOIN league l ON l.id = p.league_id
        WHERE l.name = ? AND p.item_id IN ({marks}) AND p.source = ?
          AND p.day_offset < ?
        ORDER BY p.observed_at
        """,
        [league, *item_ids, HOURLY, LAUNCH_WINDOW_DAYS],
    )
