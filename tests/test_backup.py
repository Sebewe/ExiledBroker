"""The off-site backup (storage/backup.py): each hosted pipeline pass syncs the site's
database to a second Postgres (Supabase, hosted), uploading the changes and reading
back only enough to know what they are; a restore copies it back.

On the replay fixture (Mirage's first hours), with three throwaway databases on
EB_TEST_POSTGRES_URL (as tests/test_pipeline.py; CI starts one): the site, its backup,
and a reference seeded from the local copy."""

import os
from datetime import datetime

import pytest

psycopg = pytest.importorskip("psycopg")  # the Postgres extra; CI's main job runs without it

from exiledbroker.storage import backup, db
from test_pipeline import LEAGUE, _dump, _seed, local, needs_pg, run  # noqa: F401

pytestmark = needs_pg
NAMES = ("eb_site", "eb_backup", "eb_ref")


@pytest.fixture
def dbs():
    admin = psycopg.connect(os.environ["EB_TEST_POSTGRES_URL"], autocommit=True)
    for name in NAMES:
        admin.execute(f"DROP DATABASE IF EXISTS {name} WITH (FORCE)")
        admin.execute(f"CREATE DATABASE {name}")
    base = os.environ["EB_TEST_POSTGRES_URL"].rsplit("/", 1)[0]
    urls = {name: f"{base}/{name}" for name in NAMES}
    yield urls
    for url in urls.values():  # the API's pooled connections, before the next drop
        if pool := db._pools.pop(url, None):
            pool.close()
        db._schema_ready.discard(url)
    admin.close()


def hosted(s, dbs, **extra):
    """The pipeline's settings on Railway: the site's Postgres, and the backup."""
    return s.model_copy(
        update={
            "database_url": dbs["eb_site"],
            "backup_url": dbs["eb_backup"],
            "data_dir": s.data_dir / "server",
            **extra,
        }
    )


class BackupReads:
    """Bytes read back from the backup's database (the billed egress), through the db
    helpers: rows fetched on connections to it."""

    def __init__(self, monkeypatch, dbname: str = "eb_backup"):
        self.bytes = 0
        real, meter = db._pg_query, self

        class Counted:
            def __init__(self, cur):
                self.cur, self.description = cur, cur.description

            def fetchall(self):
                rows = self.cur.fetchall()
                meter.bytes += sum(len(str(v)) for r in rows for v in r)
                return rows

            def close(self):
                self.cur.close()

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                self.cur.close()

        def query(con, sql, params):
            cur = real(con, sql, params)
            info = getattr(con, "info", None)  # the pipeline's attached DuckDB has none
            return Counted(cur) if info is not None and info.dbname == dbname else cur

        monkeypatch.setattr(db, "_pg_query", query)


def assert_same(a: str, b: str) -> None:
    left, right = _dump(a), _dump(b)
    for table in left:
        assert left[table] == right[table], table


def test_each_pass_backs_up_the_site_and_reads_little(local, dbs, monkeypatch):  # noqa: F811
    s, server = local
    _seed(s, dbs["eb_site"])
    reads = BackupReads(monkeypatch)
    for hours_in in (9, 10, 11):
        before = reads.bytes
        result, _ = run(hosted(s, dbs), server, hours_in)
        read = reads.bytes - before
        assert result.backup_error is None and result.backup is not None, result
        if hours_in > 9:  # after the first copy, a pass reads under a kB back
            assert result.backup.leagues["poe1-mirage"].hours_added == 1
            assert read < 2_000, read
        assert_same(dbs["eb_site"], dbs["eb_backup"])  # (this read isn't the pass's)
    again = backup.back_up(hosted(s, dbs))
    assert not again.changed and "up to date" in str(again)


def test_a_failed_backup_never_fails_the_pass(local, dbs):  # noqa: F811
    s, server = local
    _seed(s, dbs["eb_site"])
    broken = hosted(s, dbs, backup_url="postgresql://postgres:eb@127.0.0.1:9/nowhere")
    result, _ = run(broken, server, 9)
    assert result.live.state == "updated" and result.live.hours_added == 3
    assert result.backup is None and "OperationalError" in result.backup_error
    assert "the next pass catches up" in str(result)
    result, _ = run(hosted(s, dbs), server, 10)  # it's back: caught up in one go
    assert result.backup.leagues["poe1-mirage"].hours_added == 10
    assert_same(dbs["eb_site"], dbs["eb_backup"])


