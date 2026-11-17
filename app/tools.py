"""Read-only briefing tools with Pydantic contracts (SPEC.md section 5).

Every tool:
  - takes a UserContext plus keyword arguments, validated by a Pydantic request model;
  - reads through a read-only connection, with entitlement filters inside the SQL
    (app/db.py) or the search (app/retrieval.py);
  - returns a ToolResult of Facts, each with a stable evidence ID the LLM can cite;
  - never raises: failures become ok=False with a typed error;
  - is written to audit_log, and returns no facts if that write fails.

The @tool decorator does all of the above in one place, so each tool body only
turns rows into facts. Numbers stay raw here; app/orchestrator.py formats them.

Call tools with keyword arguments:  get_metrics(user, client_id="C001", since=date(2026, 9, 15))
"""

import datetime as dt
import functools
import json
import sqlite3
from contextlib import closing
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app import audit, db, retrieval
from app.unify import AS_OF_DATE, Resolver
from app.wording import metric_label

# ---------------------------------------------------------------------------
# Contracts
# ---------------------------------------------------------------------------

ClientId = Annotated[str, Field(pattern=r"^C\d{3}$")]
DocType = Literal["email", "meeting_note", "prior_briefing", "research", "news"]


class UserContext(BaseModel):
    user_id: str
    entitlements: list[str]


class Fact(BaseModel):
    evidence_id: str               # what the LLM cites, e.g. SQL:revenue_metrics:C001:2026Q3
    label: str
    value: float | str
    as_of: dt.date
    source: str
    details: dict[str, Any] = {}   # the record's other fields, for code (ranking, tables)


class ToolResult(BaseModel):
    ok: bool
    facts: list[Fact] = []
    error: str | None = None       # invalid_input, client_not_found, ambiguous_client, not_found,
                                   # data_unavailable, audit_unavailable, internal_error
    candidates: list[str] = []     # client IDs the user might have meant


class Request(BaseModel):
    model_config = ConfigDict(extra="forbid")  # a misspelled argument is an error, not silently ignored


class ResolveClientRequest(Request):
    name_or_alias: str = Field(min_length=1, max_length=200)


class ClientRequest(Request):
    client_id: ClientId


class MetricsRequest(ClientRequest):
    since: dt.date                 # usually the last interaction date


class SearchRequest(ClientRequest):
    query: str = Field(max_length=500)
    doc_types: list[DocType] | None = None
    since: dt.date | None = None
    top_k: int = Field(default=5, ge=1, le=20)


class NewsRequest(ClientRequest):
    since: dt.date | None = None


class SourceRequest(Request):
    evidence_id: str = Field(pattern=r"^(SQL|DOC|FLAG):.+$", max_length=200)


class ToolError(Exception):
    """Raised inside a tool body; the decorator turns it into ok=False with this code."""

    def __init__(self, code: str, candidates: list[str] | None = None):
        super().__init__(code)
        self.code = code
        self.candidates = candidates or []

# ---------------------------------------------------------------------------
# The decorator every tool goes through
# ---------------------------------------------------------------------------


def tool(request_model: type[Request]):
    def decorate(body):
        @functools.wraps(body)
        def run(user: UserContext, **kwargs) -> ToolResult:
            result = call_safely(body, request_model, user, kwargs)
            try:
                audit.log_tool_call(user.user_id, body.__name__, kwargs,
                                    [fact.evidence_id for fact in result.facts], result.error)
            except Exception:
                return ToolResult(ok=False, error=result.error or "audit_unavailable")  # no audit, no data
            return result
        return run
    return decorate


def call_safely(body, request_model, user: UserContext, kwargs: dict) -> ToolResult:
    try:
        request = request_model(**kwargs)
    except ValidationError:
        return ToolResult(ok=False, error="invalid_input")
    try:
        with closing(db.connect()) as conn:
            return ToolResult(ok=True, facts=body(conn, user, request))
    except ToolError as e:
        return ToolResult(ok=False, error=e.code, candidates=e.candidates)
    except (sqlite3.Error, OSError):  # database or embeddings file missing or unreadable
        return ToolResult(ok=False, error="data_unavailable")
    except Exception:
        return ToolResult(ok=False, error="internal_error")


def require_client(conn, client_id: str) -> str:
    canonical = db.canonical_client_id(conn, client_id)
    if canonical is None:
        raise ToolError("client_not_found")
    return canonical

# ---------------------------------------------------------------------------
# The eight briefing tools, plus get_source for the citation chips
# ---------------------------------------------------------------------------


