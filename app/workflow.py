"""The banker's workflow on a briefing: conflict decisions, and sharing it (docs/SECURITY.md#approval-before-sharing).

Two small writes, like follow-up tasks:
  - a decision: which source the banker trusts for one conflict flag;
  - a share: who approved the briefing, for which members of the client's coverage team,
    when, and the follow-up tasks it created.
Both are checked against what the user may see (a flag or source they can't see is "not
found", exactly like one that doesn't exist), sharing is blocked while any conflict is
undecided, and both are audited. They live in briefing.db, so `make unify` starts them fresh.
"""

import datetime as dt
import json
from contextlib import closing

from pydantic import BaseModel, ConfigDict, Field

from app import audit, db, tools
from app.tasks import Task, TaskRequest, create_task
from app.tools import UserContext
from app.wording import AS_OF_DATE

SCHEMA = """
CREATE TABLE IF NOT EXISTS decisions (
    user_id     TEXT,
    client_id   TEXT,
    flag_id     TEXT,   -- the conflict flag, e.g. FLAG:F009
    source_id   TEXT,   -- the source the banker trusts, one of the flag's sources
    decided_at  TEXT,
    PRIMARY KEY (user_id, client_id, flag_id)
);
CREATE TABLE IF NOT EXISTS shares (
    share_id    TEXT PRIMARY KEY,
    client_id   TEXT,
    approver    TEXT,   -- user_id
    recipients  TEXT,   -- JSON list of coverage bankers
    shared_at   TEXT,
    task_ids    TEXT    -- JSON list of the follow-up tasks it created
);
"""


class DecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    flag_id: str = Field(pattern=r"^FLAG:F\d+$")
    source_id: str = Field(max_length=200)


class Decision(BaseModel):
    flag_id: str
    source_id: str
    decided_at: str


class FollowUp(BaseModel):
    model_config = ConfigDict(extra="forbid")
    description: str = Field(min_length=3, max_length=300)
    source_id: str | None = Field(default=None, max_length=200)


class ShareRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    recipients: list[str] | None = Field(default=None, max_length=20)  # default: the whole coverage team
    follow_ups: list[FollowUp] = Field(default=[], max_length=20)


class ShareRecord(BaseModel):
    share_id: str
    client_id: str
    approver: str
    approver_name: str
    recipients: list[str]
    shared_at: str
    task_ids: list[str]
    tasks: list[Task] = []   # filled in when the share is made


class WorkflowState(BaseModel):
    decisions: list[Decision]
    open_conflicts: int
    share: ShareRecord | None    # the latest share of this briefing


class WorkflowError(Exception):
    """not_found (or not visible to this user), invalid, or conflicts_open."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def visible_conflicts(conn, user: UserContext, client_id: str) -> list:
    """The client's conflict flags this user may see (filtered in SQL)."""
    return [f for f in db.flags(conn, client_id, user.entitlements) if f["flag_type"] == "conflict"]


def decided(conn, user: UserContext, client_id: str) -> dict[str, Decision]:
    rows = conn.execute("SELECT flag_id, source_id, decided_at FROM decisions WHERE user_id = ? AND client_id = ?",
                        (user.user_id, client_id)).fetchall()
    return {r["flag_id"]: Decision(flag_id=r["flag_id"], source_id=r["source_id"], decided_at=r["decided_at"]) for r in rows}


