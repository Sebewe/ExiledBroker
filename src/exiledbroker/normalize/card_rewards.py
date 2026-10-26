"""What a divination card's random reward can roll: the pools in config/card_rewards.toml,
resolved against item names into `card_reward_pool` on each load (docs/findings.md 12).

The Market recap prices a random-reward card at its floor, the cheapest item its reward
can roll (services/divination.hourly_floor_turn_ins); the research tool
(analysis/card_ev.py) reads the same pools."""

import re
import tomllib
from pathlib import Path

ALL_CARDS = "*cards*"  # the pool token for "any divination card"
COLUMNS = ("reward_name", "item_id")


def load_pools(path: Path) -> dict[str, list[str]]:
    """{reward name: [LIKE patterns on item.canonical_name]}; empty if the file is missing."""
    if not path.exists():
        return {}
    with path.open("rb") as f:
        return {name: list(spec["like"]) for name, spec in tomllib.load(f)["pool"].items()}


def _like(pattern: str) -> re.Pattern:
    """SQL LIKE as a regex: % any run of characters, _ one character, case-sensitive."""
    parts = (".*" if c == "%" else "." if c == "_" else re.escape(c) for c in pattern)
    return re.compile("".join(parts), re.DOTALL)


def pool_rows(pools: dict[str, list[str]], items: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """(reward name, item id) for each currency-like item (id, name) a pool's patterns
    match. The any-card pool (The Gambler) is left out: hundreds of rows for a floor that
    lost 90%+ in every league, and no hour has most cards traded at once."""
    out = []
    for reward, patterns in pools.items():
        if ALL_CARDS in patterns:
            continue
        rx = [_like(p) for p in patterns]
        out += [
            (reward, item_id)
            for item_id, name in items
            if item_id.startswith("currency:") and any(r.fullmatch(name) for r in rx)
        ]
    return sorted(set(out))