@tool(ResolveClientRequest)
def resolve_client(conn, user, req: ResolveClientRequest) -> list[Fact]:
    """Which client? Same rules as unify: ID, exact name or alias, then fuzzy match."""
    r = Resolver.from_db(conn).resolve(req.name_or_alias)
    if r.client_id is None:
        code = "ambiguous_client" if r.method in ("review", "ambiguous") else "client_not_found"
        raise ToolError(code, [r.best_match] if r.best_match else [])
    c = db.client(conn, r.client_id)
    return [Fact(evidence_id=f"SQL:clients:{c['client_id']}", label="Client", value=c["legal_name"],
                 as_of=c["updated_at"], source="clients",
                 details={"client_id": c["client_id"], "matched_by": r.method, "score": r.score})]


@tool(ClientRequest)
def get_client_profile(conn, user, req: ClientRequest) -> list[Fact]:
    """Who is the client: profile, coverage team, key contacts."""
    client_id = require_client(conn, req.client_id)
    c = db.client(conn, client_id)
    facts = [Fact(evidence_id=f"SQL:clients:{client_id}", label="Client", value=c["legal_name"],
                  as_of=c["updated_at"], source="clients",
                  details={k: c[k] for k in ("client_id", "segment", "region", "status", "domain")})]
    for row in db.coverage(conn, client_id):
        facts.append(Fact(evidence_id=f"SQL:coverage:{client_id}:{row['banker_name']}",
                          label=f"Coverage ({row['coverage_role']})", value=row["banker_name"],
                          as_of=row["since"], source="coverage", details={"coverage_role": row["coverage_role"]}))
    for row in db.contacts(conn, client_id):
        facts.append(Fact(evidence_id=f"SQL:contacts:{row['contact_id']}", label=row["title"], value=row["name"],
                          as_of=row["updated_at"], source="contacts",
                          details={k: row[k] for k in ("contact_id", "relationship_role", "email",
                                                       "last_contact_date")}))
    return facts


@tool(MetricsRequest)
def get_metrics(conn, user, req: MetricsRequest) -> list[Fact]:
    """Latest value of every metric series, plus its value at `since` when it has changed.
    The change is computed here in code; the baseline is its own fact so it can be cited."""
    client_id = require_client(conn, req.client_id)
    series = {}
    for row in db.metric_rows(conn, client_id):  # oldest first
        series.setdefault(metric_label(row["source"], row["product"], row["metric"]), []).append(row)
    facts = []
    for name, rows in series.items():
        latest = rows[-1]
        before = [r for r in rows if r["as_of"] <= req.since.isoformat()]
        baseline = before[-1] if before and before[-1]["evidence_id"] != latest["evidence_id"] else None
        details = {"unit": latest["unit"], "period": latest["period"], "role": "latest"}
        if baseline is not None:
            details["change"] = round(latest["value"] - baseline["value"], 4)
            details["baseline_evidence_id"] = baseline["evidence_id"]
        facts.append(Fact(evidence_id=latest["evidence_id"], label=name, value=latest["value"],
                          as_of=latest["as_of"], source=latest["source"], details=details))
        if baseline is not None:
            facts.append(Fact(evidence_id=baseline["evidence_id"], label=f"{name} at last interaction",
                              value=baseline["value"], as_of=baseline["as_of"], source=baseline["source"],
                              details={"unit": baseline["unit"], "period": baseline["period"], "role": "baseline"}))
    return facts


@tool(ClientRequest)
def get_opportunities(conn, user, req: ClientRequest) -> list[Fact]:
    """Pipeline for the client. Restricted rows are filtered in SQL: not shown, not counted."""
    client_id = require_client(conn, req.client_id)
    return [Fact(evidence_id=f"SQL:opportunities:{o['opp_id']}", label=o["product"], value=o["est_value_usd"],
                 as_of=o["updated_at"], source="opportunities",
                 details={"opp_id": o["opp_id"], "stage": o["stage"], "owner": o["owner"],
                          "next_step": o["next_step"], "restricted": bool(o["restricted"])})
            for o in db.opportunities(conn, client_id, user.entitlements)]


