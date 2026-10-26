"""Cookie-free usage counts (api/usage.py): what's counted, what's never stored, and that
a restart, a new day and a new period count each visitor exactly once."""

import os
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from exiledbroker.api import usage
from exiledbroker.config import Settings
from exiledbroker.storage import db

UA = "Mozilla/5.0 (X11; Linux x86_64) Firefox/140.0"
DAY = datetime(2026, 10, 26, 12, tzinfo=UTC)


class Clock:
    def __init__(self, at: datetime = DAY):
        self.at = at

    def __call__(self) -> datetime:
        return self.at


PG_URL = os.environ.get("EB_TEST_POSTGRES_URL")
TABLES = ["usage_daily", "usage_salt", "usage_visitor", "usage_seen", "usage_period"]


@pytest.fixture(params=["duckdb", "postgres"])
def connect(request, tmp_path):
    """A writable connection to the site's database: DuckDB, and Postgres (the hosted
    one's engine) when EB_TEST_POSTGRES_URL points at a throwaway database."""
    if request.param == "duckdb":
        path = tmp_path / "usage.duckdb"

        @contextmanager
        def open_():
            with db.session(path) as con:
                yield con

        return open_
    if not PG_URL:
        pytest.skip("EB_TEST_POSTGRES_URL is not set")
    import psycopg

    with psycopg.connect(PG_URL, autocommit=True) as pg:
        for t in TABLES:
            pg.execute(f"DROP TABLE IF EXISTS {t}")

    @contextmanager
    def open_pg():
        with psycopg.connect(PG_URL, autocommit=True) as con:
            yield con

    return open_pg


def table(connect, sql: str) -> list[tuple]:
    with connect() as con:
        return db.rows(con, sql)


def test_counts_views_and_distinct_visitors(connect):
    clock = Clock()
    u = usage.Usage(connect, clock=clock)
    assert u.record("page:/", "1.1.1.1", UA)
    assert u.record("page:/", "1.1.1.1", UA)
    assert u.record("page:/launch", "1.1.1.1", UA)
    assert u.record("page:/", "2.2.2.2", UA)
    assert u.record("feature:theme", "2.2.2.2", UA)
    assert u.flush() == 9  # five events, plus four page views counted for the site
    rows = table(connect, "SELECT event, views, visitors FROM usage_daily ORDER BY event")
    assert rows == [
        ("feature:theme", 1, 1),
        ("page:/", 3, 2),
        ("page:/launch", 1, 1),
        ("site", 4, 2),
    ]
    stats = u.stats()
    assert stats["total"]["views"] == 4
    assert stats["periods"] == [
        {"period": "2026-10", "visitors": 2, "returning": 0, "finished": False}
    ]
    assert [e["event"] for e in stats["events"]] == ["page:/", "feature:theme", "page:/launch"]


def test_ignores_unknown_events_bots_and_floods(connect):
    u = usage.Usage(connect, clock=Clock())
    assert not u.record("page:/admin", "1.1.1.1", UA)
    assert not u.record("anything", "1.1.1.1", UA)
    assert not u.record("page:/", "1.1.1.1", "")
    assert not u.record("page:/", "1.1.1.1", "Googlebot/2.1")
    assert not u.record("page:/", "1.1.1.1", "python-httpx/0.28")
    for _ in range(usage.MAX_PER_DAY + 10):
        u.record("page:/", "3.3.3.3", UA)
    u.flush()
    assert table(connect, "SELECT views FROM usage_daily WHERE event = 'page:/'") == [
        (usage.MAX_PER_DAY,)
    ]


def test_never_stores_the_ip_or_user_agent(connect):
    u = usage.Usage(connect, clock=Clock())
    u.record("page:/", "203.0.113.7", UA)
    u.flush()
    with connect() as con:
        dump = repr([db.rows(con, f"SELECT * FROM {t}") for t in TABLES])
    assert "203.0.113.7" not in dump and "Firefox" not in dump


def test_a_restart_doesnt_count_a_visitor_twice(connect):
    clock = Clock()
    first = usage.Usage(connect, clock=clock)
    first.record("page:/", "1.1.1.1", UA)
    first.flush()
    again = usage.Usage(connect, clock=clock)  # a deploy: same salt, today's seen pairs
    again.record("page:/", "1.1.1.1", UA)
    again.flush()
    assert table(connect, "SELECT views, visitors FROM usage_daily WHERE event = 'site'") == [
        (2, 1)
    ]


