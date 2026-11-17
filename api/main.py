"""FastAPI: thin endpoints over app/ (SPEC.md section 6).

All logic stays in app/, so the eval and tests never need the frontend. The
caller is identified by the X-User-Id header (in production: the firm's login),
and their entitlements always come from the users table, never from the request.

Run:  make api   (http://localhost:8000, interactive docs at /docs)
"""

import datetime as dt
import json
from contextlib import asynccontextmanager, closing
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app import audit, db, orchestrator, retrieval, tools
from app.orchestrator import Briefing, BriefingError
from app.tasks import Task, TaskError, TaskRequest, create_task
from app.tools import ClientId, Fact, UserContext
from app.wording import AS_OF_DATE
from eval import run_eval


@asynccontextmanager
async def lifespan(_: FastAPI):
    retrieval.model()  # load the embedding model once at startup, so the first briefing isn't slow
    yield


app = FastAPI(title="Client Briefing Intelligence", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173"],  # the React dev server only
                   allow_methods=["GET", "POST"], allow_headers=["X-User-Id", "Content-Type"])

# ---------------------------------------------------------------------------
# Request and response shapes (mirrored in web/src/api.ts)
# ---------------------------------------------------------------------------


class UserInfo(BaseModel):
    user_id: str
    name: str
    role: str
    entitlements: list[str]


class ClientInfo(BaseModel):
    client_id: str
    legal_name: str
    segment: str


class ResolveResponse(BaseModel):
    query: str
    client: ClientInfo | None       # set when the name resolved
    matched_by: str | None          # id, exact, fuzzy
    error: str | None               # client_not_found or ambiguous_client
    candidates: list[ClientInfo]    # "did you mean" suggestions


class BriefingRequest(BaseModel):
    client_id: ClientId
    meeting_date: dt.date | None = None


class BriefingResponse(Briefing):
    markdown: str                   # the same briefing as Markdown, for the download button


class FlagSummary(BaseModel):
    title: str
    detail: str
    flag_type: str
    severity: str
    housekeeping: bool              # data clean-up, not something to raise at the meeting


class ClientSummary(BaseModel):
    """One row of the meetings list: who, when, and what needs the banker before the meeting."""
    client_id: str
    client_name: str
    segment: str
    region: str
    primary_banker: str | None
    aliases: list[str]
    meeting_date: dt.date
    conflicts: list[str]            # titles of conflict flags: the banker decides these
    heads_up: list[str]             # titles of the other flags that need attention (not housekeeping)
    flags: list[FlagSummary]        # every flag this user may see, for the Data health page


class AuditRow(BaseModel):
    ts: str
    user_id: str
    tool: str
    args: dict[str, Any]
    result_ids: list[str]
    error: str | None

# ---------------------------------------------------------------------------
# Who is calling
# ---------------------------------------------------------------------------


def current_user(x_user_id: Annotated[str | None, Header()] = None) -> UserContext:
    user = tools.load_user(x_user_id) if x_user_id else None
    if user is None:
        raise HTTPException(status_code=401, detail="Send a known user ID in the X-User-Id header.")
    return user


CurrentUser = Annotated[UserContext, Depends(current_user)]


def client_info(client_id: str) -> ClientInfo | None:
    with closing(db.connect()) as conn:
        row = db.client(conn, client_id)
    return ClientInfo(client_id=row["client_id"], legal_name=row["legal_name"], segment=row["segment"]) if row else None

# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@app.get("/users", response_model=list[UserInfo])
def list_users():
    """The demo users, for the user picker."""
    with closing(db.connect()) as conn:
        rows = db.users(conn)
    return [UserInfo(user_id=r["user_id"], name=r["name"], role=r["role"],
                     entitlements=tools.load_user(r["user_id"]).entitlements) for r in rows]


def flag_order(f: Fact) -> tuple:
    """What needs attention first (by severity), data housekeeping last; as in the briefing."""
    return f.label in orchestrator.HOUSEKEEPING, orchestrator.SEVERITY_ORDER[f.details["severity"]], f.evidence_id


