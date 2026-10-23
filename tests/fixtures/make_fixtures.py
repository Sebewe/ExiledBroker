"""Build the replay fixtures in tests/fixtures/ from real data in data/.

The live-pipeline tests replay these real GGG exchange pages hour by hour, so the
tools are tested against the API's actual output, not hand-written markets.
- mirage_launch.json.gz: Mirage's first 30 hours, trimmed to a handful of items.
- allflame_start.json.gz: Allflame's first 3 hours, every Allflame market untrimmed:
  what the site sees at a league's start, when the exchange is still mostly empty.

Run from the repo root (after `eb exchange sync -l Mirage` and `eb live sync -l
Allflame`; it reads pages already on disk and fetches nothing):
    .venv/bin/python tests/fixtures/make_fixtures.py
"""

import gzip
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw"
LAUNCH = 1772827200  # Mirage's first hour on the exchange, 2026-03-06 20:00 UTC
HOURS = 30
KEEP = {
    "Chaos Orb",
    "Divine Orb",
    "Orb of Alchemy",
    "Exalted Orb",
    "Mirror of Kalandra",
    "Mirror Shard",
    "Deafening Essence of Scorn",
    "Horned Scarab of Bloodlines",
    "Omen of the Jeweller",
    "Rogue's Marker",
    "The Lake",
    "Reflecting Mist",
    "Seven Years Bad Luck",
}


ALLFLAME_LAUNCH = 1784930400  # Allflame's first hour on the exchange, 2026-07-24 22:00 UTC
ALLFLAME_HOURS = 3


def _page(ts: int) -> dict:
    with gzip.open(RAW / "ggg" / "currency_exchange" / f"{ts}.json.gz", "rt") as f:
        return json.load(f)


def allflame_start(base_items: dict) -> None:
    pages = {}
    for ts in range(ALLFLAME_LAUNCH, ALLFLAME_LAUNCH + ALLFLAME_HOURS * 3600, 3600):
        page = _page(ts)
        page["markets"] = [m for m in page["markets"] if m["league"] == "Allflame"]
        pages[str(ts)] = page
    used = {x for p in pages.values() for m in p["markets"] for x in m["market_pair"]}
    ids = {k: v for k, v in base_items.items() if k in used}
    fixture = {"league": "Allflame", "launch": ALLFLAME_LAUNCH, "pages": pages, "base_items": ids}
    out = Path(__file__).parent / "allflame_start.json.gz"
    with gzip.open(out, "wt") as f:
        json.dump(fixture, f)
    markets = sum(len(p["markets"]) for p in pages.values())
    print(f"{out}: {ALLFLAME_HOURS} hours, {markets} markets, {len(ids)} items")


def main() -> None:
    base_items = json.loads((RAW / "repoe" / "base_items.min.json").read_text())
    allflame_start(base_items)
    ids = {k: v for k, v in base_items.items() if v.get("name") in KEEP}
    pages = {}
    for ts in range(LAUNCH, LAUNCH + HOURS * 3600, 3600):
        with gzip.open(RAW / "ggg" / "currency_exchange" / f"{ts}.json.gz", "rt") as f:
            page = json.load(f)
        page["markets"] = [
            m
            for m in page["markets"]
            if m["league"] == "Mirage" and all(x in ids for x in m["market_pair"])
        ]
        pages[str(ts)] = page
    fixture = {"league": "Mirage", "launch": LAUNCH, "pages": pages, "base_items": ids}
    out = Path(__file__).parent / "mirage_launch.json.gz"
    with gzip.open(out, "wt") as f:
        json.dump(fixture, f)
    markets = sum(len(p["markets"]) for p in pages.values())
    print(f"{out}: {HOURS} hours, {markets} markets, {len(ids)} items")


if __name__ == "__main__":
    main()
