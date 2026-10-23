"""Map GGG metadata ids (as used by the currency exchange) to item names via RePoE.

RePoE's base item table is kept, trimmed to the fields we use, in the database
(reference_data). It's checked for changes about once a week with a conditional
request, so it's only downloaded again when RePoE has actually changed."""

import json
from dataclasses import dataclass
from datetime import timedelta

import duckdb

from exiledbroker.config import Settings
from exiledbroker.ingest import reference
from exiledbroker.ingest.http import PoliteClient

KEY = "repoe/base_items"
MAX_AGE = timedelta(days=7)
# While the exchange trades items RePoE doesn't know (a new league's first days).
UNKNOWN_MAX_AGE = timedelta(days=1)


@dataclass(frozen=True)
class BaseItem:
    metadata_id: str
    name: str
    item_class: str
    stackable: bool = False  # has a stack size: the kind of item the exchange trades


def _trim(raw: dict) -> dict:
    """Keep only what we use: names, classes, and card set sizes/rewards (~1/5 the size)."""
    out = {}
    for mid, item in raw.items():
        if not item.get("name"):
            continue
        props = item.get("properties") or {}
        out[mid] = {
            "name": item["name"],
            "item_class": item.get("item_class", ""),
            "release_state": item.get("release_state"),
            "properties": {k: props[k] for k in ("description", "stack_size") if k in props},
        }
    return out


def ensure_base_items(
    client: PoliteClient,
    settings: Settings,
    con: duckdb.DuckDBPyConnection,
    max_age: timedelta = MAX_AGE,
) -> str:
    """Make sure RePoE's base item table is stored. Checked at most every `max_age`,
    and only downloaded if it's missing or changed. Returns the fetch state."""
    return reference.fetch_if_changed(
        con,
        client,
        KEY,
        settings.repoe_base_items_url,
        parse=lambda text: _trim(json.loads(text)),
        max_age=max_age,
    ).state


def base_items_raw(con: duckdb.DuckDBPyConnection) -> dict | None:
    """The stored (trimmed) RePoE table, or None if it hasn't been fetched yet."""
    return reference.get(con, KEY)


def load_base_items(con: duckdb.DuckDBPyConnection) -> dict[str, BaseItem]:
    raw = base_items_raw(con)
    if raw is None:
        raise LookupError("RePoE item names aren't loaded yet; run `eb exchange sync`")
    return {
        k: BaseItem(
            k,
            v["name"],
            v.get("item_class", ""),
            "stack_size" in (v.get("properties") or {}),
        )
        for k, v in raw.items()
    }
