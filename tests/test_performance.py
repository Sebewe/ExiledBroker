"""Performance budgets: what each API endpoint (each page of the site) reads from the
database and what each live update fetches and writes, measured on the real-data replay (Mirage's first 30 hours,
see test_live_pipeline.py).

The budgets are a few times today's measurements. They catch a page that starts
pulling raw hourly rows, or an update that downloads more than the new hours. If a
change legitimately needs more, raise the budget in the same change and say why.
`eb perf report` prints the same measurements for the local database."""

from datetime import timedelta

import pytest

from exiledbroker.ingest import currency_exchange as cx
from exiledbroker.ingest.live import sync_live
from exiledbroker.storage import db
from test_currency_exchange import FakeExchange, client_for
from test_live_pipeline import LAUNCH, PAGES, settings  # noqa: F401

EARLIEST = cx.from_ts(LAUNCH - 72 * 3600)
HOURS = 30


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


def describe(meter: db.Meter) -> str:
    top = sorted(meter.by_caller().values(), key=lambda q: -q.bytes)[:5]
    return "; ".join(f"{q.caller}: {q.rows} rows, {q.bytes:,} B" for q in top)


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


# --- The site's API ---------------------------------------------------------------
# Rows read per cold call (cache empty) and the JSON size, at 30 hours. Today's
# measurements in comments. Cached calls read only the data version.
API_BUDGET = {
    "/api/status": (20, 2_000),  # 4 rows, 196 B
    "/api/live/{league}/loops": (120, 4_000),  # 26 rows, 351 B
    "/api/live/{league}/card-flips?lookback=48": (100, 8_000),  # 24 rows, 940 B
    "/api/arbitrage?league={league}&min_hours=1": (60, 8_000),  # 9 rows, 824 B
    "/api/cards/{league}": (30, 8_000),  # 4 rows, 1.2 KB
    "/api/missed/{league}": (500, 12_000),  # 121 rows, 7.4 KB (Allflame: ~3k rows, 10 KB)
    "/api/market/{league}/summary?group=currency&group=divination": (150, 30_000),  # 32, 5.6 KB
    "/api/market/{league}/hourly?item_id=currency:divine-orb": (150, 24_000),  # 30, 4.6 KB
    "/api/launch/picks": (60, 2_000),  # no picks in the replay; up to 30 picks hosted
}
# Endpoints about one league must not read more as other leagues' history accumulates,
# except a row per league in league lists.
ONE_LEAGUE_ENDPOINTS = [
    "/api/status",
    "/api/live/{league}/loops",
    "/api/live/{league}/card-flips?lookback=48",
    "/api/arbitrage?league={league}&min_hours=1",
    "/api/cards/{league}",
    "/api/missed/{league}",
]
PER_LEAGUE_ROWS = 2


def endpoint_reads(path: str) -> tuple[db.Meter, int]:
    from fastapi.testclient import TestClient

    from exiledbroker.api import app as app_module
    from exiledbroker.api import deps

    deps.reset()
    client = TestClient(app_module.create_app())
    with db.metered() as meter:
        r = client.get(path.format(league="Mirage"))
    assert r.status_code == 200, r.text
    return meter, len(r.content)


@pytest.mark.parametrize("path", list(API_BUDGET))
def test_endpoint_reads_stay_small(loaded, path):
    max_rows, max_bytes = API_BUDGET[path]
    meter, size = endpoint_reads(path)
    assert meter.rows <= max_rows, describe(meter)
    assert size <= max_bytes, size


@pytest.mark.parametrize("path", ONE_LEAGUE_ENDPOINTS)
def test_one_league_endpoints_do_not_grow_with_history(loaded, path):
    before, _ = endpoint_reads(path)
    _add_past_leagues(loaded, 4)
    after, _ = endpoint_reads(path)
    allowed = 4 * PER_LEAGUE_ROWS
    assert after.rows <= before.rows + allowed, f"{before.rows} → {after.rows}: {describe(after)}"
