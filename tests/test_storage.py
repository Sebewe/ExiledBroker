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
