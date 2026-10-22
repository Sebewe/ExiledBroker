"""Expose poe.ninja dump Parquet files to DuckDB.

Price rows stay in Parquet and are queried through views rather than copied into
the database file. That keeps re-runs cheap and lets the same files move to
object storage when the site is hosted.
"""

from collections.abc import Iterable
from pathlib import Path

import duckdb

from exiledbroker.ingest.poe_ninja_dumps import GAME, DumpInfo


def upsert_leagues(con: duckdb.DuckDBPyConnection, dumps: Iterable[DumpInfo]) -> int:
    rows = [
        (d.league_id, GAME, d.league_name, d.min_date, d.max_date, d.kind, d.league_name)
        for d in dumps
    ]
    if rows:
        con.executemany(
            """
            INSERT INTO league (id, game, name, start_at, end_at, kind, dump_name)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (id) DO UPDATE SET
                start_at = excluded.start_at, end_at = excluded.end_at,
                kind = excluded.kind, dump_name = excluded.dump_name
            """,
            rows,
        )
    return len(rows)


def refresh_views(con: duckdb.DuckDBPyConnection, dumps_dir: Path) -> list[str]:
    """(Re)create the dump views for whichever Parquet files exist. Returns view names."""
    created = []
    for kind, view in (("items", "dump_item_price"), ("currency", "dump_currency_price")):
        files = sorted((dumps_dir / kind).glob("*.parquet"))
        if not files:
            con.execute(f"DROP VIEW IF EXISTS {view}")
            continue
        paths = ", ".join(f"'{f.resolve().as_posix()}'" for f in files)
        con.execute(
            f"""
            CREATE OR REPLACE VIEW {view} AS
            SELECT p.*, datediff('day', CAST(l.start_at AS DATE), p.date) AS day_offset
            FROM read_parquet([{paths}]) p
            JOIN league l ON l.id = p.league_id
            """
        )
        created.append(view)
    return created
