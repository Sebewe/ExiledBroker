import duckdb

TRACKED_TABLES = ("league", "item", "price_observation", "patch_change", "prediction")


def table_counts(con: duckdb.DuckDBPyConnection) -> dict[str, int]:
    """Row counts for the core tables; a quick view of how much data is loaded."""
    return {t: con.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in TRACKED_TABLES}
