"""How the API serves tables: computed once per data version, then sent as cached bytes.

A `View` is one table (an endpoint plus its arguments) and how to compute it. The
first request for a view after new data is loaded computes it in the database, checks
it against its response model, and stores the JSON body, gzipped once. Every later
request, from any visitor, gets those bytes: no database query, no serialization. A
client that already has the current version gets `304 Not Modified` (ETag), with no
body at all. The pages' default views are computed in the background as soon as a new
hour is loaded (api/warm.py), so visitors don't wait for them either.

The data version (when the latest load finished) is read from the database at most
every VERSION_TTL seconds, so a burst of requests costs one tiny query. ETags also
carry the code version, so a deploy that changes a response (a new field, a new
calculation) isn't answered with 304 for data browsers cached from the old code."""

import gzip
import hashlib
import math
import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import polars as pl
from fastapi import HTTPException, Request, Response
from pydantic import BaseModel, TypeAdapter

from exiledbroker.api.cache import results
from exiledbroker.config import get_settings
from exiledbroker.storage import db

VERSION_TTL = 15.0  # seconds a data version is trusted before it's read again
CACHE_CONTROL = "public, max-age=30"  # browsers revalidate with the ETag after this


def _code_version() -> str:
    """A hash of the package's code and SQL: the same on every replica of a deploy,
    different after any change to it."""
    root = Path(__file__).resolve().parent.parent
    h = hashlib.sha1()
    for f in sorted(root.rglob("*")):
        if f.suffix in (".py", ".sql"):
            h.update(f.relative_to(root).as_posix().encode())
            h.update(f.read_bytes())
    return h.hexdigest()[:12]


CODE_VERSION = _code_version()

_ready: set[str] = set()
_version_lock = threading.Lock()
_version: dict[str, Any] = {"where": None, "at": 0.0, "value": None}


def reset() -> None:
    """Forget everything cached (tests, `eb perf report`)."""
    results.clear()
    _ready.clear()
    with _version_lock:
        _version.update(where=None, at=0.0, value=None)


def _where() -> str:
    settings = get_settings()
    return settings.database_url or str(settings.db_path)


def connection() -> Iterator:
    """A read connection to the site's database. Before anything has been loaded (no
    database, or no schema yet) this raises 503."""
    settings = get_settings()
    where = _where()
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


def data_version(force: bool = False) -> str | None:
    """When the latest load finished; changes with every hourly update or rebuild."""
    where = _where()
    with _version_lock:
        fresh = _version["where"] == where and time.monotonic() - _version["at"] < VERSION_TTL
        if fresh and not force:
            return _version["value"]
    for con in connection():
        at = db.scalar(con, "SELECT max(loaded_at) FROM ingest_load")
    value = at.isoformat() if at else None
    with _version_lock:
        _version.update(where=where, at=time.monotonic(), value=value)
    return value


# --- Rows -----------------------------------------------------------------------


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


# --- Views and cached responses ----------------------------------------------------


@dataclass(frozen=True)
class View:
    name: str
    args: tuple
    compute: Callable[[Any], pl.DataFrame | list[dict]]  # given a connection
    model: Any  # the response model of one row


@dataclass(frozen=True)
class Payload:
    rows: list  # the validated rows, for code that needs the data itself
    body: bytes
    gzipped: bytes
    etag: str


_adapters: dict[Any, TypeAdapter] = {}


def _adapter(model) -> TypeAdapter:
    if model not in _adapters:
        _adapters[model] = TypeAdapter(list[model])
    return _adapters[model]


def payload(view: View) -> Payload:
    """The view's response for the current data version, computed at most once."""
    version = data_version()

    def build() -> Payload:
        for con in connection():
            out = view.compute(con)
        rows = records(out) if isinstance(out, pl.DataFrame) else out
        adapter = _adapter(view.model)
        checked = adapter.validate_python(rows)
        body = adapter.dump_json(checked)
        tag = hashlib.sha1(
            repr((CODE_VERSION, view.name, view.args, version)).encode()
        ).hexdigest()[:20]
        return Payload(checked, body, gzip.compress(body, compresslevel=6), f'W/"{tag}"')

    return results.get_or_compute((view.name, view.args, version), build)


def respond(request: Request, view: View) -> Response:
    """Send the view's cached bytes: 304 if the client has them, gzipped if it can."""
    p = payload(view)
    headers = {"ETag": p.etag, "Cache-Control": CACHE_CONTROL, "Vary": "Accept-Encoding"}
    if request.headers.get("if-none-match") == p.etag:
        return Response(status_code=304, headers=headers)
    if "gzip" in request.headers.get("accept-encoding", ""):
        headers["Content-Encoding"] = "gzip"
        return Response(p.gzipped, media_type="application/json", headers=headers)
    return Response(p.body, media_type="application/json", headers=headers)


class _Name(BaseModel):
    name: str


LEAGUE_NAMES = View(
    "league_names",
    (),
    lambda con: [{"name": r[0]} for r in db.rows(con, "SELECT name FROM league")],
    _Name,
)


def require_league(name: str) -> None:
    """404 for a league the site doesn't have (checked against a cached list)."""
    if name not in {row.name for row in payload(LEAGUE_NAMES).rows}:
        raise HTTPException(404, f"unknown league {name!r}")


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
