"""End to end on real API output: replay Mirage's first hours exactly as GGG's
exchange API published them (tests/fixtures/mirage_launch.json.gz), one hour at a
time, and after each update check what the site's API reports (tests/test_api.py
calls every endpoint the same way).

This is what a live league looks like: nothing at first, then hours arriving with
gaps (no Divine trades for the first two hours, items that haven't traded yet)."""

import gzip
import json
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from exiledbroker.config import Settings
from exiledbroker.ingest import core_pool, item_names, loot_filter, reference
from exiledbroker.ingest import currency_exchange as cx
from exiledbroker.ingest.http import PoliteClient
from exiledbroker.ingest.live import sync_live
from exiledbroker.storage import db
from test_currency_exchange import FakeExchange, client_for

with gzip.open(Path(__file__).parent / "fixtures" / "mirage_launch.json.gz", "rt") as _f:
    FIXTURE = json.load(_f)
LAUNCH = FIXTURE["launch"]
PAGES = {int(ts): page["markets"] for ts, page in FIXTURE["pages"].items()}


def store_reference_data(s: Settings) -> None:
    """Names (RePoE) and the core pool / loot-filter snapshots, stored in the database
    (reference_data) as `eb live` leaves them, fresh so nothing is re-fetched."""
    names = {v["name"] for v in FIXTURE["base_items"].values()}
    cards = sorted(
        v["name"] for v in FIXTURE["base_items"].values() if v.get("item_class") == "DivinationCard"
    )
    ninja = f"{s.poe_ninja_base_url}/poe1/api/economy"
    with db.session(s.db_path) as con:
        db.init_schema(con)
        reference.put(con, item_names.KEY, FIXTURE["base_items"], s.repoe_base_items_url)
        reference.put(con, core_pool.LEAGUES_KEY, [{"id": "Mirage"}], f"{ninja}/leagues")
        for group, (ninja_type, _) in core_pool.SOURCES.items():
            reference.put(
                con,
                core_pool.snapshot_key(group),
                {"league": "Mirage", "names": sorted(names)},
                f"{ninja}/exchange/current/overview?league=Mirage&type={ninja_type}",
            )
        reference.put(
            con,
            loot_filter.KEY,
            {"tiers": {c: "t1" for c in cards}, "shown": cards},
            s.loot_filter_url.format(strictness=s.loot_filter_strictness),
        )


@pytest.fixture
def settings(tmp_path, monkeypatch):
    monkeypatch.setenv("EB_DATA_DIR", str(tmp_path))
    s = Settings(data_dir=tmp_path, request_min_interval=0)
    store_reference_data(s)
    return s


def site_status() -> dict:
    """What the site's API says about the leagues right now (caches cleared)."""
    from exiledbroker.api import app as app_module
    from exiledbroker.api import deps

    deps.reset()
    r = TestClient(app_module.create_app()).get("/api/status")
    assert r.status_code == 200, r.text
    return r.json()


def test_live_league_hour_by_hour(settings):
    server = FakeExchange(PAGES, now=LAUNCH)
    earliest = cx.from_ts(LAUNCH - 72 * 3600)

    def update(hours_in: int):
        server.now = LAUNCH + hours_in * 3600  # this hour is still being traded
        now = cx.from_ts(server.now) + timedelta(minutes=10)
        with client_for(settings, server) as client:
            return sync_live(client, settings, "Mirage", now=now, earliest=earliest)

    # Before the first hour is published, the league isn't trading anywhere yet.
    status = update(0)
    assert status.state == "not_running"
    assert not settings.db_path.exists() or site_status()["leagues"] == []

    for hours_in in (1, 2, 3, 6, 12, 24, 30):
        status = update(hours_in)
        latest = cx.from_ts(LAUNCH + (hours_in - 1) * 3600)
        assert status.state == "updated", status
        assert status.latest_hour == latest
        assert status.fetched >= 1  # at least the newly published hour
        site = site_status()["leagues"]
        with db.session(read_only=True) as con:
            traded = db.rows(
                con,
                "SELECT max(observed_at), count(DISTINCT observed_at) FROM price_observation "
                "WHERE source = 'ggg-exchange-hourly'",
            )[0]
        assert [lg["name"] for lg in site] == ["Mirage"]
        if traded[1] == 0:
            # Mirage's launch hour: published, but nothing had traded yet.
            assert site[0]["latest_hour"] is None and site[0]["launched_at"]
        else:
            assert site[0]["latest_hour"] == f"{traded[0]:%Y-%m-%dT%H:%M:%S}Z"
        assert site[0]["hours"] == hours_in
        assert traded[1] <= hours_in

    # After 30 hours: prices, cards and cross-market hours are all there.
    with db.session(read_only=True) as con:
        divine = db.scalar(
            con,
            "SELECT median(chaos_value) FROM price_observation "
            "WHERE item_id = 'currency:divine-orb' AND day_offset >= 1",
        )
        cross = db.scalar(con, "SELECT count(*) FROM cross_market_hour")
        cards = db.scalar(con, "SELECT count(*) FROM divination_card WHERE followed")
    assert 50 < divine < 200  # Mirage's day-2 Divine traded around 86–100c
    assert cross > 0 and cards == 2

    # Repeating an update with nothing new published fetches nothing and changes nothing.
    again = update(30)
    assert (again.state, again.fetched) == ("unchanged", 0)


