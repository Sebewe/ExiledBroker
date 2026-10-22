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
from exiledbroker.normalize import exchange_loader
from exiledbroker.storage import db
from exiledbroker.storage import dumps as dump_store

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
    groups = dict(db.rows(con, "SELECT item_id, group_id FROM tracked_item"))
    assert groups == {
        "currency:chaos-orb": "chaos",
        "currency:divine-orb": "divine",
        "currency:mirror-of-kalandra": "mirror",
        "currency:orb-of-alchemy": "alchemy",
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
    groups = market.tracked_groups(con)["group_id"].to_list()
    assert groups == ["chaos", "divine", "alchemy", "mirror"]
    s = market.summary(con, "Mirage", ["mirror"], "divine").row(0, named=True)
    # All three hours fall in day 1: (400 + 500) divines over 2 mirrors.
    assert s["name"] == "Mirror of Kalandra" and s["day_1"] == 450 and s["trend"] == [450]
    h = market.hourly(con, "Mirage", ["currency:mirror-of-kalandra"], "divine")
    assert h["value"].to_list() == [400, 500]
    assert h.row(0, named=True)["low"] == pytest.approx(350)
    with pytest.raises(ValueError):
        market.summary(con, "Mirage", ["mirror"], "exalt")
    con.close()
