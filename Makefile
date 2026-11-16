# Run every target from the repo root with the virtualenv activated,
# or point at it directly:  make test PYTHON=.venv/Scripts/python
PYTHON ?= python

.PHONY: data load unify api web test eval

# Write the raw source files: data/raw/*.csv, data/raw/docs/, claims, trap answer key
data:
	$(PYTHON) -m data.generate_data

# Load data/raw/*.csv into briefing.db: stg_ tables as-is, then cleaned typed tables
load:
	$(PYTHON) -m app.load_structured

# Reload from data/raw, then resolve aliases, dedupe, flag stale/conflicting data, chunk docs
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
