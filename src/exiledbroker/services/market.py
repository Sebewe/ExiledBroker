"""Hourly launch-market queries over the tracked price mappings.

SQL here must stay Postgres-compatible: Supabase will serve the same queries.
"""

import duckdb
import polars as pl

from exiledbroker.normalize.exchange_loader import SOURCE as HOURLY
from exiledbroker.storage import db

UNIT_COLUMN = {"chaos": "chaos_value", "divine": "divine_value"}
SUMMARY_DAYS = (1, 3, 7, 14)  # 1-based: "day 1" is the first 24 hours after launch


def _unit(unit: str) -> str:
    if unit not in UNIT_COLUMN:
        raise ValueError(f"unit must be one of {', '.join(UNIT_COLUMN)}")
    return UNIT_COLUMN[unit]


def hourly_leagues(con: duckdb.DuckDBPyConnection) -> pl.DataFrame:
    """Leagues with hourly exchange data: name, launch time, hours covered."""
    return db.frame(
        con,
        """
        SELECT l.name, l.launched_at, il.row_count,
               (SELECT max(p.day_offset) FROM price_observation p
                WHERE p.league_id = l.id AND p.source = ?) AS days_covered
        FROM league l JOIN ingest_load il ON il.league_id = l.id AND il.source = ?
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


def daily(
    con: duckdb.DuckDBPyConnection, league: str, group_ids: list[str], unit: str = "chaos"
) -> pl.DataFrame:
    """Volume-weighted price per tracked item per launch day (day 1 = first 24 hours)."""
    col = _unit(unit)
    marks = ", ".join("?" for _ in group_ids)
    return db.frame(
        con,
        f"""
        SELECT i.id AS item_id, i.canonical_name AS name, t.group_id,
               CAST(floor(p.day_offset) AS INTEGER) + 1 AS day,
               sum(p.{col} * p.volume) / sum(p.volume) AS value,
               sum(p.volume) AS volume, sum(p.chaos_volume) AS chaos_volume
        FROM price_observation p
        JOIN item i ON i.id = p.item_id
        JOIN tracked_item t ON t.item_id = i.id
        JOIN league l ON l.id = p.league_id
        WHERE l.name = ? AND t.group_id IN ({marks}) AND p.source = ? AND p.day_offset >= 0
        GROUP BY i.id, i.canonical_name, t.group_id, CAST(floor(p.day_offset) AS INTEGER)
        ORDER BY name, day
        """,
        [league, *group_ids, HOURLY],
    )


def summary(
    con: duckdb.DuckDBPyConnection, league: str, group_ids: list[str], unit: str = "chaos"
) -> pl.DataFrame:
    """One row per item: average and key-day prices, change, peak, volume and a daily trend.

    Sorted by `average`, the item's volume-weighted price over the whole window.
    """
    d = daily(con, league, group_ids, unit)
    if d.is_empty():
        return d
    last_day = d["day"].max()
    out = (
        d.sort("day")
        .group_by("item_id", "name", "group_id", maintain_order=True)
        .agg(
            *[
                pl.col("value").filter(pl.col("day") == n).first().alias(f"day_{n}")
                for n in SUMMARY_DAYS
            ],
            pl.col("value").filter(pl.col("day") == last_day).first().alias("latest"),
            ((pl.col("value") * pl.col("volume")).sum() / pl.col("volume").sum()).alias("average"),
            pl.col("value").max().alias("peak"),
            pl.col("day").sort_by("value").last().alias("peak_day"),
            pl.col("volume").sum().alias("volume"),
            pl.col("chaos_volume").sum().alias("chaos_volume"),
            pl.col("value").alias("trend"),
        )
        .with_columns(change=pl.col("latest") / pl.col("day_1") - 1)
        .sort("average", descending=True)
    )
    return out


def hourly(
    con: duckdb.DuckDBPyConnection, league: str, item_ids: list[str], unit: str = "chaos"
) -> pl.DataFrame:
    """Hourly price, traded range and volume for the given items."""
    if not item_ids:
        return pl.DataFrame()
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
        ORDER BY p.observed_at
        """,
        [league, *item_ids, HOURLY],
    )
