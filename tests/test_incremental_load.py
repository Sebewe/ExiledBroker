"""The exchange loader is incremental: new hours are added, hours that leave the
window are removed, and nothing else in the database is rewritten."""

from datetime import timedelta

import pytest

from exiledbroker.config import Settings
from exiledbroker.ingest import currency_exchange as cx
from exiledbroker.normalize import exchange_loader, mappings
from exiledbroker.storage import db
from test_currency_exchange import ALCH, CHAOS, DIVINE, MIRROR, NAMES, T0, market
from test_dashboard import register

H = cx.HOUR
LAUNCH = cx.from_ts(T0)


def pages(n: int) -> dict[int, list]:
    """n hours. Divine trades only in even hours, so odd hours carry its rate forward."""
    out = {}
    for i in range(n):
        markets = [
            market("Mirage", ALCH, CHAOS, 50 + i, 10),
            market("Mirage", MIRROR, DIVINE, 1, 400 + i),
            market("Mirage", ALCH, DIVINE, 1000, 3, lo=(1000, 2), hi=(1000, 4)),
        ]
        if i % 2 == 0:
            markets.append(market("Mirage", CHAOS, DIVINE, 300 + 10 * i, 10))
        out[T0 + i * H] = markets
    return out


@pytest.fixture
def setup(tmp_path):
    settings = Settings(data_dir=tmp_path, request_min_interval=0)
    for ts, markets in pages(12).items():
        cx.write_page(settings, ts, {"next_change_id": ts + H, "markets": markets})
    con = register(settings)
    yield settings, con
    con.close()


def window(start_h: int, end_h: int) -> cx.Window:
    return cx.Window(
        "Mirage", LAUNCH, LAUNCH + timedelta(hours=end_h), start=LAUNCH + timedelta(hours=start_h)
    )


def snapshot(con) -> tuple[list, list]:
    prices = db.rows(
        con,
        "SELECT item_id, observed_at, chaos_value, divine_value, volume, chaos_low, chaos_high "
        "FROM price_observation ORDER BY 1, 2",
    )
    cross = db.rows(con, "SELECT * FROM cross_market_hour ORDER BY item_id, observed_at")
    return prices, cross


def test_hour_by_hour_matches_one_load(setup, tmp_path):
    settings, con = setup
    for end in range(1, 13):
        r = exchange_loader.load_league(con, settings, window(0, end), NAMES)
        assert r.hours_added == 1 and r.hours_removed == 0
    stepwise = snapshot(con)

    other = Settings(data_dir=tmp_path / "other", request_min_interval=0)
    for ts, markets in pages(12).items():
        cx.write_page(other, ts, {"next_change_id": ts + H, "markets": markets})
    con2 = register(other)
    exchange_loader.load_league(con2, other, window(0, 12), NAMES)
    assert snapshot(con2) == stepwise  # incl. the Divine rate carried over earlier loads
    con2.close()


def test_new_hour_leaves_existing_rows_alone(setup):
    settings, con = setup
    first = exchange_loader.load_league(con, settings, window(0, 7), NAMES)
    assert first.rebuilt and first.hours_added == 7
    before, _ = snapshot(con)
    r = exchange_loader.load_league(con, settings, window(0, 8), NAMES)
    after, _ = snapshot(con)
    assert (r.rebuilt, r.hours_added, r.hours_removed) == (False, 1, 0)
    assert set(before) <= set(after)  # every earlier row is still there, unchanged
    new_rows = set(after) - set(before)
    hour7 = (LAUNCH + timedelta(hours=7)).replace(tzinfo=None)
    assert len(new_rows) == r.rows_added and {row[1] for row in new_rows} == {hour7}
    # Hour 7 has no Divine trade, so its Divine-priced rows use the rate carried over
    # from hour 6, which was loaded earlier: 360c / 10 = 36c.
    mirror7 = next(row for row in new_rows if row[0] == "currency:mirror-of-kalandra")
    assert mirror7[2] == pytest.approx(407 * 36)
    assert exchange_loader.load_league(con, settings, window(0, 8), NAMES).skipped


def test_sliding_window_removes_only_old_hours(setup):
    settings, con = setup
    exchange_loader.load_league(con, settings, window(0, 8), NAMES)
    keep, _ = snapshot(con)
    r = exchange_loader.load_league(con, settings, window(2, 10), NAMES)
    assert (r.hours_added, r.hours_removed) == (2, 2)
    now, _ = snapshot(con)
    first_kept = (LAUNCH + timedelta(hours=2)).replace(tzinfo=None)
    assert {row for row in keep if row[1] >= first_kept} <= set(now)
    assert min(row[1] for row in now) == first_kept
    hours = db.scalar(con, "SELECT count(*) FROM exchange_hour_loaded")
    assert hours == 8