def test_hours_leaving_the_window_leave_the_backup_with_their_pages(local, dbs):  # noqa: F811
    """What the pipeline deletes as hours leave the window (the replay's hours all sit
    in the launch fortnight, which is always kept, so they're deleted here directly)."""
    s, server = local
    _seed(s, dbs["eb_site"])
    run(hosted(s, dbs), server, 9)
    with psycopg.connect(dbs["eb_site"], autocommit=True) as con:
        first = db.scalar(con, "SELECT min(hour) FROM exchange_hour_loaded")
        for table, col in (
            ("price_observation", "observed_at"),
            ("cross_market_hour", "observed_at"),
            ("exchange_hour_loaded", "hour"),
        ):
            con.execute(f"DELETE FROM {table} WHERE {col} = %s", [first])
        con.execute("DELETE FROM exchange_page WHERE hour = (SELECT min(hour) FROM exchange_page)")
    result = backup.back_up(hosted(s, dbs))
    assert result.leagues["poe1-mirage"].hours_removed == 1 and result.pages_removed == 1
    assert not result.warnings
    assert_same(dbs["eb_site"], dbs["eb_backup"])


def test_a_league_rebuilt_by_a_new_loader_is_copied_afresh(local, dbs):  # noqa: F811
    """After a deploy that rebuilds the league, the backup's copy is emptied and
    vacuumed before the new rows go in, so it doesn't hold both."""
    s, server = local
    _seed(s, dbs["eb_site"])
    run(hosted(s, dbs), server, 9)
    with psycopg.connect(dbs["eb_site"], autocommit=True) as con:
        con.execute("UPDATE ingest_load SET fingerprint = 'loader_version=999'")
    result = backup.back_up(hosted(s, dbs))
    league = result.leagues["poe1-mirage"]
    assert league.rebuilt and league.hours_added == 9 and not result.warnings
    assert_same(dbs["eb_site"], dbs["eb_backup"])


def test_restoring_rebuilds_the_site_and_the_pipeline_carries_on(local, dbs):  # noqa: F811
    s, server = local
    _seed(s, dbs["eb_site"])
    run(hosted(s, dbs), server, 9)
    with (
        psycopg.connect(dbs["eb_ref"], autocommit=True) as lost,  # an empty new database
        psycopg.connect(dbs["eb_backup"], autocommit=True) as src,
    ):
        restored = backup.sync(src, lost, hosted(s, dbs, exchange_pages="database"))
    assert restored.leagues["poe1-mirage"].hours_added == 9
    assert_same(dbs["eb_backup"], dbs["eb_ref"])
    on_restored = hosted(s, dbs, database_url=dbs["eb_ref"], backup_url=None)
    result, requests = run(on_restored, server, 12)
    assert result.live.hours_added == 3 and len(requests) == 3  # only the new hours


def test_a_league_switch_reaches_the_backup(local, dbs):  # noqa: F811
    s, server = local
    _seed(s, dbs["eb_site"])
    run(hosted(s, dbs), server, 9)
    with psycopg.connect(dbs["eb_backup"], autocommit=True) as con:
        con.execute(
            "INSERT INTO league (id, game, name, start_at, kind, exchange_tracked) VALUES "
            "('poe1-old', 'poe1', 'Old', '2026-01-01', 'challenge', TRUE)"
        )
        con.execute(
            "INSERT INTO ingest_load (league_id, source, fingerprint) VALUES "
            "('poe1-old', 'ggg-exchange-hourly', 'x')"
        )
    result = backup.back_up(hosted(s, dbs))
    assert result.dropped == ["poe1-old"]
    assert_same(dbs["eb_site"], dbs["eb_backup"])


def test_backing_up_the_local_copy_matches_a_seed(local, dbs, monkeypatch):  # noqa: F811
    """`eb site backup` without EB_DATABASE_URL: from the local research copy, the
    named league only, as `eb site seed --hosted` copies it."""
    s, _ = local
    _seed(s, dbs["eb_ref"])
    with (
        db.session(s.db_path, read_only=True) as duck,
        psycopg.connect(dbs["eb_backup"], autocommit=True) as dst,
    ):
        first = backup.sync(duck, dst, s, [LEAGUE])
        reads = BackupReads(monkeypatch)
        again = backup.sync(duck, dst, s, [LEAGUE])
    assert first.leagues["poe1-mirage"].hours_added == 6 and first.pages_added == 6
    assert not again.changed and reads.bytes < 10_000
    assert_same(dbs["eb_ref"], dbs["eb_backup"])


def test_a_copy_needs_autocommit(local, dbs):  # noqa: F811
    s, _ = local
    with (
        db.session(s.db_path, read_only=True) as duck,
        psycopg.connect(dbs["eb_backup"]) as dst,
        pytest.raises(ValueError, match="autocommit"),
    ):
        backup.sync(duck, dst, s, [LEAGUE])


# --- The commands -------------------------------------------------------------------


def _eb(*args):
    from typer.testing import CliRunner

    from exiledbroker.cli import app

    return CliRunner().invoke(app, list(args))


