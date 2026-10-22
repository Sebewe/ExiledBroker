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

# poe.ninja exchange type per group, and categories within it that aren't the group.
SOURCES = {
    "currency": ("Currency", {"Catalysts"}),
    "essence": ("Essence", set()),
    "scarab": ("Scarab", set()),
}


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


def snapshot_key(group_id: str) -> str:
    return f"core_pool/{group_id}"


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
    for group_id in SOURCES:
        snap = reference.get(con, snapshot_key(group_id))
        if snap:
            pool.listed[group_id] = set(snap["names"])
            pool.league = snap["league"]
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
) -> CorePool:
    """Check the current league's lists and the loot filter's card tiers for changes.

    Each source is checked at most every `max_age` (0 = check now) with a conditional
    request: unchanged sources answer "304 Not Modified" and aren't downloaded."""
    base = f"{settings.poe_ninja_base_url}/poe1/api/economy"
    leagues = reference.fetch_if_changed(
        con, client, LEAGUES_KEY, f"{base}/leagues", json.loads, max_age
    ).value
    league = leagues[0]["id"]
    for group_id, (ninja_type, skip) in SOURCES.items():

        def parse(text: str, skip=skip) -> dict:
            items = json.loads(text).get("items", ())
            names = sorted(i["name"] for i in items if i.get("category") not in skip)
            return {"league": league, "names": names}

        reference.fetch_if_changed(
            con,
            client,
            snapshot_key(group_id),
            f"{base}/exchange/current/overview?league={league}&type={ninja_type}",
            parse,
            max_age,
        )
    refresh_card_tiers(client, settings, con, max_age)
    return load_pool(con, settings)


def refresh_pool_if_stale(
    client: PoliteClient,
    con: duckdb.DuckDBPyConnection,
    settings: Settings,
    max_age: timedelta = MAX_AGE,
) -> CorePool:
    """The pool, checking its sources at most once a day (`max_age`): it changes with
    leagues and loot-filter updates, not hourly."""
    return refresh_pool(client, con, settings, max_age)
