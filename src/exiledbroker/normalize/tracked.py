"""Price mappings: the curated groups of items the demo tracks.

Groups are defined by item name so they work for every source (dumps, exchange).
Item ids for currency-like items are `currency:<slug of name>` everywhere.
"""

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from exiledbroker.normalize.leagues import slugify

CHAOS = "Chaos Orb"
DIVINE = "Divine Orb"
CHAOS_METADATA = "Metadata/Items/Currency/CurrencyRerollRare"
DIVINE_METADATA = "Metadata/Items/Currency/CurrencyModValues"

# Always currency, even before poe.ninja's currency list has been fetched.
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
    rule: Callable[[str, set[str]], bool]

    def matches(self, name: str, currency_names: set[str] = frozenset()) -> bool:
        return self.rule(name, currency_names)


GROUPS = [
    # poe.ninja's Currency category (minus Catalysts), see ingest/poe_ninja_categories.py.
    Group("currency", "Currency", 1, lambda n, cur: n in CORE_CURRENCY or n in cur),
    Group(
        "essence",
        "High-tier essences",
        2,
        lambda n, cur: n.startswith("Deafening Essence of ") or n in CORRUPTED_ESSENCES,
    ),
    Group("scarab", "Scarabs", 3, lambda n, cur: re.search(r"\bScarab\b", n) is not None),
]


def currency_item_id(name: str) -> str:
    return f"currency:{slugify(name)}"


def groups_for(name: str, currency_names: Iterable[str] = ()) -> list[Group]:
    cur = set(currency_names)
    return [g for g in GROUPS if g.matches(name, cur)]
