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


def refresh_tracked(con: duckdb.DuckDBPyConnection, pool: CorePool | None = None) -> int:
    """Rebuild tracked_item: every known item that fits a group and is in the core pool."""
    rows = [
        (item_id, g.id, g.label, g.order)
        for item_id, name in db.rows(
            con, "SELECT id, canonical_name FROM item WHERE id LIKE 'currency:%'"
        )
        for g in GROUPS
        if g.matches(name, pool)
    ]
    con.execute("DELETE FROM tracked_item")
    if rows:
        con.executemany("INSERT INTO tracked_item VALUES (?, ?, ?, ?)", rows)
    return len(rows)


def refresh_cards(con: duckdb.DuckDBPyConnection, settings: Settings, pool: CorePool) -> int:
    """Rebuild divination_card from RePoE (rewards) and the loot filter (tiers)."""
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
    con.execute("DELETE FROM divination_card")
    con.executemany(
        """
        INSERT INTO divination_card (item_id, name, stack_size, reward_kind, reward_name,
            reward_quantity, reward_item_id, reward_text, filter_tier, followed, reward_fixed)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    return len(rows)


def refresh_mappings(con: duckdb.DuckDBPyConnection, settings: Settings) -> CorePool:
    pool = load_pool(settings)
    refresh_tracked(con, pool)
    refresh_cards(con, settings, pool)
    return pool
