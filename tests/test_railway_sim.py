"""The Railway simulation's own logic (deploy/railway-sim): the visitors' browser
schedule matches the site's (web/src/lib/schedule.test.ts, same cases), the cost
maths matches Railway's rates, the meter reads docker stats, and the upstream
stand-in follows GGG's rules. The simulation itself runs with run.py, not here."""

import gzip
import json
import random
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

SIM = Path(__file__).resolve().parents[1] / "deploy" / "railway-sim"
sys.path.insert(0, str(SIM))
import loadgen
import meter

MIN = 60
T = datetime(2026, 10, 22, 9, tzinfo=UTC).timestamp()


def status(latest: str | None, now: str = "2026-10-22T09:00:00Z", upcoming=None) -> dict:
    return {
        "now": now,
        "data_version": "v1",
        "leagues": [{"name": "Allflame", "latest_hour": latest}],
        "upcoming": upcoming,
    }


def at(hhmm: str, day: int = 22) -> float:
    h, m = map(int, hhmm.split(":"))
    return datetime(2026, 10, day, h, m, tzinfo=UTC).timestamp()


# --- The browser schedule: the same cases as web/src/lib/schedule.test.ts ------------


def test_waits_until_the_next_hour_is_due_then_asks_once():
    s = status("2026-10-22T08:00:00Z")
    assert loadgen.next_check_in(s, T, T) == 68 * MIN
    assert loadgen.next_check_in(s, T, T + 30 * MIN) == 38 * MIN
    assert loadgen.next_check_in(s, T, T, 45) == 68 * MIN + 45


def test_corrects_for_a_wrong_computer_clock():
    ours = T - 20 * MIN  # 20 minutes slow
    assert loadgen.next_check_in(status("2026-10-22T08:00:00Z"), ours, ours) == 68 * MIN


@pytest.mark.parametrize(("now", "every"), [("10:10", 3), ("10:40", 5), ("12:00", 10)])
def test_backs_off_while_a_new_hour_is_late(now, every):
    s = status("2026-10-22T08:00:00Z", now=f"2026-10-22T{now}:00Z")
    assert loadgen.next_check_in(s, at(now), at(now)) == every * MIN


def test_never_asks_more_often_than_every_2_minutes():
    due = at("10:08")
    s = status("2026-10-22T08:00:00Z", now="2026-10-22T10:07:30Z")
    assert loadgen.next_check_in(s, due - 30, due - 30) == loadgen.MIN_CHECK


def test_counts_down_to_an_announced_league_and_idles_otherwise():
    up = {
        "name": "Next",
        "start_at": "2026-10-22T09:00:00Z",
        "first_data_at": "2026-10-22T10:10:00Z",
    }
    assert loadgen.next_check_in({**status(None), "leagues": [], "upcoming": up}, T, T) == 70 * MIN
    assert loadgen.next_check_in({**status(None), "leagues": []}, T, T) == 30 * MIN


def test_visits_follow_the_daily_model():
    visits = loadgen.plan_visits(1000, T, 24, random.Random(1))
    per_user = len(visits) / 1000
    assert 2.7 < per_user < 3.3  # about 3 a day
    assert all(v[3][0] == "missed" for v in visits)  # every visit lands on the landing page
    hours = [datetime.fromtimestamp(v[1], UTC).hour for v in visits]
    assert hours.count(19) > 2 * hours.count(3)  # evenings busier than nights


def test_visitors_ask_only_for_what_the_api_serves():
    """Each page a visitor views makes the request the built page makes, on a route the
    API has: the Farming page included, for a league before its first trades too."""
    from exiledbroker.api.app import create_app

    routes = list(create_app().openapi()["paths"])

    def served(url: str) -> bool:
        path = url.split("?")[0]
        return any(re.fullmatch(re.sub(r"\{[^}]+\}", "[^/]+", route), path) for route in routes)

    site = loadgen.Site(None, loadgen.Stats(), immutable_assets=True)
    b = loadgen.Browser(jitter=0)
    b.status = {
        "leagues": [{"name": "Next", "latest_hour": None}, {"name": "Allflame", "latest_hour": "x"}]
    }
    asks = {page: site.endpoint(page, b) for page in ["missed", *loadgen.OTHER_PAGES]}
    assert asks["loops"] == asks["cards"] == asks["missed"] == ("missed", "/api/missed/Allflame")
    assert asks["conversions"] is None and asks["about"] is None  # static pages
    assert all(served(url) for kind, url in filter(None, asks.values())), asks
    b.status = {"leagues": []}  # nothing loaded yet: only the Launch picks and the Backtest
    assert {p for p in asks if site.endpoint(p, b)} == {"launch", "backtest"}


# --- Railway's bill -------------------------------------------------------------------


