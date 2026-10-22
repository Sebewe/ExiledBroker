from fastapi.testclient import TestClient

from exiledbroker.api.app import app


def test_health():
    r = TestClient(app).get("/api/health")
    assert r.status_code == 200
    assert r.json()["game"] == "poe1"


def test_leagues_endpoint(tmp_path, monkeypatch):
    from exiledbroker.storage import db

    monkeypatch.setenv("EB_DATA_DIR", str(tmp_path))
    with db.session(tmp_path / "exiledbroker.duckdb") as con:
        db.init_schema(con)
    client = TestClient(app)
    assert client.get("/api/leagues").json() == []
    assert client.get("/api/leagues/Mirage/items/Mageblood/curve").status_code == 404
