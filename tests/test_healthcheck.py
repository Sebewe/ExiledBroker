"""The pipeline's dead-man's-switch ping (ingest/healthcheck.py, wired in
`pipeline.run`): /start, then success or /fail with a reason. Everything runs against
httpx.MockTransport; no test reaches a monitoring service."""

from datetime import timedelta
from types import SimpleNamespace

import httpx
import pytest

from exiledbroker.config import Settings
from exiledbroker.ingest import healthcheck as healthcheck_mod
from exiledbroker.ingest import pipeline
from exiledbroker.ingest.healthcheck import Healthcheck
from test_currency_exchange import FakeExchange, client_for
from test_live_pipeline import PAGES
from test_pipeline import LAUNCH, at, local, run, seeded  # noqa: F401 (fixtures)

URL = "https://hc-ping.com/00000000-secret"


class Monitor:
    """A stand-in monitoring service: records each ping as (path, body)."""

    def __init__(self, status: int = 200, error: Exception | None = None):
        self.pings: list[tuple[str, str]] = []
        self.status, self.error = status, error

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.pings.append((request.url.path, request.content.decode()))
        if self.error:
            raise self.error
        return httpx.Response(self.status, text="OK")

    def check(self) -> Healthcheck:
        return Healthcheck(URL, "ExiledBroker/test", httpx.MockTransport(self.handler))

    @property
    def paths(self) -> list[str]:
        return [p for p, _ in self.pings]


def test_no_url_means_no_requests(seeded, monkeypatch):  # noqa: F811
    s, server = seeded

    def no_client(*a, **kw):
        raise AssertionError("a pass without EB_HEALTHCHECK_URL built an HTTP client")

    monkeypatch.setattr(
        healthcheck_mod, "httpx", SimpleNamespace(Client=no_client, HTTPStatusError=Exception)
    )
    assert not Healthcheck.from_settings(s) and not Healthcheck(None) and not Healthcheck("")
    result, _ = run(s, server, 9)
    assert result.live.state == "updated" and result.ping_errors == []


def test_settings_url_builds_a_client_with_the_user_agent():
    s = Settings(healthcheck_url=URL + "/")
    check = Healthcheck.from_settings(s)
    assert check and check.url == URL  # a trailing slash can't double up
    assert check._client.headers["User-Agent"] == s.user_agent
    check.close()


def test_a_good_pass_pings_start_then_success_with_its_summary(seeded):  # noqa: F811
    s, server = seeded
    monitor = Monitor()
    result, _ = run(s, server, 9, healthcheck=monitor.check())
    assert monitor.paths == ["/00000000-secret/start", "/00000000-secret"]
    assert monitor.pings[1][1] == str(result)
    assert result.ping_errors == [] and result.stale is None


def test_a_raised_pass_pings_fail_with_the_exception_and_still_raises(tmp_path):
    s = Settings(data_dir=tmp_path, request_min_interval=0)  # unseeded: the pass refuses
    monitor = Monitor()
    with (
        client_for(s, FakeExchange(PAGES, now=LAUNCH + 6 * 3600)) as c,
        pytest.raises(pipeline.NotSeeded),
    ):
        pipeline.run(c, s, "Mirage", now=at(6), healthcheck=monitor.check())
    assert monitor.paths == ["/00000000-secret/start", "/00000000-secret/fail"]
    assert "NotSeeded" in monitor.pings[1][1] and "seed" in monitor.pings[1][1]


def test_a_failed_backup_pings_fail_though_the_pass_succeeded(seeded, monkeypatch):  # noqa: F811
    s, server = seeded
    s = s.model_copy(update={"backup_url": "postgresql://backup.invalid/postgres"})

    def broken(settings):
        raise ConnectionError("backup unreachable")

    monkeypatch.setattr(pipeline.backup_mod, "back_up", broken)
    monitor = Monitor()
    result, _ = run(s, server, 9, healthcheck=monitor.check())
    assert result.live.state == "updated" and result.backup_error  # the pass itself is fine
    assert monitor.paths[-1].endswith("/fail")
    assert "Backup failed: ConnectionError: backup unreachable" in monitor.pings[-1][1]


def _stalled(s, server, hours: float, monitor, **announced):
    """A pass `hours` after the feed's last hour was loaded, with GGG publishing nothing
    new (the fake exchange's clock stays where it was)."""
    run(s, server, 9)  # hours 0-8 loaded: the latest one ended at launch + 9 h
    s = s.model_copy(update=announced)
    with client_for(s, server) as c:
        return pipeline.run(c, s, now=at(9) + timedelta(hours=hours), healthcheck=monitor.check())


def test_a_stopped_feed_pings_fail(seeded):  # noqa: F811
    s, server = seeded
    monitor = Monitor()
    result = _stalled(s, server, 4, monitor)
    assert result.live.state == "not_running" and result.stale
    assert monitor.paths[-1].endswith("/fail")
    assert "feed looks stopped" in monitor.pings[-1][1] and "Mirage" in monitor.pings[-1][1]


def test_a_late_hour_is_not_a_stopped_feed(seeded):  # noqa: F811
    s, server = seeded
    monitor = Monitor()
    result = _stalled(s, server, 1.5, monitor)  # the site warns at 75 min; the alert waits
    assert result.stale is None and monitor.paths[-1] == "/00000000-secret"


def test_an_ended_league_with_a_next_one_announced_is_not_stale(seeded):  # noqa: F811
    s, server = seeded
    monitor = Monitor()
    later = at(9) + timedelta(days=2)
    result = _stalled(s, server, 4, monitor, next_league="Next", next_league_start=later)
    assert result.league == "Mirage" and result.live.state == "not_running"
    assert result.stale is None and monitor.paths[-1] == "/00000000-secret"


def test_a_league_without_data_is_waiting_not_stale(seeded):  # noqa: F811
    s, _ = seeded
    assert pipeline.stale_feed(s, "Mirage", at(6)) is None  # hour 5 ended 10 min ago
    assert pipeline.stale_feed(s, "Not loaded yet", at(6) + timedelta(days=9)) is None


@pytest.mark.parametrize(
    "monitor",
    [Monitor(status=500), Monitor(error=httpx.ConnectTimeout("slow"))],
    ids=["5xx", "unreachable"],
)
def test_a_monitor_that_is_down_never_fails_the_pass(seeded, monitor):  # noqa: F811
    s, server = seeded
    result, _ = run(s, server, 9, healthcheck=monitor.check())
    assert result.live.state == "updated"
    assert len(monitor.pings) == 2 * 2  # start and success, each tried twice (one retry)
    assert len(result.ping_errors) == 2 and "Healthcheck not reached" in str(result)
    assert "secret" not in str(result)  # the URL never lands in the logs


def test_a_long_body_is_truncated():
    monitor = Monitor()
    monitor.check().fail("x" * 50_000)
    assert len(monitor.pings[0][1]) == healthcheck_mod.BODY_MAX
