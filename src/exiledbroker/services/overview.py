import duckdb
import polars as pl

from exiledbroker.storage import db

TRACKED_TABLES = ("league", "item", "price_observation", "patch_change", "prediction")


def table_counts(con: duckdb.DuckDBPyConnection) -> dict[str, int]:
    """Row counts for the core tables; a quick view of how much data is loaded."""
    return {t: db.scalar(con, f"SELECT count(*) FROM {t}") for t in TRACKED_TABLES}


def has_view(con: duckdb.DuckDBPyConnection, name: str) -> bool:
    return db.scalar(con, "SELECT count(*) FROM duckdb_views() WHERE view_name = ?", [name]) > 0


def league_calendar(con: duckdb.DuckDBPyConnection) -> pl.DataFrame:
    """Leagues with their dates, kind and how many price rows are loaded for each."""
    if has_view(con, "dump_item_price"):
        coverage = """
            LEFT JOIN (
                SELECT league_id, count(*) AS item_rows, max(day_offset) AS days_covered
                FROM dump_item_price WHERE NOT hardcore GROUP BY league_id
            ) c ON c.league_id = l.id
        """
        cols = "coalesce(c.item_rows, 0) AS item_rows, c.days_covered"
    else:
        coverage, cols = "", "0 AS item_rows, NULL AS days_covered"
    return db.frame(
        con,
        f"""
        SELECT l.name, l.kind, CAST(l.start_at AS DATE) AS start_date,
               CAST(l.end_at AS DATE) AS end_date, {cols}
        FROM league l {coverage}
        ORDER BY l.start_at DESC
        """,
    )


def leagues_with_prices(con: duckdb.DuckDBPyConnection) -> list[str]:
    if not has_view(con, "dump_item_price"):
        return []
    q = """
        SELECT l.name FROM league l
        WHERE l.id IN (SELECT DISTINCT league_id FROM dump_item_price)
        ORDER BY l.start_at DESC
    """
    return [r[0] for r in db.rows(con, q)]
