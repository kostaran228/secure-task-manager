import os
import secrets
import json
from io import BytesIO
from datetime import datetime, timedelta, timezone

from fastapi import Depends, FastAPI, Header, HTTPException, status
from fastapi.responses import FileResponse, Response
import qrcode
import qrcode.image.svg
from jwt import InvalidTokenError, decode, encode
from pwdlib import PasswordHash
from pydantic import BaseModel, ConfigDict, Field
from prometheus_fastapi_instrumentator import Instrumentator
from sqlalchemy import DateTime, ForeignKey, String, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column


DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./tasks.db")
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args)
password_hash = PasswordHash.recommended()
TOKEN_ALGORITHM = "HS256"
TOKEN_LIFETIME_HOURS = 12
REMEMBERED_TOKEN_LIFETIME_DAYS = 30
SERVER_URL = os.getenv("SERVER_URL", "http://localhost:8000").rstrip("/")
PAIRING_CODE = secrets.token_urlsafe(6)


class Base(DeclarativeBase):
    pass


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    owner_id: Mapped[int | None] = mapped_column(nullable=True, index=True)
    reminder_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    group_id: Mapped[int | None] = mapped_column(ForeignKey("groups.id"), nullable=True, index=True)
    assignee_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)


class Group(Base):
    __tablename__ = "groups"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Membership(Base):
    __tablename__ = "memberships"

    id: Mapped[int] = mapped_column(primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    role: Mapped[str] = mapped_column(String(16), default="member")


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    # email is retained only to preserve data from early local versions.
    email: Mapped[str | None] = mapped_column(String(320), unique=True, index=True, nullable=True)
    username: Mapped[str | None] = mapped_column(String(32), unique=True, index=True, nullable=True)
    is_server_admin: Mapped[bool] = mapped_column(default=False, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class TaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=1000)
    reminder_at: datetime | None = None
    group_id: int | None = None
    assignee_username: str | None = Field(default=None, max_length=32)


class TaskRead(TaskCreate):
    model_config = ConfigDict(from_attributes=True)
    id: int
    created_at: datetime


class Credentials(BaseModel):
    username: str = Field(min_length=3, max_length=32)
    password: str = Field(min_length=8, max_length=128)
    remember_me: bool = False


class AccessToken(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserProfile(BaseModel):
    username: str
    is_server_admin: bool


class PairingInfo(BaseModel):
    server_url: str
    pairing_code: str


class AdminStatus(PairingInfo):
    server_status: str = "running"


class GroupCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class MemberAdd(BaseModel):
    username: str
    role: str


class GroupRead(BaseModel):
    id: int
    name: str
    role: str


is_production = os.getenv("APP_ENV") == "production"
app = FastAPI(
    title="Secure Task Manager",
    version="0.1.0",
    docs_url=None if is_production else "/docs",
    redoc_url=None if is_production else "/redoc",
)
Instrumentator().instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)


@app.get("/", include_in_schema=False)
def dashboard() -> FileResponse:
    return FileResponse("app/static/index.html")


@app.on_event("startup")
def create_tables() -> None:
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        if connection.dialect.name == "postgresql":
            connection.exec_driver_sql("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS owner_id INTEGER")
            connection.exec_driver_sql("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS reminder_at TIMESTAMP")
            connection.exec_driver_sql("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS group_id INTEGER")
            connection.exec_driver_sql("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS assignee_id INTEGER")
            connection.exec_driver_sql("ALTER TABLE users ADD COLUMN IF NOT EXISTS username VARCHAR(32)")
            connection.exec_driver_sql("ALTER TABLE users ADD COLUMN IF NOT EXISTS is_server_admin BOOLEAN NOT NULL DEFAULT FALSE")
            connection.exec_driver_sql("UPDATE users SET username = CONCAT('user-', id) WHERE username IS NULL")
            connection.exec_driver_sql("CREATE UNIQUE INDEX IF NOT EXISTS ix_users_username ON users (username)")
            connection.exec_driver_sql("UPDATE users SET is_server_admin = TRUE WHERE id = (SELECT MIN(id) FROM users) AND NOT EXISTS (SELECT 1 FROM users WHERE is_server_admin = TRUE)")


def normalized_username(username: str) -> str:
    normalized = username.strip().casefold()
    if len(normalized) < 3 or len(normalized) > 32 or not all(character.isalnum() or character in "_.-" for character in normalized):
        raise HTTPException(status_code=422, detail="Username must be 3-32 characters and use letters, numbers, dot, dash, or underscore")
    return normalized


def jwt_secret() -> str:
    secret = os.getenv("JWT_SECRET")
    if not secret:
        raise HTTPException(status_code=503, detail="Authentication is not configured")
    return secret


def create_access_token(user: User, remember_me: bool = False) -> str:
    lifetime = timedelta(days=REMEMBERED_TOKEN_LIFETIME_DAYS) if remember_me else timedelta(hours=TOKEN_LIFETIME_HOURS)
    expires_at = datetime.now(timezone.utc) + lifetime
    return encode({"sub": str(user.id), "username": user.username, "exp": expires_at}, jwt_secret(), algorithm=TOKEN_ALGORITHM)


def current_user(authorization: str | None = Header(default=None)) -> User:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Sign in to access tasks")
    try:
        payload = decode(authorization.removeprefix("Bearer "), jwt_secret(), algorithms=[TOKEN_ALGORITHM])
        user_id = int(payload["sub"])
    except (InvalidTokenError, KeyError, TypeError, ValueError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired access token") from None
    with Session(engine) as session:
        user = session.get(User, user_id)
        if user is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
        session.expunge(user)
        return user


ROLE_RANK = {"member": 1, "manager": 2, "admin": 3}


def membership_for(session: Session, group_id: int, user_id: int) -> Membership:
    membership = session.scalar(select(Membership).where(Membership.group_id == group_id, Membership.user_id == user_id))
    if membership is None:
        raise HTTPException(status_code=403, detail="You are not a member of this group")
    return membership


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/pairing", response_model=PairingInfo)
def pairing_info() -> PairingInfo:
    return PairingInfo(server_url=SERVER_URL, pairing_code=PAIRING_CODE)


def server_admin(user: User = Depends(current_user)) -> User:
    if not user.is_server_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Server administrator access is required")
    return user


@app.get("/admin", include_in_schema=False)
def admin_dashboard() -> FileResponse:
    return FileResponse("app/static/admin.html")


@app.get("/admin/status", response_model=AdminStatus)
def admin_status(_: User = Depends(server_admin)) -> AdminStatus:
    return AdminStatus(server_url=SERVER_URL, pairing_code=PAIRING_CODE)


@app.get("/admin/pairing/qr.svg", include_in_schema=False)
def admin_pairing_qr(_: User = Depends(server_admin)) -> Response:
    payload = json.dumps({"server_url": SERVER_URL, "pairing_code": PAIRING_CODE})
    image = qrcode.make(payload, image_factory=qrcode.image.svg.SvgPathImage)
    output = BytesIO()
    image.save(output)
    return Response(content=output.getvalue(), media_type="image/svg+xml")


@app.get("/pairing/qr.svg", include_in_schema=False)
def pairing_qr() -> Response:
    payload = json.dumps({"server_url": SERVER_URL, "pairing_code": PAIRING_CODE})
    image = qrcode.make(payload, image_factory=qrcode.image.svg.SvgPathImage)
    output = BytesIO()
    image.save(output)
    return Response(content=output.getvalue(), media_type="image/svg+xml")


@app.post("/auth/register", response_model=AccessToken, status_code=status.HTTP_201_CREATED)
def register(payload: Credentials) -> AccessToken:
    username = normalized_username(payload.username)
    with Session(engine) as session:
        if session.scalar(select(User).where(User.username == username)) is not None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Username is already taken")
        # The legacy email column remains for database compatibility; it never
        # receives a real address and is not used for authentication.
        first_server_admin = session.scalar(select(User.id).where(User.is_server_admin.is_(True))) is None
        user = User(username=username, email=f"{username}@local.invalid", password_hash=password_hash.hash(payload.password), is_server_admin=first_server_admin)
        session.add(user)
        session.commit()
        session.refresh(user)
        return AccessToken(access_token=create_access_token(user, payload.remember_me))


@app.post("/auth/login", response_model=AccessToken)
def login(payload: Credentials) -> AccessToken:
    username = normalized_username(payload.username)
    with Session(engine) as session:
        user = session.scalar(select(User).where(User.username == username))
        if user is None or not password_hash.verify(payload.password, user.password_hash):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect username or password")
        return AccessToken(access_token=create_access_token(user, payload.remember_me))


@app.get("/auth/me", response_model=UserProfile)
def me(user: User = Depends(current_user)) -> UserProfile:
    return UserProfile(username=user.username or f"user-{user.id}", is_server_admin=user.is_server_admin)


@app.post("/groups", response_model=GroupRead, status_code=status.HTTP_201_CREATED)
def create_group(payload: GroupCreate, user: User = Depends(current_user)) -> GroupRead:
    with Session(engine) as session:
        group = Group(name=payload.name.strip())
        session.add(group)
        session.flush()
        session.add(Membership(group_id=group.id, user_id=user.id, role="admin"))
        session.commit()
        return GroupRead(id=group.id, name=group.name, role="admin")


@app.get("/groups", response_model=list[GroupRead])
def list_groups(user: User = Depends(current_user)) -> list[GroupRead]:
    with Session(engine) as session:
        rows = session.execute(select(Group, Membership.role).join(Membership).where(Membership.user_id == user.id)).all()
        return [GroupRead(id=group.id, name=group.name, role=role) for group, role in rows]


@app.post("/groups/{group_id}/members", status_code=status.HTTP_201_CREATED)
def add_member(group_id: int, payload: MemberAdd, user: User = Depends(current_user)) -> dict[str, str]:
    if payload.role not in ROLE_RANK:
        raise HTTPException(status_code=422, detail="Role must be admin, manager, or member")
    with Session(engine) as session:
        actor = membership_for(session, group_id, user.id)
        if actor.role != "admin":
            raise HTTPException(status_code=403, detail="Only an admin can manage group roles")
        target = session.scalar(select(User).where(User.username == normalized_username(payload.username)))
        if target is None:
            raise HTTPException(status_code=404, detail="This username has not registered yet")
        existing = session.scalar(select(Membership).where(Membership.group_id == group_id, Membership.user_id == target.id))
        if existing:
            existing.role = payload.role
        else:
            session.add(Membership(group_id=group_id, user_id=target.id, role=payload.role))
        session.commit()
        return {"status": "member updated"}


@app.post("/tasks", response_model=TaskRead, status_code=status.HTTP_201_CREATED)
def create_task(payload: TaskCreate, user: User = Depends(current_user)) -> Task:
    with Session(engine) as session:
        assignee_id = user.id
        if payload.group_id is not None:
            actor = membership_for(session, payload.group_id, user.id)
            if actor.role == "member":
                raise HTTPException(status_code=403, detail="Members cannot assign group tasks")
            if payload.assignee_username is None:
                raise HTTPException(status_code=422, detail="Choose a group member to assign this task")
            target = session.scalar(select(User).where(User.username == normalized_username(payload.assignee_username)))
            target_membership = membership_for(session, payload.group_id, target.id) if target else None
            if target_membership is None:
                raise HTTPException(status_code=404, detail="Assignee is not in this group")
            if actor.role == "manager" and ROLE_RANK[target_membership.role] >= ROLE_RANK[actor.role]:
                raise HTTPException(status_code=403, detail="Managers can assign tasks only to members")
            assignee_id = target.id
        task_data = payload.model_dump(exclude={"assignee_username"})
        task = Task(**task_data, owner_id=user.id, assignee_id=assignee_id)
        session.add(task)
        session.commit()
        session.refresh(task)
        return task


@app.get("/tasks", response_model=list[TaskRead])
def list_tasks(user: User = Depends(current_user)) -> list[Task]:
    with Session(engine) as session:
        groups = session.scalars(select(Membership.group_id).where(Membership.user_id == user.id)).all()
        return list(session.scalars(select(Task).where((Task.owner_id == user.id) | (Task.group_id.in_(groups))).order_by(Task.id.desc())))


@app.get("/tasks/{task_id}", response_model=TaskRead)
def get_task(task_id: int, user: User = Depends(current_user)) -> Task:
    with Session(engine) as session:
        task = session.get(Task, task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="Task not found")
        if task.group_id is None and task.owner_id != user.id:
            raise HTTPException(status_code=404, detail="Task not found")
        if task.group_id is not None:
            membership_for(session, task.group_id, user.id)
        return task
