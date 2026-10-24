"""The hosted pipeline (`eb pipeline run`): one hourly pass on the site's database over
the replay fixture (Mirage's first 30 hours, as GGG published them).

The site's database is "seeded" with the first 6 hours, their pages and a Launch
history, as `eb site seed --hosted` does from the local copy; each pass then fetches
only what's newer, keeps only the window's pages in the database, and never reads
the disk. These run on a DuckDB file as the site's database; the seed-then-catch-up
comparison also runs on a disposable Postgres (EB_TEST_POSTGRES_URL, as
tests/test_postgres.py; CI starts one)."""

import ctypes
import gzip
import json
import os
import shutil
from datetime import UTC, datetime, timedelta

import pytest

from exiledbroker.config import Settings
from exiledbroker.ingest import currency_exchange as cx
from exiledbroker.ingest import pipeline
from exiledbroker.ingest.live import sync_live
from exiledbroker.services import item_history, launch_picks
from exiledbroker.storage import backup, db, site
from test_currency_exchange import FakeExchange, client_for
from test_live_pipeline import LAUNCH, PAGES, store_reference_data

PG_URL = os.environ.get("EB_TEST_POSTGRES_URL")
needs_pg = pytest.mark.skipif(not PG_URL, reason="EB_TEST_POSTGRES_URL is not set")
LEAGUE = "Mirage"
EARLIEST = cx.from_ts(LAUNCH - 72 * 3600)
SEEDED_HOURS = 6


def at(hours_in: int):
    """Ten minutes into hour `hours_in` after launch (that hour still trading)."""
    return cx.from_ts(LAUNCH + hours_in * 3600) + timedelta(minutes=10)


def _old_league_history(con, league: str = "Old") -> None:
    """A past league's Launch history, as `eb launch picks` captures it locally."""
    db.execute(
        con,
        "INSERT INTO launch_history VALUES (?, ?, 'currency:chaos-orb', 'day1', 0.01, 5)",
        [league, datetime(2026, 1, 1)],
    )


@pytest.fixture
def local(tmp_path, monkeypatch):
    """The local copy: the league's first hours loaded from pages on disk, as `eb live`
    leaves them, plus the fake exchange."""
    monkeypatch.setenv("EB_DATA_DIR", str(tmp_path))
    s = Settings(data_dir=tmp_path, request_min_interval=0)
    store_reference_data(s)
    server = FakeExchange(PAGES, now=LAUNCH + SEEDED_HOURS * 3600)
    with client_for(s, server) as c:
        sync_live(c, s, LEAGUE, now=at(SEEDED_HOURS), earliest=EARLIEST)
    with db.session(s.db_path) as con:
        _old_league_history(con)
    # The pipeline's own window search starts from its history, not 2024.
    monkeypatch.setattr(cx, "HISTORY_START", EARLIEST)
    return s, server


@pytest.fixture
def seeded(local):
    """The local copy used as the site's database: its pages moved into the database
    and the disk emptied, so the pipeline can only use what was seeded."""
    s, server = local
    hosted = pipeline.hosted(s)
    with db.session(s.db_path, read_only=True) as con:
        loaded = db.rows(con, "SELECT hour FROM exchange_hour_loaded")
    hours = [cx.to_ts(h.replace(tzinfo=UTC)) for (h,) in loaded]
    for ts in hours:
        cx.write_page(hosted, ts, cx.read_page(s, ts))
    shutil.rmtree(s.exchange_raw_dir)
    return s, server


def run(s, server, hours_in: int, **kw):
    server.now = LAUNCH + hours_in * 3600
    before = len(server.requests)
    with client_for(s, server) as c:
        result = pipeline.run(c, s, now=at(hours_in), **kw)
    return result, server.requests[before:]


def _pages(s) -> list[int]:
    with db.session(s.db_path, read_only=True) as con:
        return [r[0] for r in db.rows(con, "SELECT hour FROM exchange_page ORDER BY hour")]


