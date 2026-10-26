"""analysis/triangles.py: loops through the item-to-item markets the loader drops, on a
made-up hour and on the recorded Mirage pages."""

import gzip
import json
from datetime import datetime
from pathlib import Path

import polars as pl
import pytest

from exiledbroker.analysis import triangles as tri
from exiledbroker.ingest import currency_exchange as cx
from exiledbroker.normalize.tracked import CHAOS_METADATA as CHAOS

EXALT = "Metadata/Items/Currency/CurrencyAddModToRare"
ALCH = "Metadata/Items/Currency/CurrencyUpgradeToRare"
H = datetime(2026, 3, 7)


def market(a, b, vol_a, vol_b, lo, hi):
    """A market row as `cx.market_rows` yields it; lo/hi are {a: n, b: m} ratios."""
    return {
        "hour": H,
        "market_id": f"{a}|{b}",
        "a": a,
        "b": b,
        "volume_traded_a": vol_a,
        "volume_traded_b": vol_b,
        "lowest_ratio_a": lo[0],
        "lowest_ratio_b": lo[1],
        "highest_ratio_a": hi[0],
        "highest_ratio_b": hi[1],
    }


def frame(rows):
    return pl.DataFrame(rows, schema={k: cx.MARKET_SCHEMA[k] for k in rows[0]}, strict=False)


def test_a_triangle_is_priced_fair_and_at_worst_ratios():
    markets = frame(
        [
            # Exalted at 20c (19 to 22 an Exalt).
            market(CHAOS, EXALT, 2000, 100, (19, 1), (22, 1)),
            # Alchemy at 0.5c (0.4 to 0.6).
            market(CHAOS, ALCH, 500, 1000, (2, 5), (3, 5)),
            # 1 Exalt buys 50 Alchemy on average (45 to 55 an Exalt).
            market(EXALT, ALCH, 10, 500, (1, 55), (1, 45)),
        ]
    )
    loops = tri.triangles(markets, CHAOS)
    by = {(r["a"], r["b"]): r for r in loops.iter_rows(named=True)}
    # Chaos -> Exalt -> Alchemy -> Chaos: 20c buys 50 Alchemy worth 25c.
    fwd = by[(EXALT, ALCH)]
    assert fwd["gap"] == pytest.approx(25 / 20 - 1)
    # Worst: an Exalt at 22c, 1/45 Exalt an Alchemy, sold at 0.4c: 0.4 / (22 / 45) - 1.
    assert fwd["worst"] == pytest.approx(0.4 / (22 / 45) - 1)
    # The other way round loses what the first way gains.
    back = by[(ALCH, EXALT)]
    assert back["gap"] == pytest.approx(20 / 25 - 1)
    s = tri.summary(loops)
    assert s.height == 2
    assert tri.coverage(markets) == {
        "market_hours": 3,
        "cross_market_hours": 1,
        "cross_markets": 1,
    }


def test_untraded_markets_make_no_loop():
    markets = frame(
        [
            market(CHAOS, EXALT, 2000, 100, (19, 1), (22, 1)),
            market(CHAOS, ALCH, 500, 1000, (2, 5), (3, 5)),
            market(EXALT, ALCH, 0, 0, (1, 55), (1, 45)),
        ]
    )
    assert tri.triangles(markets, CHAOS).is_empty()


def test_the_recorded_mirage_pages_have_item_to_item_markets():
    data = json.loads(
        gzip.decompress((Path(__file__).parent / "fixtures" / "mirage_launch.json.gz").read_bytes())
    )
    rows = []
    for ts, page in data["pages"].items():
        for m in page["markets"]:
            a, b = m["market_pair"]
            row = {"hour": cx.from_ts(int(ts)).replace(tzinfo=None), "market_id": m["market_id"]}
            row |= {"a": a, "b": b}
            for f in ("volume_traded", "lowest_ratio", "highest_ratio"):
                row[f"{f}_a"], row[f"{f}_b"] = m[f].get(a), m[f].get(b)
            rows.append(row)
    markets = frame(rows)
    c = tri.coverage(markets)
    assert c["cross_markets"] > 0
    loops = tri.triangles(markets, CHAOS)
    assert not loops.is_empty()
    assert loops["gap"].is_finite().all()
