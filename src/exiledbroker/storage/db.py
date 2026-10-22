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
# reads from every thread, because Streamlit's AppTest runs pages on its own thread.
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