def test_an_unseeded_database_is_not_backfilled_from_ggg(tmp_path):
    s = Settings(data_dir=tmp_path, request_min_interval=0)
    server = FakeExchange(PAGES, now=LAUNCH + 6 * 3600)
    with client_for(s, server) as c, pytest.raises(pipeline.NotSeeded):
        pipeline.run(c, s, LEAGUE, now=at(6))
    assert server.requests == []


def test_the_league_comes_from_the_announcement_or_the_cached_list(seeded):
    s, server = seeded
    with client_for(s, server) as c:
        # poe.ninja's list, stored fresh (store_reference_data): no request.
        assert pipeline.pick_league(c, s, at(8)) == LEAGUE
        assert c.requests == 0
        announced = s.model_copy(update={"next_league": "Next", "next_league_start": at(7)})
        assert pipeline.pick_league(c, announced, at(8)) == "Next"
        assert pipeline.pick_league(c, announced, at(6)) == LEAGUE  # not started yet


def test_a_pass_fetches_only_the_hours_since_the_seed(seeded):
    s, server = seeded
    result, requests = run(s, server, 9)
    assert result.live.state == "updated" and result.live.hours_added == 3
    assert len(requests) == 3 and result.live.fetched == 3  # one per new hour
    assert _pages(s) == [LAUNCH + h * 3600 for h in range(9)]  # stored in the database
    assert not s.exchange_raw_dir.exists()  # and never on disk
    again, requests = run(s, server, 9)
    assert again.live.state == "unchanged" and requests == []
    with db.session(s.db_path, read_only=True) as con:
        assert db.scalar(con, "SELECT count(*) FROM ingest_run") >= 2  # every pass recorded


def test_after_downtime_it_catches_up_exactly_the_missed_hours(seeded):
    s, server = seeded
    run(s, server, 8)
    result, requests = run(s, server, 20)  # down for 12 hours
    assert result.live.hours_added == 12 and len(requests) == 12
    assert len(set(requests)) == len(requests)  # nothing fetched twice


def test_pages_that_leave_the_window_are_deleted(seeded):
    s, server = seeded
    # A 6-hour look-back (and no launch days kept beyond it): old pages are pruned.
    run(s, server, 12, lookback_hours=6)
    window = list(range(LAUNCH + 6 * 3600, LAUNCH + 12 * 3600, 3600))
    assert set(_pages(s)) - set(window) <= set(
        range(LAUNCH, LAUNCH + 14 * 24 * 3600, 3600)
    )  # only the launch fortnight's pages are kept beyond the look-back
    assert set(window) <= set(_pages(s))


def test_a_loader_rebuild_rereads_the_stored_pages(seeded):
    s, server = seeded
    run(s, server, 9)
    with db.session(s.db_path) as con:
        con.execute("UPDATE ingest_load SET fingerprint = 'loader_version=0'")
    result, requests = run(s, server, 9)
    assert result.live.state == "updated" and requests == []  # rebuilt from the database
    assert result.live.hours_added == 9


def test_the_picks_are_ranked_from_the_history_once(seeded):
    s, server = seeded
    first, _ = run(s, server, 8)
    assert first.picks_from == ["Old"]  # nothing was built yet
    second, _ = run(s, server, 9)
    assert second.picks_from is None  # the same leagues: not rebuilt
    with db.session(s.db_path, read_only=True) as con:
        assert launch_picks.windows(con)["leagues"].to_list() == ["Old"] * 3


