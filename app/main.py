import os
import secrets
import json
from base64 import urlsafe_b64encode
from io import BytesIO
from datetime import datetime, timedelta, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from fastapi import Depends, FastAPI, Header, HTTPException, Request as FastAPIRequest, status
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2 import id_token
import qrcode
import qrcode.image.svg
from jwt import InvalidTokenError, decode, encode
from pwdlib import PasswordHash
from pydantic import BaseModel, ConfigDict, Field
from prometheus_fastapi_instrumentator import Instrumentator
from sqlalchemy import DateTime, ForeignKey, Integer, String, create_engine, select
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
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
GOOGLE_REDIRECT_URI = os.getenv("GOOGLE_REDIRECT_URI", "")


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
    task_type: Mapped[str] = mapped_column(String(16), default="once", nullable=False)
    task_status: Mapped[str] = mapped_column(String(16), default="pending", nullable=False, index=True)
    points: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    next_occurrence_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    points_awarded: Mapped[bool] = mapped_column(default=False, nullable=False)


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
    priority: Mapped[int] = mapped_column(Integer, default=1, nullable=False)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    # email is retained only to preserve data from early local versions.
    email: Mapped[str | None] = mapped_column(String(320), unique=True, index=True, nullable=True)
    username: Mapped[str | None] = mapped_column(String(32), unique=True, index=True, nullable=True)
    is_server_admin: Mapped[bool] = mapped_column(default=False, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    points_balance: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class GoogleIdentity(Base):
    __tablename__ = "google_identities"

    id: Mapped[int] = mapped_column(primary_key=True)
    google_sub: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True, index=True)


class TaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=1000)
    reminder_at: datetime | None = None
    group_id: int | None = None
    assignee_username: str | None = Field(default=None, max_length=32)
    assignee_usernames: list[str] = Field(default_factory=list, max_length=100)
    task_type: str = Field(default="once", pattern="^(once|daily|weekly)$")
    points: int = Field(default=0, ge=0, le=100000)


class TaskRead(TaskCreate):
    model_config = ConfigDict(from_attributes=True)
    id: int
    created_at: datetime
    task_status: str
    assignee_id: int | None = None
    owner_id: int | None = None
    approved_at: datetime | None = None
    next_occurrence_at: datetime | None = None


class Credentials(BaseModel):
    username: str = Field(min_length=3, max_length=32)
    password: str = Field(min_length=8, max_length=128)
    remember_me: bool = False


class AccessToken(BaseModel):
    access_token: str
    token_type: str = "bearer"


class GoogleAuthStatus(BaseModel):
    enabled: bool


class UserProfile(BaseModel):
    id: int
    username: str
    is_server_admin: bool
    points_balance: int


class PairingInfo(BaseModel):
    server_url: str
    pairing_code: str


class AdminStatus(PairingInfo):
    server_status: str = "running"


class AiStatus(BaseModel):
    available: bool
    models: list[str] = []


class ServerSetupStatus(BaseModel):
    configured: bool


class GroupCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class MemberAdd(BaseModel):
    username: str
    role: str
    priority: int = Field(default=1, ge=0, le=100000)


class MemberPriorityUpdate(BaseModel):
    priority: int = Field(ge=0, le=100000)


class GroupRead(BaseModel):
    id: int
    name: str
    role: str


class GroupMemberRead(BaseModel):
    username: str
    role: str
    priority: int


class RegisteredUserRead(BaseModel):
    username: str


is_production = os.getenv("APP_ENV") == "production"
app = FastAPI(
    title="Secure Task Manager",
    version="0.1.0",
    docs_url=None if is_production else "/docs",
    redoc_url=None if is_production else "/redoc",
)
Instrumentator().instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)