def test_eb_site_backup_from_the_local_copy(local, dbs, monkeypatch):  # noqa: F811
    monkeypatch.setenv("EB_BACKUP_URL", dbs["eb_backup"])
    out = _eb("site", "backup", "-l", LEAGUE)
    assert out.exit_code == 0, out.output
    assert "Backup: poe1-mirage +6/-0 hours" in out.output and "pages +6/-0" in out.output
    assert "up to date" in _eb("site", "backup", "-l", LEAGUE).output


def test_eb_site_restore_says_the_size_first_and_needs_yes(local, dbs, monkeypatch):  # noqa: F811
    s, _ = local
    _seed(s, dbs["eb_backup"])
    monkeypatch.setenv("EB_BACKUP_URL", dbs["eb_backup"])
    monkeypatch.setenv("EB_DATABASE_URL", dbs["eb_ref"])
    refused = _eb("site", "restore")
    assert refused.exit_code == 1 and "The backup's database is " in refused.output
    assert "--yes" in refused.output
    with psycopg.connect(dbs["eb_ref"]) as con:  # nothing was copied
        assert not db.scalar(
            con, "SELECT count(*) FROM information_schema.tables WHERE table_name = 'ingest_load'"
        )
    done = _eb("site", "restore", "--yes")
    assert done.exit_code == 0, done.output
    assert "Restored from the backup: poe1-mirage +6/-0 hours" in done.output
    assert_same(dbs["eb_backup"], dbs["eb_ref"])


# --- The tables built from past leagues -----------------------------------------------


def _sell_helper_report(con, built_at: datetime) -> None:
    db.execute(con, "DELETE FROM sell_helper_report")
    db.execute(
        con,
        "INSERT INTO sell_helper_report VALUES ('report', ?, ?)",
        [built_at, '{"impact": {"y": null, "bands": [0.25, 1.0]}}'],
    )


def _has_table(url: str, table: str) -> bool:
    with psycopg.connect(url) as con:
        q = "SELECT count(*) FROM information_schema.tables WHERE table_name = ?"
        return bool(db.scalar(con, q, [table]))


def test_the_sell_helper_report_is_backed_up_incrementally(local, dbs, monkeypatch):  # noqa: F811
    """Seeded with the report, then the report rebuilt: each sync sends only what
    changed, and a pass where nothing did reads back only the stamps."""
    s, server = local
    with db.session(s.db_path) as con:
        _sell_helper_report(con, datetime(2026, 10, 24, 9))
    _seed(s, dbs["eb_site"])
    reads = BackupReads(monkeypatch)
    first, _ = run(hosted(s, dbs), server, 9)
    assert "sell helper report" in first.backup.tables
    assert_same(dbs["eb_site"], dbs["eb_backup"])

    before = reads.bytes
    second, _ = run(hosted(s, dbs), server, 10)  # a new hour; nothing built changed
    assert not {"sell helper report", "launch tables"} & set(second.backup.tables)
    assert reads.bytes - before < 2_000, reads.bytes - before

    with psycopg.connect(dbs["eb_site"], autocommit=True) as con:  # `eb sell-helper build`, seeded
        _sell_helper_report(con, datetime(2026, 10, 25, 9))
    assert backup.back_up(hosted(s, dbs)).tables == ["sell helper report"]
    assert_same(dbs["eb_site"], dbs["eb_backup"])
    assert not backup.back_up(hosted(s, dbs)).changed


def test_the_retired_farming_history_is_dropped_from_the_site_and_the_backup(local, dbs):  # noqa: F811
    """A site and a backup from before the Farming page's removal still hold
    item_day_history (~10 MB hosted): the schema drops it on the next pass and sync,
    and nothing reads it first."""
    s, server = local
    _seed(s, dbs["eb_site"])
    run(hosted(s, dbs), server, 9)
    old = (
        "CREATE TABLE item_day_history (league VARCHAR, league_start TIMESTAMP, "
        "item_id VARCHAR, day INTEGER, chaos DOUBLE PRECISION)"
    )
    for name in ("eb_site", "eb_backup"):
        with psycopg.connect(dbs[name], autocommit=True) as con:
            con.execute(old)
            con.execute("INSERT INTO item_day_history VALUES ('Keepers', now(), 'x', 0, 1.0)")
        db._schema_ready.discard(dbs[name])  # a new deploy: the schema runs again
    result, _ = run(hosted(s, dbs), server, 10)
    assert result.backup_error is None and result.backup is not None, result
    assert not _has_table(dbs["eb_site"], "item_day_history")
    assert not _has_table(dbs["eb_backup"], "item_day_history")
    assert_same(dbs["eb_site"], dbs["eb_backup"])


