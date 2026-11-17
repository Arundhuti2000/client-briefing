# Client Briefing Intelligence

Builds a pre-meeting client briefing from messy CRM data, metrics, notes and news.
Code decides what's true; the LLM only explains it, and code checks the explanation.
See [SPEC.md](SPEC.md) for the full design.

## Setup

```
python -m venv .venv
.venv\Scripts\Activate.ps1        # Windows PowerShell (macOS/Linux: source .venv/bin/activate)
pip install -r requirements.txt
npm --prefix web install
copy .env.example .env            # LLM_CHAIN=mock works with no API key
```

## Commands

Run from the repo root with the venv activated.

| Command      | What it does                                           |
| ------------ | ------------------------------------------------------ |
| `make data`  | Write all the data the app shows to `data/raw/`: dev, dev2 and held-out clients, red-team documents |
| `make dev2`  | Write dev2 (held-out round 1, now development data) to `data/dev2/` |
| `make holdout` | Write the held-out dataset (round 2) to `data/holdout/` |
| `make load`  | Load the raw CSVs into `briefing.db` and clean them    |
| `make unify` | Resolve aliases, dedupe, flag stale/conflicting data   |
| `make briefing CLIENT=NWC USER_ID=u2` | Print one briefing as Markdown   |
| `make api`   | Start the FastAPI backend on http://localhost:8000     |
| `make web`   | Start the React frontend on http://localhost:5173      |
| `make test`  | Run unit tests                                         |
| `make eval`  | Scorecard on dev and held-out data, then the quality metrics report (template, no AI) |
| `make eval-real` | The same, then again with the LLM chain in `.env` (adds faithfulness) |
| `make eval-break` | The eval with the entitlement filter off: Restricted leakage must FAIL |
| `make llm-check` | Ping each LLM provider and show which ones work    |
| `make mcp`   | Start the read-only tools as an MCP server (stdio)     |

## Run the briefing workspace

```
make data      # once
make unify     # once (also after changing the data)
make api       # terminal 1: http://localhost:8000 (API docs at /docs)
make web       # terminal 2: http://localhost:5173
```

Pick a user (Alex Morgan, Nadia Rahman and Sofia Marchetti may see restricted deals; Sam Rivera,
Daniel Osei and Kwame Mensah may not), type a client (`NWC`, `Helios`, `Arbor`, `HPF`,
`Kestrel Aviation`, `Copperleaf`, `Vossberg`, `LRS`, `Cedar Hollow`), and press
**Generate briefing**. Click any citation chip to open its source. Deep link (a demo backup):
`http://localhost:5173/?user=u1&client=Helios`.

For UI work without spending requests, start the API with the template only:
`$env:LLM_CHAIN="mock"; make api` (PowerShell).

## Ask a follow-up

In a briefing's Read step, type a question ("Who is the CFO?", "What did Raj Patel say about FX
hedging?"). The router sends it to one route: numbers and records are answered by code from SQL,
documents and news by a short tool-calling loop (at most 3 AI steps) whose answer must pass the
validator. Under each answer you see the route, how it was chosen, the tools called and who wrote it.
Instructions or off-topic questions are refused. API: `POST /briefings/{client_id}/ask`.

## Evaluation

`make eval` builds fresh copies of the data in temp folders (it never reads `data/`), then:

1. **Scorecard** on three datasets, side by side:
   - **dev** (`eval/golden.yaml`): Northwind, Helios, Arbor. The rules were built on it.
   - **dev2** (`eval/dev2/golden.yaml`): Harbor & Pine, Kestrel Aviation, Copperleaf Dental.
     It was held-out round 1: scored once (`eval/history/holdout_round1.json`), then used to fix
     the four gaps it found, so it is now development data and a regression test.
   - **holdout** (`eval/holdout/golden.yaml`): round 2, Vossberg, Lattice Ridge, Cedar Hollow.
     Never used to change anything; its first result is in `eval/history/`.

   Each held-out set plants the same kinds of trap as the dev data, in different forms, with
   realistic emails, notes and news, plus controls that must not be flagged. See
   [DECISIONS.md](DECISIONS.md) for every decision and the held-out history. Restricted leakage, injection and the red team are zero-tolerance: one
   failure exits non-zero. Cost per briefing (LLM requests, tokens, cache hits) is reported.
