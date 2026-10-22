"""Price mappings: the curated groups of items the demo tracks.

Groups are defined by item name so they work for every source (dumps, exchange).
Item ids for currency-like items are `currency:<slug of name>` everywhere. Every
group is also limited to the core drop pool (see ingest/core_pool.py).
"""

import re
from collections.abc import Callable
from dataclasses import dataclass

from exiledbroker.ingest.core_pool import CorePool
from exiledbroker.normalize.leagues import slugify

CHAOS = "Chaos Orb"
DIVINE = "Divine Orb"
CHAOS_METADATA = "Metadata/Items/Currency/CurrencyRerollRare"
DIVINE_METADATA = "Metadata/Items/Currency/CurrencyModValues"

# Shown even before the core pool has been fetched (they're always core).
CORE_CURRENCY = {CHAOS, DIVINE, "Orb of Alchemy", "Mirror of Kalandra", "Mirror Shard"}

# Essences that only come from corrupting (Remnant of Corruption); top tier with Deafening.
CORRUPTED_ESSENCES = {
    "Essence of Hysteria",
    "Essence of Insanity",
    "Essence of Horror",
    "Essence of Delirium",
}


@dataclass(frozen=True)
class Group:
    id: str
    label: str
    order: int
    rule: Callable[[str], bool]  # does the name belong to this group at all?
    fallback: Callable[[str], bool]  # used only when there's no pool snapshot yet

    def matches(self, name: str, pool: CorePool | None = None) -> bool:
        if not self.rule(name):
            return False
        allowed = pool.allows(self.id, name) if pool else None
        return self.fallback(name) if allowed is None else allowed


def _high_tier_essence(name: str) -> bool:
    return name.startswith("Deafening Essence of ") or name in CORRUPTED_ESSENCES


def _scarab(name: str) -> bool:
    return re.search(r"\bScarab\b", name) is not None


GROUPS = [
    # Membership comes from the pool (poe.ninja's Currency list); without one, only the core five.
    Group("currency", "Currency", 1, rule=lambda n: True, fallback=lambda n: n in CORE_CURRENCY),
    Group("essence", "High-tier essences", 2, rule=_high_tier_essence, fallback=lambda n: True),
    Group("scarab", "Scarabs", 3, rule=_scarab, fallback=lambda n: True),
    # Cards the loot filter shows; without the filter's tiers we follow none.
    Group("divination", "Divination cards", 4, rule=lambda n: True, fallback=lambda n: False),
]


def currency_item_id(name: str) -> str:
    return f"currency:{slugify(name)}"


def groups_for(name: str, pool: CorePool | None = None) -> list[Group]:
    return [g for g in GROUPS if g.matches(name, pool)]