@app.get("/", include_in_schema=False)
def dashboard() -> HTMLResponse:
    content = open("app/static/index.html", encoding="utf-8").read()
    live_updates = """
    <script>
      // Group tasks update in-place for every connected participant.
      setInterval(() => {
        if (typeof token !== 'undefined' && token && typeof loadTasks === 'function') {
          loadTasks().catch(() => {});
        }
      }, 2000);
    </script>
    """
    return HTMLResponse(content.replace("</body>", live_updates + "</body>"))


@app.on_event("startup")
def create_tables() -> None:
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        if connection.dialect.name == "postgresql":
            connection.exec_driver_sql("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS owner_id INTEGER")
            connection.exec_driver_sql("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS reminder_at TIMESTAMP")
            connection.exec_driver_sql("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS group_id INTEGER")
            connection.exec_driver_sql("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS assignee_id INTEGER")
            connection.exec_driver_sql("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS task_type VARCHAR(16) NOT NULL DEFAULT 'once'")
            connection.exec_driver_sql("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS task_status VARCHAR(16) NOT NULL DEFAULT 'pending'")
            connection.exec_driver_sql("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS points INTEGER NOT NULL DEFAULT 0")
            connection.exec_driver_sql("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS approved_at TIMESTAMP")
            connection.exec_driver_sql("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS next_occurrence_at TIMESTAMP")
            connection.exec_driver_sql("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS points_awarded BOOLEAN NOT NULL DEFAULT FALSE")
            connection.exec_driver_sql("ALTER TABLE users ADD COLUMN IF NOT EXISTS username VARCHAR(32)")
            connection.exec_driver_sql("ALTER TABLE users ADD COLUMN IF NOT EXISTS is_server_admin BOOLEAN NOT NULL DEFAULT FALSE")
            connection.exec_driver_sql("ALTER TABLE users ADD COLUMN IF NOT EXISTS points_balance INTEGER NOT NULL DEFAULT 0")
            connection.exec_driver_sql("ALTER TABLE memberships ADD COLUMN IF NOT EXISTS priority INTEGER NOT NULL DEFAULT 1")
            connection.exec_driver_sql("CREATE TABLE IF NOT EXISTS app_settings (key VARCHAR(64) PRIMARY KEY, value VARCHAR(64) NOT NULL)")
            initialized = connection.exec_driver_sql("SELECT value FROM app_settings WHERE key = 'membership_priority_v1'").scalar()
            if initialized is None:
                connection.exec_driver_sql("UPDATE memberships SET priority = CASE role WHEN 'admin' THEN 10 WHEN 'manager' THEN 5 ELSE 1 END")
                connection.exec_driver_sql("INSERT INTO app_settings(key, value) VALUES ('membership_priority_v1', 'done')")
            connection.exec_driver_sql("UPDATE users SET username = CONCAT('user-', id) WHERE username IS NULL")
            connection.exec_driver_sql("CREATE UNIQUE INDEX IF NOT EXISTS ix_users_username ON users (username)")


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


def google_enabled() -> bool:
    return bool(GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET and GOOGLE_REDIRECT_URI)


def google_state(remember_me: bool) -> str:
    return encode({"purpose": "google-oauth", "remember": remember_me, "exp": datetime.now(timezone.utc) + timedelta(minutes=10)}, jwt_secret(), algorithm=TOKEN_ALGORITHM)


def username_for_google(name: str, session: Session) -> str:
    base = "".join(character for character in name.casefold() if character.isalnum() or character in "_.-")[:24] or "google-user"
    base = (base + "---")[:3] if len(base) < 3 else base
    candidate = base
    number = 2
    while session.scalar(select(User.id).where(User.username == candidate)) is not None:
        suffix = f"-{number}"
        candidate = f"{base[:32-len(suffix)]}{suffix}"
        number += 1
    return candidate


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
DEFAULT_PRIORITY = {"member": 1, "manager": 5, "admin": 10}


