"""The pre-launch preview's contracts (docs/preview.md): the snapshot table and its keys,
the one bounded route that serves it, /api/status's `preview`, and the announced next
league with only a date (and no name) known. The documents come from the sample
snapshot (web/src/test/preview_sample.json, made by make_preview_sample.py), which
the frontend's tests read too."""

import gzip
import json
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from exiledbroker.api import app as app_module
from exiledbroker.api import deps
from exiledbroker.api.routes import preview as preview_route
from exiledbroker.config import Settings
from exiledbroker.preview import snapshot
from exiledbroker.services import live
from exiledbroker.storage import db
from test_api import update
from test_currency_exchange import FakeExchange
from test_live_pipeline import LAUNCH, PAGES, settings  # noqa: F401

SAMPLE = Path(__file__).parents[1] / "web" / "src" / "test" / "preview_sample.json"
DOCS = json.loads(SAMPLE.read_text())


@pytest.fixture
def site(settings, monkeypatch):  # noqa: F811
    """The replay's first hours loaded and the sample snapshot stored next to them."""
    update(settings, FakeExchange(PAGES, now=LAUNCH), 3)
    with db.session(settings.db_path) as con:
        snapshot.load_file(con, SAMPLE)
    monkeypatch.setenv("EB_PREVIEW", "on")
    deps.reset()
    return TestClient(app_module.create_app())


# --- The snapshot ---------------------------------------------------------------------


def test_the_sample_holds_every_kind_of_key_and_matches_its_models():
    kinds = {snapshot.model_for(key) for key in DOCS}
    assert None not in kinds
    assert len(kinds) == len(snapshot.KINDS)  # one of each kind at least
    manifest = DOCS[snapshot.MANIFEST]
    days = [d["day"] for d in manifest["days"]]
    assert manifest["default_day"] in days
    for day in days:
        for what in ("missed", "price-check", "launch-picks", "recap-next"):
            assert snapshot.day_key(day, what) in DOCS
        listed = DOCS[snapshot.day_key(day, "price-check")]["items"]
        for item in listed:
            assert snapshot.day_key(day, "price-check", item["item_id"]) in DOCS
            assert snapshot.next_key(item["item_id"]) in DOCS
    # Stored as the route sends them: re-encoding changes nothing.
    for key, doc in DOCS.items():
        assert snapshot.decode(snapshot.encode(key, doc)) == doc, key


@pytest.mark.parametrize(
    "key",
    [
        "manifest/x",
        "d0/missed",
        "d100/missed",
        "d5/backtest",
        "d5/price-check/",
        "d5/price-check/a/b",
        "next/missed",
        "../manifest",
        "d5/price-check/" + "x" * 200,
    ],
)
def test_only_the_listed_keys_are_keys(key):
    assert snapshot.model_for(key) is None
    with pytest.raises(ValueError):
        snapshot.encode(key, {})


def test_a_document_that_doesnt_match_its_model_is_refused():
    with pytest.raises(ValueError):
        snapshot.encode("d5/price-check", {"league": "X"})


def test_writing_replaces_and_clearing_empties(tmp_path):
    with db.session(tmp_path / "x.duckdb") as con:
        db.init_schema(con)
        manifest = DOCS[snapshot.MANIFEST]
        snapshot.put(con, {snapshot.MANIFEST: manifest})
        snapshot.put(con, {snapshot.MANIFEST: {**manifest, "version": "two"}})
        assert snapshot.keys(con) == {snapshot.MANIFEST}
        assert snapshot.read(con, snapshot.MANIFEST)["version"] == "two"
        snapshot.clear(con)
        assert snapshot.keys(con) == set() and snapshot.read(con, "manifest") is None


# --- The route ------------------------------------------------------------------------


def test_every_stored_document_is_served_as_stored(site):
    for key, doc in DOCS.items():
        r = site.get(f"/api/preview/{key}")
        assert r.status_code == 200, (key, r.text)
        assert r.json() == doc, key


def test_a_key_the_snapshot_doesnt_hold_is_404_without_a_query(site, monkeypatch):
    site.get("/api/preview/manifest")  # the index is read once per data version
    monkeypatch.setattr(deps, "VERSION_TTL", 60.0)
    with db.metered() as meter:
        for key in ("d9/missed", "d2/price-check/currency:nothing", "anything", "d2/x/y"):
            r = site.get(f"/api/preview/{key}")
            assert r.status_code == 404, key
            assert r.headers["cache-control"] == "no-store"
    assert meter.queries == []


def test_the_versioned_url_is_cached_for_a_day_and_revalidates(site, monkeypatch):
    version = DOCS[snapshot.MANIFEST]["version"]
    key = "d2/missed"
    pinned = site.get(f"/api/preview/{key}", params={"v": version})
    assert pinned.headers["cache-control"] == preview_route.PREVIEW_CACHE_CONTROL
    assert pinned.headers["content-encoding"] == "gzip"
    other = site.get(f"/api/preview/{key}", params={"v": "old"})
    assert other.headers["cache-control"] == deps.CACHE_CONTROL
    assert other.headers["etag"] == pinned.headers["etag"]
    again = site.get(f"/api/preview/{key}", headers={"if-none-match": pinned.headers["etag"]})
    assert again.status_code == 304 and not again.content
    plain = site.get(f"/api/preview/{key}", headers={"accept-encoding": ""})
    assert "content-encoding" not in plain.headers and plain.json() == DOCS[key]
    # One query to read it, then from memory however many visitors ask.
    monkeypatch.setattr(deps, "VERSION_TTL", 60.0)
    with db.metered() as meter:
        for _ in range(5):
            site.get(f"/api/preview/{key}", params={"v": version})
    assert meter.queries == []


