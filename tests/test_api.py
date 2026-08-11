import os
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from app import main

def setup_module() -> None:
    os.environ["JWT_SECRET"] = "test-signing-secret"
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
    email = f"user-{uuid4()}@example.com"
    token = client.post("/auth/register", json={"email": email, "password": "test-password"}).json()["access_token"]
    auth_headers = {"Authorization": f"Bearer {token}"}

    created = client.post(
        "/tasks",
        json={"title": "Write CI pipeline", "description": "Portfolio milestone"},
        headers=auth_headers,
    )
    tasks = client.get("/tasks", headers=auth_headers)

    assert created.status_code == 201
    assert created.json()["title"] == "Write CI pipeline"
    assert tasks.status_code == 200
    assert any(task["id"] == created.json()["id"] for task in tasks.json())


def test_registration_and_login_issue_access_tokens() -> None:
    client = TestClient(main.app)
    email = f"login-{uuid4()}@example.com"

    registered = client.post("/auth/register", json={"email": email, "password": "test-password"})
    logged_in = client.post("/auth/login", json={"email": email, "password": "test-password"})

    assert registered.status_code == 201
    assert logged_in.status_code == 200
    assert registered.json()["access_token"]
    assert logged_in.json()["token_type"] == "bearer"


def test_task_routes_require_sign_in() -> None:
    response = TestClient(main.app).get("/tasks")

    assert response.status_code == 401
