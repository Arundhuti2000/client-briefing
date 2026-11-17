# API reference

The Client Briefing Intelligence prototype offers three interfaces over one set of read-only,
entitlement-filtered and audited tools: an HTTP API built with FastAPI (`api/main.py`), the tool
layer itself (`app/tools.py`), which the briefing builder and the follow-up agent call, and an MCP
server (`mcp_server/server.py`) for external AI assistants. The HTTP API is deliberately thin: it
identifies the caller, validates input and maps errors to status codes, while all logic lives in
`app/`. This document describes the conventions shared by every endpoint, each endpoint with its
request and response fields, the contract of each tool, and the MCP server. The controls that
these interfaces rely on are explained in [SECURITY.md](SECURITY.md), and terms such as
*evidence ID* and *entitlement* are defined in the [glossary](../SPEC.md#15-glossary).

**Contents**

- [Conventions](#conventions)
- [Endpoints](#endpoints)
- [Tool contracts](#tool-contracts)
- [MCP server](#mcp-server)

---

## Conventions

### Base URL and format

- `make api` starts the server with uvicorn on `http://localhost:8000`. FastAPI also serves
  interactive documentation at `/docs` and `/redoc`, and the OpenAPI schema at `/openapi.json`.
- Request and response bodies are JSON. Dates use ISO 8601 (`YYYY-MM-DD`). Timestamps
  (`ts`, `decided_at`, `shared_at`, `created_at`) are UTC ISO 8601 strings to the second.
- Every response shape is a Pydantic model, except `GET /evaluations`, which returns a saved JSON
  file as is. The same shapes are mirrored as TypeScript types in `web/src/api.ts`.
- Amounts and percentages meant for people are strings formatted by code (for example `"$2.31M"`,
  `"8.6%"`, `"+0.7 pts"`). Raw numbers appear only where code needs them: `Fact.value` from the
  tools and `MetricPoint.value`, which exists only to draw trend lines.

### Identity and entitlements

- The caller is identified by the `X-User-Id` request header. The `current_user` dependency looks
  the ID up in the `users` table (`tools.load_user`).
- A missing or empty header, or an ID that is not in the `users` table, returns **401** with
  `{"detail": "Send a known user ID in the X-User-Id header."}`.
- Every endpoint requires the header except `GET /users`, which feeds the demo user picker, and
  FastAPI's documentation routes.
- The header stands in for the firm's login: the prototype performs no authentication of its own.
- Entitlements (the permission labels a user holds, such as `standard` or `restricted_deals`)
  always come from the `users` table and never from the request. No request model has a user or
  entitlement field. See [Entitlement model](SECURITY.md#entitlement-model).

### CORS

`CORSMiddleware` allows a single origin, `http://localhost:5173` (the React development server),
with the methods `GET` and `POST` and the headers `X-User-Id` and `Content-Type`.

### Client IDs

- Request bodies and tool requests validate client IDs against the pattern `^C\d{3}$` (the
  `ClientId` type in `app/tools.py`); a malformed ID is a 422 error in a request body and
  `invalid_input` in a tool call.
- `{client_id}` path parameters are not pattern-checked. They are looked up with
  `db.canonical_client_id`, which follows client merges, so the ID of a merged duplicate resolves to
  the surviving client. An unknown ID returns 404 `{"detail": "Client not found."}`.
- Clients themselves carry no restricted data, so "Client not found." means the client does not
  exist.

### Error responses

FastAPI returns errors as `{"detail": ...}`. Validation errors raised by FastAPI (a malformed
body, a field outside its constraints, an unknown field where a model forbids extra fields) use
FastAPI's standard shape: `detail` is a list of objects with `type`, `loc`, `msg` and `input`.
Errors raised by the application use a single string in `detail`.

| Status | Raised by | `detail` |
| --- | --- | --- |
| 401 | Every endpoint except `GET /users` | `Send a known user ID in the X-User-Id header.` |
| 404 | `POST /briefings` | `Client not found (<tool error code>).` |
| 404 | `/briefings/{client_id}/...`, `POST /tasks` | `Client not found.` |
| 404 | `POST /briefings/{client_id}/decisions` | `Conflict not found.` |
| 404 | `POST /briefings/{client_id}/share` | `A follow-up points at a source that is not available.` |
| 404 | `GET /sources/{evidence_id}` | `This source is not available.` |
| 404 | `GET /evaluations` | `No scorecard yet. Run make eval.` |
| 409 | `POST /briefings/{client_id}/share` | `Decide the <n> open conflict(s) first.` |
| 422 | Any endpoint with a body or query parameter | FastAPI validation list |
| 422 | `POST /briefings/{client_id}/ask` | `Type a question.` |
| 422 | `POST /briefings/{client_id}/decisions` | `Pick one of the conflict's own sources.` |
| 422 | `POST /briefings/{client_id}/share` | `Recipients must be members of the client's coverage team.` |
| 503 | `GET /sources/{evidence_id}` | `This source is not available.` |

The request models `AskRequest`, `DecisionRequest`, `ShareRequest`, `FollowUp` and `TaskRequest`
forbid extra fields, so a misspelt or unexpected field is a 422 error. `BriefingRequest` ignores
extra fields. An unhandled exception produces FastAPI's default 500 response.

### Restricted and missing records look the same

A record the caller may not see is reported exactly like a record that does not exist:

- `GET /sources/{evidence_id}` returns the same 404 and the same body for a restricted, a
  nonexistent and a malformed evidence ID.
- `POST /briefings/{client_id}/decisions` returns `Conflict not found.` for a flag that does not
  exist, is not a conflict, belongs to another client, or is not visible to the caller.
- `POST /briefings/{client_id}/share` refuses a follow-up whose source the caller cannot open with
  the same 404 as one whose source does not exist.

See [No leakage by count](SECURITY.md#no-leakage-by-count).

### The as-of date

`AS_OF_DATE` in `app/wording.py` (2026-11-18) is the demo's "today" and meeting date. It is the
default `meeting_date`, the reference for overdue actions and stale metrics, the `as_of` date of
data-quality flags, and the due date of follow-up tasks created by a share.

---

## Endpoints

| Method | Path | Purpose | Success |
| --- | --- | --- | --- |
| GET | `/users` | Demo users and their entitlements (no header needed) | 200 `list[UserInfo]` |
| GET | `/clients` | Meetings list: every client with what needs checking | 200 `list[ClientSummary]` |
| GET | `/clients/resolve` | Which client a name or alias means | 200 `ResolveResponse` |
| POST | `/briefings` | Build the full briefing for the caller | 200 `BriefingResponse` |
| POST | `/briefings/{client_id}/ask` | Answer a follow-up question about one client | 200 `Answer` |
| GET | `/briefings/{client_id}/workflow` | The caller's conflict decisions and the latest share | 200 `WorkflowState` |
| POST | `/briefings/{client_id}/decisions` | Record which source the caller trusts for a conflict | 200 `Decision` |
| POST | `/briefings/{client_id}/share` | Approve and share the briefing; create follow-up tasks | 201 `ShareRecord` |
| GET | `/sources/{evidence_id}` | Open the record or document behind a citation | 200 `Fact` |
| POST | `/tasks` | Create a follow-up task | 201 `Task` |
| GET | `/evaluations` | The last saved evaluation scorecard | 200 object |
| GET | `/audit` | The caller's own recent audit rows | 200 `list[AuditRow]` |

### Users and clients

#### `GET /users`

Lists every row of the `users` table, ordered by `user_id`, for the demo user picker. This is the
only application endpoint that does not require `X-User-Id`.

| Field | Type | Description |
| --- | --- | --- |
| `user_id` | string | For example `u1` |
| `name` | string | Display name |
| `role` | string | Job title |
| `entitlements` | list of strings | From the `users` table, for example `["standard", "restricted_deals"]` |

#### `GET /clients`

The meetings list. For every client (ordered by legal name) the summary is built from the audited,
entitlement-filtered tools `get_client_profile`, `get_data_quality_flags` and
`get_metric_history`, without any LLM call. A client whose profile cannot be loaded is omitted.

`ClientSummary`:

| Field | Type | Description |
| --- | --- | --- |
| `client_id` | string | Canonical client ID |
| `client_name` | string | Legal name |
| `segment`, `region` | string | From the client record |
| `primary_banker` | string or null | The coverage banker with the `primary` role |
| `aliases` | list of strings | Names the source data uses for this client |
| `meeting_date` | date | `AS_OF_DATE` |
| `conflicts` | list of strings | Titles of the conflict flags the caller may see |
| `heads_up` | list of strings | Titles of the other visible flags that are not housekeeping |
| `flags` | list of `FlagSummary` | Every visible flag: housekeeping last, then by severity (high, medium, low), then by ID |
| `metrics` | list of `MetricSeries` | Every metric series, Revenue and Wallet share first |

`FlagSummary`: `title`, `detail`, `flag_type`, `severity` (`high`, `medium` or `low`) and
`housekeeping` (true for the clean-up types `duplicate_client`, `duplicate_contact`, `stale`,
`excluded_source` and `unresolved_reference`).

`MetricSeries`:

| Field | Type | Description |
| --- | --- | --- |
| `label` | string | For example `Revenue`, `Wallet share` |
| `unit` | string | `usd` or `pct` |
| `points` | list of `MetricPoint` | Oldest first |
| `change` | string or null | Latest value minus the one before, formatted (`"+$270K"`, `"+0.7 pts"`); null with one point |
| `stale` | boolean | True when the latest value is more than `STALE_AFTER_DAYS` (120) days before `AS_OF_DATE` |

`MetricPoint`: `period` (`"Q3 2026"`, or the balance date for holdings), `value` (raw number, for
drawing only), `text` (formatted by code), `as_of` and `evidence_id`.

#### `GET /clients/resolve?q=<name>`

Resolves a client ID, name or alias with the `resolve_client` tool. `q` must be 1 to 200
characters (otherwise 422). The response is 200 whether or not the name resolves.

| Field | Type | Description |
| --- | --- | --- |
| `query` | string | The `q` value |
| `client` | `ClientInfo` or null | Set when the name resolved: `client_id`, `legal_name`, `segment` |
| `matched_by` | string or null | `id`, `exact` or `fuzzy` |
| `error` | string or null | The tool's error code, normally `client_not_found` or `ambiguous_client` |
| `candidates` | list of `ClientInfo` | "Did you mean" suggestions when the name did not resolve |

### Briefings and follow-up questions

#### `POST /briefings`

Builds the full briefing for the caller with `orchestrator.build_briefing`: a fixed plan of tool
calls, code-written metrics and data-quality sections, one request down the LLM provider chain for
the remaining sections, and the validator on every section. The flow is described in
[LLM provider chain](ARCHITECTURE.md#llm-provider-chain) and [Validator rules](SECURITY.md#validator-rules).

Request (`BriefingRequest`):

| Field | Type | Constraints |
| --- | --- | --- |
| `client_id` | string | Required; pattern `^C\d{3}$`; a merged ID resolves to the survivor |
| `meeting_date` | date or null | Optional; default `AS_OF_DATE`. Sets the 90-day news window (`NEWS_WINDOW_DAYS`) and the metrics baseline when no prior interaction is visible |

Errors: 404 `Client not found (<code>).` when `get_client_profile` fails for any reason (the
code is the tool's error code, for example `client_not_found`; a database or audit failure on
that tool also produces this 404); 422 for an invalid body.

Response (`BriefingResponse`, the `Briefing` model plus `markdown`):

| Field | Type | Description |
| --- | --- | --- |
| `client_id`, `client_name`, `segment`, `region` | string | The resolved client |
| `user_id` | string | The caller |
| `prepared_for` | string | For example `"Sam Rivera (Analyst)"` |
| `meeting_date` | date | As requested, or `AS_OF_DATE` |
| `last_interaction` | date or null | Latest meeting note or prior briefing the caller may see |
| `coverage` | list of strings | `"<banker> (<role>)"` |
| `contacts` | list of strings | `"<name>, <title>"` |
| `aliases` | list of strings | Names the data uses for the client |
| `what_changed` | list of `Change` | Since the last interaction: metric changes, opportunity updates, new documents, new actions. Empty without a last interaction |
| `sections` | list of `Section` | The eight sections, in plan order |
| `metrics` | list of `MetricRow` | Latest value of every series |
| `opportunities` | list of `OpportunityRow` | Live opportunities ranked first, then Won and Lost |
| `actions` | list of `ActionRow` | Every action, open first |
| `flags` | list of `FlagRow` | Every visible flag, housekeeping last |
| `evidence` | object of `Evidence` by evidence ID | Everything a citation can open: the section evidence, documents since the last interaction, all action and service-issue rows, and both sides of every visible conflict |
| `llm_runs` | list of `LLMRun` | One entry per request to the provider chain |
| `generated_ms` | integer | Build time in milliseconds |
| `markdown` | string | The same briefing as Markdown, with numbered footnotes instead of internal IDs |

Sections, in order:

| `id` | `title` | Written by |
| --- | --- | --- |
| `client_overview` | Who the client is | Provider chain |
| `metrics` | Material metrics | Code |
| `client_said` | What the client asked, said, or committed | Provider chain |
| `opportunities` | Opportunities to discuss | Provider chain |
| `open_items` | Open actions and service issues | Provider chain |
| `news` | Recent news | Provider chain |
| `uncertain` | Uncertain, conflicting, or unavailable | Code |
| `talking_points` | Talking points | Provider chain |

`Section` fields:

| Field | Type | Description |
| --- | --- | --- |
| `id`, `title`, `question` | string | From the plan |
| `bullets` | list of `Bullet` | Each `{text, citations}`; `citations` is a list of evidence IDs |
| `written_by` | string | `code`, `mock`, the model that answered, or `evidence (fallback)` |
| `provider` | string or null | `gemini`, `openrouter`, `ollama` or `mock`; null when code wrote it or the evidence is shown |
| `author` | string | `ai` (a real model), `template` (mock mode), `code` or `evidence` (fallback) |
| `status` | string | `ok`, `empty`, `unavailable` (the section's tool failed) or `fallback` |
| `check` | `Check` | The validator's result on the final text: `passed`, `errors`, `reasons` |
| `retry_note` | string or null | Plain explanation when a first draft was rejected |
| `retry_errors` | list of strings | Technical detail of that rejection |
| `note` | string or null | For example `"Nothing on file for this question."` |

Other row models:

| Model | Fields |
| --- | --- |
| `Change` | `text`, `evidence_ids` |
| `MetricRow` | `label`, `value` (formatted), `change` (formatted or null), `period` (or null), `as_of`, `evidence_id` |
| `OpportunityRow` | `opp_id`, `product`, `stage`, `value` (formatted), `owner`, `next_step` (empty string if none), `updated`, `live`, `rank` (1 = discuss first; null for Won and Lost), `evidence_id` |
| `ActionRow` | `action_id`, `description`, `owner`, `due_date`, `status` (`Open` or `Done`), `overdue`, `evidence_id` |
| `FlagRow` | `flag_id` (without the `FLAG:` prefix), `flag_type`, `title`, `severity`, `housekeeping`, `detail`, `source_ids`, `evidence_id`, `uses` (conflicts: the evidence ID of the side the briefing uses) |
| `Evidence` | `evidence_id`, `kind` (`fact`, `document` or `flag`), `label`, `text`, `as_of`, `source`, `suggestion`, `caveat`, `caveat_id` |
| `LLMRun` | `provider`, `model`, `cached`, `notes`, `seconds`, `requests`, `tokens_in`, `tokens_out` |

Opportunities are ranked by code: expected value (estimate multiplied by the stage probability:
Discovery 0.2, Proposal 0.5, Negotiation 0.8), then recency.

#### `POST /briefings/{client_id}/ask`

Answers one follow-up question about one client. The question is routed (keyword rule, then
meaning, then an LLM tie-breaker, then document search by default); routes about numbers and
records are answered by code from SQL, and only the `documents` and `news` routes use a bounded
tool-calling loop of at most `MAX_STEPS` (3) model turns whose answer must pass the validator. See
[Routing and the bounded agent](ARCHITECTURE.md#routing-and-the-bounded-agent).

Request (`AskRequest`, extra fields forbidden): `question`, a string of 1 to 500 characters.

Errors: 404 `Client not found.` for an unknown client; 422 `Type a question.` when the question is
only whitespace; 422 for an invalid body.

Response (`Answer`):

| Field | Type | Description |
| --- | --- | --- |
| `question` | string | The question, trimmed |
| `client_id` | string | Canonical client ID |
| `route` | string | `metrics`, `people`, `pipeline`, `actions`, `data_quality`, `documents`, `news` or `out_of_scope` |
| `method` | string | How the route was chosen: `rule`, `meaning`, `llm` or `default` |
| `reason` | string | Why, for example `matched "cfo"` |
| `status` | string | `answered`, `couldnt_summarize` or `refused` |
| `answered_by` | string | `code`, `ai`, `evidence` or `nobody` |
| `provider`, `model` | string or null | The LLM that answered or was asked, if any |
| `tools_called` | list of strings | Tools called for this answer (for the agent, only calls that succeeded) |
| `llm_steps` | integer | Model turns used (0 for code routes) |
| `bullets` | list of `Bullet` | At most `MAX_BULLETS` (8) |
| `note` | string or null | Refusal text, `"Couldn't summarize this, so here is the evidence the tools found."` or `"Nothing on file for this question."` |
| `evidence` | object of `Evidence` | Everything the bullets may cite |
| `check` | `Check` | The validator's result on the bullets |

A question routed to `out_of_scope`, which includes every question containing instruction-like
text, is refused (`status` `refused`, `answered_by` `nobody`) without any tool or LLM call. The
steps are audited as `ask_router` (the routing decision), `ask_llm` (each model turn of the
agent), `validator` (a rejected agent answer) and `ask_answer` (the final answer), in addition to
the tool calls themselves.

### Workflow and tasks

#### `GET /briefings/{client_id}/workflow`

Returns `WorkflowState`:

| Field | Type | Description |
| --- | --- | --- |
| `decisions` | list of `Decision` | The caller's saved decisions on conflicts the caller can see |
| `open_conflicts` | integer | Visible conflict flags without a decision from the caller |
| `share` | `ShareRecord` or null | The latest share of this client's briefing, by any approver; its `tasks` list is empty here |

#### `POST /briefings/{client_id}/decisions`

Records which source the caller trusts for one conflict flag. Saving again for the same flag
replaces the earlier decision (one decision per user, client and flag). Audited as `decision`.

Request (`DecisionRequest`, extra fields forbidden):

| Field | Type | Constraints |
| --- | --- | --- |
| `flag_id` | string | Pattern `^FLAG:F\d+$` |
| `source_id` | string | At most 200 characters; must be one of the flag's `source_ids` |

Response (`Decision`): `flag_id`, `source_id`, `decided_at`.

Errors: 404 `Client not found.`; 404 `Conflict not found.` when the flag does not exist, is not a
conflict, belongs to another client or is not visible to the caller; 422 `Pick one of the
conflict's own sources.`; 422 for an invalid body.

#### `POST /briefings/{client_id}/share`

Approves and shares the briefing. Returns **201** with a `ShareRecord`. The checks run in this
order, and no task or share is created until all of them pass:

1. Every conflict the caller can see must have the caller's decision, otherwise **409**
   `Decide the <n> open conflict(s) first.`
2. Recipients must be a non-empty list of members of the client's coverage team, otherwise **422**.
   When `recipients` is omitted or null, the whole coverage team receives it.
3. Every follow-up `source_id` must open for the caller through `get_source`, otherwise **404**
   `A follow-up points at a source that is not available.`

Each follow-up then becomes a task (due on `AS_OF_DATE`, audited as `create_task`), the share is
stored, and the share is audited as `share` with the new task IDs. The share is a record of the
approval; the prototype sends no message.

Request (`ShareRequest`, extra fields forbidden):

| Field | Type | Constraints |
| --- | --- | --- |
| `recipients` | list of strings or null | At most 20 names; default: the whole coverage team |
| `follow_ups` | list of `FollowUp` | At most 20; default empty |

`FollowUp` (extra fields forbidden): `description` (3 to 300 characters) and `source_id`
(optional, at most 200 characters).

Response (`ShareRecord`):

| Field | Type | Description |
| --- | --- | --- |
| `share_id` | string | `S-` followed by a three-digit sequence number |
| `client_id` | string | Canonical client ID |
| `approver`, `approver_name` | string | The approver's user ID and display name |
| `recipients` | list of strings | Coverage bankers |
| `shared_at` | string | UTC timestamp |
| `task_ids` | list of strings | The follow-up tasks created |
| `tasks` | list of `Task` | The tasks themselves |

#### `POST /tasks`

Creates a follow-up task. Returns **201** with a `Task`. Audited as `create_task`.

Request (`TaskRequest`, extra fields forbidden):

| Field | Type | Constraints |
| --- | --- | --- |
| `client_id` | string | Required; pattern `^C\d{3}$`; a merged ID is stored as the survivor |
| `description` | string | 3 to 300 characters |
| `due_date` | date or null | Optional |
| `source_id` | string or null | Optional evidence ID, at most 200 characters; stored as given |

Response (`Task`): the request fields plus `task_id` (`T-` followed by a three-digit sequence
number), `user_id` (the caller), `status` (`Open`) and `created_at` (UTC timestamp).

Errors: 404 `Client not found.`; 422 for an invalid body.

### Sources

#### `GET /sources/{evidence_id}`

Opens the record or document behind an evidence ID, through the `get_source` tool. The path
accepts the whole ID, colons included (for example `/sources/SQL:opportunities:OPP-NOR-TM`);
characters such as the spaces in coverage IDs must be URL-encoded. Returns **200** with a `Fact`
(see [Tool contracts](#tool-contracts)).

| Tool result | Status | `detail` |
| --- | --- | --- |
| `not_found` (missing or restricted) or `invalid_input` (malformed) | 404 | `This source is not available.` |
| `data_unavailable`, `audit_unavailable`, `internal_error` | 503 | `This source is not available.` |

### Evaluation and audit

#### `GET /evaluations`

Returns the contents of `eval/last_run.json`, written by `make eval`: an object with `ran_at`,
`runs`, `holdout_runs` and `quality`. The scorecard rows hold counts and statuses only; failure
messages, which can name restricted records, stay in the terminal. Requires `X-User-Id`. Returns
404 `No scorecard yet. Run make eval.` when the file does not exist. See
[Scorecard](EVALUATION.md#scorecard).

#### `GET /audit?limit=<n>`

Returns the caller's own audit rows, newest first. `limit` is an integer from 1 to 200, default 50.
Rows of other users are never returned. An empty list is returned when nothing has been logged.

`AuditRow`:

| Field | Type | Description |
| --- | --- | --- |
| `ts` | string | UTC timestamp |
| `user_id` | string | The caller |
| `tool` | string | Tool name, or a workflow step such as `create_task`, `decision`, `share`, `validator`, `ask_router` |
| `args` | object | The call's arguments |
| `result_ids` | list of strings | Evidence IDs (or task IDs) returned |
| `error` | string or null | Error code or validator detail; null on success |

See [Audit log](SECURITY.md#audit-log).

---

## Tool contracts

The tools in `app/tools.py` are the read-only, audited functions through which the briefing
builder, the follow-up agent, most endpoints and the MCP server read client data. They are
plain Python functions called as `tool(user, **kwargs)` with keyword arguments, for example
`get_metrics(user, client_id="C001", since=date(2026, 9, 15))`.

### Result shapes

`ToolResult`:

| Field | Type | Description |
| --- | --- | --- |
| `ok` | boolean | False when the call failed |
| `facts` | list of `Fact` | Empty when `ok` is false |
| `error` | string or null | A typed error code (below) |
| `candidates` | list of strings | Client IDs the caller may have meant (`resolve_client` only) |

`Fact`:

| Field | Type | Description |
| --- | --- | --- |
| `evidence_id` | string | Stable ID that a bullet cites |
| `label` | string | Short label, for example `Client`, `Revenue`, `Action` |
| `value` | number or string | Raw value; numbers are not formatted here |
| `as_of` | date | When the record was valid |
| `source` | string | Table or document source |
| `details` | object | The record's other fields, for code (ranking, tables) |

### Evidence ID formats

| Format | Example | Notes |
| --- | --- | --- |
| `SQL:clients:<client_id>` | `SQL:clients:C001` | |
| `SQL:coverage:<client_id>:<banker_name>` | | Contains the banker's full name |
| `SQL:contacts:<contact_id>` | | |
| `SQL:revenue_metrics:<client_id>:<period>` | `SQL:revenue_metrics:C001:2026Q3` | Revenue and wallet share of one row share this ID |
| `SQL:holdings:<client_id>:<product>:<as_of>` | | |
| `SQL:performance:<client_id>:<product>:<metric>:<period>` | | |
| `SQL:opportunities:<opp_id>` | `SQL:opportunities:OPP-NOR-TM` | |
| `SQL:open_actions:<action_id>` | `SQL:open_actions:A-001` | |
| `SQL:service_issues:<issue_id>` | | |
| `DOC:<doc_id>` | `DOC:note_001` | One ID per document; the chunk is in `details.chunk_id` |
| `FLAG:<flag_id>` | `FLAG:F009` | A data-quality flag |

### The `@tool` decorator

Every tool is wrapped by `@tool(RequestModel)`, which does the following in one place:

1. **Validation.** The keyword arguments are validated by the tool's Pydantic request model. Every
   request model forbids extra fields, so a misspelt argument (or an attempt to pass `user_id` or
   `entitlements`) is `invalid_input` rather than being ignored.
2. **Read-only execution.** The body runs on a read-only SQLite connection (`db.connect()`, URI
   `mode=ro`) and turns rows into facts.
3. **Error handling.** A tool never raises. A `ToolError` raised by the body becomes its code (and
   candidates); `sqlite3.Error` or `OSError` (database or embeddings file missing or unreadable)
   becomes `data_unavailable`; any other exception becomes `internal_error`.
4. **Auditing.** One row is written to `audit_log` with the user, the tool name, the arguments, the
   evidence IDs returned and the error.
5. **No audit, no data.** If the audit write fails, the call returns `ok=false` with no facts and
   the error `audit_unavailable` (or the call's own error code, if it had already failed).

The decorator also attaches the request model to the function as `request_model`, which is the
schema offered to models and to MCP clients.

### Error codes

| Code | Meaning |
| --- | --- |
| `invalid_input` | Arguments failed the request model, or a model's arguments were not a JSON object |
| `unknown_tool` | `call_tool` was asked for a tool that is not offered |
| `client_not_found` | No client matches the ID or name |
| `ambiguous_client` | A name matches several clients, or its fuzzy match needs human review |
| `not_found` | `get_source`: the record does not exist or the caller may not see it |
| `data_unavailable` | The database or embeddings file is missing or unreadable |
| `audit_unavailable` | The audit row could not be written, so no data is returned |
| `internal_error` | Any other failure inside the tool |

The MCP server adds `unknown_user` (see [MCP server](#mcp-server)).

### Tool reference

Every request model forbids extra fields. `client_id` always uses the pattern `^C\d{3}$`, and
every client-scoped tool resolves a merged client ID to the surviving client before reading
(`client_not_found` otherwise). "Filtered" means the entitlement filter is inside the SQL query
or search; see [Filtering in the query](SECURITY.md#filtering-in-the-query).

| Tool | Request model and fields | Filtered |
| --- | --- | --- |
| `resolve_client` | `ResolveClientRequest`: `name_or_alias` (string, 1 to 200 characters) | No restricted data |
| `get_client_profile` | `ClientRequest`: `client_id` | No restricted data |
| `get_metric_history` | `ClientRequest`: `client_id` | No restricted data |
| `get_metrics` | `MetricsRequest`: `client_id`; `since` (date, required) | No restricted data |
| `get_opportunities` | `ClientRequest`: `client_id` | Yes |
| `get_open_items` | `ClientRequest`: `client_id` | No restricted data |
| `search_documents` | `SearchRequest`: `client_id`; `query` (string, at most 500 characters, may be empty); `doc_types` (optional list of `email`, `meeting_note`, `prior_briefing`, `research`, `news`); `since` (optional date); `top_k` (integer 1 to 20, default 5) | Yes |
| `get_news` | `NewsRequest`: `client_id`; `since` (optional date) | Yes |
| `get_data_quality_flags` | `ClientRequest`: `client_id` | Yes |
| `get_source` | `SourceRequest`: `evidence_id` (pattern `^(SQL\|DOC\|FLAG):.+$`, at most 200 characters) | Yes |

What each tool returns:

- **`resolve_client`**: one fact `SQL:clients:<id>` (label `Client`, value the legal name) with
  `details` `client_id`, `matched_by` (`id`, `exact` or `fuzzy`) and `score`. The rules are those
  of unification: an exact client ID (merged IDs map to the survivor), then an exact normalized name
  or alias, then a fuzzy match, which resolves only at a score of `RESOLVE_SCORE` (90) or more
  for a single client; a score from `REVIEW_SCORE` (75) up is reported as `ambiguous_client`
  (needs review) and a lower one as `client_not_found`. See
  [Unification rules](DATA.md#unification-rules). On either error, `candidates` holds the closest
  client when there is one.
- **`get_client_profile`**: the client fact (`details`: `client_id`, `segment`, `region`,
  `status`, `domain`), one `SQL:coverage:...` fact per coverage banker (label
  `Coverage (<role>)`), and one `SQL:contacts:...` fact per contact (label the contact's title;
  `details`: `contact_id`, `relationship_role`, `email`, `last_contact_date`).
- **`get_metric_history`**: every value of every metric series, oldest first within each series,
  with `details` `unit` (`usd` or `pct`) and `period`. Used by `GET /clients` for trend lines.
- **`get_metrics`**: the latest value of every series (`details`: `unit`, `period`, `role`
  `latest`). When the series has a value dated on or before `since` that is not the latest row, the
  latest fact also carries `change` (computed in code, rounded to four decimals) and
  `baseline_evidence_id`, and the baseline is returned as its own fact (label
  `<series> at last interaction`, `role` `baseline`) so that it can be cited.
- **`get_opportunities`**: one fact per visible opportunity (label the product, value the estimated
  value in USD; `details`: `opp_id`, `stage`, `owner`, `next_step`, `restricted`).
- **`get_open_items`**: actions (label `Action`, value the description, `as_of` the due date;
  `details`: `action_id`, `owner`, `due_date`, `status`, `overdue`, `source_doc_id`), open ones
  first by due date, then service issues (label `Service issue`; `details`: `issue_id`,
  `severity`, `status`, `opened`, `closed`), open ones first, newest first. An action is overdue
  when it is open and due before `AS_OF_DATE`.
- **`search_documents`**: hybrid search (BM25 keyword ranking and vector similarity, merged with
  Reciprocal Rank Fusion) over the chunks the caller may see; one fact per chunk (value the chunk
  text; `details`: `doc_id`, `chunk_id`, `doc_type`, `score`). A query with no keywords returns the
  newest chunks with score 0.
- **`get_news`**: every visible chunk of approved news for the client, newest first, optionally
  from `since` on (`score` is null).
- **`get_data_quality_flags`**: one fact per visible flag (label the flag type, value the detail,
  `as_of` `AS_OF_DATE`; `details`: `title`, `severity`, `source_ids`, `action`, `caveat`, `uses`).
- **`get_source`**: the record or document behind one evidence ID. `DOC:` returns the document's
  visible chunks joined into one fact; `FLAG:` returns the visible flag; `SQL:<table>:<key>` returns
  the row as `details`, for the tables listed in `db.SOURCE_TABLES` only. Anything else, anything
  missing and anything restricted is `not_found`. Documents that were never indexed (unattached,
  or news from an unapproved source) cannot be opened.

### Tools offered to the LLM

`AGENT_TOOLS` lists the eight tools a model may be offered: `resolve_client`,
`get_client_profile`, `get_metrics`, `get_opportunities`, `get_open_items`, `search_documents`,
`get_news` and `get_data_quality_flags`. `openai_tool_specs()` turns them into OpenAI-style
function definitions:

```json
{"type": "function",
 "function": {"name": "<tool name>",
              "description": "<the tool's docstring>",
              "parameters": "<the request model's JSON schema>"}}
```

The user is never a parameter: identity and entitlements come from the session. Two tools are not
offered to any model: `get_source` (what a citation opens) and `get_metric_history` (trend lines
for the Clients page). The follow-up agent offers only the current route's tools, and only the
`documents` route (`search_documents`) and the `news` route (`get_news`) use the agent.

### `call_tool`

`call_tool(user, name, arguments)` runs one tool call that a model asked for. `arguments` is a JSON
string.

- A name outside `AGENT_TOOLS` returns `unknown_tool`.
- Arguments that are not valid JSON, or not a JSON object, return `invalid_input`.
- Otherwise the named tool runs as `user`, through the same validation, entitlement filter and
  audit as any other call.

The two refusals above are returned before any tool runs, so they do not produce an audit row.
In the follow-up agent, `run_tool_call` additionally refuses tools outside the route and replaces
any `client_id` the model supplied with the session's client before calling `call_tool`.

---

## MCP server

`mcp_server/server.py` serves the read-only tools to any client of the Model Context Protocol
(MCP), a standard way for AI assistants to call external tools, for example Claude Desktop. It
uses the official Python MCP SDK (`mcp.server.lowlevel.Server`, named `client-briefing`) over the
**stdio** transport: the server reads requests on standard input and writes responses on standard
output.

**Running.** `make mcp` (or `python -m mcp_server.server`) starts the server, which then waits for
an MCP client. The README shows a Claude Desktop configuration.

**Tools.** Nine tools: the eight in `AGENT_TOOLS` plus `get_source`. Each is listed with:

- `name`: the tool's function name;
- `description`: the tool's docstring;
- `inputSchema`: the tool's Pydantic request schema with a required `user_id` string added as
  the first property (extra properties are not allowed);
- `annotations`: `readOnlyHint: true`.

The server also sends the instructions "Read-only tools over the client briefing data. Pass user_id
on every call; results are filtered by that user's entitlements."

**Calls.**

1. An unknown tool name returns `{"ok": false, "error": "unknown_tool"}`.
2. `user_id` is removed from the arguments and looked up in the `users` table; a missing or unknown
   ID returns `{"ok": false, "error": "unknown_user"}`.
3. Otherwise the tool runs as that user with the remaining arguments, through the same validation,
   entitlement filter and audit log as the web application. Passing `entitlements` as an argument
   is `invalid_input`.

The result is the `ToolResult` as JSON, returned both as one text content item and as
`structuredContent`; `isError` is true whenever `ok` is false. The refusals in steps 1 and 2
happen before any tool runs and leave no audit row.

**Not exposed.** `get_metric_history`; every write (`create_task`, conflict decisions, shares);
briefing generation; follow-up questions; the audit log; and the evaluation scorecard.

**Identity.** As with `X-User-Id`, the server does not authenticate `user_id`; it plays the role of
the session identity. See [Entitlement model](SECURITY.md#entitlement-model).
