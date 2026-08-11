import os
from datetime import datetime

from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from prometheus_fastapi_instrumentator import Instrumentator
from sqlalchemy import DateTime, String, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column


DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./tasks.db")
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args)


class Base(DeclarativeBase):
    pass


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class TaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=1000)


class TaskRead(TaskCreate):
    model_config = ConfigDict(from_attributes=True)
    id: int
    created_at: datetime


app = FastAPI(title="Secure Task Manager", version="0.1.0")
Instrumentator().instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)


@app.on_event("startup")
def create_tables() -> None:
    Base.metadata.create_all(engine)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/tasks", response_model=TaskRead, status_code=status.HTTP_201_CREATED)
def create_task(payload: TaskCreate) -> Task:
    with Session(engine) as session:
        task = Task(**payload.model_dump())
        session.add(task)
        session.commit()
        session.refresh(task)
        return task


@app.get("/tasks", response_model=list[TaskRead])
def list_tasks() -> list[Task]:
    with Session(engine) as session:
        return list(session.scalars(select(Task).order_by(Task.id.desc())))


@app.get("/tasks/{task_id}", response_model=TaskRead)
def get_task(task_id: int) -> Task:
    with Session(engine) as session:
        task = session.get(Task, task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="Task not found")
        return task
