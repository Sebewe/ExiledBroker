"""The site's API on the real-data replay (Mirage's first 30 hours, see
test_live_pipeline.py): every endpoint after every update, from no data at all to a
day and a half, plus validation, the result cache and serving the frontend."""

import gzip
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from exiledbroker.api import app as app_module
from exiledbroker.api import cache, deps
from exiledbroker.ingest import currency_exchange as cx
from exiledbroker.ingest.live import sync_live
from exiledbroker.storage import db
from test_currency_exchange import FakeExchange, client_for
from test_live_pipeline import LAUNCH, PAGES, settings  # noqa: F401

LEAGUE = "Mirage"


@pytest.fixture
def client():
    deps.reset()
    return TestClient(app_module.create_app())


def update(s, server, hours_in: int):
    server.now = LAUNCH + hours_in * 3600
    now = cx.from_ts(server.now) + timedelta(minutes=10)
    with client_for(s, server) as c:
        return sync_live(c, s, LEAGUE, now=now, earliest=cx.from_ts(LAUNCH - 72 * 3600))


def endpoints(league: str) -> list[str]:
    """Everything the API serves: exactly what the site's pages request."""
    return [
        "/api/status",
        f"/api/missed/{league}",
        "/api/launch/picks",
        "/api/backtest",
    ]


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200 and r.json()["game"] == "poe1"


def test_status_is_cached_by_browsers_for_a_minute(client, settings):  # noqa: F811
    update(settings, FakeExchange(PAGES, now=LAUNCH), 2)
    r = client.get("/api/status")
    assert r.status_code == 200 and r.headers["cache-control"] == "public, max-age=60"


def test_no_data_yet(client, settings):  # noqa: F811
    """Before anything is loaded every data endpoint says so, rather than erroring."""
    settings.db_path.unlink()
    assert client.get("/api/status").status_code == 503
    with db.session(settings.db_path) as con:  # a schema but no loads yet
        db.init_schema(con)
    deps.reset()
    r = client.get("/api/status")
    assert r.status_code == 200 and r.json()["data_version"] is None


def test_every_endpoint_as_a_league_arrives(client, settings):  # noqa: F811
    server = FakeExchange(PAGES, now=LAUNCH)
    assert update(settings, server, 0).state == "not_running"
    for hours_in in (1, 2, 3, 6, 12, 24, 30):
        assert update(settings, server, hours_in).state == "updated"
        for path in endpoints(LEAGUE):
            r = client.get(path)
            assert r.status_code == 200, (hours_in, path, r.text)
        status = client.get("/api/status").json()
        assert status["leagues"][0]["name"] == LEAGUE
        assert status["leagues"][0]["hours"] == hours_in

    # After 30 hours there is something to recap, timed in UTC explicitly.
    recap = client.get(f"/api/missed/{LEAGUE}").json()
    assert recap and any(w["rising"] or w["falling"] or w["volatile"] for w in recap)
    assert recap[0]["latest_hour"].endswith("Z")


def test_tables_are_computed_once_per_data_version(client, settings, monkeypatch):  # noqa: F811
    server = FakeExchange(PAGES, now=LAUNCH)
    update(settings, server, 6)
    monkeypatch.setattr(deps, "VERSION_TTL", 60.0)  # as in production
    path = f"/api/missed/{LEAGUE}"
    with db.metered() as first:
        r1 = client.get(path)
    with db.metered() as again:
        r2 = client.get(path)
    assert first.queries and not again.queries  # a repeat never touches the database
    assert r1.content == r2.content

    # A client that has this version gets 304 and no body.
    r3 = client.get(path, headers={"If-None-Match": r1.headers["etag"]})
    assert r3.status_code == 304 and not r3.content
    # Gzipped once, in the cache: the bytes on the wire are the compressed ones.
    raw = client.get(path, headers={"Accept-Encoding": "identity"})
    gz = client.get(path, headers={"Accept-Encoding": "gzip"})
    assert "content-encoding" not in raw.headers and gz.headers["content-encoding"] == "gzip"
    assert gz.json() == raw.json()

    update(settings, server, 12)  # a new hour loaded: a new version, recomputed
    monkeypatch.setattr(deps, "VERSION_TTL", 0.0)
    with db.metered() as fresh:
        r4 = client.get(path, headers={"If-None-Match": r1.headers["etag"]})
    assert fresh.queries and r4.status_code == 200 and r4.headers["etag"] != r1.headers["etag"]
    # The old version's results are dropped, not left to the LRU (hosting.md: memory).
    assert {key[-1] for key in cache.results._entries} == {deps.data_version()}
    assert [key[0] for key in cache.results._entries].count("missed") == 1


def test_a_deploy_invalidates_browser_caches(client, settings, monkeypatch):  # noqa: F811
    """New code with the same data must not answer 304: the browser's cached body
    came from the old code and may lack fields the new pages read."""
    update(settings, FakeExchange(PAGES, now=LAUNCH), 6)
    path = f"/api/missed/{LEAGUE}"
    before = client.get(path).headers["etag"]
    monkeypatch.setattr(deps, "CODE_VERSION", "a-new-deploy")
    deps.reset()  # the new process starts with an empty cache
    r = client.get(path, headers={"If-None-Match": before})
    assert r.status_code == 200 and r.headers["etag"] != before


