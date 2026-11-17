# Operations

This guide covers installing, configuring, running and troubleshooting the Client Briefing Intelligence prototype on a single workstation. The system runs as a Python backend (FastAPI, served by uvicorn on port 8000) and a React frontend (Vite dev server on port 5173), over a SQLite database and an embedding index built from synthetic data by `make data` and `make unify`. Narrative text is written by a configurable chain of LLM providers, which can end in a template that needs no key or network; every answer is cached on disk and real requests can be capped. All commands are run from the repository root. The components themselves are described in `docs/ARCHITECTURE.md`; design rationale is in [DECISIONS.md](../DECISIONS.md).

**Contents**

- [Setup](#setup)
- [Configuration](#configuration)
- [Make commands](#make-commands)
- [LLM providers and fallback](#llm-providers-and-fallback)
- [Request budget and caching](#request-budget-and-caching)
- [Running the demo](#running-the-demo)
- [Troubleshooting](#troubleshooting)

## Setup

### Prerequisites

| Requirement | Notes |
| --- | --- |
| Python with `venv` | CI runs Python 3.14 (`.github/workflows/ci.yml`). |
| Node.js with npm | For the frontend in `web/`. |
| GNU make | Optional. Every target is a single command and can be run directly (see [Make commands](#make-commands)). |
| Network access | Needed for `pip install`, `npm install` and the first download of the embedding model `all-MiniLM-L6-v2` (about 90 MB, per `app/retrieval.py`). After that the model loads from the local copy. LLM providers other than `mock` also need network access, except a local Ollama server. |

### Installation

Windows PowerShell:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
npm --prefix web install
copy .env.example .env
```

macOS or Linux:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
npm --prefix web install
cp .env.example .env
```

`requirements.txt` includes `sentence-transformers`, which pulls in PyTorch. CI installs the CPU-only PyTorch build first (`pip install torch --index-url https://download.pytorch.org/whl/cpu`) so that pip does not fetch the CUDA build; the same step can be used locally before installing the requirements.

The copied `.env` sets `LLM_CHAIN=mock`, which needs no API key. `.env` is excluded from Git.

### Building the data and checking the installation

```bash
make data     # write the synthetic datasets into data/raw/
make unify    # build data/briefing.db and the embedding index
make test     # unit tests (temporary folders, template LLM only)
```

`make unify` downloads the embedding model on its first run. `make test` builds its own data in temporary folders and never touches `data/`.

## Configuration

`app/llm.py` loads `.env` from the repository root with python-dotenv when it is first imported. Variables already set in the process environment take precedence over `.env`, so a value set in the shell overrides the file for that process. Because `.env` is read at import, edits to it take effect only after the process (for example `make api`) is restarted.

| Variable | Default in code | Read by | Effect |
| --- | --- | --- | --- |
| `LLM_CHAIN` | `gemini,openrouter,ollama,mock` (`.env.example` sets `mock`) | `app/llm.py`, on every call | Providers to try, in order. Case-insensitive; duplicates and unknown names are ignored. |
| `GEMINI_API_KEY` | none | `app/llm.py`, `app/llm_check.py` | Required for `gemini`; when empty the provider is skipped. |
| `GEMINI_MODEL` | `gemini-3.5-flash-lite` | `app/llm.py` | First Gemini model. |
| `GEMINI_FALLBACK_MODEL` | empty | `app/llm.py` | Optional second Gemini model, tried with its own request after the first fails. |
| `OPENROUTER_API_KEY` | none | `app/llm.py`, `app/llm_check.py` | Required for `openrouter`; when empty the provider is skipped. |
| `OPENROUTER_MODELS` | empty | `app/llm.py` | Comma-separated model IDs. The first is requested; the rest travel in the same request as OpenRouter's own fallback list. When empty, the provider is skipped. |
| `OLLAMA_URL` | `http://localhost:11434` | `app/llm.py` | Base URL of a local Ollama server (`/api/chat`). |
| `OLLAMA_MODEL` | `llama3.1:8b` | `app/llm.py` | Ollama model name. |
| `LLM_TIMEOUT_SECONDS` | `30` | `app/llm.py`, once at import | Timeout for each provider call; a call that exceeds it fails and the chain moves on. |
| `LLM_REQUEST_BUDGET` | unset (no cap) | `app/llm.py`, before every request | Maximum number of real LLM requests for the process. Once used up, further requests are refused and the chain moves on. |
| `CACHE_REPLAY` | empty | `app/llm.py`, on every cache lookup | `any` also replays a cached briefing answer that passed the validator, even from a model no longer in `LLM_CHAIN`. |
| `EVAL_BREAK_ENTITLEMENTS` | unset | `eval/run_eval.py` | `1` switches the entitlement filter off inside the evaluation process only. Set by `make eval-break`; the app and API have no such switch. |
| `VITE_API_BASE` | `http://localhost:8000` | `web/src/api.ts` (Vite) | Base URL the frontend calls. Set in the shell before `make web`, or in a Vite env file in `web/` such as `web/.env.local` (excluded by `web/.gitignore`). |

Some processes set these variables themselves:

- `tests/conftest.py` forces `LLM_CHAIN=mock`, and CI sets `LLM_CHAIN: mock`, so tests and CI never call a real model.
- `make demo-check` (without `--generate`) sets `CACHE_REPLAY=any` and `LLM_REQUEST_BUDGET=0`.
- `make eval` sets `LLM_CHAIN` for each run and removes `CACHE_REPLAY` for template runs.

Two settings are fixed in code rather than configured: the API allows cross-origin requests only from `http://localhost:5173` (`api/main.py`), and the demo meeting date is `AS_OF_DATE` = 2026-11-18 (`app/wording.py`).

## Make commands

Run every target from the repository root with the virtual environment activated, or pass the interpreter explicitly, for example `make test PYTHON=.venv/Scripts/python`. In the table, `python` stands for the Makefile's `$(PYTHON)`.

| Target | Command it runs | What it does | Writes |
| --- | --- | --- | --- |
| `make data` | `python -m data.build_app_data` | Writes every dataset the app shows: dev, dev2, held-out and the red-team documents. | `data/raw/`, `data/extracted_claims.json`, `data/planted_traps.json`, `data/dev2/`, `data/holdout/` |
| `make dev2` | `python -m data.generate_dev2` | Writes the dev2 dataset on its own, for inspection. | `data/dev2/` |
| `make holdout` | `python -m data.generate_holdout` | Writes the held-out dataset on its own. | `data/holdout/` |
| `make load` | `python -m app.load_structured` | Recreates the database from `data/raw/*.csv`: staging tables, then cleaned typed tables. Does not run unification. | `data/briefing.db` |
| `make unify` | `python -m app.unify` | Reloads from `data/raw`, then merges, resolves, dedupes, flags, chunks and embeds; prints a summary of merges, unattached references and flags. | `data/briefing.db`, `data/embeddings.npy`, `data/embeddings_index.json` |
| `make briefing` | `python -m app.orchestrator --client "$(CLIENT)" --user $(USER_ID)` | Prints one briefing as Markdown; provider notes go to stderr as `warning:` lines. | Audit rows; LLM cache |
| `make api` | `python -m uvicorn api.main:app --reload --port 8000` | Starts the API with auto-reload on code changes. | Audit rows, decisions, shares, tasks; LLM cache |
| `make web` | `npm --prefix web run dev` | Starts the Vite dev server. | None |
| `make test` | `python -m pytest` | Runs the unit tests in `tests/` against temporary data. | None in `data/` |
| `make eval` | `python -m eval.run_eval` | Scorecards on the dev, dev2 and held-out datasets (each rebuilt in a temporary folder) with the template LLM, then the quality-metrics report. Exits with code 1 if a zero-tolerance check fails. | `eval/last_run.json` |
| `make eval-break` | `python -m eval.run_eval` with `EVAL_BREAK_ENTITLEMENTS=1` | The evaluation with the entitlement filter switched off in that process; restricted leakage must fail and the run must exit non-zero. | `eval/history/eval_break.json` only |
| `make eval-real` | `python -m eval.run_eval --real` | As `make eval`, then the dev cases again through the configured `LLM_CHAIN` (skipped when the chain is only `mock`). | `eval/last_run.json`, `eval/history/eval_real.json`; LLM cache |
| `make results` | `python -m eval.report_md` | Rewrites the text between the results markers in `README.md` and in `docs/EVALUATION.md` (Current results) from the saved reports, and the key numbers of a `PRESENTATION.md` in the root, if one exists. | `README.md`, `docs/EVALUATION.md` |
| `make llm-check` | `python -m app.llm_check` | Sends one small request to each configured provider and prints which work. | None |
| `make demo-check` | `python -m app.demo_check` | Replays the demo paths from the cache with zero requests; prints PASS or FAIL per path; exits with code 1 on any FAIL. | Audit rows |
| `make mcp` | `python -m mcp_server.server` | Serves the read-only tools as an MCP server over stdio. | Audit rows |

Make variables:

| Variable | Default | Used by |
| --- | --- | --- |
| `CLIENT` | `C001` | `make briefing`: a client ID, name or alias, for example `CLIENT=NWC` or `CLIENT=Helios` |
| `USER_ID` | `u2` | `make briefing`: the user whose entitlements apply |
| `PYTHON` | `python` | Every Python target |

`make unify` already reloads the raw files, so `make load` is only needed to inspect the cleaned tables before unification. The scorecards and their interpretation are described in [EVALUATION.md](EVALUATION.md#scorecard).

## LLM providers and fallback

### Choosing a chain

`LLM_CHAIN` lists providers in the order they are tried. Typical settings:

| Setting | Behaviour |
| --- | --- |
| `LLM_CHAIN=mock` | No key and no network. Narrative sections are written by the template from the evidence. The router's LLM tie-breaker is off, and document and news follow-up questions show their evidence instead of a written answer. |
| `LLM_CHAIN=gemini,mock` | Gemini writes the narrative; the template answers when Gemini is unavailable. |
| `LLM_CHAIN=gemini,openrouter,ollama,mock` | The default when the variable is unset. |

Keeping `mock` last guarantees that a briefing always renders. Without it, a briefing whose providers all fail shows each section's evidence as plain bullets.

### Keys and free tiers

| Provider | Setup | Notes from the repository |
| --- | --- | --- |
| `gemini` | Set `GEMINI_API_KEY`. `GEMINI_MODEL` defaults to `gemini-3.5-flash-lite`; `GEMINI_FALLBACK_MODEL` is empty unless set. | The free tier allowed about 20 requests a day (README, D79); the in-process limit is 4 calls a minute. |
| `openrouter` | Set `OPENROUTER_API_KEY` and `OPENROUTER_MODELS`. | List only `:free` models: a free model that falls back to a paid one is billed at the paid price. Free models allow 50 requests a day without credits (`.env.example`). A 402 (out of credits) moves the request down the chain. In-process limit: 10 calls a minute. |
| `ollama` | Run an Ollama server at `OLLAMA_URL` with `OLLAMA_MODEL` available. No key. | In-process limit: 60 calls a minute. |
| `mock` | Nothing. | The template; never sends a request. |

Free providers may log prompts. The data in this repository is synthetic; client data would need a contracted provider (README, "LLM providers").

### Checking providers

`make llm-check` sends one small request to `gemini` (using `GEMINI_MODEL` only), `openrouter` (one request with the whole `OPENROUTER_MODELS` list) and `ollama`, and reports `mock` as always available. For each provider it prints:

- the status: `OK`, `FAIL` (with the reason, for example rate limited, out of credits, server error or timeout) or `SKIP` (no key or no models configured);
- the model that answered, which for OpenRouter may be any model in the list;
- whether the reply was valid JSON and how long it took;
- whether the provider is in `LLM_CHAIN`.

The last line names the first working provider in the chain, which will write briefings. API keys are never printed. The check calls the providers directly: it bypasses the cache, the rate limiter and `LLM_REQUEST_BUDGET`, so each run spends one request per configured provider.

### Fallback in practice

A request moves down the chain on a missing key, missing models, HTTP 429 (after a 5-second wait and one retry), 402, 5xx, a timeout, any other error, or a used-up request budget. For briefings, sections that fail the validator twice are also sent to the next provider. The reasons are recorded as notes, for example `gemini skipped: no GEMINI_API_KEY`, `openrouter skipped: no models configured`, `<provider> <models> failed: <reason>`, `used the template` and `no provider answered`. The notes appear:

- in the API response, under `llm_runs[].notes`;
- in the Markdown export footer ("Narrative: ... (after: ...)");
- on stderr as `warning:` lines from `make briefing`.

Each section is labelled with who wrote it: the AI provider and model (only when a real model wrote it and every check passed), "Template (no AI)", "Computed by code · no AI", or "Source facts shown" when every draft failed validation.

## Request budget and caching

### The answer cache

Every real LLM answer that parses as a JSON object is stored in `.cache/llm/<prompt hash>/<provider>--<model>.json`. The hash covers the system prompt and the full prompt, so identical evidence replays the same answer at no cost and any change to the data, the wording code or the prompt produces a cache miss. A briefing answer is marked `validated` once all of its sections pass the validator. Deleting `.cache/llm/` (or one prompt folder) forces fresh requests. The cache is excluded from Git.

A cached answer is replayed only when its provider and model are configured in `LLM_CHAIN`, unless `CACHE_REPLAY=any` is set (see below). Router and follow-up answers are cached but never marked validated, so they replay only while the model that produced them remains in `LLM_CHAIN`.

### Capping requests with `LLM_REQUEST_BUDGET`

`LLM_REQUEST_BUDGET` caps the real requests a single process may send. Each request through the chain counts, including a retry after a 429. When the budget is used up, the next request is refused and the chain moves on, so briefings fall back to the template rather than spending more. Cache hits and the template cost nothing. The count starts at zero in each process: for `make api` it covers every briefing and question since the server started.

PowerShell (the variable stays set for the session until removed):

```powershell
$env:LLM_REQUEST_BUDGET = "5"
make eval-real
Remove-Item Env:LLM_REQUEST_BUDGET
```

bash:

```bash
LLM_REQUEST_BUDGET=5 make eval-real
```

The value can also be set in `.env`, which applies it to every process. `make eval` and `make demo-check` print the number of real requests sent. One request is not counted: when OpenRouter rejects the structured-output request as a bad request, the client repeats it in JSON mode, and that second HTTP call bypasses the counter. `make llm-check` is not counted either.

### Replaying with `CACHE_REPLAY=any`

With `CACHE_REPLAY=any`, a briefing whose evidence matches a validated cached answer is replayed even if the chain no longer contains that model, for example after switching `LLM_CHAIN` to `mock`. This gives a free and repeatable rehearsal. The evaluation never replays AI answers into its template scorecards; under `make eval-real` the setting applies only to the real-model run.

### Preparing a zero-request demo

1. Configure a real chain and its keys in `.env`.
2. Fill the cache once, with a cap:

   ```powershell
   $env:LLM_REQUEST_BUDGET = "10"
   python -m app.demo_check --generate
   Remove-Item Env:LLM_REQUEST_BUDGET
   ```

3. Verify the replay with `make demo-check`. It sets `CACHE_REPLAY=any` and `LLM_REQUEST_BUDGET=0`, so a cache miss shows as FAIL instead of spending a request. The paths are the briefings for Northwind as Sam (`u2`, `C001`), Helios as Alex (`u1`, `C002`) and Helios as Sam (`u2`, `C002`), and three follow-up questions on Northwind as Sam (`DEMO_QUESTIONS` in `app/demo_check.py`). A briefing path passes when every section sent to the LLM was written by a real model and, in replay, came from the cache with no request. A question path passes when it is answered, by code or by a real model, with no request in replay.
4. To make the running API behave the same way, start it with `CACHE_REPLAY=any` and `LLM_REQUEST_BUDGET=0` and the same `LLM_CHAIN` used in step 2 (follow-up answers replay only from models in the chain):

   ```powershell
   $env:CACHE_REPLAY = "any"; $env:LLM_REQUEST_BUDGET = "0"; make api
   ```

## Running the demo

### Starting the services

```bash
make api   # terminal 1
make web   # terminal 2
```

| Service | URL |
| --- | --- |
| Web application | http://localhost:5173 |
| API | http://localhost:8000 |
| Interactive API documentation | http://localhost:8000/docs |

The API loads the embedding model at startup so that the first briefing is not delayed. `data/briefing.db` must exist (`make data` and `make unify`). The endpoints are listed in [API.md](API.md#endpoints).

To work on the interface without spending requests, start the API with the template only:

```powershell
$env:LLM_CHAIN = "mock"; make api
```

### Demo users

`make data` creates six users. Entitlements decide what each may see; see [SECURITY.md](SECURITY.md#entitlement-model).

| User ID | Name | Role | Entitlements |
| --- | --- | --- | --- |
| `u1` | Alex Morgan | Senior coverage banker | `standard`, `restricted_deals` |
| `u2` | Sam Rivera | Analyst | `standard` |
| `u3` | Nadia Rahman | Coverage director | `standard`, `restricted_deals` |
| `u4` | Daniel Osei | Analyst | `standard` |
| `u5` | Sofia Marchetti | Managing director | `standard`, `restricted_deals` |
| `u6` | Kwame Mensah | Associate | `standard` |

Client names and aliases that resolve include `NWC`, `Helios`, `Arbor`, `HPF`, `Kestrel Aviation`, `Copperleaf`, `Vossberg`, `LRS` and `Cedar Hollow` (README). The datasets are described in [DATA.md](DATA.md#datasets).

### Deep links

The web application reads these query parameters:

| Parameter | Values | Effect |
| --- | --- | --- |
| `user` | A user ID; default `u2` | The user the page starts as |
| `client` | A client ID, name or alias | Resolves the client through the API and generates its briefing once |
| `step` | `gather`, `check`, `read`, `share`; default `gather` | The workspace step to open |
| `page` | `meetings`, `clients`, `health`, `evals`; default `meetings` | The page to open, and the page the workspace's back link returns to |

Examples: `http://localhost:5173/?user=u2&client=NWC&step=read` and `http://localhost:5173/?user=u1&client=Helios`.

### Walkthrough

The README's demo follows this path:

1. Switch the sidebar user to Sam Rivera.
2. On Meetings, search `NWC`; Northwind Capital Partners is found by its alias. Open it with **Review**.
3. **Gather** lists the sources read and what was cleaned up.
4. **Check** presents the two Northwind conflicts ("Who is the CFO?" and "Is the FX hedging deal still live?") as choices between two sources; **Suggested** marks the side the briefing uses. Decide both.
5. **Read** shows the briefing one section at a time; a numbered citation chip opens its source in the side panel. Ask a follow-up such as `Is the FX hedging deal still live?`; the answer shows its route, how the route was chosen, the tools called and who wrote it.
6. **Share** keeps Approve blocked until every conflict is decided; Approve then records the approval and creates the ticked follow-up tasks, and the briefing can be downloaded as Markdown.
7. Switch to Alex Morgan and open Helios Energy Group: the restricted M&A Advisory deal and its confidential note are present. Switch back to Sam: they are absent, with no count or hint.

Run `make demo-check` before a live demo (see [Preparing a zero-request demo](#preparing-a-zero-request-demo)).

### Command line and MCP

- `make briefing CLIENT=Helios USER_ID=u1` prints a briefing as Markdown without the web stack.
- `make mcp` starts the MCP server on stdio and waits for a client; configuration for an MCP client is described in [API.md](API.md#mcp-server). Every MCP call names a `user_id` and is filtered and audited like a web request.

## Troubleshooting

| Symptom | Likely cause | Resolution |
| --- | --- | --- |
| The web page shows "Cannot reach the API at http://localhost:8000". | The API is not running, `VITE_API_BASE` points elsewhere, the page was opened from an origin other than `http://localhost:5173` and CORS blocks it, or `data/briefing.db` has not been built, so the user list cannot load. | Start `make api`; check `VITE_API_BASE`; open exactly `http://localhost:5173` (not `127.0.0.1`); run `make data` and `make unify` if the database is missing. |
| `make api` or `make web` reports the port in use, or the web app opens on a port other than 5173. | Another process holds port 8000 or 5173. Vite moves to the next free port, which the API's CORS policy does not allow. | Stop the other process so the services use 8000 and 5173. |
| API calls return 401 "Send a known user ID in the X-User-Id header." | The header is missing (for example in `/docs`) or names a user not in the `users` table. | Send `X-User-Id` with one of `u1` to `u6`. |
| Requests fail, or tools return `data_unavailable`. | `data/briefing.db` or the embedding files are missing, or only `make load` was run, so the unification tables do not exist. | Run `make data` and `make unify`. |
| `make unify`, `make test` or `make api` pauses on first use. | The embedding model is being downloaded. | Allow network access once; later runs use the local copy. |
| Sections are labelled "Template (no AI)" although a real provider is configured. | Missing key (provider skipped), empty `OPENROUTER_MODELS`, a used-up `LLM_REQUEST_BUDGET`, or every provider failed. | Run `make llm-check`; read the run notes (see [Fallback in practice](#fallback-in-practice)). |
| Briefings load slowly. | The rate limiter is waiting (4 calls a minute for Gemini), a 429 triggered the 5-second backoff and retry, or calls are timing out after `LLM_TIMEOUT_SECONDS` before the chain moves on. | Reorder or shorten `LLM_CHAIN`, lower `LLM_TIMEOUT_SECONDS`, replay from the cache, or use `LLM_CHAIN=mock`. |
| A section shows "Source facts shown" with a retry note. | Its draft failed validation on the retry and on every later provider. | Expected safe behaviour. The technical reasons are in the section's `retry_errors` and in audit rows with tool `validator`. |
| Follow-up answers show "No AI answer · evidence shown" or "Couldn't summarize". | Document and news questions need a model; with `LLM_CHAIN=mock`, or when no model answers or the answer fails validation, the evidence is shown instead. | Configure a real provider. |
| An off-topic question is answered by document search instead of refused. | Without keywords or a clear meaning match, routing needs the LLM tie-breaker, which is off with `LLM_CHAIN=mock` (D46). | Expected in template mode. |
| The Evaluations page shows "No scorecard yet. Run make eval." | `eval/last_run.json` does not exist; it is excluded from Git. | Run `make eval`. Results are described in [EVALUATION.md](EVALUATION.md#current-results). |
| `make demo-check` reports FAIL. | A cache miss: the path was never generated, the data or prompts changed, or a follow-up's model is no longer in `LLM_CHAIN`. | Run `python -m app.demo_check --generate` with a real chain, then `make demo-check` again. |
| `make eval` exits with code 1. | A zero-tolerance check (restricted leakage, injection, red team) failed. | Read the `FAIL` lines in the terminal. For `make eval-break` this exit code is the expected result. |
| `make llm-check` shows `FAIL` for `openrouter` with status 402 ("out of credits"). | The account has no credits for a requested model. | List only `:free` models in `OPENROUTER_MODELS`. |
| `make llm-check` shows `FAIL` for `ollama`. | No Ollama server at `OLLAMA_URL`, or `OLLAMA_MODEL` is not available there. | Start the server and make the model available, or remove `ollama` from `LLM_CHAIN`. |
| A change to `.env` has no effect. | `.env` is read when the process starts. | Restart the process (for example `make api`). |

### Windows and PowerShell

- Activate the environment with `.venv\Scripts\Activate.ps1`, or skip activation and pass the interpreter to make: `make api PYTHON=.venv/Scripts/python`.
- Set variables with `$env:NAME = "value"`; they last for the PowerShell session. Remove them with `Remove-Item Env:NAME`. The bash form `NAME=value make api` does not work in PowerShell.
- Where make is unavailable, run the command from the [Make commands](#make-commands) table directly. For `make eval-break`: `$env:EVAL_BREAK_ENTITLEMENTS = "1"; python -m eval.run_eval; Remove-Item Env:EVAL_BREAK_ENTITLEMENTS`.
- `make briefing` and the evaluation switch standard output to UTF-8, so characters such as "⚠" survive redirection to a file.
- `copy .env.example .env` creates the configuration file; `.env` holds API keys and must not be committed.

### Rebuilding the data

`make data && make unify` regenerates the raw files and recreates `data/briefing.db` from scratch. Because the audit log, conflict decisions, shares and follow-up tasks are stored in that database, a rebuild resets all of them (see [SECURITY.md](SECURITY.md#audit-log)). Browser-side step progress is kept in `localStorage` and is not reset; the Meetings list can show earlier progress until a briefing is reopened, at which point decisions and the latest share are re-read from the API. Clearing the site data in the browser removes it. The LLM cache is keyed by the prompt, so it remains valid when a rebuild produces identical evidence.
