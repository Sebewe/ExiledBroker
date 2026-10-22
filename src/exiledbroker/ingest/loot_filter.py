"""Divination card tiers from NeverSink's loot filter (what FilterBlade serves).

Most cards are worthless and hidden by every common filter. We follow only the cards
the filter shows, at the configured strictness. The filter's card section is a list
of blocks like:

    Show # %HS6 $type->divination $tier->t3
        Class == "Divination Cards"
        BaseType == "A Fate Worse Than Death" "A Modest Request" ...

`Hide` blocks (tier t5) are the cards nobody picks up.
"""

import re
from datetime import UTC, datetime

from exiledbroker.config import Settings
from exiledbroker.ingest.files import read_json, write_json_atomic
from exiledbroker.ingest.http import PoliteClient

BLOCK = re.compile(
    r"^(Show|Hide)\b[^\n]*\$type->divination \$tier->(\w+)\n((?:[ \t]+[^\n]*\n)*)", re.MULTILINE
)


def parse_card_tiers(filter_text: str) -> dict[str, tuple[str, bool]]:
    """{card name: (tier, shown)} from a NeverSink filter."""
    filter_text = filter_text.replace("\r\n", "\n")  # the published files use CRLF
    tiers = {}
    for action, tier, body in BLOCK.findall(filter_text):
        # Stack-size rules (e.g. "show 3+ of this card") aren't the card's tier.
        if 'Class == "Divination Cards"' not in body or "StackSize" in body:
            continue
        m = re.search(r"BaseType == (.*)", body)
        for name in re.findall(r'"([^"]+)"', m.group(1)) if m else ():
            # A card listed in several tier blocks keeps the first.
            tiers.setdefault(name, (tier, action == "Show"))
    if not tiers:
        raise ValueError("no divination card tiers found; has the filter format changed?")
    return tiers


def tiers_path(settings: Settings):
    return settings.raw_dir / "neversink" / "divination_tiers.json"


def refresh_card_tiers(client: PoliteClient, settings: Settings) -> dict:
    url = settings.loot_filter_url.format(strictness=settings.loot_filter_strictness)
    tiers = parse_card_tiers(client.get_text(url))
    snapshot = {
        "strictness": settings.loot_filter_strictness,
        "fetched_at": datetime.now(UTC).isoformat(),
        "tiers": {name: tier for name, (tier, _) in sorted(tiers.items())},
        "shown": sorted(name for name, (_, shown) in tiers.items() if shown),
    }
    write_json_atomic(tiers_path(settings), snapshot)
    return snapshot


def load_card_tiers(settings: Settings) -> dict | None:
    return read_json(tiers_path(settings))
