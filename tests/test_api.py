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
    assert "Task Manager" in response.text


def test_create_and_list_task() -> None:
    client = TestClient(main.app)
    username = f"user-{uuid4().hex[:20]}"
    token = client.post("/auth/register", json={"username": username, "password": "test-password"}).json()["access_token"]
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
    deleted = client.delete(f"/tasks/{created.json()['id']}", headers=auth_headers)
    assert deleted.status_code == 200
    assert all(task["id"] != created.json()["id"] for task in client.get("/tasks", headers=auth_headers).json())


def test_registration_and_login_issue_access_tokens() -> None:
    client = TestClient(main.app)
    username = f"login-{uuid4().hex[:19]}"

    registered = client.post("/auth/register", json={"username": username, "password": "test-password"})
    logged_in = client.post("/auth/login", json={"username": username, "password": "test-password"})
    profile = client.get("/auth/me", headers={"Authorization": f"Bearer {logged_in.json()['access_token']}"})

    assert registered.status_code == 201
    assert logged_in.status_code == 200
    assert registered.json()["access_token"]
    assert logged_in.json()["token_type"] == "bearer"
    assert profile.json()["username"] == username


def test_task_routes_require_sign_in() -> None:
    response = TestClient(main.app).get("/tasks")

    assert response.status_code == 401


def test_manager_can_assign_only_to_members() -> None:
    client = TestClient(main.app)

    def register(role: str) -> tuple[str, str]:
        username = f"{role}-{uuid4().hex[:20]}"
        token = client.post("/auth/register", json={"username": username, "password": "test-password"}).json()["access_token"]
        return username, token

    admin_username, admin_token = register("admin")
    manager_username, manager_token = register("manager")
    member_username, member_token = register("member")
    admin_headers = {"Authorization": f"Bearer {admin_token}"}
    group_id = client.post("/groups", headers=admin_headers, json={"name": "Portfolio team"}).json()["id"]
    client.post(f"/groups/{group_id}/members", headers=admin_headers, json={"username": manager_username, "role": "manager", "priority": 5})
    client.post(f"/groups/{group_id}/members", headers=admin_headers, json={"username": member_username, "role": "member", "priority": 1})
    manager_headers = {"Authorization": f"Bearer {manager_token}"}
    member_headers = {"Authorization": f"Bearer {member_token}"}

    assigned = client.post("/tasks", headers=manager_headers, json={"title": "Prepare demo", "group_id": group_id, "assignee_username": member_username})
    blocked = client.post("/tasks", headers=manager_headers, json={"title": "Override admin", "group_id": group_id, "assignee_username": admin_username})
    member_blocked = client.post("/tasks", headers=member_headers, json={"title": "Assign task", "group_id": group_id, "assignee_username": member_username})

    assert assigned.status_code == 201
    assert blocked.status_code == 403
    assert member_blocked.status_code == 403


def test_priority_limits_assignment_and_allows_multiple_assignees() -> None:
    client = TestClient(main.app)

    def register(prefix: str) -> tuple[str, str]:
        username = f"{prefix}-{uuid4().hex[:20]}"
        token = client.post("/auth/register", json={"username": username, "password": "test-password"}).json()["access_token"]
        return username, token

    admin_name, admin_token = register("pa")
    manager_name, manager_token = register("pm")
    first_name, _ = register("pf")
    second_name, _ = register("ps")
    group_id = client.post("/groups", headers={"Authorization": f"Bearer {admin_token}"}, json={"name": "Priorities"}).json()["id"]
    admin_headers = {"Authorization": f"Bearer {admin_token}"}
    for username, role, priority in [(manager_name, "manager", 5), (first_name, "member", 2), (second_name, "member", 1)]:
        assert client.post(f"/groups/{group_id}/members", headers=admin_headers, json={"username": username, "role": role, "priority": priority}).status_code == 201

    manager_headers = {"Authorization": f"Bearer {manager_token}"}
    created = client.post("/tasks", headers=manager_headers, json={"title": "Shared work", "group_id": group_id, "assignee_usernames": [first_name, second_name], "points": 3})
    assert created.status_code == 201
    tasks = client.get("/tasks", headers=manager_headers).json()
    assert len([task for task in tasks if task["title"] == "Shared work"]) == 2
    blocked = client.post("/tasks", headers=manager_headers, json={"title": "Not allowed", "group_id": group_id, "assignee_usernames": [manager_name]})
    assert blocked.status_code == 403


def test_task_confirmation_awards_points_and_recurring_task_returns() -> None:
    client = TestClient(main.app)

    def register(prefix: str) -> tuple[str, str]:
        username = f"{prefix}-{uuid4().hex[:20]}"
        token = client.post("/auth/register", json={"username": username, "password": "test-password"}).json()["access_token"]
        return username, token

    admin_name, admin_token = register("review-a")
    member_name, member_token = register("review-m")
    admin_headers = {"Authorization": f"Bearer {admin_token}"}
    member_headers = {"Authorization": f"Bearer {member_token}"}
    group_id = client.post("/groups", headers=admin_headers, json={"name": "Review team"}).json()["id"]
    client.post(f"/groups/{group_id}/members", headers=admin_headers, json={"username": member_name, "role": "member"})

    created = client.post(
        "/tasks",
        headers=admin_headers,
        json={"title": "Daily check", "group_id": group_id, "assignee_username": member_name, "task_type": "daily", "points": 15},
    ).json()
    assert created["task_status"] == "pending"
    assert client.post(f"/tasks/{created['id']}/complete", headers=member_headers).json()["status"] == "submitted"
    assert client.post(f"/tasks/{created['id']}/approve", headers=admin_headers).json()["status"] == "approved"

    member = client.get("/auth/me", headers=member_headers).json()
    tasks = client.get("/tasks", headers=member_headers).json()
    assert member["points_balance"] == 15
    assert tasks[0]["task_status"] == "approved"
    assert tasks[0]["task_type"] == "daily"