def test_failed_load_changes_nothing(setup, monkeypatch):
    settings, con = setup
    exchange_loader.load_league(con, settings, window(0, 4), NAMES)
    before = snapshot(con)

    def boom(*args, **kwargs):
        raise RuntimeError("crash mid-load")

    monkeypatch.setattr(exchange_loader, "refresh_mappings", boom)
    with pytest.raises(RuntimeError):
        exchange_loader.load_league(con, settings, window(0, 6), NAMES)
    assert snapshot(con) == before
    assert db.scalar(con, "SELECT count(*) FROM exchange_hour_loaded") == 4
    monkeypatch.undo()
    r = exchange_loader.load_league(con, settings, window(0, 6), NAMES)
    assert r.hours_added == 2


def test_version_bump_or_force_rebuilds(setup, monkeypatch):
    settings, con = setup
    exchange_loader.load_league(con, settings, window(0, 4), NAMES)
    before = snapshot(con)
    assert exchange_loader.load_league(con, settings, window(0, 4), NAMES, force=True).rebuilt
    monkeypatch.setattr(exchange_loader, "LOADER_VERSION", exchange_loader.LOADER_VERSION + 1)
    r = exchange_loader.load_league(con, settings, window(0, 4), NAMES)
    assert r.rebuilt and r.hours_added == 4
    assert snapshot(con) == before


def test_mapping_refresh_only_writes_changes(setup):
    settings, con = setup
    exchange_loader.load_league(con, settings, window(0, 4), NAMES)
    rows = db.rows(con, "SELECT * FROM tracked_item ORDER BY 1")
    assert mappings._sync_rows(
        con, "tracked_item", mappings.TRACKED_COLUMNS, 2, [tuple(r) for r in rows]
    ) == (0, 0)
    changed = [rows[0][:3] + (99,)] + [tuple(r) for r in rows[1:]]
    assert mappings._sync_rows(con, "tracked_item", mappings.TRACKED_COLUMNS, 2, changed) == (1, 1)
    assert db.scalar(con, "SELECT sort_order FROM tracked_item ORDER BY item_id LIMIT 1") == 99


FRAGMENT = "Metadata/Items/MapFragments/VaalFragment1_1"
CARD = "Metadata/Items/DivinationCards/DivinationCardTest"


def test_only_used_items_get_hourly_prices(tmp_path):
    """Hourly prices are stored only for what the site reads (cost issue #7): price-
    mapping items, followed cards' rewards, Chaos and Divine. Cross-market rows stay
    complete for arbitrage."""
    from exiledbroker.ingest import item_names, loot_filter, reference
    from exiledbroker.ingest.item_names import BaseItem

    settings = Settings(data_dir=tmp_path, request_min_interval=0)
    names = {
        **NAMES,
        FRAGMENT: BaseItem(FRAGMENT, "Sacrifice at Dusk", "MapFragment"),
        CARD: BaseItem(CARD, "The Test", "DivinationCard"),
    }
    markets = [
        market("Mirage", CHAOS, DIVINE, 300, 10),
        market("Mirage", FRAGMENT, CHAOS, 10, 20),
        market("Mirage", FRAGMENT, DIVINE, 10, 1),
    ]
    cx.write_page(settings, T0, {"next_change_id": T0 + H, "markets": markets})
    con = register(settings)

    def fragment_rows():
        prices = db.scalar(
            con, "SELECT count(*) FROM price_observation WHERE item_id LIKE '%sacrifice%'"
        )
        cross = db.scalar(
            con, "SELECT count(*) FROM cross_market_hour WHERE item_id LIKE '%sacrifice%'"
        )
        return prices, cross

    exchange_loader.load_league(con, settings, window(0, 1), names)
    assert fragment_rows() == (0, 1)  # no hourly price; still an arbitrage candidate
    assert (
        db.scalar(con, "SELECT count(*) FROM item WHERE canonical_name = 'Sacrifice at Dusk'") == 1
    )

    # A followed card turns into the fragment: now its price is needed for turn-ins.
    reference.put(
        con,
        item_names.KEY,
        {
            CARD: {
                "name": "The Test",
                "item_class": "DivinationCard",
                "release_state": "released",
                "properties": {"description": "<currencyitem>{Sacrifice at Dusk}", "stack_size": 3},
            },
            FRAGMENT: {
                "name": "Sacrifice at Dusk",
                "item_class": "MapFragment",
                "release_state": "released",
                "properties": {},
            },
        },
    )
    reference.put(con, loot_filter.KEY, {"tiers": {"The Test": "t1"}, "shown": ["The Test"]})
    exchange_loader.load_league(con, settings, window(0, 1), names, force=True)
    assert fragment_rows() == (1, 1)
    con.close()
