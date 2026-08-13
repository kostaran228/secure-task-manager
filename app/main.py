import os
import secrets
import json
import re
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
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3:1.7b")
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
    reminder_interval_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    group_id: Mapped[int | None] = mapped_column(ForeignKey("groups.id"), nullable=True, index=True)
    assignee_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    task_type: Mapped[str] = mapped_column(String(16), default="once", nullable=False)
    task_status: Mapped[str] = mapped_column(String(16), default="pending", nullable=False, index=True)
    points: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
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
    reminder_interval_minutes: int | None = Field(default=None, ge=15, le=10080)
    group_id: int | None = None
    assignee_username: str | None = Field(default=None, max_length=32)
    assignee_usernames: list[str] = Field(default_factory=list, max_length=100)
    task_type: str = Field(default="once", pattern="^(once|daily|weekly)$")
    points: int = Field(default=1, ge=0, le=100000)


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
    installing: bool = False
    selected_model: str | None = None


class AssistantCommand(BaseModel):
    text: str = Field(min_length=1, max_length=1000)


class AssistantReply(BaseModel):
    reply: str
    action: str | None = None
    task_id: int | None = None


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
    return HTMLResponse(
        content.replace("</body>", live_updates + "</body>"),
        headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0", "Pragma": "no-cache"},
    )


@app.on_event("startup")
def create_tables() -> None:
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        if connection.dialect.name == "postgresql":
            connection.exec_driver_sql("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS owner_id INTEGER")
            connection.exec_driver_sql("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS reminder_at TIMESTAMP")
            connection.exec_driver_sql("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS reminder_interval_minutes INTEGER")
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


def local_ai_reply(text: str) -> str:
    """Ask the locally running Ollama model; no cloud key is used here."""
    try:
        with urlopen(f"{OLLAMA_BASE_URL}/api/tags", timeout=2) as response:
            installed = [item.get("name", "") for item in json.load(response).get("models", [])]
        model = OLLAMA_MODEL if OLLAMA_MODEL in installed else next((name for name in installed if name.startswith("qwen3:")), None)
        if not model:
            return "Локальная модель ещё не установлена. Откройте панель администратора и установите Qwen3."
        prompt = (
            "Ты локальный помощник Task Manager. Отвечай по-русски, коротко и дружелюбно. "
            "Не выдумывай выполненные действия: сервер сам подтверждает изменения. "
            f"Сообщение пользователя: {text}"
        )
        payload = json.dumps({"model": model, "prompt": prompt, "stream": False, "options": {"temperature": 0.3}}).encode()
        request = Request(f"{OLLAMA_BASE_URL}/api/generate", data=payload, headers={"Content-Type": "application/json"})
        with urlopen(request, timeout=60) as response:
            return str(json.load(response).get("response", "Готово.")).strip() or "Готово."
    except (HTTPError, URLError, TimeoutError, ValueError):
        return "Локальный ИИ сейчас недоступен. Проверьте, что Ollama и выбранная модель запущены у администратора."


