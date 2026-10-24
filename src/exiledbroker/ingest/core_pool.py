"""The core drop pool: which items are currently obtainable, per price-mapping group.

The automatic part comes from poe.ninja's exchange overview for the *current* league,
one snapshot per type, replaced (not merged) on every refresh, so items that leave
the game or whose league mechanic didn't go core drop out. The manual part is
config/core_pool.toml: `exclude` and `include` lists of exact item names.
"""

import json
import tomllib
from dataclasses import dataclass, field
from datetime import timedelta

import duckdb

from exiledbroker.config import Settings
from exiledbroker.ingest import reference
from exiledbroker.ingest.http import PoliteClient
from exiledbroker.ingest.loot_filter import load_card_tiers, refresh_card_tiers

# poe.ninja exchange types per group. Catalysts (in the Currency list), fragments and
# oils trade on the exchange like any currency, so they're grouped with it.
SOURCES = {
    "currency": ("Currency", "Fragment", "Oil"),
    "essence": ("Essence",),
    "scarab": ("Scarab",),
    # The Farming page's mechanic outputs (config/mechanics.toml); no price-mapping
    # group reads these, so they don't change what the other pages show.
    "mechanics": (
        "AllflameEmber",
        "Artifact",
        "Astrolabe",
        "DeliriumOrb",
        "EnshroudingCrystal",
        "Fossil",
        "Omen",
        "Resonator",
        "Runegraft",
        "Tattoo",
    ),
}
# Snapshot keys from before snapshots were per poe.ninja type (one per group, with
# Catalysts left out of currency). Deleted on refresh so a stale list can't be read.
LEGACY_KEYS = tuple(f"core_pool/{group_id}" for group_id in ("currency", "essence", "scarab"))


@dataclass
class CorePool:
    listed: dict[str, set[str]] = field(default_factory=dict)  # group -> names on poe.ninja
    exclude: set[str] = field(default_factory=set)  # never shown, any group
    include: dict[str, set[str]] = field(default_factory=dict)  # group -> always shown
    league: str | None = None

    def allows(self, group_id: str, name: str) -> bool | None:
        """True/False when the pool decides; None when there's no snapshot for the group."""
        if name in self.exclude:
            return False
        if name in self.include.get(group_id, ()):
            return True
        if group_id not in self.listed:
            return None
        return name in self.listed[group_id]


MAX_AGE = timedelta(days=1)
LEAGUES_KEY = "poe_ninja/leagues"


def snapshot_key(ninja_type: str) -> str:
    return f"core_pool/type/{ninja_type}"


def load_overrides(settings: Settings) -> tuple[set[str], dict[str, set[str]]]:
    path = settings.core_pool_file
    if not path.exists():
        return set(), {}
    with open(path, "rb") as f:
        raw = tomllib.load(f)
    include = raw.get("include", {})
    if not isinstance(include, dict):
        raise TypeError(f"{path}: [include] must list names per group, e.g. currency = [...]")
    return set(raw.get("exclude", [])), {g: set(names) for g, names in include.items()}


def load_pool(con: duckdb.DuckDBPyConnection, settings: Settings) -> CorePool:
    """The pool from the stored snapshots (reference_data) plus config/core_pool.toml."""
    exclude, include = load_overrides(settings)
    pool = CorePool(exclude=exclude, include=include)
    for group_id, ninja_types in SOURCES.items():
        snaps = [reference.get(con, snapshot_key(t)) for t in ninja_types]
        if all(snaps):  # a group is decided only once all its lists are in
            pool.listed[group_id] = {n for snap in snaps for n in snap["names"]}
            pool.league = snaps[0]["league"]
    # Divination cards: the ones NeverSink's filter shows (FilterBlade's tiers).
    tiers = load_card_tiers(con)
    if tiers:
        pool.listed["divination"] = set(tiers["shown"])
    return pool


def refresh_pool(
    client: PoliteClient,
    con: duckdb.DuckDBPyConnection,
    settings: Settings,
    max_age: timedelta = timedelta(0),
    league: str | None = None,
) -> CorePool:
    """Check a league's lists (default: poe.ninja's current league, its first listed)
    and the loot filter's card tiers for changes.

    Each source is checked at most every `max_age` (0 = check now) with a conditional
    request: unchanged sources answer "304 Not Modified" and aren't downloaded. A
    `league` poe.ninja doesn't list (one that ended, or one so new poe.ninja hasn't
    added it yet) keeps the stored lists: the pool never comes from another league,
    such as Standard in the days between leagues."""
    base = f"{settings.poe_ninja_base_url}/poe1/api/economy"
    leagues = reference.fetch_if_changed(
        con, client, LEAGUES_KEY, f"{base}/leagues", json.loads, max_age
    ).value
    listed = [lg["id"] for lg in leagues]
    league = league or listed[0]

    def parse(text: str) -> dict:
        items = json.loads(text).get("items", ())
        return {"league": league, "names": sorted(i["name"] for i in items)}

    for ninja_type in sorted({t for types in SOURCES.values() for t in types}):
        if league not in listed:
            break
        reference.fetch_if_changed(
            con,
            client,
            snapshot_key(ninja_type),
            f"{base}/exchange/current/overview?league={league}&type={ninja_type}",
            parse,
            max_age,
        )
    con.execute(
        f"DELETE FROM reference_data WHERE key IN ({', '.join('?' for _ in LEGACY_KEYS)})",
        list(LEGACY_KEYS),
    )
    refresh_card_tiers(client, settings, con, max_age)
    return load_pool(con, settings)


def refresh_pool_if_stale(
    client: PoliteClient,
    con: duckdb.DuckDBPyConnection,
    settings: Settings,
    max_age: timedelta = MAX_AGE,
    league: str | None = None,
) -> CorePool:
    """The pool, checking its sources at most once a day (`max_age`): it changes with
    leagues and loot-filter updates, not hourly."""
    return refresh_pool(client, con, settings, max_age, league)
