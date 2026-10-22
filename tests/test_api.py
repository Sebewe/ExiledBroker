"""The site's API on the real-data replay (Mirage's first 30 hours, see
test_live_pipeline.py): every endpoint after every update, from no data at all to a
day and a half, plus validation, the result cache and serving the frontend."""

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
CARD = "currency:the-doctor"


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
    return [
        "/api/status",
        f"/api/live/{league}/loops",
        f"/api/live/{league}/card-flips?lookback=48",
        f"/api/arbitrage?league={league}&min_hours=1",
        f"/api/arbitrage/hourly?league={league}&item_id=currency:exalted-orb",
        f"/api/cards/{league}",
        f"/api/cards/{league}/{CARD}/hourly",
        "/api/market/leagues",
        "/api/market/groups",
        f"/api/market/{league}/summary?group=currency&group=divination",
        f"/api/market/{league}/hourly?item_id=currency:divine-orb&unit=divine",
        "/api/leagues",
    ]


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200 and r.json()["game"] == "poe1"


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

    # After 30 hours there is something to trade.
    assert client.get(f"/api/live/{LEAGUE}/loops?lookback=48&min_price=0").json()
    arbitrage = client.get(f"/api/arbitrage?league={LEAGUE}&min_hours=1&min_price=0").json()
    assert arbitrage and arbitrage[0]["score"] >= arbitrage[-1]["score"]
    hourly = client.get(f"/api/market/{LEAGUE}/hourly?item_id=currency:divine-orb").json()
    assert hourly[-1]["observed_at"].endswith("Z")  # UTC, explicitly


def test_tables_are_computed_once_per_data_version(client, settings, monkeypatch):  # noqa: F811
    server = FakeExchange(PAGES, now=LAUNCH)
    update(settings, server, 6)
    monkeypatch.setattr(deps, "VERSION_TTL", 60.0)  # as in production
    path = f"/api/cards/{LEAGUE}"
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


def test_default_pages_are_precomputed(client, settings, monkeypatch):  # noqa: F811
    """After warm(), what the pages ask for with their default controls is cached."""
    from exiledbroker.api import warm

    update(settings, FakeExchange(PAGES, now=LAUNCH), 30)
    assert warm.warm() >= 6
    monkeypatch.setattr(deps, "VERSION_TTL", 60.0)
    # Exactly the requests the frontend makes on first load (web/src/api/queries.ts).
    page_loads = [
        "/api/status",
        f"/api/live/{LEAGUE}/loops?direction=chaos_first&buffer=0.02&lookback=6&min_price=1",
        f"/api/live/{LEAGUE}/card-flips?lookback=6&unit=chaos",
        f"/api/arbitrage?league={LEAGUE}&direction=chaos_first&buffer=0.02&min_hours=24&min_price=1",
        f"/api/cards/{LEAGUE}?unit=chaos&prefer_cheaper_sets=true",
        "/api/market/leagues",
        "/api/market/groups",
        f"/api/market/{LEAGUE}/summary?group=currency&unit=chaos",
    ]
    for path in page_loads:
        with db.metered() as meter:
            assert client.get(path).status_code == 200
        assert not meter.queries, (path, [q.sql for q in meter.queries])


def test_charts_send_only_the_latest_hours(client, settings):  # noqa: F811
    update(settings, FakeExchange(PAGES, now=LAUNCH), 30)
    path = f"/api/arbitrage/hourly?league={LEAGUE}&item_id=currency:exalted-orb"
    every = client.get(f"{path}&hours=672").json()
    latest = client.get(f"{path}&hours=6").json()
    assert len({r["observed_at"] for r in latest}) <= 6 < len({r["observed_at"] for r in every})
    assert latest[-1]["observed_at"] == every[-1]["observed_at"]
    assert client.get(f"{path}&hours=10000").status_code == 422


def test_cache_is_bounded():
    c = cache.ResultCache(max_entries=3)
    for i in range(10):
        c.get_or_compute(("k", i), lambda i=i: i)
    assert len(c) == 3
    assert c.get_or_compute(("k", 9), lambda: "recomputed") == 9  # newest kept


def test_validation(client, settings):  # noqa: F811
    update(settings, FakeExchange(PAGES, now=LAUNCH), 3)
    assert client.get("/api/live/Nowhere/loops").status_code == 404
    assert client.get(f"/api/live/{LEAGUE}/loops?direction=sideways").status_code == 422
    assert client.get(f"/api/live/{LEAGUE}/loops?buffer=5").status_code == 422
    assert client.get(f"/api/live/{LEAGUE}/loops?weights=luck:3").status_code == 422
    assert client.get(f"/api/live/{LEAGUE}/loops?weights=volume:x").status_code == 422
    assert client.get(f"/api/live/{LEAGUE}/loops?weights=volume:0").status_code == 200
    assert client.get(f"/api/market/{LEAGUE}/summary?group=gems").status_code == 404


def test_serves_the_frontend(tmp_path, settings):  # noqa: F811
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<div id=root></div>")
    (dist / "assets" / "app.js").write_text("console.log(1)")
    c = TestClient(app_module.create_app(web_dist=dist))
    assert c.get("/").text == "<div id=root></div>"
    assert c.get("/arbitrage").text == "<div id=root></div>"  # client-side route
    assert c.get("/assets/app.js").text == "console.log(1)"
    assert c.get("/../pyproject.toml").text == "<div id=root></div>"  # no escaping dist
    assert c.get("/api/health").json()["status"] == "ok"
    assert c.get("/api/nope").status_code == 404  # API paths never fall through


def test_frontend_types_are_up_to_date():
    """web/openapi.json (the source of the frontend's TS types) matches the API.
    If this fails: `cd web && npm run gen:api`, then fix any type errors it shows."""
    from pathlib import Path

    from exiledbroker.api.schema import schema

    committed = Path(__file__).resolve().parents[1] / "web" / "openapi.json"
    assert committed.read_text() == schema()
