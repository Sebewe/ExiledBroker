"""Stack impact and market depth (analysis/impact.py): reading both sides' stock from
pages on disk, hour-to-hour moves, volatility and the book-imbalance test."""

import math
from datetime import datetime, timedelta

import polars as pl
import pytest

from exiledbroker.analysis import impact as im
from exiledbroker.config import Settings
from exiledbroker.ingest import currency_exchange as cx
from exiledbroker.normalize.tracked import CHAOS_METADATA, DIVINE_METADATA
from exiledbroker.storage import db

H = timedelta(hours=1)
T0 = datetime(2026, 3, 6, 20)
ITEM = "Metadata/Items/Currency/CurrencyAddModToRare"


def _market(a: str, b: str, vol: tuple, stock: tuple, lo: tuple, hi: tuple) -> dict:
    return {
        "league": "Mirage",
        "market_id": f"{a}|{b}",
        "market_pair": [a, b],
        "volume_traded": {a: vol[0], b: vol[1]},
        "lowest_stock": {a: stock[0], b: stock[1]},
        "highest_stock": {a: stock[2], b: stock[3]},
        "lowest_ratio": {a: lo[0], b: lo[1]},
        "highest_ratio": {a: hi[0], b: hi[1]},
    }


def test_markets_reads_both_sides_from_pages(tmp_path):
    settings = Settings(data_dir=tmp_path)
    con = db.connect(settings.db_path)
    db.init_schema(con)
    con.execute(
        "INSERT INTO league (id, game, name, start_at, kind, launched_at) "
        "VALUES ('poe1-mirage', 'poe1', 'Mirage', ?, 'challenge', ?)",
        [T0, T0],
    )
    con.execute(
        "INSERT INTO item (id, game, canonical_name, category, metadata_id) "
        "VALUES ('currency:exalted-orb', 'poe1', 'Exalted Orb', 'Currency', ?)",
        [ITEM],
    )
    pages = [
        # Hour 0: 10 Exalts for 150 Chaos (the pair listed Chaos first), and 2 for 1 Divine.
        [
            _market(CHAOS_METADATA, ITEM, (150, 10), (900, 40, 1000, 60), (14, 1), (16, 1)),
            _market(ITEM, DIVINE_METADATA, (2, 1), (5, 3, 7, 4), (2, 1), (2, 1)),
        ],
        # Hour 1: a book but no trades.
        [_market(CHAOS_METADATA, ITEM, (0, 0), (800, 30, 800, 30), (0, 0), (0, 0))],
    ]
    for k, markets in enumerate(pages):
        ts = cx.to_ts(T0 + k * H)
        cx.write_page(settings, ts, {"next_change_id": ts + 3600, "markets": markets})
        con.execute("INSERT INTO exchange_hour_loaded VALUES ('poe1-mirage', ?)", [T0 + k * H])
    mk = im.markets(con, settings, "Mirage").sort("hour", "market")
    c0, d0, c1 = mk.to_dicts()
    assert (c0["market"], c0["item_id"], c0["vol"], c0["p"]) == (
        "chaos",
        "currency:exalted-orb",
        10,
        15.0,
    )
    assert (c0["lo"], c0["hi"]) == (14.0, 16.0)
    # The item's stock and the Chaos bid, each at its lowest and highest in the hour.
    assert (c0["stock_x_lo"], c0["stock_x_hi"], c0["stock_ref_lo"], c0["stock_ref_hi"]) == (
        40,
        60,
        900,
        1000,
    )
    assert d0["market"] == "divine" and d0["p"] == 0.5 and d0["stock_x_hi"] == 7
    assert c1["p"] is None and c1["stock_x_hi"] == 30  # untraded, but the book is kept
    con.close()


def _mk(prices: list, vols: list | None = None, market: str = "chaos", item: str = "a"):
    n = len(prices)
    vols = vols or [100] * n
    return pl.DataFrame(
        {
            "league": ["L"] * n,
            "item_id": [item] * n,
            "market": [market] * n,
            "hour": [T0 + k * H for k in range(n)],
            "day_offset": [k / 24 for k in range(n)],
            "p": prices,
            "lo": [None if p is None else p * 0.9 for p in prices],
            "hi": [None if p is None else p * 1.1 for p in prices],
            "vol": vols,
            "stock_x_hi": [50] * n,
            "stock_ref_hi": [500] * n,
            "chaos": prices,
            "cv": [None if p is None else p * v for p, v in zip(prices, vols, strict=True)],
        }
    )


def test_moves_skip_gaps_and_untraded_hours():
    mv = im.moves(_mk([10.0, 11.0, None, 12.0, 12.0], vols=[100, 200, 0, 100, 50]))
    # 10 → 11 is a move; 11 → 12 spans an untraded hour, so it isn't.
    assert mv["r"].to_list() == pytest.approx([math.log(1.1), 0.0])
    assert mv["lag_r"].to_list() == [None, None]
    assert mv["rel_vol"].to_list() == pytest.approx([2.0, 0.5])  # median hour: 100
    assert mv["vol_stock"].to_list() == pytest.approx([4.0, 1.0])
    # Same book every hour: the imbalance is its item mean, so zero after demeaning.
    assert mv["imbalance"].to_list() == pytest.approx([0.0, 0.0])


def test_sigmas_close_to_close_and_parkinson():
    prices = [10.0 * (1.1 if k % 2 else 1.0) for k in range(60)]
    sg = im.sigmas(im.moves(_mk(prices))).to_dicts()[0]
    assert sg["n"] == 59
    assert sg["sigma_cc"] == pytest.approx(math.log(1.1), rel=0.05)
    assert sg["sigma_pk"] == pytest.approx(math.log(1.1 / 0.9) / math.sqrt(4 * math.log(2)))
    assert im.sigmas(im.moves(_mk(prices[:20]))).is_empty()  # under MIN_HOURS


def test_fit_y_finds_moves_that_grow_with_volume():
    # Moves of ±1% in quiet hours and ±4% in hours four times as busy: y > 0.
    prices, vols, p = [], [], 10.0
    for k in range(200):
        busy = k % 2
        p *= math.exp((0.04 if busy else 0.01) * (1 if (k // 2) % 2 else -1))
        prices.append(p)
        vols.append(400 if busy else 100)
    mv = im.moves(_mk(prices, vols))
    fit = im.fit_y(mv, im.sigmas(mv))
    assert fit["y"] > 0 and fit["r"] > 0.9


def test_reversal_and_imbalance():
    # A price that bounces between two levels reverses every hour.
    mv = im.moves(_mk([10.0, 11.0] * 40))
    s = im.imbalance_signal(mv)
    assert s["reversal"] == pytest.approx(-1.0)


def test_depth_compares_the_two_markets():
    rate = 200.0
    chaos = _mk([10.0] * 10)
    divine = _mk([10.0] * 10, vols=[25] * 10, market="divine").with_columns(
        p=pl.lit(10.0 / rate), chaos=pl.lit(10.0), cv=pl.lit(250.0)
    )
    dp = im.depth(pl.concat([chaos, divine])).to_dicts()[0]
    assert dp["divine_share"] == pytest.approx(0.2)  # 250c of 1250c an hour
    assert dp["divine_hours"] == 1.0 and dp["offered_ratio"] == 1.0


def test_stock_cost():
    assert im.stock_cost(pl.DataFrame(), 1000) == {
        "bytes_per_row": 64,
        "rows": 1000,
        "mb": 0.064,
    }
