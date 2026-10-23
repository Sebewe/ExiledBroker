import sys
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path

import duckdb
import polars as pl

from exiledbroker.config import get_settings


def connect(path: Path | None = None, *, read_only: bool = False) -> duckdb.DuckDBPyConnection:
    """Open the project database. The API opens it read-only; pipeline jobs write."""
    path = path or get_settings().db_path
    if not read_only:
        path.parent.mkdir(parents=True, exist_ok=True)
    return duckdb.connect(str(path), read_only=read_only)


@contextmanager
def session(
    path: Path | None = None, *, read_only: bool = False
) -> Iterator[duckdb.DuckDBPyConnection]:
    con = connect(path, read_only=read_only)
    try:
        yield con
    finally:
        con.close()


_pools: dict[str, object] = {}
_pools_lock = threading.Lock()


def _pool(url: str):
    """One small connection pool per database URL, opened on first use. Autocommit
    (each read is its own statement) and no prepared statements, so Supabase's
    transaction pooler works."""
    with _pools_lock:
        if url not in _pools:
            from psycopg_pool import ConnectionPool

            _pools[url] = ConnectionPool(
                url,
                min_size=1,
                max_size=5,
                kwargs={"autocommit": True, "prepare_threshold": None},
                open=True,
            )
        return _pools[url]


@contextmanager
def site_session(settings=None, *, read_only: bool = True) -> Iterator:
    """A read connection to what the site serves: Postgres (pooled) when
    `EB_DATABASE_URL` is set, otherwise the local DuckDB file. The API uses this;
    the live worker writes through `site_writer`; research commands keep `session`."""
    settings = settings or get_settings()
    if not settings.database_url:
        with session(settings.db_path, read_only=read_only) as con:
            yield con
        return
    with _pool(settings.database_url).connection() as con:
        yield con


_schema_ready: set[str] = set()
# Print every query `site_writer`'s DuckDB sends to Postgres (to stderr; tests check
# that a hosted pass never copies a whole table).
SHOW_PG_QUERIES = False


@contextmanager
def site_writer(settings=None) -> Iterator[duckdb.DuckDBPyConnection]:
    """A DuckDB connection that writes what the site reads (the live worker's).

    With `EB_DATABASE_URL` set, an in-memory DuckDB with the Postgres database attached
    and selected (`USE site`): the loaders run unchanged, staging in DuckDB (Parquet,
    ASOF joins, temp tables) while their tables and transactions are Postgres's.
    Otherwise the local DuckDB file. Either way the schema is created first."""
    settings = settings or get_settings()
    url = settings.database_url
    if not url:
        with session(settings.db_path) as con:
            init_schema(con)
            yield con
        return
    if url not in _schema_ready:
        import psycopg

        with psycopg.connect(url, autocommit=True) as pg:
            init_schema(pg)
        _schema_ready.add(url)
    con = duckdb.connect()
    try:
        con.execute("INSTALL postgres")  # a no-op once installed (the image bakes it in)
        con.execute("LOAD postgres")
        if SHOW_PG_QUERIES:
            con.execute("SET pg_debug_show_queries = true")
        # Only `public`: each attach reads the catalog of the schemas it sees (~0.5 MB
        # for all of them; Supabase adds auth, storage and more), ~40 kB for ours.
        con.execute(
            f"ATTACH '{url.replace(chr(39), chr(39) * 2)}' AS site (TYPE postgres, SCHEMA 'public')"
        )
        con.execute("USE site")
        yield con
    finally:
        con.close()


def init_schema(con: duckdb.DuckDBPyConnection) -> None:
    sql = resources.files("exiledbroker.storage").joinpath("schema.sql").read_text()
    con.execute(sql)


@dataclass
class Query:
    caller: str  # the function that ran it, e.g. "services.live.live_loops"
    rows: int
    bytes: int  # size of the result as returned to Python (estimated)
    ms: float
    sql: str = ""
    params: list | None = None


@dataclass
class Meter:
    """What a block of code read from the database, query by query."""

    queries: list[Query] = field(default_factory=list)

    @property
    def rows(self) -> int:
        return sum(q.rows for q in self.queries)

    @property
    def bytes(self) -> int:
        return sum(q.bytes for q in self.queries)

    @property
    def ms(self) -> float:
        return sum(q.ms for q in self.queries)

    def by_caller(self) -> dict[str, Query]:
        out: dict[str, Query] = {}
        for q in self.queries:
            t = out.setdefault(q.caller, Query(q.caller, 0, 0, 0.0))
            t.rows, t.bytes, t.ms = t.rows + q.rows, t.bytes + q.bytes, t.ms + q.ms
        return out


# Open meters. Off (empty) in normal use, so reads cost nothing extra. A meter sees
# reads from every thread (FastAPI runs sync endpoints on a thread pool).
_meters: list[Meter] = []
_meters_lock = threading.Lock()


@contextmanager
def metered() -> Iterator[Meter]:
    """Record every read made through rows/scalar/frame while the block runs.
    Used by the performance tests and `eb perf report`."""
    meter = Meter()
    with _meters_lock:
        _meters.append(meter)
    try:
        yield meter
    finally:
        with _meters_lock:
            _meters.remove(meter)


