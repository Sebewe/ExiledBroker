"""The origin's abuse guards (api/guard.py): only Cloudflare gets in when a key is set,
each visitor gets a fair share of /api, and the docs are off when asked."""

import pytest
from fastapi.testclient import TestClient

from exiledbroker.api import app as app_module
from exiledbroker.api import guard

KEY = "s3cret-edge-key"


@pytest.fixture
def guarded(monkeypatch):
    monkeypatch.setenv("EB_ORIGIN_KEY", KEY)
    monkeypatch.setenv("EB_API_RATE_LIMIT", "3")
    return TestClient(app_module.create_app())


def test_no_key_configured_lets_everything_in():
    c = TestClient(app_module.create_app())
    for _ in range(200):
        assert c.get("/api/health", headers={"cf-connecting-ip": "1.2.3.4"}).status_code == 200
    assert c.get("/api/launch/picks").status_code != 403


def test_requests_without_the_key_are_refused(guarded):
    for headers in ({}, {"x-eb-origin-key": "wrong"}, {"x-eb-origin-key": KEY + "x"}):
        for path in ["/api/status", "/api/launch/picks", "/", "/docs"]:
            r = guarded.get(path, headers=headers)
            assert r.status_code == 403, (path, headers)
            assert r.headers["x-eb-origin"] == "app"  # the app's own answer, not Railway's
            assert r.headers["cache-control"] == "no-store"
    # Railway's health check has no key.
    assert guarded.get("/api/health").status_code == 200


def test_with_the_key_requests_pass(guarded):
    r = guarded.get("/api/launch/picks", headers={"x-eb-origin-key": KEY})
    assert r.status_code not in (403, 429)


def test_each_visitor_gets_a_limited_share(guarded):
    def get(ip):
        return guarded.get(
            "/api/launch/picks", headers={"x-eb-origin-key": KEY, "cf-connecting-ip": ip}
        )

    assert all(get("1.1.1.1").status_code != 429 for _ in range(3))
    r = get("1.1.1.1")
    assert r.status_code == 429
    assert 1 <= int(r.headers["retry-after"]) <= 61
    assert r.headers["cache-control"] == "no-store"
    assert r.json()["detail"]
    assert get("2.2.2.2").status_code != 429  # another visitor isn't held up
    # The Worker's copy of the address is read first.
    worker = {"x-eb-origin-key": KEY, "x-eb-client-ip": "1.1.1.1", "cf-connecting-ip": "9.9.9.9"}
    assert guarded.get("/api/launch/picks", headers=worker).status_code == 429
    # The health check and the pages' files aren't counted.
    h = {"x-eb-origin-key": KEY, "cf-connecting-ip": "1.1.1.1"}
    assert guarded.get("/api/health", headers=h).status_code == 200


def test_the_limit_resets_each_minute_and_stays_bounded(monkeypatch):
    limiter = guard.PerClientLimit(None, limit=2)
    assert limiter.allow(b"a", now=0) and limiter.allow(b"a", now=1)
    assert not limiter.allow(b"a", now=59)
    assert limiter.allow(b"a", now=60)  # a new window
    monkeypatch.setattr(guard, "MAX_CLIENTS", 10)
    for i in range(25):
        limiter.allow(str(i).encode(), now=120)
    assert len(limiter._counts) <= 10  # a flood of addresses can't grow it


def test_docs_can_be_switched_off(monkeypatch, tmp_path):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<div id=root></div>")
    monkeypatch.setenv("EB_API_DOCS", "false")
    c = TestClient(app_module.create_app(web_dist=dist))
    for path in ["/docs", "/redoc", "/openapi.json"]:
        r = c.get(path)
        # The page's catch-all answers them with the app (index.html), not the docs.
        assert "swagger" not in r.text.lower() and "openapi" not in r.text.lower(), path
    # The frontend's types are still generated from the code.
    assert app_module.create_app().openapi()["paths"]
