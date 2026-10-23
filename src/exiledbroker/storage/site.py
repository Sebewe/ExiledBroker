"""Copy leagues from DuckDB (the research database) into the site's Postgres database.

- `seed` (`eb site seed`): a development bootstrap, replacing the leagues' rows.
- `publish` (the hosted pipeline, `eb pipeline run`): the same rows, incrementally:
  only the hours Postgres lacks are copied and only hours that left the window are
  deleted, so each hourly run writes one hour. Postgres keeps only the live league
  ("store only what the site reads"); the history stays in the pipeline's DuckDB.

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


@dataclass
class PublishResult:
    league: str
    hours_added: int = 0
    hours_removed: int = 0
    rebuilt: bool = False  # the league's rows were replaced (a loader rebuild)
    picks: bool = False  # the launch tables were replaced
    leagues_dropped: list[str] | None = None

    @property
    def changed(self) -> bool:
        return bool(
            self.hours_added
            or self.hours_removed
            or self.rebuilt
            or self.picks
            or self.leagues_dropped
        )


def _hours(con, lid: str) -> set:
    return {
        r[0]
        for r in db.rows(con, "SELECT hour FROM exchange_hour_loaded WHERE league_id = ?", [lid])
    }


def _load_row(con, lid: str) -> tuple | None:
    q = (
        "SELECT fingerprint, item_count, row_count, loaded_at FROM ingest_load "
        "WHERE league_id = ? AND source = ?"
    )
    rows = db.rows(con, q, [lid, HOURLY])
    return tuple(rows[0]) if rows else None


def _built_at(con):
    has = db.scalar(
        con, "SELECT count(*) FROM information_schema.tables WHERE table_name = 'launch_window'"
    )
    return db.scalar(con, "SELECT max(built_at) FROM launch_window") if has else None


def publish(duck: duckdb.DuckDBPyConnection, pg, league: str) -> PublishResult:
    """Bring Postgres in line with the league's rows in DuckDB, in one transaction,
    writing only what changed. Other leagues' rows are dropped from Postgres (the site
    shows the live league). A league DuckDB rebuilt (new loader version) is replaced
    whole, as `seed` would. Nothing changed: nothing is written, so the site's data
    version (and every visitor's cache) stays as it is."""
    result = PublishResult(league)
    rows = db.rows(duck, "SELECT id FROM league WHERE name = ?", [league])
    if not rows:
        raise LookupError(f"not in the pipeline's database: {league}")
    lid = rows[0][0]
    db.init_schema(pg)
    duck_load, pg_load = _load_row(duck, lid), _load_row(pg, lid)
    if duck_load is None:
        return result  # nothing loaded yet (a league registered before its first trade)
    others = sorted(
        name
        for (name,) in db.rows(
            pg,
            "SELECT DISTINCT l.name FROM ingest_load il JOIN league l ON l.id = il.league_id "
            "WHERE il.league_id <> ?",
            [lid],
        )
    )
    picks = _built_at(duck) is not None and _built_at(duck) != _built_at(pg)
    if pg_load is not None and pg_load[0] != duck_load[0]:
        result.rebuilt = True
    duck_hours, pg_hours = _hours(duck, lid), set() if result.rebuilt else _hours(pg, lid)
    add, remove = sorted(duck_hours - pg_hours), sorted(pg_hours - duck_hours)
    result.hours_added, result.hours_removed = len(add), len(remove)
    result.picks, result.leagues_dropped = picks, others or None
    if not (result.changed or pg_load != duck_load):
        return result

    with pg.transaction():
        if others:
            other_ids = [
                r[0] for r in db.rows(pg, "SELECT id FROM league WHERE name = ANY(?)", [others])
            ]
            for table in LEAGUE_TABLES:
                pg.execute(f"DELETE FROM {table} WHERE league_id = ANY(%s)", [other_ids])
        if result.rebuilt:
            for table in LEAGUE_TABLES:
                pg.execute(f"DELETE FROM {table} WHERE league_id = %s", [lid])
        elif remove:
            for table, col in (
                ("exchange_hour_loaded", "hour"),
                ("cross_market_hour", "observed_at"),
            ):
                pg.execute(
                    f"DELETE FROM {table} WHERE league_id = %s AND {col} = ANY(%s)", [lid, remove]
                )
            pg.execute(
                "DELETE FROM price_observation WHERE league_id = %s AND source = %s "
                "AND observed_at = ANY(%s)",
                [lid, HOURLY, remove],
            )
        # Shared tables: the league itself and every item its rows use, upserted (small).
        used = """
            SELECT item_id FROM price_observation WHERE league_id = ? AND source = ?
            UNION SELECT item_id FROM cross_market_hour WHERE league_id = ?
        """
        shared = {
            "league": ("WHERE id = ?", [lid]),
            "item": (f"WHERE id IN ({used})", [lid, HOURLY, lid]),
            "reference_data": ("", []),
        }
        for table, (where, params) in shared.items():
            cols = _columns(duck, table)
            data = db.rows(duck, f"SELECT {', '.join(cols)} FROM {table} {where}", params)
            _upsert(pg, table, SHARED_TABLES[table], cols, data)
        # The mappings are rebuilt on every load, so items can leave them: mirror them.
        for table, where, params in (
            ("tracked_item", f"WHERE item_id IN ({used})", [lid, HOURLY, lid]),
            ("divination_card", "", []),
        ):
            cols = _columns(duck, table)
            data = db.rows(duck, f"SELECT {', '.join(cols)} FROM {table} {where}", params)
            pg.execute(f"DELETE FROM {table}")
            _copy(pg, table, cols, data)
        # The new hours, parents first.
        if add:
            span, wanted = [min(add), max(add)], set(add)
            for table, where, params in (
                (
                    "price_observation",
                    "source = ? AND observed_at BETWEEN ? AND ?",
                    [HOURLY, *span],
                ),
                ("cross_market_hour", "observed_at BETWEEN ? AND ?", span),
                ("exchange_hour_loaded", "hour BETWEEN ? AND ?", span),
            ):
                cols = _columns(duck, table)
                col = "hour" if table == "exchange_hour_loaded" else "observed_at"
                data = [
                    r
                    for r in db.rows(
                        duck,
                        f"SELECT {', '.join(cols)} FROM {table} WHERE league_id = ? AND {where}",
                        [lid, *params],
                    )
                    if r[cols.index(col)] in wanted
                ]
                _copy(pg, table, cols, data)
        cols = _columns(duck, "ingest_load")
        _upsert(
            pg,
            "ingest_load",
            ["league_id", "source"],
            cols,
            db.rows(
                duck,
                f"SELECT {', '.join(cols)} FROM ingest_load WHERE league_id = ? AND source = ?",
                [lid, HOURLY],
            ),
        )
        if picks:
            for table in REPLACED_TABLES:
                pg.execute(f"DELETE FROM {table}")
                cols = _columns(duck, table)
                _copy(pg, table, cols, db.rows(duck, f"SELECT {', '.join(cols)} FROM {table}"))
    return result