def test_a_replaced_league_is_dropped_once_the_new_one_has_data(seeded):
    s, server = seeded
    with db.session(s.db_path) as con:
        con.execute(
            "INSERT INTO league (id, game, name, start_at, kind, exchange_tracked) VALUES "
            "('poe1-old', 'poe1', 'Old', '2026-01-01', 'challenge', TRUE)"
        )
        con.execute(
            "INSERT INTO ingest_load (league_id, source, fingerprint) VALUES ('poe1-old', ?, 'x')",
            [site.HOURLY],
        )
    result, _ = run(s, server, 8)
    assert result.dropped == ["Old"]
    with db.session(s.db_path, read_only=True) as con:
        assert db.scalar(con, "SELECT count(*) FROM ingest_load") == 1
        assert not db.scalar(con, "SELECT exchange_tracked FROM league WHERE id = 'poe1-old'")
        assert launch_picks.captured_leagues(con) == ["Old"]  # its history stays


def _past_league(con) -> None:
    """A finished league in the site's database (on either engine): the replayed hours
    a year earlier, with a Chaos price 13.5 days in, so its fortnight is complete
    (`launch_picks.complete_leagues`). Not followed, so the pass keeps Mirage."""
    db.execute(
        con,
        "INSERT INTO league (id, game, name, start_at, launched_at, kind, exchange_tracked) "
        "SELECT 'poe1-past', game, 'Past', start_at - INTERVAL '365 days', "
        "launched_at - INTERVAL '365 days', kind, FALSE FROM league WHERE id = 'poe1-mirage'",
    )
    cols = backup._columns(con, "cross_market_hour")
    picked = ", ".join(
        {"league_id": "'poe1-past'", "observed_at": "observed_at - INTERVAL '365 days'"}.get(c, c)
        for c in cols
    )
    db.execute(
        con,
        f"INSERT INTO cross_market_hour ({', '.join(cols)}) SELECT {picked} "
        "FROM cross_market_hour WHERE league_id = 'poe1-mirage'",
    )
    start = db.scalar(con, "SELECT start_at FROM league WHERE id = 'poe1-past'")
    db.execute(
        con,
        "INSERT INTO price_observation (item_id, league_id, observed_at, day_offset, "
        "chaos_value, source) VALUES (?, 'poe1-past', ?, 13.5, 1.0, ?)",
        [launch_picks.CHAOS, start + timedelta(days=13.5), site.HOURLY],
    )


def test_a_finished_league_is_captured_into_the_farming_history_once(seeded):
    s, server = seeded
    with db.session(s.db_path) as con:
        _past_league(con)
    first, _ = run(s, server, 8)
    assert first.league == LEAGUE and first.farming_from == ["Past"]
    assert "Farming history captured for Past." in str(first)
    with db.session(s.db_path, read_only=True) as con:
        rows = db.scalar(con, "SELECT count(*) FROM item_day_history WHERE league = 'Past'")
        assert item_history.captured_leagues(con) == ["Past"]
    assert rows > 0  # the replay's basket items, day 0
    for hours_in in (9, 10):  # every later pass only checks
        later, _ = run(s, server, hours_in)
        assert later.farming_from == [] and "Farming history" not in str(later)
    with db.session(s.db_path, read_only=True) as con:
        assert db.scalar(con, "SELECT count(*) FROM item_day_history") == rows


def _killed_capture(monkeypatch):
    """item_history.capture that writes the league's rows, then dies (a pass stopped
    partway: a deploy, the cron's stop). Returns the real one, to put back."""
    real = item_history.capture

    def dies(con, league, item_ids):
        assert real(con, league, item_ids) > 0
        raise OSError("killed")

    monkeypatch.setattr(item_history, "capture", dies)
    return real


def test_a_capture_cut_short_leaves_nothing_and_the_next_pass_retries(seeded, monkeypatch):
    """A league with any rows counts as captured, so a half-written league would stay
    half-written for good (and be backed up so): the capture is one transaction."""
    s, server = seeded
    with db.session(s.db_path) as con:
        _past_league(con)
    real = _killed_capture(monkeypatch)
    with pytest.raises(OSError):
        run(s, server, 8)
    with db.session(s.db_path, read_only=True) as con:
        assert db.scalar(con, "SELECT count(*) FROM item_day_history") == 0
    monkeypatch.setattr(item_history, "capture", real)
    again, _ = run(s, server, 8)
    assert again.farming_from == ["Past"]


