"""Divination card rewards: what a full set of each card turns into.

RePoE's card descriptions look like `<currencyitem>{10x Exalted Orb}`,
`<uniqueitem>{Headhunter}` or `<gemitem>{Level 21 Spell Gem}\\r\\n<corrupted>{Corrupted}`,
sometimes wrapped in `<size:31>{...}`.
"""

import re
from collections import Counter
from dataclasses import dataclass

from exiledbroker.normalize.tracked import currency_item_id

KINDS = {
    "currencyitem": "currency",
    "divination": "divination",
    "uniqueitem": "unique",
    "gemitem": "gem",
    "rareitem": "rare",
    "magicitem": "magic",
    "whiteitem": "normal",
    "normal": "normal",
}
# Rewards that trade on the exchange, so a set's value can be priced directly.
EXCHANGE_PRICED = {"currency", "divination"}
TAG = re.compile(r"<(\w+)>\{([^{}]*)\}")
QUANTITY = re.compile(r"^([\d,]+)x (.+)$")


@dataclass(frozen=True)
class Card:
    item_id: str
    name: str
    stack_size: int | None
    reward_kind: str | None
    reward_name: str | None
    reward_quantity: int | None
    reward_item_id: str | None
    reward_text: str
    # One specific item (True) or random, like "5x Currency" (False). Only decided for
    # rewards priced on the exchange; None for others (e.g. uniques) until their
    # expected value is modelled.
    reward_fixed: bool | None


def parse_reward(description: str) -> tuple[str | None, str | None, int | None]:
    """(kind, name, quantity) of a card's reward, or Nones for disabled cards."""
    text = re.sub(r"<size:\d+>\{", "", description or "")
    m = TAG.search(text)
    if not m:
        return None, None, None
    kind = KINDS.get(m.group(1), "other")
    name, quantity = m.group(2).strip(), 1
    if q := QUANTITY.match(name):
        quantity, name = int(q.group(1).replace(",", "")), q.group(2)
    return kind, name, quantity


def cards_from_base_items(raw: dict[str, dict]) -> list[Card]:
    """Every released card in RePoE's base item table (the raw JSON).

    A currency or card reward is *fixed* when its name is exactly one item in the table
    (e.g. "Exalted Orb"). Generic names ("Currency", "Essence", "Delirium Orb",
    "Divination Card") are random rewards: they need an expected value over what they
    can roll, not a price. Other kinds (uniques, gems, ...) aren't classified yet,
    because the base item table doesn't list uniques.
    """
    counts = Counter(v.get("name") for v in raw.values() if v.get("release_state") == "released")
    cards = []
    for item in raw.values():
        if item.get("item_class") != "DivinationCard" or item.get("release_state") != "released":
            continue
        props = item.get("properties", {})
        kind, reward, quantity = parse_reward(props.get("description", ""))
        fixed = counts[reward] == 1 if kind in EXCHANGE_PRICED else None
        reward_id = currency_item_id(reward) if fixed else None
        cards.append(
            Card(
                item_id=currency_item_id(item["name"]),
                name=item["name"],
                stack_size=props.get("stack_size"),
                reward_kind=kind,
                reward_name=reward,
                reward_quantity=quantity,
                reward_item_id=reward_id,
                reward_text=(props.get("description") or "").replace("\r\n", " / "),
                reward_fixed=fixed,
            )
        )
    return cards
