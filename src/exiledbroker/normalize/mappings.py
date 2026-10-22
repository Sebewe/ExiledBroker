"""Rebuild the curated mapping tables: tracked_item (price-mapping groups) and
divination_card. Both loaders call refresh_mappings at the end of a load, and
`eb exchange sync` calls it after refreshing the core pool."""

import json

import duckdb

from exiledbroker.config import Settings
from exiledbroker.ingest.core_pool import CorePool, load_pool
from exiledbroker.ingest.item_names import base_items_path
from exiledbroker.ingest.loot_filter import load_card_tiers
from exiledbroker.normalize.divination import cards_from_base_items
from exiledbroker.normalize.tracked import GROUPS
from exiledbroker.storage import db

TRACKED_COLUMNS = ("item_id", "group_id", "group_label", "sort_order")
CARD_COLUMNS = (
    "item_id",
    "name",
    "stack_size",
    "reward_kind",
    "reward_name",
    "reward_quantity",
    "reward_item_id",
    "reward_text",
    "filter_tier",
    "followed",
    "reward_fixed",
)


def _sync_rows(
    con: duckdb.DuckDBPyConnection, table: str, columns: tuple[str, ...], key: int, rows: list
) -> tuple[int, int]:
    """Make `table` hold exactly `rows`, changing only the rows that differ.

    `key` is how many leading columns form the primary key. Returns (written, deleted)."""
    existing = set(db.rows(con, f"SELECT {', '.join(columns)} FROM {table}"))
    wanted = set(rows)
    stale = existing - wanted
    fresh = wanted - existing
    key_cols = columns[:key]
    if stale:
        where = " AND ".join(f"{c} = ?" for c in key_cols)
        con.executemany(f"DELETE FROM {table} WHERE {where}", [r[:key] for r in stale])
    if fresh:
        marks = ", ".join("?" for _ in columns)
        con.executemany(
            f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({marks})",
            # A changed row was deleted above (same key), so this never conflicts.
            sorted(fresh, key=str),
        )
    return len(fresh), len(stale)


def refresh_tracked(con: duckdb.DuckDBPyConnection, pool: CorePool | None = None) -> int:
    """Update tracked_item to every known item that fits a group and is in the core
    pool, changing only rows that differ. Returns the number of tracked rows."""
    rows = [
        (item_id, g.id, g.label, g.order)
        for item_id, name in db.rows(
            con, "SELECT id, canonical_name FROM item WHERE id LIKE 'currency:%'"
        )
        for g in GROUPS
        if g.matches(name, pool)
    ]
    _sync_rows(con, "tracked_item", TRACKED_COLUMNS, 2, rows)
    return len(rows)


def refresh_cards(con: duckdb.DuckDBPyConnection, settings: Settings, pool: CorePool) -> int:
    """Update divination_card from RePoE (rewards) and the loot filter (tiers), changing
    only rows that differ."""
    if not base_items_path(settings).exists():
        return 0
    raw = json.loads(base_items_path(settings).read_text())
    cards = cards_from_base_items(raw)
    tiers = (load_card_tiers(settings) or {}).get("tiers", {})
    rows = [
        (
            c.item_id,
            c.name,
            c.stack_size,
            c.reward_kind,
            c.reward_name,
            c.reward_quantity,
            c.reward_item_id,
            c.reward_text,
            tiers.get(c.name),
            bool(pool.allows("divination", c.name)),
            c.reward_fixed,
        )
        for c in cards
    ]
    _sync_rows(con, "divination_card", CARD_COLUMNS, 1, rows)
    return len(rows)


def refresh_mappings(con: duckdb.DuckDBPyConnection, settings: Settings) -> CorePool:
    pool = load_pool(settings)
    refresh_tracked(con, pool)
    refresh_cards(con, settings, pool)
    return pool
