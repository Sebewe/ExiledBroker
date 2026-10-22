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
from datetime import timedelta

import duckdb

from exiledbroker.config import Settings
from exiledbroker.ingest import reference
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


KEY = "neversink/divination_tiers"


def _snapshot(filter_text: str, strictness: str) -> dict:
    tiers = parse_card_tiers(filter_text)
    return {
        "strictness": strictness,
        "tiers": {name: tier for name, (tier, _) in sorted(tiers.items())},
        "shown": sorted(name for name, (_, shown) in tiers.items() if shown),
    }


def refresh_card_tiers(
    client: PoliteClient,
    settings: Settings,
    con: duckdb.DuckDBPyConnection,
    max_age: timedelta = timedelta(0),
) -> dict:
    """The filter's card tiers, downloaded only if the filter file changed (conditional
    request) and checked at most every `max_age`."""
    url = settings.loot_filter_url.format(strictness=settings.loot_filter_strictness)
    return reference.fetch_if_changed(
        con,
        client,
        KEY,
        url,
        parse=lambda text: _snapshot(text, settings.loot_filter_strictness),
        max_age=max_age,
    ).value


def load_card_tiers(con: duckdb.DuckDBPyConnection) -> dict | None:
    return reference.get(con, KEY)