def client_summary(user: UserContext, client_id: str) -> ClientSummary | None:
    """Built from the same audited, entitlement-filtered tools as the briefing, without the LLM."""
    profile = tools.get_client_profile(user, client_id=client_id)
    if not profile.ok:
        return None
    flags = tools.get_data_quality_flags(user, client_id=client_id)
    attention = [f for f in flags.facts if f.label not in orchestrator.HOUSEKEEPING]
    client = profile.facts[0]
    primary = [f.value for f in profile.facts if f.source == "coverage" and f.details["coverage_role"] == "primary"]
    return ClientSummary(client_id=client_id, client_name=client.value, segment=client.details["segment"],
                         region=client.details["region"], primary_banker=primary[0] if primary else None,
                         aliases=orchestrator.client_aliases(client_id), meeting_date=AS_OF_DATE,
                         conflicts=[f.details["title"] for f in attention if f.label == "conflict"],
                         heads_up=[f.details["title"] for f in attention if f.label != "conflict"],
                         flags=[FlagSummary(title=f.details["title"], detail=str(f.value), flag_type=f.label,
                                            severity=f.details["severity"],
                                            housekeeping=f.label in orchestrator.HOUSEKEEPING)
                                for f in sorted(flags.facts, key=flag_order)])


@app.get("/clients", response_model=list[ClientSummary])
def list_clients(user: CurrentUser):
    """The meetings list: every client, with what needs checking. No LLM call."""
    with closing(db.connect()) as conn:
        client_ids = [row["client_id"] for row in db.clients(conn)]
    return [s for s in (client_summary(user, cid) for cid in client_ids) if s]


@app.get("/clients/resolve", response_model=ResolveResponse)
def resolve_client(q: Annotated[str, Query(min_length=1, max_length=200)], user: CurrentUser):
    """Which client does the search box mean? Shows alias resolution ("NWC" -> C001)."""
    result = tools.resolve_client(user, name_or_alias=q)
    candidates = [c for c in (client_info(cid) for cid in result.candidates) if c]
    if not result.ok:
        return ResolveResponse(query=q, client=None, matched_by=None, error=result.error, candidates=candidates)
    details = result.facts[0].details
    return ResolveResponse(query=q, client=client_info(details["client_id"]), matched_by=details["matched_by"],
                           error=None, candidates=[])


@app.post("/briefings", response_model=BriefingResponse)
def create_briefing(body: BriefingRequest, user: CurrentUser):
    """Build the full briefing for this user: one LLM call at most twice, every section validated."""
    try:
        briefing = orchestrator.build_briefing(user, body.client_id, body.meeting_date)
    except BriefingError as e:
        raise HTTPException(status_code=404, detail=f"Client not found ({e}).")
    return BriefingResponse(**briefing.model_dump(), markdown=orchestrator.to_markdown(briefing))


@app.get("/sources/{evidence_id:path}", response_model=Fact)
def get_source(evidence_id: str, user: CurrentUser):
    """What a citation chip opens. Restricted and nonexistent IDs get the same 404."""
    result = tools.get_source(user, evidence_id=evidence_id)
    if not result.ok:
        status = 404 if result.error in ("not_found", "invalid_input") else 503
        raise HTTPException(status_code=status, detail="This source is not available.")
    return result.facts[0]


@app.post("/tasks", response_model=Task, status_code=201)
def new_task(body: TaskRequest, user: CurrentUser):
    """Create a follow-up task: the only write a user can make."""
    try:
        return create_task(user, body)
    except TaskError:
        raise HTTPException(status_code=404, detail="Client not found.")


@app.get("/evaluations")
def evaluations(user: CurrentUser) -> dict:
    """The last `make eval` scorecard: counts and statuses only (never failure text, which
    could name restricted records). Written by eval/run_eval.py."""
    if not run_eval.REPORT_PATH.exists():
        raise HTTPException(status_code=404, detail="No scorecard yet. Run make eval.")
    return json.loads(run_eval.REPORT_PATH.read_text(encoding="utf-8"))


@app.get("/audit", response_model=list[AuditRow])
def audit_log(user: CurrentUser, limit: Annotated[int, Query(ge=1, le=200)] = 50):
    """The caller's own recent tool calls (another user's could name restricted records)."""
    return audit.recent(limit, user_id=user.user_id)
