import gzip
import json
from datetime import UTC, date, datetime

import httpx
import pytest

from exiledbroker.config import Settings
from exiledbroker.ingest import currency_exchange as cx
from exiledbroker.ingest.http import PoliteClient
from exiledbroker.ingest.item_names import BaseItem
from exiledbroker.ingest.poe_ninja_dumps import parse_index
from exiledbroker.normalize import exchange_loader, mappings
from exiledbroker.storage import db
from exiledbroker.storage import dumps as dump_store

FILTER = """
Show # $type->divination $tier->excustomstack
\tStackSize >= 3
\tClass == "Divination Cards"
\tBaseType == "The Hoarder"

Show # $type->divination $tier->t1
\tClass == "Divination Cards"
\tBaseType == "House of Mirrors" "The Doctor"
\tSetFontSize 45

Show # %HS3 $type->divination $tier->t4
\tClass == "Divination Cards"
\tBaseType == "The Hoarder"

Hide # %H0 $type->divination $tier->t5
\tClass == "Divination Cards"
\tBaseType == "Rain of Chaos" "The Doctor"

Show # $type->divination $tier->restex
\tClass == "Divination Cards"
"""
CHAOS = "Metadata/Items/Currency/CurrencyRerollRare"
DIVINE = "Metadata/Items/Currency/CurrencyModValues"
MIRROR = "Metadata/Items/Currency/CurrencyDuplicate"
ALCH = "Metadata/Items/Currency/CurrencyUpgradeToRare"
NAMES = {
    CHAOS: BaseItem(CHAOS, "Chaos Orb", "StackableCurrency"),
    DIVINE: BaseItem(DIVINE, "Divine Orb", "StackableCurrency"),
    MIRROR: BaseItem(MIRROR, "Mirror of Kalandra", "StackableCurrency"),
    ALCH: BaseItem(ALCH, "Orb of Alchemy", "StackableCurrency"),
}
LAUNCH = datetime(2026, 3, 6, 20, tzinfo=UTC)
T0 = cx.to_ts(LAUNCH)


def market(league, a, b, vol_a, vol_b, lo=(1, 1), hi=(1, 1)):
    return {
        "league": league,
        "market_id": f"{a}|{b}",
        "market_pair": [a, b],
        "volume_traded": {a: vol_a, b: vol_b},
        "lowest_stock": {a: 1, b: 1},
        "highest_stock": {a: 1, b: 1},
        "lowest_ratio": {a: lo[0], b: lo[1]},
        "highest_ratio": {a: hi[0], b: hi[1]},
    }


class FakeExchange:
    """Serves hourly pages; hours >= `now` are the unfinished current hour."""

    def __init__(self, pages: dict[int, list], now: int):
        self.pages, self.now, self.requests = pages, now, []

    def handler(self, request: httpx.Request) -> httpx.Response:
        ts = int(request.url.path.rsplit("/", 1)[-1])
        self.requests.append(ts)
        if ts >= self.now:
            return httpx.Response(200, json={"next_change_id": ts, "markets": []})
        return httpx.Response(
            200, json={"next_change_id": ts + 3600, "markets": self.pages.get(ts, [])}
        )


@pytest.fixture
def settings(tmp_path):
    return Settings(data_dir=tmp_path, request_min_interval=0)


def client_for(settings, server):
    return PoliteClient(settings, transport=httpx.MockTransport(server.handler))


def pages_for_launch():
    other = [market("Standard", CHAOS, DIVINE, 100, 1)]
    return {
        T0 - 3600: other,  # before Mirage exists
        # Hour 0: Divine at 30c; Mirror priced in Divines; Alchemy vs Chaos.
        T0: [
            market("Mirage", CHAOS, DIVINE, 300, 10, lo=(25, 1), hi=(35, 1)),
            market("Mirage", MIRROR, DIVINE, 1, 400, lo=(1, 350), hi=(1, 450)),
            market("Mirage", ALCH, CHAOS, 50, 10, lo=(10, 1), hi=(4, 1)),
            market("Hardcore Mirage", CHAOS, DIVINE, 1, 1),
        ],
        # Hour 1: no Divine trades; the rate carries forward from hour 0.
        T0 + 3600: [market("Mirage", MIRROR, DIVINE, 1, 500)],
        T0 + 7200: [market("Mirage", CHAOS, DIVINE, 400, 10)],
    }