def membership_for(session: Session, group_id: int, user_id: int) -> Membership:
    membership = session.scalar(select(Membership).where(Membership.group_id == group_id, Membership.user_id == user_id))
    if membership is None:
        raise HTTPException(status_code=403, detail="You are not a member of this group")
    return membership


def refresh_recurring_tasks(session: Session) -> None:
    """Make an approved recurring task available again when its next cycle starts."""
    now = datetime.utcnow()
    tasks = session.scalars(
        select(Task).where(
            Task.task_type.in_(("daily", "weekly")),
            Task.task_status == "approved",
            Task.next_occurrence_at.is_not(None),
            Task.next_occurrence_at <= now,
        )
    ).all()
    for task in tasks:
        task.task_status = "pending"
        task.approved_at = None
        task.next_occurrence_at = None
        task.points_awarded = False
    if tasks:
        session.commit()


def task_read(session: Session, task: Task) -> TaskRead:
    assignee = session.get(User, task.assignee_id) if task.assignee_id is not None else None
    return TaskRead(
        id=task.id,
        title=task.title,
        description=task.description,
        reminder_at=task.reminder_at,
        group_id=task.group_id,
        assignee_username=assignee.username if assignee is not None else None,
        assignee_usernames=[],
        task_type=task.task_type,
        points=task.points,
        created_at=task.created_at,
        task_status=task.task_status,
        assignee_id=task.assignee_id,
        owner_id=task.owner_id,
        approved_at=task.approved_at,
        next_occurrence_at=task.next_occurrence_at,
    )


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


@app.get("/setup", include_in_schema=False)
def server_setup_dashboard() -> FileResponse:
    return FileResponse("app/static/setup.html")


@app.get("/server/setup/status", response_model=ServerSetupStatus)
def server_setup_status() -> ServerSetupStatus:
    with Session(engine) as session:
        configured = session.scalar(select(User.id).where(User.is_server_admin.is_(True))) is not None
        return ServerSetupStatus(configured=configured)


@app.post("/server/setup/claim")
def claim_server(user: User = Depends(current_user)) -> dict[str, str]:
    with Session(engine) as session:
        existing_owner = session.scalar(select(User).where(User.is_server_admin.is_(True)))
        if existing_owner is not None and existing_owner.id != user.id:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This server already has an owner")
        owner = session.get(User, user.id)
        if owner is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
        owner.is_server_admin = True
        session.commit()
        return {"status": "server owner configured"}


@app.get("/admin/status", response_model=AdminStatus)
def admin_status(_: User = Depends(server_admin)) -> AdminStatus:
    return AdminStatus(server_url=SERVER_URL, pairing_code=PAIRING_CODE)


@app.get("/admin/users", response_model=list[RegisteredUserRead])
def registered_users(_: User = Depends(server_admin)) -> list[RegisteredUserRead]:
    with Session(engine) as session:
        users = session.scalars(select(User).where(User.username.is_not(None)).order_by(User.created_at.desc())).all()
        return [RegisteredUserRead(username=user.username or f"user-{user.id}") for user in users]


@app.get("/admin/pairing/qr.svg", include_in_schema=False)
def admin_pairing_qr(url: str | None = None, code: str | None = None, _: User = Depends(server_admin)) -> Response:
    server_url = (url or SERVER_URL).rstrip("/")
    if not (server_url.startswith("http://") or server_url.startswith("https://")):
        raise HTTPException(status_code=422, detail="Invalid server URL")
    payload = json.dumps({"server_url": server_url, "pairing_code": code or PAIRING_CODE})
    image = qrcode.make(payload, image_factory=qrcode.image.svg.SvgPathImage)
    output = BytesIO()
    image.save(output)
    return Response(content=output.getvalue(), media_type="image/svg+xml")


