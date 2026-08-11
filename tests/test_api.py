from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from app import main


def setup_module() -> None:
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


def test_create_and_list_task() -> None:
    client = TestClient(main.app)

    created = client.post(
        "/tasks",
        json={"title": "Write CI pipeline", "description": "Portfolio milestone"},
    )
    tasks = client.get("/tasks")

    assert created.status_code == 201
    assert created.json()["title"] == "Write CI pipeline"
    assert tasks.status_code == 200
    assert any(task["id"] == created.json()["id"] for task in tasks.json())
