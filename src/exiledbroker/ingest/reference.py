"""Reference data kept in the database (table reference_data): small JSON documents
the pipeline needs on every run (RePoE item names, core-pool lists, loot-filter tiers).

Nothing we already have is downloaded again. Each document keeps the version tag
(ETag / Last-Modified) of the response it came from. When a check is due, the
request sends that tag back, and an unchanged source answers "304 Not Modified"
with no body. Checks also aren't made more often than `max_age`.

Callers pass the connection they already hold, so a check can happen inside a load's
transaction."""

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import duckdb

from exiledbroker.ingest.http import PoliteClient
from exiledbroker.storage import db


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


@dataclass
class Fetch:
    state: str  # "skipped" (checked recently) | "unchanged" (304) | "downloaded"
    # The document, read from the database only when asked for (RePoE's is ~1 MB, and
    # the hourly check only needs `state`). Read it while the connection is open.
    _load: Callable[[], Any]

    @property
    def value(self) -> Any:
        return self._load()


# Documents already read by this process, by key and the content's MD5. A pass reads
# RePoE's (~1 MB) from several places; the hash, computed by the database, is all
# that crosses the network after the first read.
_texts: dict[tuple[str, str], str] = {}


def get(con: duckdb.DuckDBPyConnection, key: str) -> Any | None:
    site = db.pushdown(con)
    digest = db.rows(site, "SELECT md5(content) FROM reference_data WHERE key = ?", [key])
    if not digest:
        return None
    cached = (key, digest[0][0])
    if cached not in _texts:
        text = db.scalar(site, "SELECT content FROM reference_data WHERE key = ?", [key])
        if len(_texts) > 32:  # a long-running process: old versions pile up
            _texts.clear()
        _texts[cached] = text
    return json.loads(_texts[cached])


def checked_at(con: duckdb.DuckDBPyConnection, key: str) -> datetime | None:
    """When the source was last checked (whether or not it had changed)."""
    rows = db.rows(
        con, "SELECT coalesce(checked_at, fetched_at) FROM reference_data WHERE key = ?", [key]
    )
    return rows[0][0] if rows else None


def is_fresh(con: duckdb.DuckDBPyConnection, key: str, max_age: timedelta) -> bool:
    at = checked_at(con, key)
    return at is not None and _now() - at < max_age


def put(
    con: duckdb.DuckDBPyConnection,
    key: str,
    value: Any,
    source_url: str | None = None,
    etag: str | None = None,
    last_modified: str | None = None,
) -> None:
    now = _now()
    con.execute(
        """
        INSERT INTO reference_data
            (key, fetched_at, content, source_url, etag, last_modified, checked_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (key) DO UPDATE SET fetched_at = excluded.fetched_at,
            content = excluded.content, source_url = excluded.source_url,
            etag = excluded.etag, last_modified = excluded.last_modified,
            checked_at = excluded.checked_at
        """,
        [key, now, json.dumps(value, sort_keys=True), source_url, etag, last_modified, now],
    )


def fetch_if_changed(
    con: duckdb.DuckDBPyConnection,
    client: PoliteClient,
    key: str,
    url: str,
    parse: Callable[[str], Any],
    max_age: timedelta,
) -> Fetch:
    """The document at `url`, downloaded only if we don't have it or it changed.

    - Checked less than `max_age` ago: no request at all.
    - Otherwise a conditional request with our version tag. "304 Not Modified" means
      we keep the stored copy and only record the check; a changed source (or a
      different URL, e.g. a new league) is downloaded, parsed and stored."""
    rows = db.rows(
        con,
        "SELECT NULL, source_url, etag, last_modified, coalesce(checked_at, fetched_at) "
        "FROM reference_data WHERE key = ?",
        [key],
    )
    have = rows[0] if rows else None
    same_source = have is not None and have[1] == url
    stored = lambda: get(con, key)
    if same_source and have[4] is not None and _now() - have[4] < max_age:
        return Fetch("skipped", stored)
    response = client.get_if_changed(
        url, etag=have[2] if same_source else None, last_modified=have[3] if same_source else None
    )
    if response is None:  # 304: unchanged, nothing downloaded
        con.execute("UPDATE reference_data SET checked_at = ? WHERE key = ?", [_now(), key])
        return Fetch("unchanged", stored)
    value = parse(response.text)
    put(
        con,
        key,
        value,
        source_url=url,
        etag=response.headers.get("ETag"),
        last_modified=response.headers.get("Last-Modified"),
    )
    return Fetch("downloaded", lambda: value)