@app.get("/admin/ai/status", response_model=AiStatus)
def admin_ai_status(_: User = Depends(server_admin)) -> AiStatus:
    try:
        with urlopen(f"{OLLAMA_BASE_URL}/api/tags", timeout=2) as response:
            payload = json.loads(response.read())
        return AiStatus(available=True, models=[model["name"] for model in payload.get("models", [])])
    except (URLError, TimeoutError, OSError, json.JSONDecodeError):
        return AiStatus(available=False)


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
        user = User(username=username, email=f"{username}@local.invalid", password_hash=password_hash.hash(payload.password))
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


@app.get("/auth/google/status", response_model=GoogleAuthStatus)
def google_auth_status() -> GoogleAuthStatus:
    return GoogleAuthStatus(enabled=google_enabled())


@app.get("/auth/google/start", include_in_schema=False)
def google_auth_start(remember_me: bool = False) -> RedirectResponse:
    if not google_enabled():
        raise HTTPException(status_code=503, detail="Google sign-in is not configured yet")
    query = urlencode({"client_id": GOOGLE_CLIENT_ID, "redirect_uri": GOOGLE_REDIRECT_URI, "response_type": "code", "scope": "openid profile email", "state": google_state(remember_me), "prompt": "select_account"})
    return RedirectResponse(f"https://accounts.google.com/o/oauth2/v2/auth?{query}")


@app.get("/auth/google/callback", include_in_schema=False)
def google_auth_callback(code: str, state: str) -> RedirectResponse:
    if not google_enabled():
        raise HTTPException(status_code=503, detail="Google sign-in is not configured yet")
    try:
        flow = decode(state, jwt_secret(), algorithms=[TOKEN_ALGORITHM])
        if flow.get("purpose") != "google-oauth":
            raise InvalidTokenError()
        body = urlencode({"code": code, "client_id": GOOGLE_CLIENT_ID, "client_secret": GOOGLE_CLIENT_SECRET, "redirect_uri": GOOGLE_REDIRECT_URI, "grant_type": "authorization_code"}).encode()
        with urlopen(Request("https://oauth2.googleapis.com/token", data=body, headers={"Content-Type": "application/x-www-form-urlencoded"}), timeout=10) as response:
            tokens = json.loads(response.read())
        claims = id_token.verify_oauth2_token(tokens["id_token"], GoogleRequest(), GOOGLE_CLIENT_ID)
        subject = claims["sub"]
    except (InvalidTokenError, KeyError, HTTPError, URLError, ValueError) as error:
        raise HTTPException(status_code=401, detail="Google sign-in could not be verified") from error
    with Session(engine) as session:
        identity = session.scalar(select(GoogleIdentity).where(GoogleIdentity.google_sub == subject))
        if identity:
            user = session.get(User, identity.user_id)
        else:
            username = username_for_google(str(claims.get("name") or claims.get("email", "google-user")), session)
            user = User(username=username, email=f"{username}@google.local.invalid", password_hash=password_hash.hash(urlsafe_b64encode(secrets.token_bytes(32)).decode()))
            session.add(user)
            session.flush()
            session.add(GoogleIdentity(google_sub=subject, user_id=user.id))
            session.commit()
        if user is None:
            raise HTTPException(status_code=401, detail="Google account is unavailable")
        token = create_access_token(user, bool(flow.get("remember")))
    response = RedirectResponse("/?google=1")
    response.set_cookie("task_manager_google_login", token, httponly=True, samesite="lax", secure=GOOGLE_REDIRECT_URI.startswith("https://"), max_age=60)
    return response


@app.get("/auth/google/session", response_model=AccessToken)
def google_auth_session(request: FastAPIRequest) -> AccessToken:
    token = request.cookies.get("task_manager_google_login")
    if not token:
        raise HTTPException(status_code=401, detail="Google sign-in session is missing or expired")
    return AccessToken(access_token=token)


@app.get("/auth/me", response_model=UserProfile)
def me(user: User = Depends(current_user)) -> UserProfile:
    return UserProfile(
        id=user.id,
        username=user.username or f"user-{user.id}",
        is_server_admin=user.is_server_admin,
        points_balance=user.points_balance,
    )


