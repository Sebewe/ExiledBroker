"""The admin API: off (404) without EB_ADMIN_TOKEN, 401 without the right token, never
cached, and the pipeline's health from ingest_run once a league updates."""

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from exiledbroker.api import app as app_module
from exiledbroker.api import deps
from exiledbroker.config import Settings
from test_api import LEAGUE, update
from test_currency_exchange import FakeExchange
from test_live_pipeline import LAUNCH, PAGES, settings  # noqa: F401

TOKEN = "t" * 40
URL = "/api/admin/overview"


@pytest.fixture
def admin(monkeypatch, settings):  # noqa: F811
    monkeypatch.setenv("EB_ADMIN_TOKEN", TOKEN)
    deps.reset()
    return TestClient(app_module.create_app())


def auth(token: str = TOKEN) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_off_without_a_token(settings):  # noqa: F811
    c = TestClient(app_module.create_app())
    assert c.get(URL, headers=auth()).status_code == 404


def test_refuses_without_the_token(admin):
    for headers in ({}, auth("wrong"), auth(TOKEN + "x"), {"Authorization": TOKEN}):
        r = admin.get(URL, headers=headers)
        assert r.status_code == 401 and r.headers["www-authenticate"] == "Bearer"
        assert r.headers["cache-control"] == "no-store"


def test_a_short_token_is_refused_at_startup(monkeypatch):
    monkeypatch.setenv("EB_ADMIN_TOKEN", "hunter2")
    with pytest.raises(ValidationError, match="at least 32"):
        Settings()
    monkeypatch.setenv("EB_ADMIN_TOKEN", "")  # set but empty: off
    assert Settings().admin_token is None


def test_overview_before_any_data(admin, settings):  # noqa: F811
    settings.db_path.unlink(missing_ok=True)
    r = admin.get(URL, headers=auth())
    assert r.status_code == 200 and r.json()["pipeline"] == []


def test_pipeline_health(admin, settings):  # noqa: F811
    server = FakeExchange(PAGES, now=LAUNCH)
    for hours_in in (1, 2, 3):
        assert update(settings, server, hours_in).state == "updated"
    r = admin.get(URL, headers=auth())
    assert r.status_code == 200
    assert r.headers["cache-control"] == "no-store, private"  # never at the edge
    body = r.json()
    assert body["data_version"]
    (league,) = body["pipeline"]
    assert league["league"] == LEAGUE and league["last_state"] == "updated"
    assert league["last_success"] == league["last_run"] and league["last_failure"] is None
    assert league["last_error"] is None and league["failures_day"] == 0
    assert league["runs_day"] == 3 and league["requests_day"] > 0
    assert league["latest_hour"] and league["hours_added_day"] > 0


def test_a_failed_update_shows(admin, settings):  # noqa: F811
    from datetime import UTC, datetime

    from exiledbroker.storage import db

    update(settings, FakeExchange(PAGES, now=LAUNCH), 2)
    with db.session(settings.db_path) as con:
        lid = db.scalar(con, "SELECT league_id FROM ingest_run")
        failed_at = datetime.now(UTC).replace(tzinfo=None)
        con.execute(
            "INSERT INTO ingest_run (league_id, started_at, state, error) VALUES (?, ?, ?, ?)",
            [lid, failed_at, "failed", "ReadTimeout: the exchange didn't answer"],
        )
    (league,) = admin.get(URL, headers=auth()).json()["pipeline"]
    assert league["last_state"] == "failed" and "ReadTimeout" in league["last_error"]
    assert league["last_failure"] == league["last_run"] != league["last_success"]
    assert league["failures_day"] == 1 and league["runs_day"] == 2