def _price_paths(con, built_at: datetime, leagues: list[str]) -> None:
    """Price check's tables as `eb price-check build` leaves them (a few rows)."""
    for table in ("price_path_league", "price_path", "price_path_constant"):
        db.execute(con, f"DELETE FROM {table}")
    for lg in leagues:
        db.execute(
            con,
            "INSERT INTO price_path_league VALUES (?, ?, 'currency:x', '[-0.1]', '[-0.2]')",
            [lg, built_at],
        )
    db.execute(
        con, "INSERT INTO price_path VALUES ('currency:x', 0, -0.1, ?, -0.2, ?)", [len(leagues)] * 2
    )
    db.execute(
        con,
        "INSERT INTO price_path_constant VALUES ('days 0-2', TRUE, 'h24', 0.9, -0.4, 0.3, ?, ?)",
        [",".join(leagues), built_at],
    )


def test_price_check_paths_are_backed_up_once_a_league(local, dbs, monkeypatch):  # noqa: F811
    """Seeded with the paths, then a league captured: each sync sends them only when
    they changed, and a pass where nothing did reads back only the stamps."""
    s, server = local
    with db.session(s.db_path) as con:
        _price_paths(con, datetime(2026, 10, 24, 9), ["Keepers", "Mirage"])
    _seed(s, dbs["eb_site"])
    reads = BackupReads(monkeypatch)
    first, _ = run(hosted(s, dbs), server, 9)
    assert "price paths" in first.backup.tables
    assert_same(dbs["eb_site"], dbs["eb_backup"])

    before = reads.bytes
    second, _ = run(hosted(s, dbs), server, 10)
    assert "price paths" not in second.backup.tables
    assert reads.bytes - before < 2_000, reads.bytes - before

    with psycopg.connect(dbs["eb_site"], autocommit=True) as con:  # the pipeline's capture
        db.execute(
            con,
            "INSERT INTO price_path_league VALUES ('Allflame', now(), 'currency:x', '[0.1]', '[0.2]')",
        )
    assert backup.back_up(hosted(s, dbs)).tables == ["price paths"]
    assert_same(dbs["eb_site"], dbs["eb_backup"])
    assert not backup.back_up(hosted(s, dbs)).changed


def test_price_check_stamp_reads_under_150_bytes_for_five_leagues(dbs, monkeypatch):
    """What a pass reads back from the backup to know whether Price check's paths are
    current (`backup._price_stamp`, every pass): the captured leagues with their row
    counts, the paths' row count and the constants' count and build time. Five leagues
    is the real size (Settlers to Allflame); the paths themselves are never read back."""
    leagues = ["Settlers", "Mercenaries", "Keepers", "Mirage", "Allflame"]
    with psycopg.connect(dbs["eb_backup"], autocommit=True) as con:
        db.init_schema(con)
        _price_paths(con, datetime(2026, 10, 25, 9), leagues)
        db.execute(  # a real league has hundreds of rows: they stay on the backup
            con,
            "INSERT INTO price_path_league SELECT 'Allflame', now(), 'currency:' || g, '[0]', "
            "'[0]' FROM generate_series(1, 500) g",
        )
        reads = BackupReads(monkeypatch)
        stamp = backup._price_stamp(con)
    assert len(stamp[0]) == 5 and stamp[1] == 1
    assert 0 < reads.bytes < 150, reads.bytes


def test_usage_totals_are_backed_up_but_never_the_visitor_ids(local, dbs):  # noqa: F811
    """The counts survive a lost database (and come back on a restore); the period's
    salt and visitor ids stay on the site, deleted when the period ends."""
    from contextlib import contextmanager

    from exiledbroker.api import usage

    s, server = local
    _seed(s, dbs["eb_site"])

    @contextmanager
    def site_db():
        with psycopg.connect(dbs["eb_site"], autocommit=True) as con:
            yield con

    counter = usage.Usage(site_db)
    counter.record("page:/", "203.0.113.7", "Mozilla/5.0 Firefox/140.0")
    counter.flush()
    run(hosted(s, dbs), server, 9)
    with psycopg.connect(dbs["eb_backup"], autocommit=True) as con:
        assert db.rows(con, "SELECT event, views FROM usage_daily ORDER BY event") == [
            ("page:/", 1),
            ("site", 1),
        ]
        for private in ("usage_salt", "usage_visitor", "usage_seen"):
            assert db.scalar(con, f"SELECT count(*) FROM {private}") == 0
    with (
        psycopg.connect(dbs["eb_ref"], autocommit=True) as lost,
        psycopg.connect(dbs["eb_backup"], autocommit=True) as src,
    ):
        backup.sync(src, lost, hosted(s, dbs, exchange_pages="database"))
        assert db.scalar(lost, "SELECT sum(views) FROM usage_daily") == 2