def test_without_a_snapshot_every_key_is_404(settings):  # noqa: F811
    update(settings, FakeExchange(PAGES, now=LAUNCH), 3)
    client = TestClient(app_module.create_app())
    assert client.get("/api/preview/manifest").status_code == 404
    assert client.get("/api/status").json()["preview"] is None


# --- /api/status ----------------------------------------------------------------------


def _status(client, monkeypatch, **env) -> dict:
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    deps.reset()
    r = client.get("/api/status")
    assert r.status_code == 200, r.text
    return r.json()


def test_status_offers_the_preview_until_the_announced_league_trades(site, monkeypatch):
    manifest = DOCS[snapshot.MANIFEST]
    # On: whenever a snapshot is there.
    assert _status(site, monkeypatch)["preview"] == manifest
    # Auto: only while a next league is announced and hasn't traded.
    monkeypatch.delenv("EB_NEXT_LEAGUE", raising=False)
    off = _status(site, monkeypatch, EB_PREVIEW="auto", EB_NEXT_LEAGUE_START="")
    assert off["preview"] is None and off["upcoming"] is None
    on = _status(site, monkeypatch, EB_NEXT_LEAGUE_START="2026-11-13")
    assert on["preview"] == manifest
    assert on["upcoming"] == {
        "name": None,
        "start_date": "2026-11-13",
        "time_known": False,
        "start_at": None,
        "first_data_at": None,
    }
    # Named, and that league has traded (the replay's league stands in for it): off.
    gone = _status(site, monkeypatch, EB_NEXT_LEAGUE="Mirage")
    assert gone["upcoming"] is None and gone["preview"] is None
    # Off: never.
    never = _status(site, monkeypatch, EB_PREVIEW="off", EB_NEXT_LEAGUE="Next")
    assert never["upcoming"]["name"] == "Next" and never["preview"] is None


# --- The announced league -------------------------------------------------------------


def _settings(**kw) -> Settings:
    return Settings(**kw)


def test_a_date_alone_is_a_date_and_a_time_is_a_time():
    day = _settings(next_league_start="2026-11-13")
    assert day.next_league_start == date(2026, 11, 13)
    assert day.next_league_start_at is None and day.next_league_date == date(2026, 11, 13)
    at = _settings(next_league_start="2026-11-13T21:00:00Z")
    assert at.next_league_start_at == datetime(2026, 11, 13, 21, tzinfo=UTC)
    naive = _settings(next_league_start="2026-11-14T03:00")  # UTC unless it says
    assert naive.next_league_start_at == datetime(2026, 11, 14, 3, tzinfo=UTC)
    assert naive.next_league_date == date(2026, 11, 14)
    blank = _settings(next_league_start="", next_league="")
    assert blank.next_league_start is None and blank.next_league is None


def test_upcoming_with_a_time_estimates_the_first_hour():
    s = _settings(next_league="Next", next_league_start="2026-11-13T21:30:00Z")
    up = live.upcoming_league(s, {})
    assert up == {
        "name": "Next",
        "start_date": date(2026, 11, 13),
        "time_known": True,
        "start_at": datetime(2026, 11, 13, 21, 30, tzinfo=UTC),
        "first_data_at": datetime(2026, 11, 13, 22, 10, tzinfo=UTC),
    }
    assert live.upcoming_league(s, {"Next": datetime(2026, 11, 13, 21)}) is None
    # Another league trading doesn't end a named one's wait.
    assert live.upcoming_league(s, {"Other": datetime(2026, 11, 13, 21)}) is not None


def test_a_nameless_league_has_arrived_once_a_league_launched_around_its_day_trades():
    s = _settings(next_league_start="2026-11-13")
    old = datetime(2026, 7, 25, 20)
    assert live.upcoming_league(s, {"Allflame": old})["name"] is None
    assert live.upcoming_league(s, {"Allflame": old, "New": datetime(2026, 11, 13, 21)}) is None
    assert live.upcoming_league(s, {"New": None}) is not None  # launch not known yet
    assert live.upcoming_league(_settings(), {}) is None  # nothing announced


def test_the_pipeline_switches_only_with_a_name_and_a_time(tmp_path):
    from exiledbroker.ingest import pipeline

    s = _settings(data_dir=tmp_path, next_league="Next", next_league_start="2026-11-13")
    assert pipeline.launch_search_from(s, "Next") == pipeline.cx.HISTORY_START
    timed = s.model_copy(update={"next_league_start": datetime(2026, 11, 13, 21, tzinfo=UTC)})
    assert pipeline.launch_search_from(timed, "Next") == datetime(2026, 11, 12, 21, tzinfo=UTC)


def test_the_sample_is_small():
    """It's committed, and the frontend's tests import it."""
    assert SAMPLE.stat().st_size < 150_000
    assert len(gzip.compress(SAMPLE.read_bytes())) < 40_000
