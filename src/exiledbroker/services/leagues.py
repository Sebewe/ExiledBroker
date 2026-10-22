"""League names → ids, for filtering the big tables.

Filter price_observation / cross_market_hour by `league_id IN (?, …)` with the ids
looked up first. Joining league and filtering on its name, or `IN (SELECT id …)`,
leaves Postgres no league id to seek the (league, time) indexes with, so it reads
every league's rows in the time range (tests/test_postgres.py checks this)."""

import duckdb

from exiledbroker.storage import db


def ids(con: duckdb.DuckDBPyConnection, names: list[str]) -> list[str]:
    if not names:
        return []
    marks = ", ".join("?" for _ in names)
    return [r[0] for r in db.rows(con, f"SELECT id FROM league WHERE name IN ({marks})", names)]


def marks(values: list) -> str:
    """Placeholders for `IN (…)`; an empty list matches nothing (rather than `IN ()`,
    a syntax error)."""
    return ", ".join("?" for _ in values) or "NULL"
