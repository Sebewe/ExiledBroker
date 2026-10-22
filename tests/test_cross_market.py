from datetime import date

import polars as pl
import pytest

from exiledbroker.config import Settings
from exiledbroker.ingest import currency_exchange as cx
from exiledbroker.normalize import exchange_loader
from exiledbroker.services import cross_market as xm
from exiledbroker.storage import db
from test_currency_exchange import ALCH, CHAOS, DIVINE, NAMES, T0, FakeExchange, client_for, market
from test_dashboard import register


@pytest.fixture
def con(tmp_path):
    settings = Settings(data_dir=tmp_path, request_min_interval=0)
    # Hour 0: Divine 100c (range 90–110). Alchemy: 1c in the Chaos market (range 0.9–1.2),
    # 0.015 div in the Divine market (range 0.014–0.016) = 1.5c via Divines.
    # Hour 1: Alchemy trades against Chaos only, so it isn't a cross-market hour.
    pages = {
        T0: [
            market("Mirage", CHAOS, DIVINE, 1000, 10, lo=(90, 1), hi=(110, 1)),
            market("Mirage", ALCH, CHAOS, 100, 100, lo=(10, 9), hi=(10, 12)),
            market("Mirage", ALCH, DIVINE, 200, 3, lo=(1000, 14), hi=(1000, 16)),
        ],
        T0 + 3600: [
            market("Mirage", CHAOS, DIVINE, 1000, 10),
            market("Mirage", ALCH, CHAOS, 100, 100),
        ],
    }
    c = register(settings)
    with client_for(settings, FakeExchange(pages, now=T0 + 7200)) as client:
        r = cx.sync_league(client, settings, "Mirage", date(2026, 3, 6), days=1)
    exchange_loader.load_league(c, settings, r.window, NAMES)
    yield c
    c.close()


def test_loader_fills_cross_market_hours(con):
    rows = db.rows(
        con,
        "SELECT item_id, chaos_price, chaos_low, chaos_high, divine_price, divine_low, "
        "divine_high, divine_rate, divine_rate_low, divine_rate_high FROM cross_market_hour",
    )
    assert len(rows) == 1  # only hour 0 traded in both markets
    item, *values = rows[0]
    assert item == "currency:orb-of-alchemy"
    assert values == pytest.approx([1.0, 0.9, 1.2, 0.015, 0.014, 0.016, 100, 90, 110])


def test_loop_edges_at_worst_prices(con):
    chaos_first = xm.hourly(con, ["Mirage"]).row(0, named=True)
    # Via Divines at average prices: 0.015 × 100 = 1.5c, a 50% gap.
    assert chaos_first["via_divines"] == pytest.approx(1.5)
    assert chaos_first["gap"] == pytest.approx(0.5)
    # Buy at 1.2c, sell for 0.014 div, sell divines at 90c: 1.26 / 1.2 - 1 = 5%.
    assert chaos_first["edge"] == pytest.approx(0.014 * 90 / 1.2 - 1)
    # Reverse: buy at 0.016 div, sell at 0.9c, buy divines back at 110c.
    divine_first = xm.hourly(con, ["Mirage"], direction="divine_first").row(0, named=True)
    assert divine_first["edge"] == pytest.approx(0.9 / (0.016 * 110) - 1)
    # Overlap: min(100 bought with chaos, 200 sold for divines) × 1c.
    assert chaos_first["overlap_chaos"] == pytest.approx(100)
    assert xm.hourly(con, ["Mirage"], item_ids=[]).is_empty()
    with pytest.raises(ValueError):
        xm.hourly(con, ["Mirage"], direction="sideways")


def test_buffer_and_missing_leagues():
    hours = pl.DataFrame(
        {
            "league": ["A", "A", "A", "B"],
            "item_id": ["x"] * 4,
            "name": ["X"] * 4,
            "edge": [0.05, 0.01, -0.2, 0.3],
            "gap": [0.1, 0.1, 0.1, 0.4],
            "chaos_price": [2.0] * 4,
            "overlap_chaos": [100.0] * 4,
        }
    )
    per = xm.per_league(hours, buffer=0.02, min_hours=1)
    a = per.filter(league="A").row(0, named=True)
    assert (a["hours"], a["share"], a["edge_when_paying"]) == (3, pytest.approx(1 / 3), 0.05)
    assert a["capacity_chaos"] == pytest.approx(5.0)
    both = xm.across_leagues(per, ["A", "B"], {"A": 1.0, "B": 1.0}).row(0, named=True)
    assert both["weighted_share"] == pytest.approx((1 / 3 + 1) / 2)
    assert both["worst_league_share"] == pytest.approx(1 / 3)
    # A league where the item never traded in both markets counts as 0.
    three = xm.across_leagues(per, ["A", "B", "C"], {"A": 1.0, "B": 1.0, "C": 1.0})
    assert three["worst_league_share"].item() == 0.0
    assert three["weighted_share"].item() == pytest.approx((1 / 3 + 1) / 3)
    assert xm.score(three)["score"].item() == 1.0


def test_since_limits_hours_in_sql(con):
    from datetime import timedelta

    from test_currency_exchange import LAUNCH

    hour0 = LAUNCH.replace(tzinfo=None)
    assert xm.hourly(con, ["Mirage"], since=hour0 - timedelta(hours=1)).height == 1
    assert xm.hourly(con, ["Mirage"], since=hour0).is_empty()  # exclusive
