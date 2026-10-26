import pytest

from exiledbroker import cli
from exiledbroker.config import get_settings
from exiledbroker.storage import db


@pytest.fixture(autouse=True)
def _own_data_dir(tmp_path, monkeypatch):
    """A database of this test's own, not the session's shared fallback directory."""
    monkeypatch.setenv("EB_DATA_DIR", str(tmp_path))


def _tables(path) -> set[str]:
    with db.session(path, read_only=True) as con:
        return {r[0] for r in db.rows(con, "SELECT table_name FROM information_schema.tables")}


def test_serve_upgrades_an_older_local_copy(monkeypatch):
    """A local copy from before a table was added (card_reward_pool, 2026-10-26) gets it
    before the read-only API starts, instead of the Market recap failing on it."""
    settings = get_settings()
    with db.session(settings.db_path) as con:
        db.init_schema(con)
        con.execute("DROP TABLE card_reward_pool")
    assert "card_reward_pool" not in _tables(settings.db_path)
    monkeypatch.setattr(cli.uvicorn, "run", lambda *a, **k: None)

    cli.serve()

    assert "card_reward_pool" in _tables(settings.db_path)


def test_serve_leaves_a_copy_in_use_alone(monkeypatch):
    settings = get_settings()
    with db.session(settings.db_path) as con:
        db.init_schema(con)
    monkeypatch.setattr(cli.uvicorn, "run", lambda *a, **k: None)

    def busy(*a, **k):
        raise cli.duckdb.IOException("Could not set lock on file")

    monkeypatch.setattr(cli.db, "session", busy)
    cli.serve()  # serves anyway