def test_without_baskets_the_farming_history_waits(seeded):
    s, server = seeded
    with db.session(s.db_path) as con:
        _past_league(con)
    missing = s.model_copy(update={"mechanics_file": s.data_dir / "nowhere.toml"})
    result, _ = run(missing, server, 8)
    assert result.farming_from == [] and "the Farming history waits" in str(result)
    with db.session(s.db_path, read_only=True) as con:  # not "captured" as empty
        assert item_history.captured_leagues(con) == []


# --- On Postgres, seeded with `eb site seed --hosted` ---------------------------------


@pytest.fixture
def pg():
    """Two empty databases: the server's, and one seeded whole at the end to compare."""
    import psycopg

    admin = psycopg.connect(PG_URL, autocommit=True)
    for name in ("eb_site", "eb_seeded"):
        admin.execute(f"DROP DATABASE IF EXISTS {name} WITH (FORCE)")
        admin.execute(f"CREATE DATABASE {name}")
    base = PG_URL.rsplit("/", 1)[0]
    urls = {name: f"{base}/{name}" for name in ("eb_site", "eb_seeded")}
    yield urls
    for url in urls.values():  # the API's pooled connections, before the next drop
        if pool := db._pools.pop(url, None):
            pool.close()
        db._schema_ready.discard(url)
    admin.close()


def _dump(url: str) -> dict:
    import psycopg

    tables = [*site.LEAGUE_TABLES, *site.SHARED_TABLES, *site.REPLACED_TABLES, "exchange_page"]
    with psycopg.connect(url) as con:
        out = {t: sorted(map(repr, db.rows(con, f"SELECT * FROM {t}"))) for t in tables}
        # Pages compare by content (gzip stamps a time, and the copies differ in it).
        out["exchange_page"] = [
            (hour, json.loads(gzip.decompress(body)))
            for hour, body in db.rows(con, "SELECT hour, body FROM exchange_page ORDER BY hour")
        ]
    return out


def _seed(s, url: str) -> None:
    import psycopg

    with (
        db.session(s.db_path, read_only=True) as duck,
        psycopg.connect(url, autocommit=True) as pg,
    ):
        site.seed(duck, pg, [LEAGUE], s)


@needs_pg
def test_seeded_then_caught_up_matches_the_local_copy(local, pg):
    """The server, seeded from the local copy and then left to catch up hour by hour,
    ends with the same rows as the local copy kept up to date and seeded at the end."""
    s, server = local
    _seed(s, pg["eb_site"])
    server_settings = s.model_copy(
        update={"database_url": pg["eb_site"], "data_dir": s.data_dir / "server"}
    )
    for hours_in in (9, 12, 20, 30):
        result, requests = run(server_settings, server, hours_in)
        assert result.live.state == "updated" and len(requests) == result.live.hours_added
    # The local copy, updated the usual way (pages on disk), then seeded whole.
    with client_for(s, server) as c:
        sync_live(c, s, LEAGUE, now=at(30), earliest=EARLIEST)
    with db.session(s.db_path) as con:
        launch_picks.refresh(con)  # `eb launch picks`
    _seed(s, pg["eb_seeded"])
    server_rows, local_rows = _dump(pg["eb_site"]), _dump(pg["eb_seeded"])
    for table in server_rows:
        if table in ("ingest_load", "reference_data", "launch_window"):
            # Load and build times differ; the counts and everything else must match.
            assert len(server_rows[table]) == len(local_rows[table]), table
            continue
        assert server_rows[table] == local_rows[table], table
    assert not (s.data_dir / "server" / "raw").exists()  # the server never used a disk