def local_ai_task_command(text: str, usernames: list[str], tasks: list[Task], assignee_names: dict[int, str]) -> str | None:
    """Use the local model only to turn a natural phrase into a constrained task command."""
    try:
        with urlopen(f"{OLLAMA_BASE_URL}/api/tags", timeout=2) as response:
            installed = [item.get("name", "") for item in json.load(response).get("models", [])]
        model = OLLAMA_MODEL if OLLAMA_MODEL in installed else next((name for name in installed if name.startswith("qwen3:")), None)
        if not model:
            return None
        prompt = (
            "Ты переводишь голосовую фразу в JSON для менеджера задач. Никаких пояснений и Markdown. "
            "Верни только один объект. Доступные action: create, update_title, update_description, assign, complete, approve, delete, list, none. "
            "Для create: {\"action\":\"create\",\"title\":\"...\",\"assignees\":[\"точное_имя\"],\"task_type\":\"once|daily|weekly\",\"points\":0}. "
            "Для update_title: {\"action\":\"update_title\",\"task_id\":12,\"title\":\"...\"}. "
            "Для update_description: {\"action\":\"update_description\",\"task_id\":12,\"description\":\"...\"}. "
            "Для assign: {\"action\":\"assign\",\"task_id\":12,\"assignees\":[\"точное_имя\"]}. "
            "Если фраза содержит «баллы» или «награда» и говорит о существующей задаче, это всегда update_points именно для этой задачи. "
            "Для update_points: {\"action\":\"update_points\",\"task_id\":12,\"points\":5}. "
            "Для complete, approve или delete укажи task_ids — массив номеров, можно несколько. Для list других полей не нужно. "
            "Если задача названа словами, найди её по title, description или assignee в списке и верни её номер. "
            "Если намерение неясно, верни только {\"action\":\"none\"}. Никогда не объясняй, как нажимать кнопки. "
            f"Допустимые имена участников: {', '.join(usernames) or 'нет'}. "
            f"Текущие задачи, по которым можно выполнять действия: {json.dumps([{'id': task.id, 'title': task.title, 'description': task.description or '', 'assignee': assignee_names.get(task.assignee_id or -1, ''), 'points': task.points, 'status': task.task_status} for task in tasks], ensure_ascii=False)}. "
            f"Фраза: {text}"
        )
        payload = json.dumps({"model": model, "prompt": prompt, "stream": False, "format": "json", "options": {"temperature": 0}}).encode()
        request = Request(f"{OLLAMA_BASE_URL}/api/generate", data=payload, headers={"Content-Type": "application/json"})
        with urlopen(request, timeout=60) as response:
            decoded = json.loads(str(json.load(response).get("response", "{}")))
        action = decoded.get("action")
        if action in {"complete", "approve", "delete", "list"}:
            task_ids = decoded.get("task_ids", [decoded.get("task_id")])
            valid_ids = [str(int(task_id)) for task_id in task_ids if isinstance(task_id, int)] if isinstance(task_ids, list) else []
            return f"{action} {','.join(valid_ids)}" if action != "list" and valid_ids else ("list" if action == "list" else None)
        if action in {"update_title", "update_description"}:
            task_id = decoded.get("task_id")
            field = "title" if action == "update_title" else "description"
            value = decoded.get(field)
            return f"{action} {int(task_id)} {str(value).strip()}" if isinstance(task_id, int) and isinstance(value, str) and value.strip() else None
        if action == "assign":
            task_id = decoded.get("task_id")
            assignees = [str(name).casefold() for name in decoded.get("assignees", []) if str(name).casefold() in {name.casefold() for name in usernames}]
            return f"assign {int(task_id)} {' и '.join(assignees)}" if isinstance(task_id, int) and assignees else None
        if action == "update_points":
            task_id = decoded.get("task_id")
            try:
                points = max(0, min(100000, int(decoded.get("points"))))
            except (TypeError, ValueError):
                return None
            return f"update_points {int(task_id)} {points}" if isinstance(task_id, int) else None
        if action != "create" or not isinstance(decoded.get("title"), str) or not decoded["title"].strip():
            return None
        allowed = {name.casefold() for name in usernames}
        assignees = [str(name).casefold() for name in decoded.get("assignees", []) if str(name).casefold() in allowed]
        task_type = decoded.get("task_type") if decoded.get("task_type") in {"once", "daily", "weekly"} else "once"
        try:
            points = max(1, min(100000, int(decoded.get("points", 1))))
        except (TypeError, ValueError):
            points = 0
        canonical = f"создай задачу {task_type} {decoded['title'].strip()} на {points} баллов"
        return canonical + (f" для {' и '.join(assignees)}" if assignees else "")
    except (HTTPError, URLError, TimeoutError, ValueError, json.JSONDecodeError):
        return None


