# Run every target from the repo root with the virtualenv activated,
# or point at it directly:  make test PYTHON=.venv/Scripts/python
PYTHON ?= python

.PHONY: data load unify briefing api web test eval eval-real

# Which briefing `make briefing` prints: CLIENT is an ID, name or alias; USER_ID is u1 or u2.
# (Not "AS" or "USER": make predefines AS as the assembler, and USER is a shell variable.)
CLIENT ?= C001
USER_ID ?= u2

# Write the raw source files: data/raw/*.csv, data/raw/docs/, claims, trap answer key
data:
	$(PYTHON) -m data.generate_data

# Load data/raw/*.csv into briefing.db: stg_ tables as-is, then cleaned typed tables
load:
	$(PYTHON) -m app.load_structured

# Reload from data/raw, then resolve aliases, dedupe, flag stale/conflicting data, chunk docs
unify:
	$(PYTHON) -m app.unify

# Phase 4: print one briefing as Markdown, e.g.  make briefing CLIENT=Helios USER_ID=u1
briefing:
	$(PYTHON) -m app.orchestrator --client "$(CLIENT)" --user $(USER_ID)

# FastAPI backend on http://localhost:8000 (endpoints built in Phase 5)
api:
	$(PYTHON) -m uvicorn api.main:app --reload --port 8000

# React frontend on http://localhost:5173 (first time: npm --prefix web install)
web:
	npm --prefix web run dev

# Unit tests in tests/
test:
	$(PYTHON) -m pytest

# Phase 6: the scorecard on the golden set, mock LLM (deterministic, free).
# Exits non-zero if restricted leakage or injection is above zero.
eval:
	$(PYTHON) -m eval.run_eval

# The same, then again with the LLM in .env (cached answers cost no requests)
eval-real:
	$(PYTHON) -m eval.run_eval --real
