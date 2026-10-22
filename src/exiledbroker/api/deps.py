"""Shared request plumbing: the database connection, the data version, cached reads,
and turning polars frames into JSON-safe rows."""

import math
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from decimal import Decimal

import polars as pl
from fastapi import HTTPException

from exiledbroker.api.cache import results
from exiledbroker.config import get_settings
from exiledbroker.storage import db

_ready: set[str] = set()


def connection() -> Iterator:
    """FastAPI dependency: a read connection to the site's database. Before anything
    has been loaded (no database, or no schema yet) every endpoint answers 503."""
    settings = get_settings()
    where = settings.database_url or str(settings.db_path)
    if not settings.database_url and not settings.db_path.exists():
        raise HTTPException(503, "no data loaded yet")
    with db.site_session(settings) as con:
        if where not in _ready:
            if not db.scalar(
                con,
                "SELECT count(*) FROM information_schema.tables WHERE table_name = 'ingest_load'",
            ):
                raise HTTPException(503, "no data loaded yet")
            _ready.add(where)
        yield con


def data_version(con) -> str | None:
    """Changes whenever a load finishes (the worker's hourly update, a rebuild).
    One read of a tiny table, so it's cheap to check on every request."""
    at = db.scalar(con, "SELECT max(loaded_at) FROM ingest_load")
    return at.isoformat() if at else None


def cached(con, name: str, args: tuple, compute: Callable[[], list[dict]]) -> list[dict]:
    """Rows for (endpoint, args), recomputed only when the data version changes."""
    return results.get_or_compute((name, args, data_version(con)), compute)


def _clean(value):
    if isinstance(value, float) and not math.isfinite(value):
        return None  # NaN / inf aren't JSON
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, list):
        return [_clean(v) for v in value]
    return value


def records(df: pl.DataFrame) -> list[dict]:
    """Rows as dicts with UTC-aware timestamps and JSON-safe numbers."""
    if df.is_empty():
        return []
    df = df.with_columns(
        pl.col(c).dt.replace_time_zone("UTC")
        for c, t in df.schema.items()
        if isinstance(t, pl.Datetime) and t.time_zone is None
    )
    return [{k: _clean(v) for k, v in row.items()} for row in df.to_dicts()]


def league_id(con, name: str) -> str:
    rows = db.rows(con, "SELECT id FROM league WHERE name = ?", [name])
    if not rows:
        raise HTTPException(404, f"unknown league {name!r}")
    return rows[0][0]


def parse_weights(text: str | None, defaults: dict[str, float]) -> dict[str, float]:
    """`edge:4,volume:2` → a full weights dict (unnamed factors keep their default)."""
    weights = dict(defaults)
    if not text:
        return weights
    for part in text.split(","):
        name, _, value = part.partition(":")
        name = name.strip()
        if name not in defaults:
            raise HTTPException(422, f"unknown weight {name!r}; use {', '.join(defaults)}")
        try:
            weights[name] = float(value)
        except ValueError:
            raise HTTPException(422, f"weight {name!r} must be a number") from None
        if not 0 <= weights[name] <= 10:
            raise HTTPException(422, f"weight {name!r} must be between 0 and 10")
    return weights


def now_utc() -> datetime:
    return datetime.now(UTC)
