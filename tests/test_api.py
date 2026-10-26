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


ITEM = "currency:orb-of-alchemy"  # trades in the replay from its first hours


def endpoints(league: str, item: str | None = None) -> list[str]:
    """Everything the API serves: exactly what the site's pages request (Price check's
    item view with `item`)."""
    return [
        "/api/status",
        f"/api/missed/{league}",
        "/api/launch/picks",
        "/api/backtest",
        f"/api/price-check/{league}",
        *([f"/api/price-check/{league}/{item}"] if item else []),
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
    no_data = client.get("/api/status")
    assert no_data.status_code == 503
    assert no_data.headers["cache-control"] == "no-store"  # never cached at the edge
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
        listed = client.get(f"/api/price-check/{LEAGUE}").json()["items"]
        item = listed[0]["item_id"] if listed else None
        for path in endpoints(LEAGUE, item):
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
    # League names, launch picks, backtest, the recap, Price check's list and its movers.
    assert warm.warm() >= 5
    monkeypatch.setattr(deps, "VERSION_TTL", 60.0)
    movers = client.get(f"/api/price-check/{LEAGUE}").json()["movers"]
    assert movers
    # Exactly the requests the frontend makes on first load (web/src/api/queries.ts),
    # and the movers a Price check visitor opens.
    page_loads = [
        "/api/status",
        f"/api/missed/{LEAGUE}",
        "/api/launch/picks",
        "/api/backtest",
        f"/api/price-check/{LEAGUE}",
        *[f"/api/price-check/{LEAGUE}/{i}" for i in movers],
    ]
    for path in page_loads:
        with db.metered() as meter:
            assert client.get(path).status_code == 200
        assert not meter.queries, (path, [q.sql for q in meter.queries])
    # Any other item is built on its first request (not warmed: ~900 cached responses
    # would hold the LRU for one data version), then served from the cache.
    listed = client.get(f"/api/price-check/{LEAGUE}").json()["items"]
    others = [x["item_id"] for x in listed if x["item_id"] not in movers]
    assert others
    path = f"/api/price-check/{LEAGUE}/{others[0]}"
    with db.metered() as first:
        assert client.get(path).status_code == 200
    assert first.queries
    with db.metered() as again:
        assert client.get(path).status_code == 200
    assert not again.queries


def test_cache_is_bounded():
    c = cache.ResultCache(max_entries=3)
    for i in range(10):
        c.get_or_compute(("k", i), lambda i=i: i)
    assert len(c) == 3
    assert c.get_or_compute(("k", 9), lambda: "recomputed") == 9  # newest kept


def test_concurrent_misses_compute_once():
    """A burst of requests for one uncached key (a streamer's audience opening the same
    item) runs its queries once; the others wait for that result."""
    import threading
    import time

    c = cache.ResultCache()
    calls = []

    def slow():
        calls.append(1)
        time.sleep(0.2)
        return "value"

    got = []
    threads = [
        threading.Thread(target=lambda: got.append(c.get_or_compute("k", slow))) for _ in range(20)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(calls) == 1 and got == ["value"] * 20


def test_a_failed_computation_lets_the_next_request_retry():
    c = cache.ResultCache()

    def boom():
        raise RuntimeError("database went away")

    with pytest.raises(RuntimeError):
        c.get_or_compute("k", boom)
    assert c.get_or_compute("k", lambda: "ok") == "ok"


def test_items_are_cached_slim_in_their_own_cache(client, settings):  # noqa: F811
    """Price check's items (one per item, ~900 a league) go in the item cache as gzipped
    bytes only, so a whole league fits (~26 kB each instead of ~155 kB), and they never
    push the pages' tables out."""
    update(settings, FakeExchange(PAGES, now=LAUNCH), 6)
    plain = client.get(f"/api/price-check/{LEAGUE}/{ITEM}", headers={"accept-encoding": ""})
    zipped = client.get(f"/api/price-check/{LEAGUE}/{ITEM}")
    assert plain.status_code == zipped.status_code == 200
    assert plain.json() == zipped.json()  # a client without gzip gets it decompressed
    (key,) = cache.items._entries
    held = cache.items._entries[key]
    assert key[0] == "price_check_item" and held.plain is None and held.rows == []
    assert all(k[0] != "price_check_item" for k in cache.results._entries)
    assert cache.MAX_ITEMS >= 1000


def test_api_responses_without_their_own_cache_header_are_never_cached(client, settings):  # noqa: F811
    """Cloudflare caches what Cache-Control allows; with no header it would apply its
    default edge TTL (2 hours for a 200, minutes for a 404). So errors and /api/health
    say no-store, and the tables keep their own short max-age."""
    update(settings, FakeExchange(PAGES, now=LAUNCH), 3)
    assert client.get("/api/health").headers["cache-control"] == "no-store"
    assert client.get("/api/missed/Nowhere").headers["cache-control"] == "no-store"  # 404
    assert client.get(f"/api/missed/{LEAGUE}").headers["cache-control"] == deps.CACHE_CONTROL


def test_the_version_parameter_only_keys_caches(client, settings):  # noqa: F811
    """The pages send `v` (the data version they have) so each hour has its own URL in
    browser and edge caches. The server ignores it: same bytes, same server cache entry."""
    update(settings, FakeExchange(PAGES, now=LAUNCH), 3)
    a = client.get(f"/api/missed/{LEAGUE}")
    b = client.get(f"/api/missed/{LEAGUE}", params={"v": "anything"})
    assert a.content == b.content and a.headers["etag"] == b.headers["etag"]
    assert [k[0] for k in cache.results._entries].count("missed") == 1
    assert client.get(f"/api/missed/{LEAGUE}", params={"v": "x" * 65}).status_code == 422


def test_validation(client, settings):  # noqa: F811
    update(settings, FakeExchange(PAGES, now=LAUNCH), 3)
    assert client.get("/api/missed/Nowhere").status_code == 404


def test_only_what_the_pages_request_is_served(client, settings):  # noqa: F811
    """No endpoint takes free-form arguments: each would be computed from the
    database for every new combination, and on Supabase that's billed egress any
    visitor could run up. The API is exactly the site's requests; Price check's item is
    bounded to the league's list (the core pool's exchange items it has traded)."""
    from exiledbroker.api import app as app_module

    paths = set(app_module.create_app().openapi()["paths"]) - {"/api/health"}
    assert paths == {
        "/api/status",
        "/api/missed/{league}",
        "/api/launch/picks",
        "/api/backtest",
        "/api/price-check/{league}",
        "/api/price-check/{league}/{item_id}",
        "/api/hit",  # the usage beacon: one event from a fixed list, counted in memory
        "/api/stats",  # the usage counts, for the owner only (admin token)
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


def test_security_headers(tmp_path, settings):  # noqa: F811
    """Every response: no sniffing, no full Referer to other sites, no framing. The page
    also carries a CSP that allows its own inline theme script by hash, and nothing
    inline it doesn't know about."""
    import base64
    import hashlib

    theme = "document.documentElement.dataset.theme = 'dark'"
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text(
        f'<script>{theme}</script><script type="module" src="/assets/a.js"></script>'
    )
    (dist / "assets" / "a.js").write_text("1")
    c = TestClient(app_module.create_app(web_dist=dist))
    for path in ["/", "/price-check", "/assets/a.js", "/api/health"]:
        h = c.get(path).headers
        assert h["x-content-type-options"] == "nosniff", path
        assert h["referrer-policy"] == "strict-origin-when-cross-origin", path
        assert h["x-frame-options"] == "DENY", path
    csp = c.get("/").headers["content-security-policy"]
    digest = base64.b64encode(hashlib.sha256(theme.encode()).digest()).decode()
    assert f"'sha256-{digest}'" in csp and "frame-ancestors 'none'" in csp
    assert "'unsafe-inline'" not in csp.split("script-src")[1].split(";")[0]
    assert "content-security-policy" not in c.get("/assets/a.js").headers
    assert "content-security-policy" not in c.get("/docs").headers  # Swagger loads a CDN


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


def test_every_response_is_marked_as_the_apps(tmp_path, settings):  # noqa: F811
    """Cloudflare's fallback Worker replaces a 5xx only when it lacks X-EB-Origin: app,
    so the app's own answers (JSON errors, static files, 304s, gzip) must all carry it."""
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<div id=root></div>")
    js = "console.log(1);" * 200
    (dist / "assets" / "app-abc123.js").write_text(js)
    (dist / "assets" / "app-abc123.js.gz").write_bytes(gzip.compress(js.encode()))
    settings.db_path.unlink()  # no data yet: /api/status answers 503
    deps.reset()
    c = TestClient(app_module.create_app(web_dist=dist))
    responses = [
        c.get("/"),
        c.get("/launch"),
        c.get("/assets/app-abc123.js"),
        c.get("/assets/app-abc123.js", headers={"Accept-Encoding": "identity"}),
        c.get("/api/health"),
        c.get("/api/status"),  # 503: no data yet
        c.get("/api/missed/Nowhere"),  # 404/503
        c.get("/api/nope"),  # 404
        c.get("/api/health", headers={"Origin": "http://example.com"}),  # CORS
        c.post("/api/health"),  # 405
    ]
    assert {r.status_code for r in responses} >= {200, 404, 405, 503}
    assert all(r.headers.get("x-eb-origin") == "app" for r in responses)
    # one header, not duplicated by the several middlewares
    assert all(r.headers.get_list("x-eb-origin") == ["app"] for r in responses)


def test_a_304_is_marked_too(client, settings):  # noqa: F811
    update(settings, FakeExchange(PAGES, now=LAUNCH), 2)
    first = client.get(f"/api/missed/{LEAGUE}")
    again = client.get(f"/api/missed/{LEAGUE}", headers={"If-None-Match": first.headers["etag"]})
    assert again.status_code == 304 and again.headers["x-eb-origin"] == "app"


def test_frontend_types_are_up_to_date():
    """web/openapi.json (the source of the frontend's TS types) matches the API.
    If this fails: `cd web && npm run gen:api`, then fix any type errors it shows."""
    from pathlib import Path

    from exiledbroker.api.schema import schema

    committed = Path(__file__).resolve().parents[1] / "web" / "openapi.json"
    assert committed.read_text() == schema()