def save_decision(user: UserContext, client_id: str, request: DecisionRequest) -> Decision:
    with closing(db.connect(readonly=False)) as conn:
        conn.executescript(SCHEMA)
        flag = next((f for f in visible_conflicts(conn, user, client_id) if f"FLAG:{f['flag_id']}" == request.flag_id), None)
        if flag is None:  # unknown, not a conflict, another client's, or not visible: all the same answer
            raise WorkflowError("not_found", "Conflict not found.")
        if request.source_id not in json.loads(flag["source_ids"]):
            raise WorkflowError("invalid", "Pick one of the conflict's own sources.")
        decision = Decision(flag_id=request.flag_id, source_id=request.source_id, decided_at=now())
        conn.execute("INSERT INTO decisions VALUES (?, ?, ?, ?, ?) ON CONFLICT (user_id, client_id, flag_id) "
                     "DO UPDATE SET source_id = excluded.source_id, decided_at = excluded.decided_at",
                     (user.user_id, client_id, decision.flag_id, decision.source_id, decision.decided_at))
        conn.commit()
    audit.log_tool_call(user.user_id, "decision", {"client_id": client_id, "flag_id": request.flag_id,
                                                   "source_id": request.source_id}, [request.flag_id], None)
    return decision


def share_record(conn, row) -> ShareRecord:
    approver = db.user(conn, row["approver"])
    return ShareRecord(share_id=row["share_id"], client_id=row["client_id"], approver=row["approver"],
                       approver_name=approver["name"] if approver else row["approver"],
                       recipients=json.loads(row["recipients"]), shared_at=row["shared_at"],
                       task_ids=json.loads(row["task_ids"]))


def state(user: UserContext, client_id: str) -> WorkflowState:
    with closing(db.connect(readonly=False)) as conn:
        conn.executescript(SCHEMA)
        conflicts = {f"FLAG:{f['flag_id']}" for f in visible_conflicts(conn, user, client_id)}
        mine = [d for flag, d in decided(conn, user, client_id).items() if flag in conflicts]
        row = conn.execute("SELECT * FROM shares WHERE client_id = ? ORDER BY shared_at DESC, share_id DESC LIMIT 1",
                           (client_id,)).fetchone()
        return WorkflowState(decisions=mine, open_conflicts=len(conflicts) - len(mine),
                             share=share_record(conn, row) if row else None)


def share(user: UserContext, client_id: str, request: ShareRequest) -> ShareRecord:
    """Approve and share: only once every conflict is decided; recipients from the coverage team;
    every follow-up checked (its source must open for this user) before any task is created."""
    with closing(db.connect(readonly=False)) as conn:
        conn.executescript(SCHEMA)
        conflicts = {f"FLAG:{f['flag_id']}" for f in visible_conflicts(conn, user, client_id)}
        open_conflicts = conflicts - set(decided(conn, user, client_id))
        if open_conflicts:
            raise WorkflowError("conflicts_open", f"Decide the {len(open_conflicts)} open conflict(s) first.")
        team = [row["banker_name"] for row in db.coverage(conn, client_id)]
    recipients = request.recipients if request.recipients is not None else team
    if not recipients or any(name not in team for name in recipients):
        raise WorkflowError("invalid", "Recipients must be members of the client's coverage team.")
    for follow_up in request.follow_ups:
        if follow_up.source_id and not tools.get_source(user, evidence_id=follow_up.source_id).ok:
            raise WorkflowError("not_found", "A follow-up points at a source that is not available.")
    tasks = [create_task(user, TaskRequest(client_id=client_id, description=f.description, due_date=AS_OF_DATE,
                                           source_id=f.source_id))
             for f in request.follow_ups]  # one at a time: task IDs are numbered in order
    with closing(db.connect(readonly=False)) as conn:
        count = conn.execute("SELECT COUNT(*) FROM shares").fetchone()[0]
        row = {"share_id": f"S-{count + 1:03d}", "client_id": client_id, "approver": user.user_id,
               "recipients": json.dumps(recipients), "shared_at": now(), "task_ids": json.dumps([t.task_id for t in tasks])}
        conn.execute("INSERT INTO shares VALUES (:share_id, :client_id, :approver, :recipients, :shared_at, :task_ids)", row)
        conn.commit()
        record = share_record(conn, conn.execute("SELECT * FROM shares WHERE share_id = ?", (row["share_id"],)).fetchone())
    audit.log_tool_call(user.user_id, "share", {"client_id": client_id, "recipients": recipients},
                        [t.task_id for t in tasks], None)
    return record.model_copy(update={"tasks": tasks})
