"""The core drop pool: which items are currently obtainable, per price-mapping group.

The automatic part comes from poe.ninja's exchange overview for the *current* league,
one snapshot per type, replaced (not merged) on every refresh, so items that leave
the game or whose league mechanic didn't go core drop out. The manual part is
config/core_pool.toml: `exclude` and `include` lists of exact item names.
"""

import tomllib
from dataclasses import dataclass, field
from datetime import UTC, datetime

from exiledbroker.config import Settings
from exiledbroker.ingest.files import read_json, write_json_atomic
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


def snapshot_path(settings: Settings, group_id: str):
    return settings.raw_dir / "poe_ninja" / "core_pool" / f"{group_id}.json"


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


def load_pool(settings: Settings) -> CorePool:
    exclude, include = load_overrides(settings)
    pool = CorePool(exclude=exclude, include=include)
    for group_id in SOURCES:
        snap = read_json(snapshot_path(settings, group_id))
        if snap:
            pool.listed[group_id] = set(snap["names"])
            pool.league = snap["league"]
    # Divination cards: the ones NeverSink's filter shows (FilterBlade's tiers).
    tiers = load_card_tiers(settings)
    if tiers:
        pool.listed["divination"] = set(tiers["shown"])
    return pool


def refresh_pool(client: PoliteClient, settings: Settings) -> CorePool:
    """Re-fetch the current league's lists (one request for the league, one per group)
    and the loot filter's card tiers."""
    base = f"{settings.poe_ninja_base_url}/poe1/api/economy"
    league = client.get_json(f"{base}/leagues")[0]["id"]
    for group_id, (ninja_type, skip) in SOURCES.items():
        overview = client.get_json(
            f"{base}/exchange/current/overview?league={league}&type={ninja_type}"
        )
        names = sorted(
            i["name"] for i in overview.get("items", ()) if i.get("category") not in skip
        )
        write_json_atomic(
            snapshot_path(settings, group_id),
            {"league": league, "fetched_at": datetime.now(UTC).isoformat(), "names": names},
        )
    refresh_card_tiers(client, settings)
    return load_pool(settings)
