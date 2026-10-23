"""A league's first hours, when the exchange is still mostly empty: replay Allflame's
first 3 published hours exactly as GGG served them (tests/fixtures/allflame_start
.json.gz, every Allflame market: 57 in the first hour, 2 of them against Divine) and
check that every endpoint answers, and that the landing page's recap holds up with
next to nothing to recap. Before that, the announced league counts down."""

import gzip
import json
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from exiledbroker.api import app as app_module
from exiledbroker.api import deps
from exiledbroker.config import Settings
from exiledbroker.ingest import currency_exchange as cx
from exiledbroker.ingest.live import sync_live
from test_api import endpoints
from test_currency_exchange import FakeExchange, client_for
from test_live_pipeline import store_reference_data

with gzip.open(Path(__file__).parent / "fixtures" / "allflame_start.json.gz", "rt") as _f:
    FIXTURE = json.load(_f)
LEAGUE = FIXTURE["league"]
LAUNCH = FIXTURE["launch"]
PAGES = {int(ts): page["markets"] for ts, page in FIXTURE["pages"].items()}


@pytest.fixture
def settings(tmp_path, monkeypatch):
    monkeypatch.setenv("EB_DATA_DIR", str(tmp_path))
    # Announced a little before the first traded hour, as GGG announces it.
    monkeypatch.setenv("EB_NEXT_LEAGUE", LEAGUE)
    monkeypatch.setenv("EB_NEXT_LEAGUE_START", cx.from_ts(LAUNCH).isoformat())
    s = Settings(data_dir=tmp_path, request_min_interval=0)
    store_reference_data(s, FIXTURE)
    return s


def update(s, server, hours_in: int):
    server.now = LAUNCH + hours_in * 3600  # this hour is still being traded
    now = cx.from_ts(server.now) + timedelta(minutes=10)
    with client_for(s, server) as c:
        return sync_live(c, s, LEAGUE, now=now, earliest=cx.from_ts(LAUNCH - 72 * 3600))


def client() -> TestClient:
    deps.reset()
    return TestClient(app_module.create_app())


def test_the_announced_league_counts_down_until_its_first_trades(settings):
    server = FakeExchange(PAGES, now=LAUNCH)
    assert update(settings, server, 0).state == "not_running"
    status = client().get("/api/status").json()
    launch = cx.from_ts(LAUNCH)
    assert status["upcoming"] == {
        "name": LEAGUE,
        "start_at": f"{launch:%Y-%m-%dT%H:%M:%S}Z",
        # The first hour ends an hour after launch; published and loaded ~10 min later.
        "first_data_at": f"{launch + timedelta(hours=1, minutes=10):%Y-%m-%dT%H:%M:%S}Z",
    }
    assert update(settings, server, 1).state == "updated"
    status = client().get("/api/status").json()
    assert status["leagues"][0]["latest_hour"] and status["upcoming"] is None


@pytest.mark.parametrize("hours_in", [1, 2, 3])
def test_every_endpoint_works_in_the_first_hours(settings, hours_in):
    server = FakeExchange(PAGES, now=LAUNCH)
    for h in range(1, hours_in + 1):
        assert update(settings, server, h).state == "updated"
    api = client()
    for path in endpoints(LEAGUE):
        r = api.get(path)
        assert r.status_code == 200, (hours_in, path, r.text)

    recap = api.get(f"/api/missed/{LEAGUE}").json()
    assert [w["hours"] for w in recap] == [1, 2, 3]
    for w in recap:
        assert (
            w["latest_hour"] == f"{cx.from_ts(LAUNCH + (hours_in - 1) * 3600):%Y-%m-%dT%H:%M:%S}Z"
        )
        assert w["loops_paid"] >= 0 and w["cards_paid"] >= 0
        for key in ("rising", "falling", "volatile", "loops", "cards"):
            assert len(w[key]) <= 3
    sections = [w[k] for w in recap for k in ("rising", "falling", "volatile", "loops", "cards")]
    if hours_in == 1:
        # One hour in: nothing to compare against and too thin to count, but no errors.
        assert not any(sections) and recap[0]["loops_paid"] == recap[0]["cards_paid"] == 0
    if hours_in == 3:
        # By the third hour something shows (Allflame: the Divine rising, a loop, cards)...
        assert any(sections)
        # ...but no look-back reaches before the league, so 3 hours finds no baseline.
        assert recap[2]["rising"] == recap[2]["falling"] == []
