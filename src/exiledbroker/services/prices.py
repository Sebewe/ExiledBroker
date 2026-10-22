import duckdb
import polars as pl

from exiledbroker.storage import db


def item_names(con: duckdb.DuckDBPyConnection, league_name: str) -> list[str]:
    q = """
        SELECT DISTINCT p.name FROM dump_item_price p JOIN league l ON l.id = p.league_id
        WHERE l.name = ? AND NOT p.hardcore ORDER BY p.name
    """
    return [r[0] for r in db.rows(con, q, [league_name])]


def item_curve(
    con: duckdb.DuckDBPyConnection, league_name: str, item_name: str, max_day: int = 30
) -> pl.DataFrame:
    """Daily chaos price by day_offset, one series per variant/links combination."""
    q = """
        SELECT p.day_offset,
               concat_ws(' ', p.name, p.variant, CASE WHEN p.links IS NOT NULL
                   THEN p.links || 'L' END) AS series,
               p.chaos_value, p.confidence
        FROM dump_item_price p JOIN league l ON l.id = p.league_id
        WHERE l.name = ? AND p.name = ? AND NOT p.hardcore AND p.day_offset <= ?
        ORDER BY p.day_offset
    """
    return db.frame(con, q, [league_name, item_name, max_day])
