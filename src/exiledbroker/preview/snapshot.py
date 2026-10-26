"""The preview's snapshot: one gzipped JSON document per key in `preview_snapshot`.

The builder (`eb preview build`) writes every key, the seed copies the table to the
site, and /api/preview/{key} sends a document as stored (api/routes/preview.py). The
keys are fixed, so the route is bounded: it answers only keys the table holds.

    manifest                      PreviewManifest: the league, its days, the version
    d{day}/missed                 list[MissedWindow]: the Market recap on that day
    d{day}/price-check            PriceCheckIndex: Price check's list on that day
    d{day}/price-check/{item_id}  PriceCheckItem: one item on that day
    d{day}/launch-picks           list[LaunchWindow]: the Launch market on that day
    d{day}/recap-next             PreviewRecapNext: did the recap's trades keep paying
    next/price-check/{item_id}    PreviewItemNext: the item's series to day 10

`day` is the launch day (1-based): the site as it stood at the end of that day. Every
document is checked against its model when it's written, so the route never has to."""

import gzip
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import TypeAdapter

from exiledbroker.api import models as m
from exiledbroker.storage import db

TABLE = "preview_snapshot"
DAYS = (1, 3, 5, 7)  # the days the preview offers (decided 2026-10-26)
DEFAULT_DAY = 5
NEXT_DAYS = 10  # next/price-check series run to the end of this day
MANIFEST = "manifest"

_DAY = r"d(?P<day>[1-9][0-9]?)"
_ITEM = r"(?P<item>[A-Za-z0-9][A-Za-z0-9:._-]{0,119})"  # item ids: currency:<slug>, ninja:<id>
KINDS: list[tuple[re.Pattern, Any]] = [
    (re.compile(MANIFEST), m.PreviewManifest),
    (re.compile(rf"{_DAY}/missed"), list[m.MissedWindow]),
    (re.compile(rf"{_DAY}/price-check"), m.PriceCheckIndex),
    (re.compile(rf"{_DAY}/price-check/{_ITEM}"), m.PriceCheckItem),
    (re.compile(rf"{_DAY}/launch-picks"), list[m.LaunchWindow]),
    (re.compile(rf"{_DAY}/recap-next"), m.PreviewRecapNext),
    (re.compile(rf"next/price-check/{_ITEM}"), m.PreviewItemNext),
]
MAX_KEY = 160

_adapters: dict[Any, TypeAdapter] = {}


def day_key(day: int, what: str, item_id: str | None = None) -> str:
    """`d{day}/{what}` (missed, price-check, launch-picks, recap-next), or an item's."""
    return f"d{day}/{what}" + (f"/{item_id}" if item_id else "")


def next_key(item_id: str) -> str:
    return f"next/price-check/{item_id}"


def model_for(key: str):
    """The response model of a key's document, or None for a key that isn't one."""
    if len(key) > MAX_KEY:
        return None
    for pattern, model in KINDS:
        if pattern.fullmatch(key):
            return model
    return None


def _adapter(model) -> TypeAdapter:
    if model not in _adapters:
        _adapters[model] = TypeAdapter(model)
    return _adapters[model]


def encode(key: str, doc: Any) -> bytes:
    """The stored body: the document checked against its key's model, as gzipped JSON
    (no timestamp in the gzip header, so the same document is the same bytes)."""
    model = model_for(key)
    if model is None:
        raise ValueError(f"{key!r} isn't a preview key")
    adapter = _adapter(model)
    return gzip.compress(adapter.dump_json(adapter.validate_python(doc)), mtime=0)


def decode(body: bytes) -> Any:
    return json.loads(gzip.decompress(bytes(body)))


def has_table(con) -> bool:
    """Whether the database has the table (a site database seeded before it existed
    doesn't, until the schema runs again)."""
    q = "SELECT count(*) FROM information_schema.tables WHERE table_name = ?"
    return bool(db.scalar(con, q, [TABLE]))


def put(con, docs: dict[str, Any], built_at: datetime | None = None) -> int:
    """Write documents by key (replacing any already there); returns how many."""
    built_at = (built_at or datetime.now(UTC)).astimezone(UTC).replace(tzinfo=None)
    for key, doc in docs.items():
        db.execute(
            con,
            f"INSERT INTO {TABLE} (key, built_at, body) VALUES (?, ?, ?) "
            "ON CONFLICT (key) DO UPDATE SET built_at = excluded.built_at, body = excluded.body",
            [key, built_at, encode(key, doc)],
        )
    return len(docs)


def clear(con) -> None:
    """Empty the snapshot (before a new build, so no key of the old one lingers)."""
    db.execute(con, f"DELETE FROM {TABLE}")


def keys(con) -> set[str]:
    if not has_table(con):
        return set()
    return {r[0] for r in db.rows(con, f"SELECT key FROM {TABLE}")}


def body(con, key: str) -> bytes | None:
    """A key's stored body (gzipped JSON), or None."""
    if not has_table(con):
        return None
    found = db.rows(con, f"SELECT body FROM {TABLE} WHERE key = ?", [key])
    return bytes(found[0][0]) if found else None


def read(con, key: str) -> Any:
    """A key's document, parsed, or None."""
    stored = body(con, key)
    return decode(stored) if stored is not None else None


def load_file(con, path: Path) -> int:
    """Write a snapshot saved as one JSON object of documents by key (the sample in
    tests/fixtures/preview_sample.json), replacing the table's contents."""
    docs = json.loads(Path(path).read_text())
    clear(con)
    return put(con, docs)
