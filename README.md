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
| `make api`   | Start the FastAPI backend on http://localhost:8000     |
| `make web`   | Start the React frontend on http://localhost:5173      |
| `make test`  | Run unit tests                                         |
| `make eval`  | Print the evaluation scorecard                         |
