"""Follow-up tasks: the only thing a user can write (docs/API.md#endpoints).

Everything else is read-only. A task records who created it, for which client,
and which evidence it came from (for example SQL:open_actions:A-001). Creating a
task is audited like a tool call. Tasks live in briefing.db, so `make unify`
starts the list fresh.
"""

import datetime as dt
from contextlib import closing

from pydantic import BaseModel, ConfigDict, Field

from app import audit, db
from app.tools import ClientId, UserContext

TASKS_SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    task_id      TEXT PRIMARY KEY,
    user_id      TEXT,
    client_id    TEXT,
    description  TEXT,
    due_date     TEXT,
    source_id    TEXT,   -- the evidence the task came from, e.g. SQL:open_actions:A-001
    status       TEXT,
    created_at   TEXT
)
"""


class TaskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    client_id: ClientId
    description: str = Field(min_length=3, max_length=300)
    due_date: dt.date | None = None
    source_id: str | None = Field(default=None, max_length=200)


class Task(TaskRequest):
    task_id: str
    user_id: str
    status: str
    created_at: str


class TaskError(Exception):
    """The task can't be created, e.g. the client doesn't exist."""


def create_task(user: UserContext, request: TaskRequest) -> Task:
    with closing(db.connect(readonly=False)) as conn:
        client_id = db.canonical_client_id(conn, request.client_id)
        if client_id is None:
            raise TaskError("client_not_found")
        conn.execute(TASKS_SCHEMA)
        count = conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
        task = Task(**request.model_dump() | {"client_id": client_id}, task_id=f"T-{count + 1:03d}",
                    user_id=user.user_id, status="Open",
                    created_at=dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"))
        conn.execute("INSERT INTO tasks VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                     (task.task_id, task.user_id, task.client_id, task.description,
                      task.due_date.isoformat() if task.due_date else None, task.source_id, task.status,
                      task.created_at))
        conn.commit()
    audit.log_tool_call(user.user_id, "create_task", request.model_dump(mode="json"), [task.task_id], None)
    return task
