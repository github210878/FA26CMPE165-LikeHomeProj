from fastapi.testclient import TestClient

from app.main import app


def test_root_status_reports_running_backend():
    response = TestClient(app).get("/")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "LikeHome Backend",
        "docs": "/docs",
    }