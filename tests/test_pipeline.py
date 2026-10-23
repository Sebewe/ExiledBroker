"""The hosted pipeline (`eb pipeline run`): one hourly pass over the replay fixture
(Mirage's first 30 hours, as GGG published them). The volume is "seeded" by loading
the first hours, as a real deploy copies the research database over; each pass then
loads only new hours into DuckDB and publishes only them to Postgres.

The publishing tests need a disposable Postgres (EB_TEST_POSTGRES_URL, as
tests/test_postgres.py; CI starts one). The rest run everywhere."""

import os
from datetime import timedelta

import pytest

from exiledbroker.config import Settings
from exiledbroker.ingest import currency_exchange as cx
from exiledbroker.ingest import pipeline
from exiledbroker.ingest.live import sync_live
from exiledbroker.storage import db, site
from test_currency_exchange import FakeExchange, client_for
from test_live_pipeline import LAUNCH, PAGES, store_reference_data

PG_URL = os.environ.get("EB_TEST_POSTGRES_URL")
needs_pg = pytest.mark.skipif(not PG_URL, reason="EB_TEST_POSTGRES_URL is not set")
LEAGUE = "Mirage"
EARLIEST = cx.from_ts(LAUNCH - 72 * 3600)


def at(hours_in: int):
    """Ten minutes into hour `hours_in` after launch (that hour still trading)."""
    return cx.from_ts(LAUNCH + hours_in * 3600) + timedelta(minutes=10)


@pytest.fixture
def seeded(tmp_path, monkeypatch):
    """A pipeline volume holding the league's first 6 hours, and the fake exchange."""
    monkeypatch.setenv("EB_DATA_DIR", str(tmp_path))
    s = Settings(data_dir=tmp_path, request_min_interval=0)
    store_reference_data(s)
    server = FakeExchange(PAGES, now=LAUNCH + 6 * 3600)
    with client_for(s, server) as c:
        sync_live(c, s, LEAGUE, now=at(6), earliest=EARLIEST)
    # The pipeline's own window search starts from its history, not 2024.
    monkeypatch.setattr(cx, "HISTORY_START", EARLIEST)
    return s, server


def run(s, server, hours_in: int, **kw):
    server.now = LAUNCH + hours_in * 3600
    with client_for(s, server) as c:
        result = pipeline.run(c, s, now=at(hours_in), **kw)
        return result, c.requests


def test_an_empty_volume_is_not_backfilled_from_ggg(tmp_path):
    s = Settings(data_dir=tmp_path, request_min_interval=0)
    server = FakeExchange(PAGES, now=LAUNCH + 6 * 3600)
    with client_for(s, server) as c, pytest.raises(pipeline.EmptyVolume):
        pipeline.run(c, s, LEAGUE, now=at(6))
    assert server.requests == []


def test_it_never_writes_the_site_database_directly(seeded):
    s, server = seeded
    s = s.model_copy(update={"database_url": "postgresql://site"})
    with pytest.raises(ValueError, match="EB_PUBLISH_URL"):
        run(s, server, 8)


def test_the_league_comes_from_the_announcement_or_the_cached_list(seeded):
    s, server = seeded
    with client_for(s, server) as c:
        # poe.ninja's list, stored fresh (store_reference_data): no request.
        assert pipeline.pick_league(c, s, at(8)) == LEAGUE
        assert c.requests == 0
        announced = s.model_copy(update={"next_league": "Next", "next_league_start": at(7)})
        assert pipeline.pick_league(c, announced, at(8)) == "Next"
        assert pipeline.pick_league(c, announced, at(6)) == LEAGUE  # not started yet


def test_each_pass_loads_only_new_hours(seeded):
    s, server = seeded
    result, _ = run(s, server, 9)
    assert result.live.state == "updated" and result.live.hours_added == 3
    assert result.published is None  # no EB_PUBLISH_URL
    again, _ = run(s, server, 9)
    assert again.live.state == "unchanged" and again.live.fetched == 0
    with db.session(s.db_path, read_only=True) as con:
        runs = db.scalar(con, "SELECT count(*) FROM ingest_run")
    assert runs >= 2  # every pass is recorded


def test_launch_picks_are_rebuilt_once_when_a_fortnight_completes(seeded, monkeypatch):
    s, server = seeded
    built = []
    monkeypatch.setattr(pipeline.launch_picks, "complete_leagues", lambda con: [LEAGUE])
    real = pipeline.launch_picks.build
    monkeypatch.setattr(
        pipeline.launch_picks,
        "build",
        lambda con, leagues: built.append(leagues) or real(con, leagues),
    )
    assert run(s, server, 8)[0].picks_rebuilt
    assert not run(s, server, 9)[0].picks_rebuilt  # built from the same leagues already
    assert built == [[LEAGUE]]


