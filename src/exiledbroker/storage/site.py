"""The site's Postgres database, as seeded from the research DuckDB and kept by the
hosted pipeline.

- `seed` (`eb site seed`): copy leagues' site rows from DuckDB into Postgres, plus the
  Launch history and picks and (`pages=True`) the leagues' raw pages, so a new server
  starts from what we already have and fetches only what's newer.
- `drop_leagues` (the pipeline, after a league switch): Postgres keeps only the live
  league ("store only what the site reads").

Re-seeding a league replaces that league's rows only. Shared tables (items, card
and price mappings, reference data) are upserted, so other leagues' rows survive. The
launch tables, ranked from past leagues the site doesn't hold, are replaced whole."""

from dataclasses import dataclass
from datetime import UTC

import duckdb

from exiledbroker.config import Settings
from exiledbroker.ingest import currency_exchange as cx
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
# Derived from the research database's history and replaced whole (services/launch_picks,
# analysis/backtest).
REPLACED_TABLES = [
    "launch_history",
    "launch_window",
    "launch_pick",
    "launch_pick_league",
    "backtest_report",
]


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


def seed(
    duck: duckdb.DuckDBPyConnection,
    pg,
    league_names: list[str],
    settings: Settings | None = None,
) -> SeedResult:
    """Copy the named leagues' site rows from DuckDB into Postgres, in one transaction.
    With `settings`, also the raw pages of the hours they have loaded (from disk, into
    `exchange_page`), so the hosted pipeline can rebuild without fetching them."""
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
        if settings is not None:
            counts["exchange_page"] = _seed_pages(duck, pg, settings, ids)
    pg.execute("ANALYZE")
    return SeedResult(league_names, counts)


def _seed_pages(duck, pg, settings: Settings, ids: list[str]) -> int:
    """Copy the pages of the leagues' loaded hours from disk, replacing what's there.
    The files are already gzipped JSON: they're stored as they are."""
    hours = sorted(
        cx.to_ts(h.replace(tzinfo=UTC))
        for (h,) in db.rows(
            duck,
            f"SELECT DISTINCT hour FROM exchange_hour_loaded WHERE league_id IN ({', '.join('?' for _ in ids)})",
            ids,
        )
    )
    missing = [h for h in hours if not cx.page_path(settings, h).exists()]
    if missing:
        raise FileNotFoundError(
            f"{len(missing)} loaded hours have no page on disk, e.g. {missing[0]}"
        )
    pg.execute("DELETE FROM exchange_page")
    _copy(
        pg,
        "exchange_page",
        ["hour", "body"],
        [(h, cx.page_path(settings, h).read_bytes()) for h in hours],
    )
    return len(hours)


def drop_leagues(con, keep: str) -> list[str]:
    """Delete every other league's site rows (on the pipeline's connection), and stop
    following them, once `keep` is the live league. Returns the leagues dropped.
    Runs on the site's database itself (`db.pushdown`), not through DuckDB's scanner."""
    con = db.pushdown(con)
    q = (
        "SELECT DISTINCT l.id, l.name FROM ingest_load il JOIN league l ON l.id = il.league_id "
        "WHERE il.league_id <> (SELECT id FROM league WHERE name = ?)"
    )
    others = db.rows(con, q, [keep])
    for lid, _ in others:
        for table in LEAGUE_TABLES:
            db.execute(con, f"DELETE FROM {table} WHERE league_id = ?", [lid])
        db.execute(con, "UPDATE league SET exchange_tracked = FALSE WHERE id = ?", [lid])
    return sorted(name for _, name in others)
