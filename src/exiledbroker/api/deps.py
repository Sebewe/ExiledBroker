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
    _stamped.clear()
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
        changed = _version["where"] == where and _version["value"] != value
        _version.update(where=where, at=time.monotonic(), value=value)
    if changed:
        # Results are keyed on the version, so the old one's are never asked for again.
        # Left to the LRU they'd be kept ~40 hours (256 entries, ~6 views an hour):
        # 140 MB more memory on the web service with the Farming page (hosting.md).
        results.keep_only(lambda key: key[-1] == value)
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
    compute: Callable[[Any], pl.DataFrame | list[dict] | dict]  # given a connection
    model: Any  # the response model of one row (of the whole response when `one`)
    # For a view that changes less often than the data (e.g. a report rebuilt locally):
    # a cheap query of what it depends on. While the stamp is unchanged, a new data
    # version reuses the cached response (and its ETag) instead of reading it again.
    stamp: Callable[[Any], Any] | None = None
    # A response that is one document (compute returns a dict), not a list of rows.
    one: bool = False


@dataclass(frozen=True)
class Payload:
    rows: list  # the validated rows (one item for a one-document view), for code that needs them
    body: bytes
    gzipped: bytes
    etag: str


_adapters: dict[Any, TypeAdapter] = {}


def _adapter(model, one: bool = False) -> TypeAdapter:
    if (model, one) not in _adapters:
        _adapters[(model, one)] = TypeAdapter(model if one else list[model])
    return _adapters[(model, one)]


def payload(view: View) -> Payload:
    """The view's response for the current data version, computed at most once."""
    version = data_version()

    def build() -> Payload:
        for con in connection():
            stamp = view.stamp(con) if view.stamp else None
            kept = _stamped.get((view.name, view.args)) if view.stamp else None
            if kept and kept[0] == stamp:
                return kept[1]
            out = view.compute(con)
        rows = records(out) if isinstance(out, pl.DataFrame) else out
        adapter = _adapter(view.model, view.one)
        checked = adapter.validate_python(rows)
        body = adapter.dump_json(checked)
        if view.one:
            checked = [checked]
        tagged = ("stamp", stamp) if view.stamp else version
        tag = hashlib.sha1(repr((CODE_VERSION, view.name, view.args, tagged)).encode()).hexdigest()[
            :20
        ]
        made = Payload(checked, body, gzip.compress(body, compresslevel=6), f'W/"{tag}"')
        if view.stamp:
            _stamped[(view.name, view.args)] = (stamp, made)
        return made

    return results.get_or_compute((view.name, view.args, version), build)


# Stamped views' latest responses, by view: (stamp, payload). One entry per view.
_stamped: dict[tuple, tuple[Any, Payload]] = {}


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


def now_utc() -> datetime:
    return datetime.now(UTC)
