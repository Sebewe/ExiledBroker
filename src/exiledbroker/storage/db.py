from collections.abc import Iterator
from contextlib import contextmanager
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


# DuckDB 2.0 keeps an execute() result open until it is fully fetched, so always
# go through these helpers rather than calling fetchone() on a connection.
def rows(con: duckdb.DuckDBPyConnection, sql: str, params: list | None = None) -> list[tuple]:
    return con.execute(sql, params or []).fetchall()


def scalar(con: duckdb.DuckDBPyConnection, sql: str, params: list | None = None):
    return rows(con, sql, params)[0][0]


def frame(con: duckdb.DuckDBPyConnection, sql: str, params: list | None = None) -> pl.DataFrame:
    return con.sql(sql, params=params).pl()