@app.post("/groups", response_model=GroupRead, status_code=status.HTTP_201_CREATED)
def create_group(payload: GroupCreate, user: User = Depends(current_user)) -> GroupRead:
    with Session(engine) as session:
        group = Group(name=payload.name.strip())
        session.add(group)
        session.flush()
        session.add(Membership(group_id=group.id, user_id=user.id, role="admin", priority=DEFAULT_PRIORITY["admin"]))
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
        if not user.is_server_admin and payload.priority >= actor.priority:
            raise HTTPException(status_code=403, detail="A participant must have a lower priority than the administrator")
        target = session.scalar(select(User).where(User.username == normalized_username(payload.username)))
        if target is None:
            raise HTTPException(status_code=404, detail="This username has not registered yet")
        existing = session.scalar(select(Membership).where(Membership.group_id == group_id, Membership.user_id == target.id))
        if existing:
            existing.role = payload.role
            existing.priority = payload.priority
        else:
            session.add(Membership(group_id=group_id, user_id=target.id, role=payload.role, priority=payload.priority))
        session.commit()
        return {"status": "member updated"}


@app.patch("/groups/{group_id}/members/{username}")
def update_member_priority(group_id: int, username: str, payload: MemberPriorityUpdate, user: User = Depends(current_user)) -> dict[str, str]:
    with Session(engine) as session:
        actor = membership_for(session, group_id, user.id)
        if actor.role != "admin":
            raise HTTPException(status_code=403, detail="Only a team administrator can change priorities")
        target = session.scalar(select(User).where(User.username == normalized_username(username)))
        target_membership = membership_for(session, group_id, target.id) if target else None
        if target_membership is None:
            raise HTTPException(status_code=404, detail="This participant is not in the group")
        if target_membership.user_id != user.id and payload.priority >= actor.priority:
            raise HTTPException(status_code=403, detail="A participant cannot be given priority equal to or above the administrator")
        target_membership.priority = payload.priority
        session.commit()
        return {"status": "priority updated"}


@app.get("/groups/{group_id}/members", response_model=list[GroupMemberRead])
def list_group_members(group_id: int, user: User = Depends(current_user)) -> list[GroupMemberRead]:
    with Session(engine) as session:
        membership_for(session, group_id, user.id)
        rows = session.execute(
            select(User.username, Membership.role, Membership.priority)
            .join(Membership, Membership.user_id == User.id)
            .where(Membership.group_id == group_id)
            .order_by(Membership.priority.desc(), User.username)
        ).all()
        return [GroupMemberRead(username=username or "unknown", role=role, priority=priority) for username, role, priority in rows]


@app.post("/tasks", response_model=TaskRead, status_code=status.HTTP_201_CREATED)
def create_task(payload: TaskCreate, user: User = Depends(current_user)) -> TaskRead:
    with Session(engine) as session:
        assignee_ids = [user.id]
        if payload.group_id is not None:
            actor = membership_for(session, payload.group_id, user.id)
            if actor.role == "member":
                raise HTTPException(status_code=403, detail="Members cannot assign group tasks")
            requested_names = payload.assignee_usernames or ([payload.assignee_username] if payload.assignee_username else [])
            requested_names = list(dict.fromkeys(normalized_username(name) for name in requested_names))
            if not requested_names:
                raise HTTPException(status_code=422, detail="Choose a group member to assign this task")
            assignee_ids = []
            for name in requested_names:
                target = session.scalar(select(User).where(User.username == name))
                target_membership = membership_for(session, payload.group_id, target.id) if target else None
                if target_membership is None:
                    raise HTTPException(status_code=404, detail=f"Assignee {name} is not in this group")
                if not user.is_server_admin and target_membership.priority >= actor.priority:
                    raise HTTPException(status_code=403, detail="Tasks can be assigned only to participants with a lower priority")
                assignee_ids.append(target.id)
        task_data = payload.model_dump(exclude={"assignee_username", "assignee_usernames"})
        # Every participant gets an independent copy: each can submit it and receive points separately.
        tasks = [Task(**task_data, owner_id=user.id, assignee_id=assignee_id) for assignee_id in assignee_ids]
        session.add_all(tasks)
        session.commit()
        session.refresh(tasks[0])
        return task_read(session, tasks[0])


