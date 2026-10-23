"""Copy leagues from the local DuckDB file into the site's Postgres database.

A development bootstrap (`eb site seed`): it gives the local Postgres the same rows a
hosted worker would have written for those leagues, and nothing else ("store only
what the site reads"). In production the worker writes Postgres itself, incrementally.

Re-seeding a league replaces that league's rows only. Shared tables (items, card
and price mappings, reference data) are upserted, so other leagues' rows survive. The
launch picks, ranked from past leagues the site doesn't hold, are replaced whole."""

from dataclasses import dataclass

import duckdb

from exiledbroker.storage import db

# What the worker writes: hourly exchange rows (daily dump history stays local).
HOURLY = "ggg-exchange-hourly"
# Per-league tables, children first (the order rows are deleted in).
LEAGUE_TABLES = ["exchange_hour_loaded", "cross_market_hour", "price_observation", "ingest_load"]
# Shared tables and their primary keys, parents first (the order rows are upserted in).
SHARED_TABLES = {
    "league": ["id"],
    "item": ["id"],
    "tracked_item": ["item_id", "group_id"],
    "divination_card": ["item_id"],
    "reference_data": ["key"],
}
# Derived from the research database's history and replaced whole (services/launch_picks).
REPLACED_TABLES = ["launch_window", "launch_pick", "launch_pick_league"]


@dataclass
class SeedResult:
    leagues: list[str]
    rows: dict[str, int]


def _columns(duck: duckdb.DuckDBPyConnection, table: str) -> list[str]:
    return [r[0] for r in db.rows(duck, f"DESCRIBE {table}")]


def _copy(pg, table: str, cols: list[str], rows: list[tuple]) -> None:
    with pg.cursor() as cur, cur.copy(f"COPY {table} ({', '.join(cols)}) FROM STDIN") as cp:
        for row in rows:
            cp.write_row(row)


def _upsert(pg, table: str, key: list[str], cols: list[str], rows: list[tuple]) -> None:
    """COPY into a temp table, then insert or update by primary key."""
    tmp = f"seed_{table}"
    pg.execute(f"CREATE TEMP TABLE {tmp} (LIKE {table}) ON COMMIT DROP")
    _copy(pg, tmp, cols, rows)
    names = ", ".join(cols)
    updates = ", ".join(f"{c} = excluded.{c}" for c in cols if c not in key)
    action = f"DO UPDATE SET {updates}" if updates else "DO NOTHING"
    pg.execute(
        f"INSERT INTO {table} ({names}) SELECT {names} FROM {tmp} "
        f"ON CONFLICT ({', '.join(key)}) {action}"
    )


def seed(duck: duckdb.DuckDBPyConnection, pg, league_names: list[str]) -> SeedResult:
    """Copy the named leagues' site rows from DuckDB into Postgres, in one transaction."""
    found = dict(
        db.rows(
            duck,
            f"SELECT name, id FROM league WHERE name IN ({', '.join('?' for _ in league_names)})",
            league_names,
        )
    )
    if missing := sorted(set(league_names) - set(found)):
        raise LookupError(f"not in the local database: {', '.join(missing)}")
    ids = list(found.values())
    marks = ", ".join("?" for _ in ids)
    # Items the leagues' rows refer to, as the exchange loader would have stored them.
    used = f"""
        SELECT item_id FROM price_observation WHERE league_id IN ({marks}) AND source = ?
        UNION SELECT item_id FROM cross_market_hour WHERE league_id IN ({marks})
    """
    selects = {
        "league": (f"WHERE id IN ({marks})", ids),
        "item": (f"WHERE id IN ({used})", [*ids, HOURLY, *ids]),
        "tracked_item": (f"WHERE item_id IN ({used})", [*ids, HOURLY, *ids]),
        "divination_card": ("", []),
        "reference_data": ("", []),
        "price_observation": (f"WHERE league_id IN ({marks}) AND source = ?", [*ids, HOURLY]),
        "cross_market_hour": (f"WHERE league_id IN ({marks})", ids),
        "exchange_hour_loaded": (f"WHERE league_id IN ({marks})", ids),
        "ingest_load": (f"WHERE league_id IN ({marks}) AND source = ?", [*ids, HOURLY]),
    }
    counts = {}
    db.init_schema(pg)
    with pg.transaction():
        for table in LEAGUE_TABLES:
            pg.execute(f"DELETE FROM {table} WHERE league_id = ANY(%s)", [ids])
        for table in [*SHARED_TABLES, *reversed(LEAGUE_TABLES)]:
            cols = _columns(duck, table)
            where, params = selects[table]
            data = db.rows(duck, f"SELECT {', '.join(cols)} FROM {table} {where}", params)
            if table in SHARED_TABLES:
                _upsert(pg, table, SHARED_TABLES[table], cols, data)
            else:
                _copy(pg, table, cols, data)
            counts[table] = len(data)
        for table in REPLACED_TABLES:
            pg.execute(f"DELETE FROM {table}")
            if not db.scalar(
                duck,
                "SELECT count(*) FROM information_schema.tables WHERE table_name = ?",
                [table],
            ):
                continue  # `eb launch picks` hasn't been run locally yet
            cols = _columns(duck, table)
            data = db.rows(duck, f"SELECT {', '.join(cols)} FROM {table}")
            _copy(pg, table, cols, data)
            counts[table] = len(data)
    pg.execute("ANALYZE")
    return SeedResult(league_names, counts)
