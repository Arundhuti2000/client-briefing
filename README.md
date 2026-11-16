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
copy .env.example .env            # LLM_PROVIDER=mock works with no API key
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
| `make eval`  | Print the evaluation scorecard                         |

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

The API uses `LLM_PROVIDER` from `.env`. With `gemini`, each new briefing costs 1–2 requests,
and regenerating it replays from `.cache/llm/` for free. For UI work without spending requests,
start the API with mock mode: `$env:LLM_PROVIDER="mock"; make api` (PowerShell).
