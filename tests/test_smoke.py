"""The post-deploy smoke test (`eb site smoke`, smoke.py), run on the replay fixture
through FastAPI's TestClient: every check passes on a healthy site, and it fails or
warns on the states it exists to catch."""

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from exiledbroker import smoke
from exiledbroker.api import app as app_module
from exiledbroker.api import deps
from exiledbroker.ingest import currency_exchange as cx
from test_api import LEAGUE, update
from test_currency_exchange import FakeExchange
from test_live_pipeline import LAUNCH, PAGES, settings  # noqa: F401

INDEX = (
    '<!doctype html><script type="module" src="/assets/index-abc.js"></script>'
    '<link rel="stylesheet" href="/assets/index-abc.css"><div id="root"></div>'
)


@pytest.fixture
def dist(tmp_path):
    d = tmp_path / "dist"
    (d / "assets").mkdir(parents=True)
    (d / "index.html").write_text(INDEX)
    (d / "assets" / "index-abc.js").write_text("console.log(1)")
    (d / "assets" / "index-abc.css").write_text("body{}")
    (d / "og.png").write_bytes(b"\x89PNG")
    (d / "favicon.svg").write_text("<svg/>")
    (d / "robots.txt").write_text("User-agent: *\n")
    return d


def failures(results):
    return [str(c) for c in results if c.ok is False]


def test_a_healthy_site_passes(settings, dist):  # noqa: F811
    update(settings, FakeExchange(PAGES, now=LAUNCH), 3)
    deps.reset()
    c = TestClient(app_module.create_app(web_dist=dist))
    latest = cx.from_ts(LAUNCH) + timedelta(hours=3)
    results = smoke.run(c.get, now=latest + timedelta(minutes=10))
    assert failures(results) == []
    names = {r.name for r in results}
    assert f"/api/price-check/{LEAGUE}" in {n.split("?")[0] for n in names}
    assert any(n.startswith(f"/api/price-check/{LEAGUE}/") for n in names)  # an item
    assert f"{LEAGUE} freshness" in names and all(r.ok is not None for r in results)
    # A day later the feed is late: a warning, not a failure.
    later = smoke.run(c.get, now=latest + timedelta(days=1))
    assert failures(later) == []
    assert [r.name for r in later if r.ok is None] == [f"{LEAGUE} freshness"]


def test_no_data_fails(settings, dist):  # noqa: F811
    settings.db_path.unlink()
    deps.reset()
    c = TestClient(app_module.create_app(web_dist=dist))
    assert any(f.startswith("FAIL  /api/status") for f in failures(smoke.run(c.get)))


def test_a_missing_frontend_fails(settings):  # noqa: F811
    update(settings, FakeExchange(PAGES, now=LAUNCH), 2)
    deps.reset()
    c = TestClient(app_module.create_app(web_dist=settings.data_dir / "no-dist"))
    assert "FAIL  / is the app: 404, no app root or no CSP" in failures(smoke.run(c.get))


def test_the_origin_check(settings, dist, monkeypatch):  # noqa: F811
    update(settings, FakeExchange(PAGES, now=LAUNCH), 2)
    open_site = TestClient(app_module.create_app(web_dist=dist))
    monkeypatch.setenv("EB_ORIGIN_KEY", "k" * 32)
    deps.reset()
    keyed = TestClient(app_module.create_app(web_dist=dist))
    results = smoke.run(open_site.get, origin_check=keyed.get)
    assert failures(results) == []
    # An origin without the key set lets anyone in: that fails.
    results = smoke.run(open_site.get, origin_check=open_site.get)
    assert failures(results) == ["FAIL  origin refuses requests without the key: 200"]