def test_costs_follow_railways_rates():
    m = meter.monthly_cost(gb=0.5, vcpu=0.1, volume=2, egress_gb=10)
    assert m == {
        "memory": 5.0,
        "cpu": 2.0,
        "volume": 0.3,
        "egress": 0.5,
        "total": pytest.approx(7.8),
    }
    assert meter.hobby_bill(3.2) == 5.0  # covered by the fee
    assert meter.hobby_bill(7.8) == pytest.approx(7.8)  # $5 fee + $2.80 over


def test_the_meter_reads_docker_stats_by_service():
    m = meter.Meter()
    row = {"Name": "ebsim-web-1", "MemUsage": "512MiB / 2GiB", "CPUPerc": "50.00%"}
    m.record(row, 0.0)  # the first sample starts the clock
    m.record(row, 2.0)
    m.record({"Name": "ebsim-pipeline-run-1a2b", "MemUsage": "1GiB / 2GiB", "CPUPerc": "100%"}, 0.0)
    m.record(
        {"Name": "exiledbroker-api-1", "MemUsage": "1GiB / 2GiB", "CPUPerc": "1%"}, 1.0
    )  # not ours
    web = m.usage["web"]
    assert web.seconds == 2.0 and web.gb_s == pytest.approx(2 * 512 * 2**20 / 1e9)
    assert web.vcpu_s == pytest.approx(1.0)
    assert meter.service_of("ebsim-pipeline-run-1a2b") == "pipeline"
    assert meter.service_of("exiledbroker-api-1") is None


# --- The upstream stand-in --------------------------------------------------------------


@pytest.fixture
def upstream(tmp_path, monkeypatch):
    page = {"next_change_id": 7200 + 3600, "markets": []}
    (tmp_path / "7200.json.gz").write_bytes(gzip.compress(json.dumps(page).encode()))
    ref = tmp_path / "reference.json"
    ref.write_text(json.dumps({"poe_ninja/leagues": [{"id": "Allflame"}]}))
    import upstream as up

    monkeypatch.setattr(up, "PAGES", tmp_path)
    monkeypatch.setattr(up, "REFERENCE", ref)
    up.counts.clear()
    return TestClient(up.app), up


def test_the_stand_in_follows_ggg_rules(upstream):
    client, up = upstream
    client.post("/_sim/now", params={"ts": 7200 + 1800})
    # The hour still being traded is the end of the stream.
    assert client.get("/api/currency-exchange/7200").json()["next_change_id"] == 7200
    client.post("/_sim/now", params={"ts": 3 * 3600 + 360})
    assert client.get("/api/currency-exchange/7200").json()["next_change_id"] == 10800
    assert client.get("/api/currency-exchange/3600").status_code == 404  # not recorded
    assert (
        client.get("/ninja/poe1/api/economy/leagues", headers={"If-None-Match": "x"}).status_code
        == 304
    )
    assert client.get("/ninja/poe1/api/economy/leagues").json() == [{"id": "Allflame"}]
    assert up.counts == {
        "exchange_unfinished": 1,
        "exchange_page": 1,
        "exchange_missing": 1,
        "ninja_304": 1,
        "ninja_200": 1,
    }


def test_the_stand_in_can_serve_unrecorded_hours_as_empty(upstream):
    """For the league switch replay: the days between leagues weren't recorded."""
    client, up = upstream
    client.post("/_sim/now", params={"ts": 5 * 3600, "missing_empty": True})
    page = client.get("/api/currency-exchange/3600").json()
    assert page == {"next_change_id": 7200, "markets": []}
    assert up.counts["exchange_empty"] == 1


def test_an_unstored_list_is_refused_not_a_server_error(upstream):
    """A 500 would be retried with backoff (PoliteClient) and fail the pass."""
    client, up = upstream
    r = client.get("/ninja/poe1/api/economy/exchange/current/overview?league=A&type=Fossil")
    assert r.status_code == 404 and up.counts == {"ninja_missing": 1}


def test_the_seed_makes_up_the_pool_lists_the_copy_lacks():
    """A copy whose core pool predates a new poe.ninja list (the Farming page's): the
    stand-in serves every basket output, so a pass's pool check succeeds and the pool
    still shows the baskets."""
    import seed_server

    from exiledbroker.config import Settings
    from exiledbroker.ingest import core_pool
    from exiledbroker.normalize import mechanics

    reference = {core_pool.snapshot_key("Currency"): {"names": ["Chaos Orb"]}}
    made = seed_server.stand_in_lists(reference, Settings())
    every = {t for types in core_pool.SOURCES.values() for t in types}
    assert set(made) == every - {"Currency"} and "Fossil" in made
    assert reference[core_pool.snapshot_key("Currency")] == {"names": ["Chaos Orb"]}  # kept
    listed = {n for t in made for n in reference[core_pool.snapshot_key(t)]["names"]}
    outputs = {n for m in mechanics.load_mechanics(Settings()) for n in m.outputs}
    assert listed == outputs
