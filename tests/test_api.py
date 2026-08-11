import os

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from app import main

AUTH_HEADERS = {"X-API-Key": "test-token"}


def setup_module() -> None:
    os.environ["API_TOKEN"] = "test-token"
    main.engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    main.Base.metadata.create_all(main.engine)


def test_healthcheck() -> None:
    client = TestClient(main.app)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_dashboard_is_available() -> None:
    response = TestClient(main.app).get("/")

    assert response.status_code == 200
    assert "Secure Task Manager" in response.text


def test_create_and_list_task() -> None:
    client = TestClient(main.app)

    created = client.post(
        "/tasks",
        json={"title": "Write CI pipeline", "description": "Portfolio milestone"},
        headers=AUTH_HEADERS,
    )
    tasks = client.get("/tasks", headers=AUTH_HEADERS)

    assert created.status_code == 201
    assert created.json()["title"] == "Write CI pipeline"
    assert tasks.status_code == 200
    assert any(task["id"] == created.json()["id"] for task in tasks.json())


def test_task_routes_require_api_token() -> None:
    response = TestClient(main.app).get("/tasks")

    assert response.status_code == 401