def infer_referenced_task_command(text: str, tasks: list[Task], assignee_names: dict[int, str]) -> str | None:
    """Deterministic fallback for small local models that fail to emit structured JSON."""
    lower = text.casefold()
    is_delete = any(word in lower for word in ("удали", "удалить", "delete"))
    if not is_delete:
        return None
    requested_count_match = re.search(r"(?:удали(?:ть)?\s+)?(\d+)\s+(?:задач|задани)", lower)
    requested_count = int(requested_count_match.group(1)) if requested_count_match else 1
    requested_count = max(1, min(20, requested_count))
    stop_words = {"удали", "удалить", "задачу", "задачи", "задания", "которые", "которое", "есть", "надо", "было", "для", "это", "эти", "у", "и", "в", "на", "с", "по", "delete"}
    words = {word for word in re.findall(r"[\w-]{3,}", lower, flags=re.UNICODE) if word not in stop_words and not word.isdigit()}
    owner_match = re.search(r"\bу\s+([\w.-]+)", lower, flags=re.UNICODE)
    owner = owner_match.group(1) if owner_match else ""
    ranked: list[tuple[int, Task]] = []
    for task in tasks:
        task_words = set(re.findall(r"[\w-]{3,}", f"{task.title} {task.description or ''}".casefold(), flags=re.UNICODE))
        score = len(words & task_words) * 5
        assignee = assignee_names.get(task.assignee_id or -1, "").casefold()
        if owner and owner == assignee:
            score += 4
        if score:
            ranked.append((score, task))
    ranked.sort(key=lambda item: (-item[0], -item[1].id))
    selected = [task for _, task in ranked[:requested_count]]
    # Never guess a bulk delete without either a matching owner or words from task title/description.
    if len(selected) != requested_count or (not owner and not words):
        return None
    return "delete " + ",".join(str(task.id) for task in selected)


def infer_reward_command(text: str, tasks: list[Task], assignee_names: dict[int, str]) -> str | None:
    """Set a reward from natural wording when a lightweight model misses the JSON action."""
    lower = text.casefold()
    if not any(word in lower for word in ("балл", "баллы", "баллов", "награда", "награду")):
        return None
    match = re.search(r"(?:на\s+|в\s+|по\s+)?(\d+)\s+балл", lower)
    if not match:
        match = re.search(r"(?:баллы|баллов|награду|награда)\s+(?:на\s+|в\s+)?(\d+)", lower)
    if not match:
        return None
    points = max(0, min(100000, int(match.group(1))))
    stop_words = {"балл", "баллы", "баллов", "награда", "награду", "поставь", "поставить", "измени", "изменить", "за", "задачу", "задачи", "для", "на", "в", "у", "и", "это", "этой", "этого"}
    words = {word for word in re.findall(r"[\w-]{3,}", lower, flags=re.UNICODE) if word not in stop_words and not word.isdigit()}
    ranked: list[tuple[int, Task]] = []
    for task in tasks:
        task_words = set(re.findall(r"[\w-]{3,}", f"{task.title} {task.description or ''}".casefold(), flags=re.UNICODE))
        score = len(words & task_words) * 5
        if score:
            ranked.append((score, task))
    ranked.sort(key=lambda item: (-item[0], -item[1].id))
    if not ranked:
        task_id_match = re.search(r"(?:задач[ауе]?\s*#?)(\d+)", lower)
        if task_id_match and any(task.id == int(task_id_match.group(1)) for task in tasks):
            return f"update_points {int(task_id_match.group(1))} {points}"
        return None
    return f"update_points {ranked[0][1].id} {points}"


