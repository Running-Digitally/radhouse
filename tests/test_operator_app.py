from pathlib import Path

from fastapi.testclient import TestClient

from radhouse.api.app import create_app
from radhouse.domain.access import AuthContext


class UnusedService:
    pass


def actor(_request):
    return AuthContext("alice", "radhouse", "alice@radhouse", None)


def test_operator_app_is_served_only_when_explicitly_configured(tmp_path: Path):
    (tmp_path / "index.html").write_text("<h1>Radhouse work home</h1>", encoding="utf-8")

    with TestClient(create_app(UnusedService(), actor, web_root=tmp_path)) as client:
        response = client.get("/app/")

    assert response.status_code == 200
    assert "Radhouse work home" in response.text


def test_operator_app_has_no_implicit_filesystem_root():
    with TestClient(create_app(UnusedService(), actor)) as client:
        response = client.get("/app/")

    assert response.status_code == 404