2. **Quality metrics report** (`eval/quality.py`), dev | holdout:
   - Retrieval: Precision@5, Recall@5, MRR and nDCG@5 for BM25, vector and hybrid, with the
     entitlement filter on, from hand-labelled questions (`eval/retrieval_set.yaml`,
     `eval/holdout/retrieval_set.yaml`). The labels should be reviewed.
   - Detectors on 200+ generated perturbations (aliases, typos, suffixes, case, look-alikes,
     true conflicts and near-misses): precision, recall, F1, and every false positive and negative.
   - Router: accuracy and a confusion table on 36 labelled questions (`eval/router_set.yaml`).
   - Faithfulness of AI-written bullets (claims vs the evidence they cite, validator rejection
     rate). Template mode writes no AI bullets, so this needs `make eval-real`.
   - A short "What this does and doesn't prove" note.

The result is saved to `eval/last_run.json` and shown on the **Evaluations** page.

- **Red team** (`eval/redteam/`, see [eval/REDTEAM.md](eval/REDTEAM.md)): hidden instructions in a
  meeting note, a news item and an email footer, plus Sam calling `GET /sources/<restricted id>`
  directly (must be refused).
- **`make eval-break`** switches the entitlement filter off inside the eval process only, so
  Restricted leakage shows FAIL and the run exits non-zero. It proves the check can fail. It does
  not overwrite `eval/last_run.json`.
- **CI** (`.github/workflows/ci.yml`) runs `make test` and `make eval` in mock mode on every push.

## MCP server (Claude Desktop)

`mcp_server/server.py` exposes the read-only tools (the eight briefing tools and `get_source`)
over the official Python MCP SDK, with the same Pydantic schemas and descriptions. Every call
takes a `user_id` (`u1` Alex, `u2` Sam): entitlements come from the users table, and each call
goes through the same validation, entitlement filters and audit log as the web app. Writes
(tasks, decisions, shares) are not exposed.

Run it on its own with `make mcp` (it waits for an MCP client on stdin). To use it from
Claude Desktop, open Settings > Developer > Edit Config and add (adjust the paths):

```json
{
  "mcpServers": {
    "client-briefing": {
      "command": "D:/ClientBriefingIntelligeence/client-briefing/.venv/Scripts/python.exe",
      "args": ["D:/ClientBriefingIntelligeence/client-briefing/mcp_server/server.py"]
    }
  }
}
```

Restart Claude Desktop; the tools appear under the tools menu. Try: "As user u2, what are
Helios Energy Group's opportunities?" and then the same as u1: Sam never sees the restricted
M&A deal. Every call shows up in the app's Audit log.

## LLM providers

`LLM_CHAIN` in `.env` lists the providers to try, in order (default `gemini,openrouter,ollama,mock`):

| Provider     | Settings                                                     | Notes |
| ------------ | ------------------------------------------------------------ | ----- |
| `gemini`     | `GEMINI_API_KEY`, `GEMINI_MODEL`, `GEMINI_FALLBACK_MODEL`    | One request per model |
| `openrouter` | `OPENROUTER_API_KEY`, `OPENROUTER_MODELS` (comma-separated)   | One request carries the whole list; OpenRouter falls through it and says which model answered |
| `ollama`     | `OLLAMA_URL`, `OLLAMA_MODEL`                                  | A local model, no key |
| `mock`       | none                                                          | The template: bullets copied from the evidence, no AI |

- A briefing is **one request** (all sections in one JSON answer). It moves to the next provider
  on a 429 (after one retry), 402 (no credits), 5xx, a timeout or a missing key.
- Every answer is checked by the validator. A section that fails is retried once on the same
  provider with the errors; if it fails again, the **next provider** writes it. After the last
  one, the section shows its source facts.
- Each section is labelled with the provider and the model that actually answered.
- Answers are cached in `.cache/llm/<evidence>/<provider>--<model>.json`, so regenerating a
  briefing is free. `CACHE_REPLAY=any` also replays any cached answer that passed the validator.
- OpenRouter: list only `:free` models (a free model that falls back to a paid one is billed at
  the paid price). Free models allow 50 requests a day without credits. Free providers may log
  prompts; the data here is synthetic, but production data would need a contracted provider.
- `make llm-check` sends one tiny request to each provider and prints which work and which model
  answered. API keys are never printed.
