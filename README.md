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
| `make data`  | Write the raw source files to `data/raw/` (synthetic)  |
| `make load`  | Load the raw CSVs into `briefing.db` and clean them    |
| `make unify` | Resolve aliases, dedupe, flag stale/conflicting data   |
| `make briefing CLIENT=NWC USER_ID=u2` | Print one briefing as Markdown   |
| `make api`   | Start the FastAPI backend on http://localhost:8000     |
| `make web`   | Start the React frontend on http://localhost:5173      |
| `make test`  | Run unit tests                                         |
| `make eval`  | Print the evaluation scorecard (template, no AI)       |
| `make eval-real` | The same, then again with the LLM chain in `.env`  |
| `make llm-check` | Ping each LLM provider and show which ones work    |

## Run the briefing workspace

```
make data      # once
make unify     # once (also after changing the data)
make api       # terminal 1: http://localhost:8000 (API docs at /docs)
make web       # terminal 2: http://localhost:5173
```

Pick Sam or Alex, type a client (`NWC`, `Northwind Cap.`, `Helios`, `Arbor`), and press
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