def test_returning_visitors_and_closing_a_period(connect):
    clock = Clock(datetime(2026, 10, 30, 12, tzinfo=UTC))
    u = usage.Usage(connect, clock=clock)
    u.record("page:/", "1.1.1.1", UA)
    u.record("page:/", "2.2.2.2", UA)
    u.flush()
    clock.at += timedelta(days=1)  # Oct 31: visitor 1 comes back
    u.record("page:/launch", "1.1.1.1", UA)
    u.record("page:/launch", "1.1.1.1", UA)
    assert u.stats()["periods"][-1] == {
        "period": "2026-10",
        "visitors": 2,
        "returning": 1,
        "finished": False,
    }
    # Yesterday's seen pairs are gone; only today's remain.
    assert {r[0] for r in table(connect, "SELECT day FROM usage_seen")} == {date(2026, 10, 31)}

    clock.at += timedelta(days=1)  # November: October is closed and its salt deleted
    u.record("page:/", "1.1.1.1", UA)
    u.flush()
    assert table(connect, "SELECT * FROM usage_period") == [("2026-10", 2, 1)]
    assert table(connect, "SELECT period FROM usage_salt") == [("2026-11",)]
    assert table(connect, "SELECT period, days FROM usage_visitor") == [("2026-11", 1)]
    periods = u.stats()["periods"]
    assert [p["period"] for p in periods] == ["2026-10", "2026-11"]
    assert u.stats()["total"] == {"views": 5, "visitor_days": 4, "since": date(2026, 10, 30)}


def test_a_failed_write_keeps_the_counts(connect):
    u = usage.Usage(connect, clock=Clock())
    u.record("page:/", "1.1.1.1", UA)
    working = u.connect

    @contextmanager
    def broken():
        raise OSError("database down")
        yield

    u.connect = broken
    with pytest.raises(OSError):
        u.flush()
    u.connect = working
    u.flush()
    assert table(connect, "SELECT views FROM usage_daily WHERE event = 'site'") == [(1,)]


def test_periods():
    d = date(2026, 10, 26)
    assert usage.period_of(d, "month") == "2026-10"
    assert usage.period_of(d, "week") == "2026-W44"
    assert usage.period_of(d, "day") == "2026-10-26"


def test_frontend_names_match_the_servers():
    from pathlib import Path

    src = (Path(__file__).parents[1] / "web/src/lib/usage.ts").read_text()
    for page in usage.PAGES:
        assert f"'{page}'" in src or page == "/not-found"
    for feature in usage.FEATURES:
        assert f"'{feature}'" in src


@pytest.fixture
def app_client(tmp_path, monkeypatch):
    monkeypatch.setenv("EB_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("EB_ADMIN_TOKEN", "s3cret")
    from exiledbroker.api import app as app_module

    return TestClient(app_module.create_app(web_dist=tmp_path / "none"))


def test_the_beacon_and_the_stats(app_client):
    headers = {"user-agent": UA}
    assert app_client.post("/api/hit?e=page:/launch", headers=headers).status_code == 204
    assert app_client.post("/api/hit?e=nonsense", headers=headers).status_code == 204
    # Do-Not-Track and Global Privacy Control: answered the same, not counted.
    app_client.post("/api/hit?e=page:/", headers={**headers, "dnt": "1"})
    app_client.post("/api/hit?e=page:/", headers={**headers, "sec-gpc": "1"})
    r = app_client.post("/api/hit?e=page:/launch", headers=headers)
    assert r.headers["cache-control"] == "no-store"

    assert app_client.get("/api/stats").status_code == 404
    assert app_client.get("/api/stats?key=s3cret").status_code == 404  # header only
    wrong = app_client.get("/api/stats", headers={"authorization": "Bearer wrong"})
    assert wrong.status_code == 404
    stats = app_client.get("/api/stats", headers={"authorization": "Bearer s3cret"}).json()
    assert stats["total"] == {"views": 2, "visitor_days": 1}
    assert stats["events"] == [{"event": "page:/launch", "views": 2, "visitors": 1}]


def test_no_stats_without_a_key(tmp_path, monkeypatch):
    monkeypatch.setenv("EB_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("EB_ADMIN_TOKEN", raising=False)
    from exiledbroker.api import app as app_module

    client = TestClient(app_module.create_app(web_dist=tmp_path / "none"))
    assert client.get("/api/stats", headers={"authorization": "Bearer "}).status_code == 404
    assert Settings().admin_token is None
