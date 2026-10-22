"""Build tests/fixtures/mirage_launch.json.gz from real data in data/.

The live-pipeline tests replay these real GGG exchange pages hour by hour, so the
tools are tested against the API's actual output, not hand-written markets. The
pages are trimmed to a handful of items to keep the fixture small.

Run from the repo root (after `eb exchange sync -l Mirage`):
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


def main() -> None:
    base_items = json.loads((RAW / "repoe" / "base_items.min.json").read_text())
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