@needs_pg
def test_a_failed_pass_leaves_the_site_as_it_was(local, pg, monkeypatch):
    import psycopg

    s, server = local
    _seed(s, pg["eb_site"])
    hosted = s.model_copy(update={"database_url": pg["eb_site"]})
    with psycopg.connect(pg["eb_site"]) as con:
        before = db.scalar(con, "SELECT count(*) FROM exchange_hour_loaded")
    from exiledbroker.normalize import exchange_loader

    real = exchange_loader.refresh_mappings

    def broken(con, settings):
        raise OSError("connection lost")

    monkeypatch.setattr(exchange_loader, "refresh_mappings", broken)
    with pytest.raises(OSError):
        run(hosted, server, 9)
    with psycopg.connect(pg["eb_site"]) as con:
        assert db.scalar(con, "SELECT count(*) FROM exchange_hour_loaded") == before
    monkeypatch.setattr(exchange_loader, "refresh_mappings", real)
    result, requests = run(hosted, server, 9)  # the next pass catches up
    assert result.live.hours_added == 3 and requests == []  # its pages were kept


@needs_pg
def test_a_hosted_capture_cut_short_leaves_nothing(local, pg, monkeypatch):
    """The same on Postgres, through `site_writer`: the capture's DELETE (pushed down)
    and its INSERTs are one Postgres transaction, so nothing of the league is left."""
    import psycopg

    s, server = local
    _seed(s, pg["eb_site"])
    with psycopg.connect(pg["eb_site"], autocommit=True) as con:
        _past_league(con)
    hosted = s.model_copy(update={"database_url": pg["eb_site"]})
    real = _killed_capture(monkeypatch)
    with pytest.raises(OSError):
        run(hosted, server, 9)
    with psycopg.connect(pg["eb_site"]) as con:
        assert db.scalar(con, "SELECT count(*) FROM item_day_history") == 0
    monkeypatch.setattr(item_history, "capture", real)
    again, _ = run(hosted, server, 9)
    assert again.farming_from == ["Past"]
    with psycopg.connect(pg["eb_site"]) as con:
        assert item_history.captured_leagues(con) == ["Past"]


@needs_pg
def test_a_pass_never_copies_a_whole_table_out_of_postgres(local, pg, monkeypatch, capfd):
    """Through an attached Postgres, DuckDB answers a DELETE, an aggregate or a
    correlated subquery by copying the league's rows out (the hosted pass read ~100 MB
    that way; across the internet to Supabase, ~70 GB a month). Those statements run on
    Postgres itself (`db.pushdown`); what DuckDB still copies from the big tables must
    be limited to some hours or items. The pass also captures a finished league into
    the Farming history (`item_history.refresh`), on Postgres too. (The league is in
    the Launch history already: `launch_picks.capture` copies a league's fortnight of
    kept prices out, filtered by league and day, once a league.)"""
    import psycopg

    s, server = local
    _seed(s, pg["eb_site"])
    with psycopg.connect(pg["eb_site"], autocommit=True) as con:
        _past_league(con)
        _old_league_history(con, "Past")
    hosted = s.model_copy(update={"database_url": pg["eb_site"]})
    monkeypatch.setattr(db, "SHOW_PG_QUERIES", True)
    capfd.readouterr()
    result, requests = run(hosted, server, 9)
    assert result.live.hours_added == 3 and len(requests) == 3
    assert result.farming_from == ["Past"]
    ctypes.CDLL(None).fflush(None)  # DuckDB prints from C, to stderr
    sent = capfd.readouterr().err
    copies = [q for q in sent.split("\n\n") if q.lstrip().startswith("COPY (SELECT")]
    assert copies  # the debug output was captured
    for table in ("price_observation", "cross_market_hour", "exchange_page"):
        whole = [
            q
            for q in copies
            if f'"public"."{table}"' in q
            and not any(c in q for c in ('"observed_at"', '"item_id" ='))
        ]
        assert not whole, (table, whole[:1])
