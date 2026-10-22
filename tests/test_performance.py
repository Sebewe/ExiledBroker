"""Performance budgets: what each page reads from the database and what each live
update fetches and writes, measured on the real-data replay (Mirage's first 30 hours,
see test_live_pipeline.py).

The budgets are a few times today's measurements. They catch a page that starts
pulling raw hourly rows, or an update that downloads more than the new hours. If a
change legitimately needs more, raise the budget in the same change and say why.
`eb perf report` prints the same measurements for the local database."""

from datetime import timedelta

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from exiledbroker.ingest import currency_exchange as cx
from exiledbroker.ingest.live import sync_live
from exiledbroker.storage import db
from test_currency_exchange import FakeExchange, client_for
from test_live_pipeline import APP, LAUNCH, PAGES, PAGES_TO_RUN, settings  # noqa: F401

EARLIEST = cx.from_ts(LAUNCH - 72 * 3600)
HOURS = 30

# Rows and bytes one page view reads (cache cold), measured at 30 hours. Today's
# measurements in comments.
PAGE_BUDGET = {
    "live": (150, 20_000),  # 37 rows, 5 KB
    "market": (800, 64_000),  # 211 rows, 17 KB (hourly + daily chart of one item)
    "cards": (200, 24_000),  # 53 rows, 6 KB
    "arbitrage": (150, 20_000),  # 38 rows, 5 KB
    "analysis": (150, 20_000),  # 38 rows, 5 KB
    "data": (150, 20_000),  # 39 rows, 5 KB
}


def update(s, server, hours_in: int):
    server.now = LAUNCH + hours_in * 3600
    now = cx.from_ts(server.now) + timedelta(minutes=10)
    with client_for(s, server) as client:
        return sync_live(client, s, "Mirage", now=now, earliest=EARLIEST)


@pytest.fixture
def loaded(settings):  # noqa: F811
    server = FakeExchange(PAGES, now=LAUNCH)
    update(settings, server, HOURS)
    return settings


def page_reads(page: str) -> db.Meter:
    """What one cold view of `page` reads (not the default page it opens on first)."""
    at = AppTest.from_file(APP, default_timeout=120).run()
    st.cache_data.clear()
    with db.metered() as meter:
        at.switch_page(f"app_pages/{page}.py").run()
    assert not at.exception, (page, [e.message for e in at.exception])
    return meter


def describe(meter: db.Meter) -> str:
    top = sorted(meter.by_caller().values(), key=lambda q: -q.bytes)[:5]
    return "; ".join(f"{q.caller}: {q.rows} rows, {q.bytes:,} B" for q in top)


@pytest.mark.parametrize("page", PAGES_TO_RUN)
def test_page_reads_stay_small(loaded, page):
    max_rows, max_bytes = PAGE_BUDGET[page]
    meter = page_reads(page)
    assert meter.queries, "nothing measured: is the page reading through storage.db?"
    assert meter.rows <= max_rows, describe(meter)
    assert meter.bytes <= max_bytes, describe(meter)


def _add_past_leagues(s, n: int) -> None:
    """Copy the replayed league n times, each a year earlier: n more leagues of
    stored history, as on a database that has kept old leagues."""
    with db.session(s.db_path) as con:
        for i in range(1, n + 1):
            lid, shift = f"poe1-past{i}", f"INTERVAL {i * 365} DAY"
            con.execute(
                f"INSERT INTO league SELECT * REPLACE ('{lid}' AS id, 'Past{i}' AS name, "
                f"start_at - {shift} AS start_at, launched_at - {shift} AS launched_at) "
                "FROM league WHERE id = 'poe1-mirage'"
            )
            for table, column in (
                ("price_observation", "observed_at"),
                ("cross_market_hour", "observed_at"),
                ("exchange_hour_loaded", "hour"),
            ):
                con.execute(
                    f"INSERT INTO {table} SELECT * REPLACE ('{lid}' AS league_id, "
                    f"{column} - {shift} AS {column}) FROM {table} "
                    "WHERE league_id = 'poe1-mirage'"
                )


# Pages about the running league must not read more as history accumulates, except
# a row per league in league lists (pickers, the calendar). The others compare
# leagues, so they may grow by a small summary per league.
PER_LEAGUE_ROWS = {"live": 2, "cards": 2, "arbitrage": 2, "data": 2, "market": 60, "analysis": 60}


@pytest.mark.parametrize("page", PAGES_TO_RUN)
def test_page_reads_do_not_grow_with_history(loaded, page):
    before = page_reads(page)
    _add_past_leagues(loaded, 4)
    after = page_reads(page)
    allowed = 4 * PER_LEAGUE_ROWS[page]
    assert after.rows <= before.rows + allowed, (
        f"{before.rows} → {after.rows} rows. Now: {describe(after)}"
    )


def _runs(s) -> list[dict]:
    with db.session(s.db_path, read_only=True) as con:
        df = db.frame(con, "SELECT * FROM ingest_run ORDER BY started_at")
    return df.to_dicts()


def test_each_update_fetches_only_new_hours_and_is_recorded(settings):  # noqa: F811
    server = FakeExchange(PAGES, now=LAUNCH)
    steps = (1, 2, 3, 6, 12, 24, 30)
    for hours_in in steps:
        update(settings, server, hours_in)
    update(settings, server, 30)  # nothing new published

    runs = _runs(settings)
    assert len(runs) == len(steps) + 1
    previous = 0
    for run, hours_in in zip(runs, steps, strict=False):
        new_hours = hours_in - previous
        previous = hours_in
        assert run["state"] == "updated" and run["error"] is None
        # One request per new hour (the latest-hour check is one of them). Reference
        # data is fresh, so no checks; the first update also finds the launch hour.
        extra = 8 if hours_in == 1 else 0
        assert run["requests"] <= new_hours + extra, run
        assert run["bytes_received"] > 0
        # Rows written: at most the kept items per hour, and never the whole league.
        assert run["hours_added"] == new_hours
        assert run["rows_added"] <= new_hours * 20, run
        assert run["seconds"] < 30
    idle = runs[-1]
    assert idle["state"] == "unchanged"
    assert (idle["requests"], idle["rows_added"], idle["hours_added"]) <= (1, 0, 0), idle


def test_a_failed_update_is_recorded(settings):  # noqa: F811
    server = FakeExchange(PAGES, now=LAUNCH)

    def broken(request):
        raise OSError("disk full")

    server.handler = broken
    with pytest.raises(OSError):
        update(settings, server, 3)
    [run] = _runs(settings)
    assert run["state"] == "failed" and "disk full" in run["error"]
