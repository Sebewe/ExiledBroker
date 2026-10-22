"""Price mappings: the curated groups of items the demo tracks.

Groups are defined by item name so they work for every source (dumps, exchange).
Item ids for currency-like items are `currency:<slug of name>` everywhere.
"""

import re
from dataclasses import dataclass

from exiledbroker.normalize.leagues import slugify

CHAOS = "Chaos Orb"
DIVINE = "Divine Orb"
CHAOS_METADATA = "Metadata/Items/Currency/CurrencyRerollRare"
DIVINE_METADATA = "Metadata/Items/Currency/CurrencyModValues"

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

    def matches(self, name: str) -> bool:
        return GROUP_RULES[self.id](name)


GROUP_RULES = {
    "chaos": lambda n: n == CHAOS,
    "divine": lambda n: n == DIVINE,
    "alchemy": lambda n: n == "Orb of Alchemy",
    "mirror": lambda n: n in ("Mirror of Kalandra", "Mirror Shard"),
    "essence": lambda n: n.startswith("Deafening Essence of ") or n in CORRUPTED_ESSENCES,
    "scarab": lambda n: re.search(r"\bScarab\b", n) is not None,
}
GROUPS = [
    Group("chaos", "Chaos Orb", 1),
    Group("divine", "Divine Orb", 2),
    Group("alchemy", "Orb of Alchemy", 3),
    Group("mirror", "Mirrors", 4),
    Group("essence", "High-tier essences", 5),
    Group("scarab", "Scarabs", 6),
]


def currency_item_id(name: str) -> str:
    return f"currency:{slugify(name)}"


def groups_for(name: str) -> list[Group]:
    return [g for g in GROUPS if g.matches(name)]
