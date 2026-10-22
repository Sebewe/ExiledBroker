import duckdb
import polars as pl

from exiledbroker.storage import db

TRACKED_TABLES = ("league", "item", "price_observation", "patch_change", "prediction")


def table_counts(con: duckdb.DuckDBPyConnection) -> dict[str, int]:
    """Row counts for the core tables; a quick view of how much data is loaded."""
    return {t: db.scalar(con, f"SELECT count(*) FROM {t}") for t in TRACKED_TABLES}


def league_calendar(con: duckdb.DuckDBPyConnection) -> pl.DataFrame:
    """Leagues with their kind, length and how many price rows are loaded for each."""
    return db.frame(
        con,
        """
        SELECT l.name, l.kind, CAST(l.start_at AS DATE) AS start_date,
               CAST(l.end_at AS DATE) AS end_date,
               CAST(l.end_at AS DATE) - CAST(l.start_at AS DATE) AS length_days,
               coalesce(il.price_rows, 0) AS price_rows
        FROM league l
        LEFT JOIN (
            SELECT league_id, sum(row_count) AS price_rows FROM ingest_load GROUP BY league_id
        ) il ON il.league_id = l.id
        ORDER BY l.start_at DESC
        """,
    )


def leagues_with_prices(con: duckdb.DuckDBPyConnection) -> pl.DataFrame:
    """Loaded leagues (name, kind), newest first."""
    return db.frame(
        con,
        """
        SELECT l.name, l.kind FROM league l
        WHERE l.id IN (SELECT league_id FROM ingest_load)
        ORDER BY l.start_at DESC
        """,
    )