def test_default_pages_are_precomputed(client, settings, monkeypatch):  # noqa: F811
    """After warm(), what the pages ask for with their default controls is cached."""
    from exiledbroker.api import warm

    update(settings, FakeExchange(PAGES, now=LAUNCH), 30)
    assert warm.warm() >= 4  # league names, launch picks, backtest, the recap
    monkeypatch.setattr(deps, "VERSION_TTL", 60.0)
    # Exactly the requests the frontend makes on first load (web/src/api/queries.ts).
    page_loads = [
        "/api/status",
        f"/api/missed/{LEAGUE}",
        "/api/launch/picks",
        "/api/backtest",
    ]
    for path in page_loads:
        with db.metered() as meter:
            assert client.get(path).status_code == 200
        assert not meter.queries, (path, [q.sql for q in meter.queries])


def test_cache_is_bounded():
    c = cache.ResultCache(max_entries=3)
    for i in range(10):
        c.get_or_compute(("k", i), lambda i=i: i)
    assert len(c) == 3
    assert c.get_or_compute(("k", 9), lambda: "recomputed") == 9  # newest kept


def test_validation(client, settings):  # noqa: F811
    update(settings, FakeExchange(PAGES, now=LAUNCH), 3)
    assert client.get("/api/missed/Nowhere").status_code == 404


def test_only_what_the_pages_request_is_served(client, settings):  # noqa: F811
    """No endpoint takes free-form arguments: each would be computed from the
    database for every new combination, and on Supabase that's billed egress any
    visitor could run up. The API is exactly the site's four requests."""
    from exiledbroker.api import app as app_module

    paths = set(app_module.create_app().openapi()["paths"]) - {"/api/health"}
    assert paths == {
        "/api/status",
        "/api/missed/{league}",
        "/api/launch/picks",
        "/api/backtest",
    }
    update(settings, FakeExchange(PAGES, now=LAUNCH), 3)
    retired = [f"/api/live/{LEAGUE}/loops", f"/api/market/{LEAGUE}/hourly", "/api/leagues"]
    for gone in [*retired, f"/api/farming/{LEAGUE}"]:  # the Farming page, retired 2026-10-25
        assert client.get(gone).status_code == 404


def test_an_unchanged_report_is_reused_across_data_versions(client, settings):  # noqa: F811
    """The Backtest report changes only when it's rebuilt locally: a new hour reads its
    build time, not the report, and browsers keep their copy (same ETag)."""
    from exiledbroker.analysis import backtest

    server = FakeExchange(PAGES, now=LAUNCH)
    update(settings, server, 12)
    with db.session(settings.db_path) as con:
        backtest.store(con, backtest.build(con))
    first = client.get("/api/backtest")
    assert first.status_code == 200 and first.json()
    update(settings, server, 13)  # a new data version
    with db.metered() as meter:
        again = client.get("/api/backtest")
    assert again.headers["etag"] == first.headers["etag"] and again.content == first.content
    read = [q for q in meter.queries if "backtest_report" in q.sql]
    assert read and all("built_at" in q.sql for q in read), [q.sql for q in read]
    with db.session(settings.db_path) as con:  # rebuilt: read again, a new ETag
        backtest.store(con, backtest.build(con))
    update(settings, server, 14)
    rebuilt = client.get("/api/backtest")
    assert rebuilt.headers["etag"] != first.headers["etag"]


def test_serves_the_frontend(tmp_path, settings):  # noqa: F811
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<div id=root></div>")
    (dist / "assets" / "app.js").write_text("console.log(1)")
    c = TestClient(app_module.create_app(web_dist=dist))
    assert c.get("/").text == "<div id=root></div>"
    assert c.get("/launch").text == "<div id=root></div>"  # client-side route
    assert c.get("/assets/app.js").text == "console.log(1)"
    assert c.get("/../pyproject.toml").text == "<div id=root></div>"  # no escaping dist
    assert c.get("/api/health").json()["status"] == "ok"
    assert c.get("/api/nope").status_code == 404  # API paths never fall through


def test_frontend_caching(tmp_path, settings):  # noqa: F811
    """Hashed assets are kept for a year, index.html revalidated every visit, and the
    build's pre-gzipped copy is sent as is to browsers that take gzip."""
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<div id=root></div>")
    js = "console.log(1);" * 200
    (dist / "assets" / "app-abc123.js").write_text(js)
    (dist / "assets" / "app-abc123.js.gz").write_bytes(gzip.compress(js.encode()))
    c = TestClient(app_module.create_app(web_dist=dist))
    r = c.get("/assets/app-abc123.js")
    assert r.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert r.headers["content-encoding"] == "gzip" and "Accept-Encoding" in r.headers["vary"]
    assert r.headers["content-type"].startswith("text/javascript")
    assert r.text == js  # decoded by the client: gzipped once, not twice
    raw = c.get("/assets/app-abc123.js", headers={"Accept-Encoding": "identity"})
    assert "content-encoding" not in raw.headers and raw.text == js
    for path in ("/", "/launch"):
        assert c.get(path).headers["cache-control"] == "no-cache"


def test_frontend_types_are_up_to_date():
    """web/openapi.json (the source of the frontend's TS types) matches the API.
    If this fails: `cd web && npm run gen:api`, then fix any type errors it shows."""
    from pathlib import Path

    from exiledbroker.api.schema import schema

    committed = Path(__file__).resolve().parents[1] / "web" / "openapi.json"
    assert committed.read_text() == schema()