@app.post("/tasks/{task_id}/complete")
def submit_task_completion(task_id: int, user: User = Depends(current_user)) -> dict[str, str]:
    """The assignee confirms that the work is finished (blue -> yellow)."""
    with Session(engine) as session:
        task = session.get(Task, task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="Task not found")
        if task.assignee_id != user.id:
            raise HTTPException(status_code=403, detail="Only the assigned participant can mark this task as complete")
        if task.task_status != "pending":
            raise HTTPException(status_code=409, detail="This task has already been submitted or approved")
        task.task_status = "submitted"
        session.commit()
        return {"status": "submitted"}


@app.post("/tasks/{task_id}/approve")
def approve_task_completion(task_id: int, user: User = Depends(current_user)) -> dict[str, str]:
    """Only the server administrator verifies work and awards points."""
    with Session(engine) as session:
        task = session.get(Task, task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="Task not found")
        if task.task_status != "submitted":
            raise HTTPException(status_code=409, detail="Only a submitted task can be approved")
        if not user.is_server_admin:
            raise HTTPException(status_code=403, detail="Only the server administrator can approve this task")

        if not task.points_awarded and task.assignee_id is not None:
            assignee = session.get(User, task.assignee_id)
            if assignee is not None:
                assignee.points_balance += task.points
            task.points_awarded = True

        task.task_status = "approved"
        task.approved_at = datetime.utcnow()
        if task.task_type == "once":
            session.delete(task)
        else:
            interval = timedelta(days=1 if task.task_type == "daily" else 7)
            task.next_occurrence_at = datetime.utcnow() + interval
        session.commit()
        return {"status": "approved", "points_awarded": str(task.points)}


@app.delete("/tasks/{task_id}")
def delete_task(task_id: int, user: User = Depends(current_user)) -> dict[str, str]:
    """Remove a task only when the caller owns it or administers its team/server."""
    with Session(engine) as session:
        task = session.get(Task, task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="Task not found")
        if not user.is_server_admin:
            if task.group_id is None:
                if task.owner_id != user.id:
                    raise HTTPException(status_code=403, detail="Only the task owner can delete this task")
            elif membership_for(session, task.group_id, user.id).role != "admin":
                raise HTTPException(status_code=403, detail="Only a team administrator can delete this task")
        session.delete(task)
        session.commit()
        return {"status": "deleted"}


@app.get("/tasks", response_model=list[TaskRead])
def list_tasks(user: User = Depends(current_user)) -> list[TaskRead]:
    with Session(engine) as session:
        refresh_recurring_tasks(session)
        if user.is_server_admin:
            tasks = session.scalars(select(Task).order_by(Task.id.desc())).all()
        else:
            groups = session.scalars(select(Membership.group_id).where(Membership.user_id == user.id)).all()
            tasks = session.scalars(select(Task).where((Task.owner_id == user.id) | (Task.group_id.in_(groups))).order_by(Task.id.desc())).all()
        return [task_read(session, task) for task in tasks]


@app.get("/tasks/{task_id}", response_model=TaskRead)
def get_task(task_id: int, user: User = Depends(current_user)) -> TaskRead:
    with Session(engine) as session:
        task = session.get(Task, task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="Task not found")
        if task.group_id is None and task.owner_id != user.id and not user.is_server_admin:
            raise HTTPException(status_code=404, detail="Task not found")
        if task.group_id is not None:
            membership_for(session, task.group_id, user.id)
        return task_read(session, task)