@tool(ClientRequest)
def get_open_items(conn, user, req: ClientRequest) -> list[Fact]:
    """Actions (open first, each marked overdue or not) and service issues (open first)."""
    client_id = require_client(conn, req.client_id)
    facts = []
    for a in db.actions(conn, client_id):
        overdue = a["status"] == "Open" and a["due_date"] < AS_OF_DATE.isoformat()
        facts.append(Fact(evidence_id=f"SQL:open_actions:{a['action_id']}", label="Action", value=a["description"],
                          as_of=a["due_date"], source="open_actions",
                          details={"action_id": a["action_id"], "owner": a["owner"], "due_date": a["due_date"],
                                   "status": a["status"], "overdue": overdue, "source_doc_id": a["source_doc_id"]}))
    for s in db.service_issues(conn, client_id):
        facts.append(Fact(evidence_id=f"SQL:service_issues:{s['issue_id']}", label="Service issue",
                          value=s["summary"], as_of=s["opened"], source="service_issues",
                          details={k: s[k] for k in ("issue_id", "severity", "status", "opened", "closed")}))
    return facts


def chunk_fact(chunk, score: float | None = None) -> Fact:
    return Fact(evidence_id=f"DOC:{chunk['doc_id']}", label=f"{chunk['doc_type']} {chunk['doc_id']}",
                value=chunk["text"], as_of=chunk["date"], source=chunk["source"],
                details={"doc_id": chunk["doc_id"], "chunk_id": chunk["chunk_id"], "doc_type": chunk["doc_type"],
                         "score": score})


@tool(SearchRequest)
def search_documents(conn, user, req: SearchRequest) -> list[Fact]:
    """What the client asked, said, or committed: hybrid search over the chunks this user may see."""
    client_id = require_client(conn, req.client_id)
    hits = retrieval.search(conn, client_id, req.query, user.entitlements, req.doc_types, req.since, req.top_k)
    return [chunk_fact(chunk, round(score, 4)) for chunk, score in hits]


@tool(NewsRequest)
def get_news(conn, user, req: NewsRequest) -> list[Fact]:
    """Approved news only: unify never indexed news from unapproved sources."""
    client_id = require_client(conn, req.client_id)
    return [chunk_fact(chunk) for chunk in db.visible_chunks(conn, client_id, user.entitlements, ["news"], req.since)]


@tool(ClientRequest)
def get_data_quality_flags(conn, user, req: ClientRequest) -> list[Fact]:
    """What is uncertain, conflicting, or unavailable, as written by unify."""
    client_id = require_client(conn, req.client_id)
    return [Fact(evidence_id=f"FLAG:{f['flag_id']}", label=f["flag_type"], value=f["detail"], as_of=AS_OF_DATE,
                 source="data_quality_flags",
                 details={"title": f["title"], "severity": f["severity"], "source_ids": json.loads(f["source_ids"]),
                          "action": f["action"], "caveat": f["caveat"]})
            for f in db.flags(conn, client_id, user.entitlements)]

@tool(SourceRequest)
def get_source(conn, user, req: SourceRequest) -> list[Fact]:
    """What a citation chip opens: the record or document behind an evidence ID.
    Something the user may not see is 'not_found', exactly like an ID that doesn't exist,
    so the answer never reveals that a restricted record is there."""
    kind, _, key = req.evidence_id.partition(":")
    if kind == "DOC":
        chunks = db.visible_document(conn, key, user.entitlements)
        if not chunks:
            raise ToolError("not_found")
        first = chunks[0]
        return [Fact(evidence_id=req.evidence_id, label=f"{first['doc_type']} {key}",
                     value="\n\n".join(c["text"] for c in chunks), as_of=first["date"], source=first["source"],
                     details={k: first[k] for k in ("doc_id", "doc_type", "client_id", "source", "date")})]
    if kind == "FLAG":
        flag = db.visible_flag(conn, key, user.entitlements)
        if flag is None:
            raise ToolError("not_found")
        return [Fact(evidence_id=req.evidence_id, label=flag["title"], value=flag["detail"], as_of=AS_OF_DATE,
                     source="data_quality_flags",
                     details={"severity": flag["severity"], "client_id": flag["client_id"],
                              "source_ids": json.loads(flag["source_ids"])})]
    table, _, row_key = key.partition(":")
    row = db.source_row(conn, table, row_key, user.entitlements)
    if row is None:
        raise ToolError("not_found")
    return [Fact(evidence_id=req.evidence_id, label=f"{table} {row_key}", value=row_key,
                 as_of=row[db.SOURCE_TABLES[table][1]], source=table, details=dict(row))]

# ---------------------------------------------------------------------------
# Identity (not a tool): who is calling, and what may they see?
# ---------------------------------------------------------------------------


def load_user(user_id: str) -> UserContext | None:
    """Entitlements come from the users table, never from the caller."""
    with closing(db.connect()) as conn:
        row = db.user(conn, user_id)
    if row is None:
        return None
    return UserContext(user_id=row["user_id"], entitlements=json.loads(row["entitlements"]))
