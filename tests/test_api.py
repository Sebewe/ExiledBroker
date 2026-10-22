from fastapi.testclient import TestClient

from exiledbroker.api.app import app


def test_health():
    r = TestClient(app).get("/api/health")
    assert r.status_code == 200
    assert r.json()["game"] == "poe1"