def test_live_update_survives_an_interrupted_hour(settings):
    """A crash mid-update leaves no partial pages; the next update just carries on."""
    server = FakeExchange(PAGES, now=LAUNCH + 6 * 3600)
    now = cx.from_ts(server.now) + timedelta(minutes=10)
    earliest = cx.from_ts(LAUNCH - 72 * 3600)
    real = server.handler
    crash_at = LAUNCH + 3 * 3600  # mid-window: hours 0–2 are on disk by then

    def flaky(request):
        if int(request.url.path.rsplit("/", 1)[-1]) == crash_at:
            raise KeyboardInterrupt
        return real(request)

    server.handler = flaky
    with client_for(settings, server) as client, pytest.raises(KeyboardInterrupt):
        sync_live(client, settings, "Mirage", now=now, earliest=earliest)
    assert not list(settings.exchange_raw_dir.glob("*.tmp"))
    assert cx.page_path(settings, LAUNCH + 2 * 3600).exists()
    assert not cx.page_path(settings, crash_at).exists()
    server.handler = real
    with client_for(settings, server) as client:
        status = sync_live(client, settings, "Mirage", now=now, earliest=earliest)
    assert status.state == "updated" and status.latest_hour == cx.from_ts(LAUNCH + 5 * 3600)


def _hours_loaded(settings) -> int:
    with db.session(read_only=True) as con:
        return db.scalar(con, "SELECT count(*) FROM exchange_hour_loaded")


def test_worker_with_a_wiped_disk_fetches_only_new_hours(settings, monkeypatch):
    """On a server the disk may be wiped between runs: the database decides what's
    missing, so each hourly update needs only the new hour (cost issue #2)."""
    import shutil

    from exiledbroker.normalize import exchange_loader

    server = FakeExchange(PAGES, now=LAUNCH + 8 * 3600)
    earliest = cx.from_ts(LAUNCH - 72 * 3600)

    def update():
        now = cx.from_ts(server.now) + timedelta(minutes=10)
        with client_for(settings, server) as client:
            return sync_live(client, settings, "Mirage", now=now, earliest=earliest)

    assert update().state == "updated" and _hours_loaded(settings) == 8
    shutil.rmtree(settings.exchange_raw_dir)  # a fresh container: no pages on disk

    server.now += 3600  # one more hour published
    before = len(server.requests)
    status = update()
    new_requests = server.requests[before:]
    # The latest-hour check and the new hour, not the 8 hours already loaded.
    assert set(new_requests) == {LAUNCH + 8 * 3600}
    assert (status.hours_added, status.hours_removed) == (1, 0)
    assert _hours_loaded(settings) == 9

    # A rebuild (new loader version) on a wiped disk re-fetches the whole window,
    # so the data can't shrink to just the pages that happen to be on disk.
    shutil.rmtree(settings.exchange_raw_dir)
    monkeypatch.setattr(exchange_loader, "LOADER_VERSION", exchange_loader.LOADER_VERSION + 1)
    status = update()
    assert status.state == "updated" and _hours_loaded(settings) == 9


def test_reference_data_is_never_downloaded_again_if_unchanged(settings):
    """RePoE names, the core pool and the loot filter live in the database. A due check
    sends our version tag and an unchanged source answers 304 with no body; between
    checks there are no reference requests at all (cost issue #6)."""
    import httpx

    server = FakeExchange(PAGES, now=LAUNCH + 3 * 3600)
    reference_hosts = {"repoe-fork.github.io", "raw.githubusercontent.com", "poe.ninja"}
    log = []  # (host, status, body bytes)
    current = {"etag": '"v1"', "repoe": FIXTURE["base_items"]}

    def handler(request):
        host = request.url.host
        if host not in reference_hosts:
            return server.handler(request)
        if request.headers.get("If-None-Match") == current["etag"]:
            log.append((host, 304, 0))
            return httpx.Response(304)
        if host == "repoe-fork.github.io":
            r = httpx.Response(200, json=current["repoe"], headers={"ETag": current["etag"]})
        else:  # only RePoE changes in this test
            return httpx.Response(304)
        log.append((host, 200, len(r.content)))
        return r

    with db.session(settings.db_path) as con:  # every source last checked 8 days ago
        con.execute(
            "UPDATE reference_data SET etag = ?, checked_at = fetched_at - INTERVAL 8 DAY",
            ['"v1"'],
        )

    def update():
        now = cx.from_ts(server.now) + timedelta(minutes=10)
        with PoliteClient(settings, transport=httpx.MockTransport(handler)) as client:
            return sync_live(
                client, settings, "Mirage", now=now, earliest=cx.from_ts(LAUNCH - 72 * 3600)
            )

    # 1. Checks are due: every source is asked "changed since v1?" and nothing downloads.
    assert update().state == "updated"
    assert log and all(status == 304 and size == 0 for _, status, size in log)
    assert {host for host, _, _ in log} == reference_hosts

    # 2. Within the check interval: no reference requests at all.
    log.clear()
    server.now += 3600
    assert update().state == "updated"
    assert log == []

    # 3. RePoE really changes: due again, it's downloaded once with its new tag.
    current.update(etag='"v2"', repoe={**FIXTURE["base_items"]})
    with db.session(settings.db_path) as con:
        con.execute(
            "UPDATE reference_data SET checked_at = checked_at - INTERVAL 8 DAY WHERE key = ?",
            [item_names.KEY],
        )
    server.now += 3600
    update()
    downloads = [(h, s_) for h, s_, size in log if size > 0]
    assert downloads == [("repoe-fork.github.io", 200)]
    with db.session(settings.db_path, read_only=True) as con:
        assert (
            db.scalar(con, "SELECT etag FROM reference_data WHERE key = ?", [item_names.KEY])
            == '"v2"'
        )
