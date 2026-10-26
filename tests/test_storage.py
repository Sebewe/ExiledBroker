from exiledbroker.storage import db


def test_init_schema_is_idempotent(tmp_path):
    path = tmp_path / "test.duckdb"
    with db.session(path) as con:
        db.init_schema(con)
        db.init_schema(con)
        tables = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
    assert {"league", "item", "price_observation", "patch_change", "prediction"} <= tables


def test_table_counts_on_empty_db(tmp_path):
    from exiledbroker.services import overview

    with db.session(tmp_path / "test.duckdb") as con:
        db.init_schema(con)
        assert set(overview.table_counts(con).values()) == {0}


def _old_sell_helper_report(con) -> None:
    """A database from before 2026-10-26: the report under its old name, `farming_report`."""
    db.execute(
        con,
        "CREATE TABLE farming_report (id VARCHAR PRIMARY KEY, built_at TIMESTAMP NOT NULL, "
        "body VARCHAR NOT NULL)",
    )
    db.execute(con, "INSERT INTO farming_report VALUES ('report', '2026-10-24 09:00:00', '{}')")


def test_the_sell_helper_report_is_renamed_in_place(tmp_path):
    """`farming_report` became `sell_helper_report`: the schema renames it wherever it
    runs, so a local copy, the site and the backup keep their report (no rebuild, and
    nothing read from the backup), and running the schema again changes nothing."""
    with db.session(tmp_path / "old.duckdb") as con:
        _old_sell_helper_report(con)
        db.init_schema(con)
        db.init_schema(con)
        tables = {r[0] for r in db.rows(con, "SHOW TABLES")}
        assert "farming_report" not in tables
        assert db.rows(con, "SELECT id FROM sell_helper_report") == [("report",)]


def test_the_sell_helper_report_is_renamed_on_postgres():
    import os

    import pytest

    url = os.environ.get("EB_TEST_POSTGRES_URL")
    if not url:
        pytest.skip("EB_TEST_POSTGRES_URL is not set")
    import psycopg

    with psycopg.connect(url, autocommit=True) as pg:
        pg.execute("DROP SCHEMA public CASCADE")
        pg.execute("CREATE SCHEMA public")
        _old_sell_helper_report(pg)
        db.init_schema(pg)
        db.init_schema(pg)
        assert db.rows(pg, "SELECT to_regclass('farming_report')") == [(None,)]
        assert db.rows(pg, "SELECT id FROM sell_helper_report") == [("report",)]


def test_the_site_reads_the_report_under_its_old_name_until_the_schema_runs(tmp_path):
    """The site opens its database read-only and never runs the schema, so a database
    no writer has touched since the rename still has `farming_report`: Price check's
    item view read the new name and failed (500) on the local copy, 2026-10-26."""
    from exiledbroker.services import sell_helper

    with db.session(tmp_path / "old.duckdb") as con:
        _old_sell_helper_report(con)
        assert sell_helper.report(con) is None  # its row is 'report', not 'latest'
        db.execute(con, "UPDATE farming_report SET id = 'latest'")
        assert sell_helper.report(con) == {}
        assert sell_helper.built_at(con) is not None
