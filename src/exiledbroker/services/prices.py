import duckdb
import polars as pl

from exiledbroker.storage import db

UNITS = {"chaos": "chaos_value", "divine": "divine_value"}


def _in_list(values: list[str]) -> str:
    return ", ".join("?" for _ in values)


def item_names(con: duckdb.DuckDBPyConnection, leagues: list[str]) -> list[str]:
    """Item names priced in any of the given leagues."""
    if not leagues:
        return []
    q = f"""
        SELECT DISTINCT i.canonical_name
        FROM price_observation p
        JOIN item i ON i.id = p.item_id
        JOIN league l ON l.id = p.league_id
        WHERE l.name IN ({_in_list(leagues)})
    """
    # Sorted here: Postgres orders text by locale, DuckDB bytewise.
    return sorted(r[0] for r in db.rows(con, q, leagues))


def item_curve(
    con: duckdb.DuckDBPyConnection,
    leagues: list[str],
    item_name: str,
    max_day: int = 30,
    unit: str = "chaos",
) -> pl.DataFrame:
    """Daily price by day_offset, one series per league and variant/links combination."""
    if unit not in UNITS:
        raise ValueError(f"unit must be one of {', '.join(UNITS)}")
    if not leagues:
        return pl.DataFrame()
    q = f"""
        SELECT p.day_offset,
               concat_ws(' · ', l.name, i.variant,
                         CASE WHEN i.links IS NOT NULL THEN i.links || 'L' END) AS series,
               l.kind AS league_kind,
               p.{UNITS[unit]} AS value, p.confidence
        FROM price_observation p
        JOIN item i ON i.id = p.item_id
        JOIN league l ON l.id = p.league_id
        WHERE l.name IN ({_in_list(leagues)}) AND i.canonical_name = ? AND p.day_offset <= ?
        ORDER BY p.day_offset
    """
    return db.frame(con, q, [*leagues, item_name, max_day])