def assistant_action(session: Session, user: User, text: str) -> tuple[str | None, int | None, str | None]:
    """Safe Russian task commands. The language model never receives direct DB access."""
    command = " ".join(text.strip().split())
    lower = command.casefold()

    def can_manage(task: Task) -> bool:
        if user.is_server_admin or (task.group_id is None and task.owner_id == user.id):
            return True
        if task.group_id is None:
            return False
        membership = session.scalar(select(Membership).where(Membership.group_id == task.group_id, Membership.user_id == user.id))
        return membership is not None and membership.role in {"admin", "manager"}

    def task_by_id(value: str) -> Task | None:
        return session.get(Task, int(value)) if value.isdigit() else None

    update_title = re.match(r"^(?:измени(?:\s+название)?|переименуй)\s+задачу\s+(\d+)\s+(?:на|в)\s+(.+)$", command, re.IGNORECASE)
    generated_title = re.match(r"^update_title\s+(\d+)\s+(.+)$", command, re.IGNORECASE)
    match = update_title or generated_title
    if match:
        task = task_by_id(match.group(1))
        title = match.group(2).strip(" .,!?:;")
        if task is None or not can_manage(task):
            return None, None, "Не могу изменить эту задачу: она не найдена или у вас недостаточно прав."
        if not title:
            return None, None, "Назовите новое название задачи."
        task.title = title[:200]
        session.commit()
        return "updated", task.id, f"Переименовал задачу в «{task.title}»."

    update_description = re.match(r"^измени\s+описание\s+задачи\s+(\d+)\s+(?:на|в)\s+(.+)$", command, re.IGNORECASE)
    generated_description = re.match(r"^update_description\s+(\d+)\s+(.+)$", command, re.IGNORECASE)
    match = update_description or generated_description
    if match:
        task = task_by_id(match.group(1))
        description = match.group(2).strip()
        if task is None or not can_manage(task):
            return None, None, "Не могу изменить описание этой задачи: она не найдена или у вас недостаточно прав."
        task.description = description[:1000]
        session.commit()
        return "updated", task.id, "Описание задачи обновлено."

    update_points = re.match(r"^(?:измени\s+)?(?:баллы|награду)\s+(?:за\s+)?задачу\s+(\d+)\s+(?:на|в)\s+(\d+)$", command, re.IGNORECASE)
    generated_points = re.match(r"^update_points\s+(\d+)\s+(\d+)$", command, re.IGNORECASE)
    match = update_points or generated_points
    if match:
        task = task_by_id(match.group(1))
        if task is None or not can_manage(task):
            return None, None, "Не могу изменить баллы этой задачи: она не найдена или у вас недостаточно прав."
        task.points = min(100000, int(match.group(2)))
        session.commit()
        return "updated", task.id, f"Для задачи «{task.title}» установлено {task.points} баллов."

    assign_existing = re.match(r"^(?:назначь|назначить|поставь)\s+задачу\s+(\d+)\s+для\s+(.+)$", command, re.IGNORECASE)
    generated_assign = re.match(r"^assign\s+(\d+)\s+(.+)$", command, re.IGNORECASE)
    match = assign_existing or generated_assign
    if match:
        task = task_by_id(match.group(1))
        if task is None or not can_manage(task):
            return None, None, "Не могу переназначить эту задачу: она не найдена или у вас недостаточно прав."
        if task.group_id is None:
            return None, None, "Личную задачу нельзя назначить команде. Создайте новую задачу для участника."
        actor = session.scalar(select(Membership).where(Membership.group_id == task.group_id, Membership.user_id == user.id))
        requested_names = [name.strip().casefold() for name in re.split(r"\s*(?:,|\s+и\s+)\s*", match.group(2)) if name.strip()]
        targets = []
        for name in requested_names:
            target = session.scalar(select(User).where(User.username == name))
            membership = session.scalar(select(Membership).where(Membership.group_id == task.group_id, Membership.user_id == (target.id if target else -1)))
            if target is None or membership is None:
                return None, None, f"Участник «{name}» не состоит в команде этой задачи."
            if not user.is_server_admin and (actor is None or actor.role == "member" or membership.priority >= actor.priority):
                return None, None, "Назначать можно только участникам с приоритетом ниже вашего."
            targets.append(target)
        if not targets:
            return None, None, "Укажите участника после слова «для»."
        task.assignee_id = targets[0].id
        for target in targets[1:]:
            session.add(Task(title=task.title, description=task.description, owner_id=task.owner_id, reminder_at=task.reminder_at, reminder_interval_minutes=task.reminder_interval_minutes, group_id=task.group_id, assignee_id=target.id, task_type=task.task_type, task_status="pending", points=task.points))
        session.commit()
        return "assigned", task.id, f"Задача «{task.title}» назначена: {', '.join(target.username or '' for target in targets)}."

    if lower == "list" or lower in {"покажи задачи", "какие у меня задачи", "список задач"}:
        tasks = session.scalars(select(Task).where(Task.assignee_id == user.id, Task.task_status != "approved")).all()
        if not tasks:
            return "listed", None, "У вас сейчас нет незавершённых задач."
        preview = "; ".join(f"#{task.id} {task.title}" for task in tasks[:5])
        return "listed", None, f"Ваши текущие задачи: {preview}."
    create_prefixes = ("создай задачу ", "добавь задачу ", "назначь задачу ", "назначить задачу ", "поставь задачу ")
    prefix = next((item for item in create_prefixes if lower.startswith(item)), None)
    if prefix:
        remainder = command[len(prefix):].strip(" .,!?:;")
        split = re.split(r"\s+(?:для|участнику|участникам)\s+", remainder, maxsplit=1, flags=re.IGNORECASE)
        title = split[0].strip(" .,!?:;")
        points_match = re.search(r"\s+на\s+(\d+)\s+балл(?:а|ов)?\b", title, flags=re.IGNORECASE)
        points = max(1, int(points_match.group(1))) if points_match else 1
        if points_match:
            title = (title[:points_match.start()] + title[points_match.end():]).strip(" .,!?:;")
        task_type = "daily" if re.search(r"\b(ежедневн\w*|daily)\b", title, re.IGNORECASE) else "weekly" if re.search(r"\b(еженедельн\w*|weekly)\b", title, re.IGNORECASE) else "once"
        title = re.sub(r"\b(ежедневн\w*|еженедельн\w*|daily|weekly|once)\b", "", title, flags=re.IGNORECASE).strip(" .,!?:;")
        if not title:
            return None, None, "После команды назовите задачу, например: «Помощник, назначь задачу купить продукты для alex»."
        assignees = [user]
        group_id = None
        if len(split) == 2:
            requested_names = [name.strip().casefold() for name in re.split(r"\s*(?:,|\s+и\s+)\s*", split[1]) if name.strip()]
            targets = []
            for name in requested_names:
                target = session.scalar(select(User).where(User.username == name))
                if target is None:
                    return None, None, f"Участник «{name}» не найден. Используйте его точное имя из списка команды."
                targets.append(target)
            if not targets:
                return None, None, "Укажите хотя бы одного участника после слова «для»."
            target_group_sets = []
            for target in targets:
                memberships = session.scalars(select(Membership).where(Membership.user_id == target.id)).all()
                target_group_sets.append({membership.group_id for membership in memberships})
            common_groups = set.intersection(*target_group_sets) if target_group_sets else set()
            if not user.is_server_admin:
                actor_memberships = session.scalars(select(Membership).where(Membership.user_id == user.id)).all()
                actor_by_group = {membership.group_id: membership for membership in actor_memberships}
                common_groups &= set(actor_by_group)
                allowed_groups = []
                for candidate_group in common_groups:
                    actor_membership = actor_by_group[candidate_group]
                    if actor_membership.role == "member":
                        continue
                    target_memberships = [session.scalar(select(Membership).where(Membership.group_id == candidate_group, Membership.user_id == target.id)) for target in targets]
                    if all(membership and membership.priority < actor_membership.priority for membership in target_memberships):
                        allowed_groups.append(candidate_group)
                common_groups = set(allowed_groups)
            if not common_groups:
                return None, None, "Не могу назначить задачу: участники должны быть в одной команде и иметь приоритет ниже вашего."
            group_id = min(common_groups)
            assignees = targets
        tasks = [Task(title=title[:200], owner_id=user.id, assignee_id=assignee.id, group_id=group_id, task_type=task_type, points=points) for assignee in assignees]
        session.add_all(tasks)
        session.commit()
        session.refresh(tasks[0])
        names = ", ".join(assignee.username or "участник" for assignee in assignees)
        destination = f" для {names}" if group_id is not None else ""
        return "created", tasks[0].id, f"Создал задачу «{tasks[0].title}»{destination}. Баллы: {points}."
    if lower.startswith("выполни задачу ") or lower.startswith("заверши задачу ") or lower.startswith("complete "):
        number = re.search(r"(\d+)", lower).group(1) if re.search(r"(\d+)", lower) else ""
        if number.isdigit():
            task = session.get(Task, int(number))
            if task and task.assignee_id == user.id and task.task_status == "pending":
                task.task_status = "submitted"
                session.commit()
                return "submitted", task.id, f"Задача «{task.title}» отмечена как выполненная и ждёт подтверждения."
            return None, None, "Не нашёл доступную вам синюю задачу с таким номером."
    if lower.startswith("подтверди задачу ") or lower.startswith("approve "):
        number = re.search(r"(\d+)", lower).group(1) if re.search(r"(\d+)", lower) else ""
        if number.isdigit():
            task = session.get(Task, int(number))
            if task and user.is_server_admin and task.task_status == "submitted":
                if not task.points_awarded and task.assignee_id is not None:
                    assignee = session.get(User, task.assignee_id)
                    if assignee is not None:
                        assignee.points_balance += task.points
                    task.points_awarded = True
                task.task_status = "approved"
                task.approved_at = datetime.utcnow()
                if task.task_type == "once":
                    title = task.title
                    session.delete(task)
                    session.commit()
                    return "approved", int(number), f"Подтвердил выполнение задачи «{title}» и начислил баллы."
                task.next_occurrence_at = datetime.utcnow() + timedelta(days=1 if task.task_type == "daily" else 7)
                session.commit()
                return "approved", task.id, f"Подтвердил выполнение задачи «{task.title}»."
            return None, None, "Подтверждать можно только жёлтые задачи и только администратору сервера."
    if lower.startswith("удали задачу ") or lower.startswith("delete "):
        numbers = [int(number) for number in re.findall(r"\d+", lower)]
        if numbers:
            tasks = [session.get(Task, number) for number in numbers]
            if any(task is None or not can_manage(task) for task in tasks):
                return None, None, "Не могу удалить все указанные задачи: часть не найдена или у вас недостаточно прав."
            titles = [task.title for task in tasks if task]
            for task in tasks:
                session.delete(task)
            session.commit()
            return "deleted", numbers[0], f"Удалил задачи: {', '.join('«' + title + '»' for title in titles)}."
    return None, None, None


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
        reminder_interval_minutes=task.reminder_interval_minutes,
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
    return FileResponse(
        "app/static/admin.html",
        headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0", "Pragma": "no-cache"},
    )


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


