"""The Railway simulation's own logic (deploy/railway-sim): the visitors' browser
schedule matches the site's (web/src/lib/schedule.test.ts, same cases), the cost
maths matches Railway's rates, the meter reads docker stats, and the upstream
stand-in follows GGG's rules. The simulation itself runs with run.py, not here."""

import gzip
import json
import random
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