def test_page_must_match_requested_hour(settings):
    def handler(request):
        return httpx.Response(200, json={"next_change_id": 1722027600, "markets": []})

    transport = httpx.MockTransport(handler)
    with (
        PoliteClient(settings, transport=transport) as client,
        pytest.raises(ValueError, match="next_change_id"),
    ):
        cx.fetch_page(client, settings, 1000000000 // 3600 * 3600)
    assert not list(settings.exchange_raw_dir.glob("*"))


def test_sync_finds_launch_and_skips_cached(settings):
    server = FakeExchange(pages_for_launch(), now=T0 + 10 * 3600)
    with client_for(settings, server) as client:
        result = cx.sync_league(client, settings, "Mirage", date(2026, 3, 6), days=1)
    assert result.window.launched_at == LAUNCH
    assert result.reached_end  # stopped at the unfinished hour, not an error
    fetched = len(server.requests)

    # Nothing is fetched twice; the only new request is the still-unfinished hour.
    with client_for(settings, server) as client:
        again = cx.sync_league(client, settings, "Mirage", date(2026, 3, 6), days=1)
    assert again.fetched == 1 and len(server.requests) == fetched + 1


def test_interrupted_sync_resumes(settings):
    server = FakeExchange(pages_for_launch(), now=T0 + 48 * 3600)
    calls = {"n": 0}

    def interrupt(done, total, fetched):
        calls["n"] += 1
        if calls["n"] == 2:
            raise KeyboardInterrupt

    with client_for(settings, server) as client, pytest.raises(KeyboardInterrupt):
        cx.sync_league(client, settings, "Mirage", date(2026, 3, 6), 1, interrupt)
    on_disk = len(list(settings.exchange_raw_dir.glob("*.json.gz")))
    assert not list(settings.exchange_raw_dir.glob("*.tmp"))

    with client_for(settings, server) as client:
        result = cx.sync_league(client, settings, "Mirage", date(2026, 3, 6), 1)
    assert result.cached >= on_disk and len(list(result.window.hours)) == 24
    hours = {int(p.name.split(".")[0]) for p in settings.exchange_raw_dir.glob("*.json.gz")}
    assert set(result.window.hours) <= hours


def test_pages_are_stored_gzipped(settings):
    server = FakeExchange(pages_for_launch(), now=T0 + 3 * 3600)
    with client_for(settings, server) as client:
        cx.fetch_page(client, settings, T0)
    with gzip.open(cx.page_path(settings, T0), "rt") as f:
        assert json.load(f)["next_change_id"] == T0 + 3600


def load(settings):
    server = FakeExchange(pages_for_launch(), now=T0 + 3 * 3600)
    with client_for(settings, server) as client:
        result = cx.sync_league(client, settings, "Mirage", date(2026, 3, 6), days=1)
    cx.extract_league(settings, result.window)
    con = db.connect(settings.db_path)
    db.init_schema(con)
    index = parse_index(
        [
            {
                "leagueName": "Mirage",
                "minDate": "2026-03-06T00:00:00",
                "maxDate": "2026-07-20T00:00:00",
                "zipName": "Mirage.zip",
            }
        ]
    )
    dump_store.upsert_leagues(con, index)
    loaded = exchange_loader.load_league(con, settings, result.window, NAMES)
    return con, result.window, loaded


def row(con, item, hour):
    q = """SELECT round(chaos_value, 4), round(divine_value, 4), volume, chaos_low, chaos_high,
                  day_offset
           FROM price_observation WHERE item_id = ? AND observed_at = ?"""
    return db.rows(
        con,
        q,
        [item, datetime.fromtimestamp(T0 + hour * 3600).astimezone(UTC).replace(tzinfo=None)],
    )


def test_hourly_prices(settings):
    con, _, loaded = load(settings)
    assert not loaded.skipped
    # Divine: 300 chaos for 10 divines -> 30c, range 25-35.
    assert row(con, "currency:divine-orb", 0) == [(30.0, 1.0, 10, 25, 35, 0.0)]
    # Chaos is 1 by definition, 1/30 of a Divine.
    assert row(con, "currency:chaos-orb", 0)[0][:2] == (1.0, 0.0333)
    # Mirror: 400 divines x 30c = 12000c; range 350-450 div.
    assert row(con, "currency:mirror-of-kalandra", 0)[0][:5] == (12000.0, 400.0, 1, 10500, 13500)
    # Hour 1 has no Divine trades: the hour-0 rate (30c) is carried forward.
    assert row(con, "currency:mirror-of-kalandra", 1)[0][:2] == (15000.0, 500.0)
    assert row(con, "currency:divine-orb", 1) == []
    # Alchemy: 10 chaos for 50 alchs; ratio orientation doesn't matter for low/high.
    assert row(con, "currency:orb-of-alchemy", 0)[0][2:5] == (50, 0.1, 0.25)
    # 4 items in hour 0, Mirror in hour 1, Divine + Chaos in hour 2. Hardcore and
    # other leagues are ignored.
    assert db.scalar(con, "SELECT count(*) FROM price_observation") == 7
    assert db.scalar(con, "SELECT launched_at FROM league WHERE name = 'Mirage'") == LAUNCH.replace(
        tzinfo=None
    )
    # Core currencies are tracked even before poe.ninja's currency list is fetched.
    groups = dict(db.rows(con, "SELECT item_id, group_id FROM tracked_item"))
    assert groups == {
        "currency:chaos-orb": "currency",
        "currency:divine-orb": "currency",
        "currency:mirror-of-kalandra": "currency",
        "currency:orb-of-alchemy": "currency",
    }
    con.close()


def test_reload_skipped_until_inputs_change(settings):
    con, window, _ = load(settings)
    assert exchange_loader.load_league(con, settings, window, NAMES).skipped
    assert not exchange_loader.load_league(con, settings, window, NAMES, force=True).skipped
    assert db.scalar(con, "SELECT count(*) FROM price_observation") == 7
    con.close()


def test_ambiguous_names_never_merge_items():
    names = {
        **NAMES,
        "Metadata/Items/Currency/CurrencyAfflictionOrbCurrency": BaseItem(
            "Metadata/Items/Currency/CurrencyAfflictionOrbCurrency", "Fine Delirium Orb", "x"
        ),
        "Metadata/Items/Currency/CurrencyAfflictionOrbHarbinger": BaseItem(
            "Metadata/Items/Currency/CurrencyAfflictionOrbHarbinger", "Fine Delirium Orb", "x"
        ),
    }
    rows = exchange_loader.resolve_names(
        [
            DIVINE,
            "Metadata/Items/Currency/CurrencyAfflictionOrbHarbinger",
            "Metadata/Items/Currency/CurrencyAfflictionOrbCurrency",
            "Metadata/Items/Unknown/Thing",
        ],
        names,
    )
    ids = [r[1] for r in rows]
    assert ids[0] == "currency:divine-orb"
    assert len(set(ids)) == 4
    assert rows[1][2] == "Fine Delirium Orb (CurrencyAfflictionOrbHarbinger)"
    assert rows[3][2] == "Thing"


def test_market_services(settings):
    from exiledbroker.services import market

    con, _, _ = load(settings)
    assert market.tracked_groups(con)["group_id"].to_list() == ["currency"]
    table = market.summary(con, "Mirage", ["currency"], "divine")
    # Sorted by average price, most expensive first.
    assert table["name"].to_list()[:2] == ["Mirror of Kalandra", "Divine Orb"]
    s = table.row(0, named=True)
    # All three hours fall in day 1: (400 + 500) divines over 2 mirrors.
    assert s["day_1"] == 450 and s["average"] == 450 and s["trend"] == [450]
    h = market.hourly(con, "Mirage", ["currency:mirror-of-kalandra"], "divine")
    assert h["value"].to_list() == [400, 500]
    assert h.row(0, named=True)["low"] == pytest.approx(350)
    with pytest.raises(ValueError):
        market.summary(con, "Mirage", ["currency"], "exalt")
    con.close()


def test_core_pool_limits_groups(settings):
    from exiledbroker.ingest.core_pool import CorePool

    con, _, _ = load(settings)
    con.execute(
        "INSERT INTO item (id, game, canonical_name, category) VALUES "
        "('currency:orb-of-fusing', 'poe1', 'Orb of Fusing', 'currency'), "
        "('currency:coffin-crafts', 'poe1', 'Coffin Crafts', 'currency')"
    )

    def currency(pool):
        mappings.refresh_tracked(con, pool)
        q = "SELECT i.canonical_name FROM tracked_item t JOIN item i ON i.id = t.item_id"
        return sorted(r[0] for r in db.rows(con, q))

    # No snapshot yet: only the always-core five that exist here.
    assert currency(None) == ["Chaos Orb", "Divine Orb", "Mirror of Kalandra", "Orb of Alchemy"]
    listed = {"Chaos Orb", "Divine Orb", "Orb of Fusing", "Mirror of Kalandra"}
    pool = CorePool(listed={"currency": listed})
    # The pool decides: Alchemy isn't listed for the current league, Fusing is.
    assert currency(pool) == ["Chaos Orb", "Divine Orb", "Mirror of Kalandra", "Orb of Fusing"]
    pool.exclude, pool.include = {"Mirror of Kalandra"}, {"currency": {"Coffin Crafts"}}
    assert currency(pool) == ["Chaos Orb", "Coffin Crafts", "Divine Orb", "Orb of Fusing"]
    con.close()


def test_refresh_pool_replaces_snapshot_and_reads_overrides(settings, tmp_path):
    from exiledbroker.ingest import core_pool

    lists = {
        "Currency": [
            {"name": "Exalted Orb", "category": "Currency"},
            {"name": "Foulborn Exalted Orb", "category": "Keepers"},
            {"name": "Tainted Catalyst", "category": "Catalysts"},
        ],
        "Essence": [{"name": "Deafening Essence of Woe", "category": "Essence"}],
        "Scarab": [{"name": "Horned Scarab of Bloodlines", "category": "Scarab"}],
    }

    def handler(request):
        if request.url.host == "raw.githubusercontent.com":
            return httpx.Response(200, text=FILTER)
        if request.url.path.endswith("/leagues"):
            return httpx.Response(200, json=[{"id": "Allflame", "name": "Allflame"}])
        return httpx.Response(200, json={"items": lists[request.url.params["type"]]})

    old = core_pool.snapshot_path(settings, "currency")
    old.parent.mkdir(parents=True)
    old.write_text('{"league": "Old", "names": ["Old League Orb"]}')
    settings.core_pool_file = tmp_path / "core_pool.toml"
    settings.core_pool_file.write_text(
        'exclude = ["Exalted Orb"]\n[include]\ncurrency = ["Coffin"]\n'
    )

    with PoliteClient(settings, transport=httpx.MockTransport(handler)) as client:
        pool = core_pool.refresh_pool(client, settings)
    # Replaced, not merged: the old league's orb is gone. Catalysts are left out.
    assert pool.listed["currency"] == {"Exalted Orb", "Foulborn Exalted Orb"}
    assert pool.league == "Allflame"
    assert pool.allows("currency", "Exalted Orb") is False  # excluded by config
    assert pool.allows("currency", "Coffin") is True  # included by config
    assert pool.allows("divination", "Coffin") is False  # ...in currency only
    assert pool.allows("scarab", "Horned Scarab of Bloodlines") is True
    assert pool.allows("essence", "Deafening Essence of Rage") is False
    assert pool.allows("divination", "The Doctor") is True
    assert pool.allows("divination", "Rain of Chaos") is False  # hidden tier
    assert core_pool.load_pool(settings).listed == pool.listed


def test_turn_in_margins(settings):
    from exiledbroker.services import divination

    con, _, _ = load(settings)
    # Stand-in card: 300 "cards" (Orb of Alchemy, 0.2c in hour 0) turn into 1 Divine (30c).
    con.execute(
        "INSERT INTO divination_card (item_id, name, stack_size, reward_kind, reward_name, "
        "reward_quantity, reward_item_id, reward_text, filter_tier, followed, reward_fixed) "
        "VALUES ('currency:orb-of-alchemy', 'Test Card', 300, 'currency', 'Divine Orb', 1, "
        "'currency:divine-orb', '', 't3', TRUE, TRUE), "
        "('currency:mirror-of-kalandra', 'Unfollowed', 1, 'currency', 'Divine Orb', 1, "
        "'currency:divine-orb', '', 't5', FALSE, TRUE)"
    )
    hourly = divination.hourly_turn_ins(con, "Mirage")
    # Only hour 0 has both the card and its reward; the unfollowed card is ignored.
    assert hourly.select("card", "set_cost", "reward_value", "margin").rows() == [
        ("Test Card", 60.0, 30.0, -30.0)
    ]
    s = divination.turn_in_summary(con, "Mirage").row(0, named=True)
    assert (s["name"], s["hours"], s["profitable_share"], s["avg_margin_pct"]) == (
        "Test Card",
        1,
        0.0,
        -0.5,
    )
    assert divination.hourly_turn_ins(con, "Mirage", card_ids=[]).is_empty()
    con.close()
