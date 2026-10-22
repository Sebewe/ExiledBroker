"""Live mode: finding a running league's launch and keeping its latest hours loaded,
as hours come out of GGG's exchange API one at a time."""

from datetime import UTC, datetime

import pytest

from exiledbroker.config import Settings
from exiledbroker.ingest import currency_exchange as cx
from test_currency_exchange import CHAOS, DIVINE, FakeExchange, client_for, market

HOUR = cx.HOUR
EARLIEST = datetime(2026, 1, 1, tzinfo=UTC)
E0 = cx.to_ts(EARLIEST)


@pytest.fixture
def settings(tmp_path):
    return Settings(data_dir=tmp_path, request_min_interval=0)


def league_pages(launch_ts: int, now_ts: int, league: str = "Allflame") -> dict:
    """Every hour from EARLIEST to now; the league trades from its launch on."""
    pages = {}
    for ts in range(E0, now_ts, HOUR):
        markets = [market("Standard", CHAOS, DIVINE, 100, 1)]
        if ts >= launch_ts:
            markets.append(market(league, CHAOS, DIVINE, 300, 10))
        pages[ts] = markets
    return pages


@pytest.mark.parametrize("launch_offset", [0, 1, 2, 3, 7, 100, 717, 718])
def test_find_launch(settings, launch_offset):
    now_ts = E0 + 720 * HOUR + 30 * 60  # 30 minutes into hour 720
    launch_ts = E0 + launch_offset * HOUR
    server = FakeExchange(league_pages(launch_ts, now_ts), now=cx.to_ts(cx.from_ts(now_ts)))
    with client_for(settings, server) as client:
        found = cx.find_launch(
            client, settings, "Allflame", now=cx.from_ts(now_ts), earliest=EARLIEST
        )
    assert found == cx.from_ts(launch_ts)
    assert len(set(server.requests)) <= 14  # a binary search, not a scan


def test_find_launch_before_any_trades(settings):
    now_ts = E0 + 48 * HOUR
    server = FakeExchange(league_pages(now_ts + HOUR, now_ts), now=now_ts)
    with client_for(settings, server) as client:
        assert (
            cx.find_launch(client, settings, "Allflame", now=cx.from_ts(now_ts), earliest=EARLIEST)
            is None
        )


def test_find_launch_tolerates_publishing_delay(settings):
    # It's 3 minutes past the hour and the previous hour isn't published yet.
    now_ts = E0 + 100 * HOUR + 180
    server = FakeExchange(league_pages(E0 + 40 * HOUR, now_ts), now=E0 + 99 * HOUR)
    with client_for(settings, server) as client:
        found = cx.find_launch(
            client, settings, "Allflame", now=cx.from_ts(now_ts), earliest=EARLIEST
        )
    assert found == cx.from_ts(E0 + 40 * HOUR)


def test_sync_recent_window_and_increments(settings):
    launch_ts = E0 + 10 * HOUR
    pages = league_pages(launch_ts, E0 + 200 * HOUR)
    server = FakeExchange(pages, now=E0 + 50 * HOUR)
    launched = cx.from_ts(launch_ts)
    with client_for(settings, server) as client:
        # Hour 50 is being traded; 49 is the latest published. 24h lookback.
        r = cx.sync_recent(
            client,
            settings,
            "Allflame",
            launched,
            24,
            now=cx.from_ts(E0 + 50 * HOUR + 600),
            keep_launch_days=0,
        )
        assert list(r.window.hours) == list(range(E0 + 26 * HOUR, E0 + 50 * HOUR, HOUR))
        assert r.fetched == 24
        # By default the league's first days are kept too: launch + recent, no overlap.
        r = cx.sync_recent(
            client,
            settings,
            "Allflame",
            launched,
            24,
            now=cx.from_ts(E0 + 50 * HOUR + 600),
            keep_launch_days=0.5,
        )
        launch_hours = list(range(launch_ts, launch_ts + 12 * HOUR, HOUR))
        assert r.window.hours == launch_hours + list(range(E0 + 26 * HOUR, E0 + 50 * HOUR, HOUR))
        assert r.fetched == 12
        # An hour later: only the newly published hour is fetched.
        server.now = E0 + 51 * HOUR
        r = cx.sync_recent(
            client,
            settings,
            "Allflame",
            launched,
            24,
            now=cx.from_ts(E0 + 51 * HOUR + 600),
            keep_launch_days=0.5,
        )
        assert r.fetched == 1 and r.window.hours[-1] == E0 + 50 * HOUR
        # Early in a league the window starts at the launch, not before it.
        r = cx.sync_recent(
            client, settings, "Allflame", launched, 24 * 30, now=cx.from_ts(E0 + 51 * HOUR + 600)
        )
        assert r.window.hours[0] == launch_ts
        # Just past the hour, before GGG publishes it: stop at the last published hour.
        server.now = E0 + 51 * HOUR  # hour 51 not out yet
        r = cx.sync_recent(
            client, settings, "Allflame", launched, 24, now=cx.from_ts(E0 + 52 * HOUR + 60)
        )
        assert r.reached_end and r.window.hours[-1] == E0 + 50 * HOUR