def _caller() -> str:
    f = sys._getframe(2)
    while f is not None and f.f_code.co_filename == __file__:
        f = f.f_back
    if f is None:
        return "?"
    module = f.f_globals.get("__name__", "?").removeprefix("exiledbroker.")
    return f"{module}.{f.f_code.co_name}"


def _value_bytes(v) -> int:
    if isinstance(v, str | bytes):
        return len(v)
    return 8


def _record(sql: str, params: list | None, rows: int, size: int, started: float) -> None:
    ms = (time.perf_counter() - started) * 1000
    query = Query(_caller(), rows, size, ms, sql, params)
    with _meters_lock:
        for m in _meters:
            m.queries.append(query)


# Postgres (the hosted database) is reached through the same helpers: services take
# either connection. Their SQL uses DuckDB's `?` placeholders, which psycopg spells
# `%s` (so a literal `%`, as in LIKE patterns, is doubled).
def is_postgres(con) -> bool:
    return not isinstance(con, duckdb.DuckDBPyConnection)


def _pg_query(con, sql: str, params: list | None):
    cur = con.cursor()
    cur.execute(sql.replace("%", "%%").replace("?", "%s"), params or None)
    return cur


# DuckDB with Postgres attached (`site_writer`) reads an attached table by copying the
# columns it needs out of Postgres: fine for a join on the new hour's rows, but a
# DELETE, an aggregate or a correlated subquery over the league copies the whole table
# (the hosted pipeline read ~100 MB a pass that way; across the internet, to Supabase,
# that's ~70 GB a month). `pushdown` runs such statements on Postgres itself, inside
# the same transaction (postgres_query / postgres_execute), so only the result
# crosses the network. The SQL must be plain Postgres on site tables (no DuckDB temp
# tables or read_parquet).
def pushdown(con):
    """`con`, or for a DuckDB connection with Postgres attached and selected, a
    connection-like object that runs each statement on Postgres. Pass it to
    rows / scalar / frame / execute."""
    if is_postgres(con):
        return con
    current = con.execute(
        "SELECT database_name, type FROM duckdb_databases() "
        "WHERE database_name = current_database()"
    ).fetchall()
    if current and current[0][1] == "postgres":
        return _Attached(con, current[0][0])
    return con


class _Attached:
    """Enough of a psycopg connection for `_pg_query`: statements go to Postgres
    through the DuckDB connection, parameters inlined as Postgres literals."""

    def __init__(self, con: duckdb.DuckDBPyConnection, name: str):
        self.con, self.name = con, name

    def cursor(self) -> "_AttachedCursor":
        return _AttachedCursor(self)


@dataclass
class _Column:
    name: str


class _AttachedCursor:
    def __init__(self, attached: _Attached):
        self.attached, self.description, self._rows = attached, None, []

    def execute(self, sql: str, params: list | None = None) -> None:
        from psycopg import sql as pgsql

        literals = tuple(pgsql.Literal(p).as_string(None) for p in params or [])
        text = sql % literals if literals else sql.replace("%%", "%")
        con, name = self.attached.con, self.attached.name
        if text.lstrip().upper().startswith(("SELECT", "WITH")):
            result = con.execute(f"SELECT * FROM postgres_query('{name}', ?)", [text])
            self.description = [_Column(d[0]) for d in result.description]
            self._rows = result.fetchall()
        else:
            con.execute(f"CALL postgres_execute('{name}', ?)", [text])

    def fetchall(self) -> list[tuple]:
        return self._rows

    def close(self) -> None:
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> None:
        pass


# DuckDB 2.0 keeps an execute() result open until it is fully fetched, so always
# go through these helpers rather than calling fetchone() on a connection.
def rows(con: duckdb.DuckDBPyConnection, sql: str, params: list | None = None) -> list[tuple]:
    started = time.perf_counter()
    if is_postgres(con):
        with _pg_query(con, sql, params) as cur:
            out = cur.fetchall() if cur.description else []
    else:
        out = con.execute(sql, params or []).fetchall()
    if _meters:
        _record(sql, params, len(out), sum(_value_bytes(v) for r in out for v in r), started)
    return out


def execute(con: duckdb.DuckDBPyConnection, sql: str, params: list | None = None) -> None:
    """A write on either engine, with `?` placeholders (not metered: reads only)."""
    if is_postgres(con):
        _pg_query(con, sql, params).close()
    else:
        con.execute(sql, params or [])


def scalar(con: duckdb.DuckDBPyConnection, sql: str, params: list | None = None):
    return rows(con, sql, params)[0][0]


def frame(con: duckdb.DuckDBPyConnection, sql: str, params: list | None = None) -> pl.DataFrame:
    started = time.perf_counter()
    if is_postgres(con):
        with _pg_query(con, sql, params) as cur:
            names = [d.name for d in cur.description]
            out = pl.DataFrame(cur.fetchall(), schema=names, orient="row", infer_schema_length=None)
    else:
        out = con.sql(sql, params=params).pl()
    if _meters:
        _record(sql, params, out.height, int(out.estimated_size()), started)
    return out