# --- Publishing to the site's Postgres ----------------------------------------------


@pytest.fixture
def pg(seeded):
    """Two empty databases: the site's (published to) and one seeded whole, to compare."""
    import psycopg

    admin = psycopg.connect(PG_URL, autocommit=True)
    for name in ("eb_site", "eb_seeded"):
        admin.execute(f"DROP DATABASE IF EXISTS {name} WITH (FORCE)")
        admin.execute(f"CREATE DATABASE {name}")
    base = PG_URL.rsplit("/", 1)[0]
    yield {name: f"{base}/{name}" for name in ("eb_site", "eb_seeded")}
    admin.close()


def _dump(url: str) -> dict:
    import psycopg

    tables = [*site.LEAGUE_TABLES, *site.SHARED_TABLES, *site.REPLACED_TABLES]
    with psycopg.connect(url) as con:
        return {t: sorted(map(repr, db.rows(con, f"SELECT * FROM {t}"))) for t in tables}


@needs_pg
def test_publishing_hour_by_hour_matches_a_full_copy(seeded, pg):
    import psycopg

    s, server = seeded
    s = s.model_copy(update={"publish_url": pg["eb_site"]})
    first, _ = run(s, server, 6)
    assert first.published.hours_added == 6
    for hours_in in (9, 12, 20, 30):
        result, _ = run(s, server, hours_in)
        assert result.published.changed and result.published.hours_removed == 0
    with (
        db.session(s.db_path, read_only=True) as duck,
        psycopg.connect(pg["eb_seeded"], autocommit=True) as con,
    ):
        site.seed(duck, con, [LEAGUE])
    published, seeded_copy = _dump(pg["eb_site"]), _dump(pg["eb_seeded"])
    for table in published:
        if table == "reference_data":  # seed copies it whole too; both are the same rows
            assert len(published[table]) == len(seeded_copy[table])
            continue
        assert published[table] == seeded_copy[table], table


@needs_pg
def test_a_pass_with_nothing_new_writes_nothing(seeded, pg):
    import psycopg

    s, server = seeded
    s = s.model_copy(update={"publish_url": pg["eb_site"]})
    run(s, server, 9)
    with psycopg.connect(pg["eb_site"]) as con:
        version = db.scalar(con, "SELECT max(loaded_at) FROM ingest_load")
    again, _ = run(s, server, 9)
    assert not again.published.changed
    with psycopg.connect(pg["eb_site"]) as con:
        assert db.scalar(con, "SELECT max(loaded_at) FROM ingest_load") == version


@needs_pg
def test_a_failed_publish_leaves_the_site_as_it_was(seeded, pg, monkeypatch):
    import psycopg

    s, server = seeded
    s = s.model_copy(update={"publish_url": pg["eb_site"]})
    run(s, server, 9)
    with psycopg.connect(pg["eb_site"]) as con:
        before = db.scalar(con, "SELECT count(*) FROM exchange_hour_loaded")
    real = site._copy

    def broken(con, table, cols, rows):
        if table == "exchange_hour_loaded":
            raise OSError("connection lost")
        real(con, table, cols, rows)

    monkeypatch.setattr(site, "_copy", broken)
    with pytest.raises(OSError):
        run(s, server, 12)
    with psycopg.connect(pg["eb_site"]) as con:
        assert db.scalar(con, "SELECT count(*) FROM exchange_hour_loaded") == before
    monkeypatch.setattr(site, "_copy", real)
    result, _ = run(s, server, 12)  # the next pass catches up
    assert result.published.hours_added == 3


@needs_pg
def test_a_loader_rebuild_replaces_the_league_and_old_leagues_are_dropped(seeded, pg):
    import psycopg

    s, server = seeded
    s = s.model_copy(update={"publish_url": pg["eb_site"]})
    run(s, server, 9)
    with psycopg.connect(pg["eb_site"], autocommit=True) as con:
        # A previous league still in the site's database.
        con.execute(
            "INSERT INTO league (id, game, name, start_at, kind) VALUES ('poe1-old', 'poe1', 'Old', '2026-01-01', 'challenge')"
        )
        con.execute(
            "INSERT INTO ingest_load (league_id, source, fingerprint) VALUES ('poe1-old', %s, 'x')",
            [site.HOURLY],
        )
        # Published by an older loader version: the new version's rows replace them whole.
        con.execute(
            "UPDATE ingest_load SET fingerprint = 'loader_version=0' WHERE league_id <> 'poe1-old'"
        )
    result, _ = run(s, server, 9)
    assert result.published.rebuilt and result.published.leagues_dropped == ["Old"]
    with psycopg.connect(pg["eb_site"]) as con:
        assert db.scalar(con, "SELECT count(*) FROM ingest_load") == 1
        assert db.scalar(con, "SELECT count(DISTINCT hour) FROM exchange_hour_loaded") == 9