@app.post("/assistant/command", response_model=AssistantReply)
def run_assistant_command(payload: AssistantCommand, user: User = Depends(current_user)) -> AssistantReply:
    """Run a voice/text command through the local assistant with a safe task-action allowlist."""
    with Session(engine) as session:
        action, task_id, reply = assistant_action(session, user, payload.text)
        if reply is None:
            usernames = [name for name in session.scalars(select(User.username)).all() if name]
            if user.is_server_admin:
                visible_tasks = session.scalars(select(Task).order_by(Task.id.desc())).all()
            else:
                group_ids = session.scalars(select(Membership.group_id).where(Membership.user_id == user.id)).all()
                visible_tasks = session.scalars(select(Task).where((Task.owner_id == user.id) | (Task.group_id.in_(group_ids))).order_by(Task.id.desc())).all()
            assignee_names = {user_id: username for user_id, username in session.execute(select(User.id, User.username)).all() if username}
            generated_command = local_ai_task_command(payload.text, usernames, visible_tasks, assignee_names)
            if generated_command:
                action, task_id, reply = assistant_action(session, user, generated_command)
            if reply is None:
                fallback_command = infer_referenced_task_command(payload.text, visible_tasks, assignee_names)
                if fallback_command:
                    action, task_id, reply = assistant_action(session, user, fallback_command)
            if reply is None:
                reward_command = infer_reward_command(payload.text, visible_tasks, assignee_names)
                if reward_command:
                    action, task_id, reply = assistant_action(session, user, reward_command)
    if reply:
        return AssistantReply(reply=reply, action=action, task_id=task_id)
    if any(word in payload.text.casefold() for word in ("удали", "удалить", "измени", "переименуй", "назнач", "создай", "поставь", "выполни", "подтверди")):
        return AssistantReply(reply="Я не выполнил действие: не смог однозначно определить задачу или у вас недостаточно прав. Назовите исполнителя и часть названия задачи.")
    return AssistantReply(reply=local_ai_reply(payload.text))


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
