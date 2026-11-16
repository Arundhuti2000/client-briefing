# Run every target from the repo root with the virtualenv activated,
# or point at it directly:  make test PYTHON=.venv/Scripts/python
PYTHON ?= python

.PHONY: data unify api web test eval

# Phase 1: build briefing.db and data/docs/*.json with the planted traps
data:
	$(PYTHON) -m data.generate_data

# Phase 2: resolve aliases, dedupe, flag stale/conflicting data, index docs
unify:
	$(PYTHON) -m app.unify

# FastAPI backend on http://localhost:8000 (endpoints built in Phase 5)
api:
	$(PYTHON) -m uvicorn api.main:app --reload --port 8000

# React frontend on http://localhost:5173 (first time: npm --prefix web install)
web:
	npm --prefix web run dev

# Unit tests in tests/
test:
	$(PYTHON) -m pytest

# Phase 6: print the evaluation scorecard
eval:
	$(PYTHON) -m eval.run_eval
