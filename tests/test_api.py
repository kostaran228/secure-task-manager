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
        json={"title": "Write CI pipeline", "description": "Portfolio milestone", "reminder_at": "2026-12-31T15:30:00"},
        headers=auth_headers,
    )
    tasks = client.get("/tasks", headers=auth_headers)

    assert created.status_code == 201
    assert created.json()["title"] == "Write CI pipeline"
    assert created.json()["reminder_at"] == "2026-12-31T15:30:00"
    assert tasks.status_code == 200
    assert any(task["id"] == created.json()["id"] for task in tasks.json())


def test_registration_and_login_issue_access_tokens() -> None:
    client = TestClient(main.app)
    email = f"login-{uuid4()}@example.com"

    registered = client.post("/auth/register", json={"email": email, "password": "test-password"})
    logged_in = client.post("/auth/login", json={"email": email, "password": "test-password"})
    profile = client.get("/auth/me", headers={"Authorization": f"Bearer {logged_in.json()['access_token']}"})

    assert registered.status_code == 201
    assert logged_in.status_code == 200
    assert registered.json()["access_token"]
    assert logged_in.json()["token_type"] == "bearer"
    assert profile.json() == {"email": email}


def test_task_routes_require_sign_in() -> None:
    response = TestClient(main.app).get("/tasks")

    assert response.status_code == 401


def test_manager_can_assign_only_to_members() -> None:
    client = TestClient(main.app)

    def register(role: str) -> tuple[str, str]:
        email = f"{role}-{uuid4()}@example.com"
        token = client.post("/auth/register", json={"email": email, "password": "test-password"}).json()["access_token"]
        return email, token

    admin_email, admin_token = register("admin")
    manager_email, manager_token = register("manager")
    member_email, member_token = register("member")
    admin_headers = {"Authorization": f"Bearer {admin_token}"}
    group_id = client.post("/groups", headers=admin_headers, json={"name": "Portfolio team"}).json()["id"]
    client.post(f"/groups/{group_id}/members", headers=admin_headers, json={"email": manager_email, "role": "manager"})
    client.post(f"/groups/{group_id}/members", headers=admin_headers, json={"email": member_email, "role": "member"})
    manager_headers = {"Authorization": f"Bearer {manager_token}"}
    member_headers = {"Authorization": f"Bearer {member_token}"}

    assigned = client.post("/tasks", headers=manager_headers, json={"title": "Prepare demo", "group_id": group_id, "assignee_email": member_email})
    blocked = client.post("/tasks", headers=manager_headers, json={"title": "Override admin", "group_id": group_id, "assignee_email": admin_email})
    member_blocked = client.post("/tasks", headers=member_headers, json={"title": "Assign task", "group_id": group_id, "assignee_email": member_email})

    assert assigned.status_code == 201
    assert blocked.status_code == 403
    assert member_blocked.status_code == 403
