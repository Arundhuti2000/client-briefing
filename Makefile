# Run every target from the repo root with the virtualenv activated,
# or point at it directly:  make test PYTHON=.venv/Scripts/python
PYTHON ?= python

.PHONY: data dev2 holdout load unify briefing api web test eval eval-real eval-judge eval-break results llm-check demo-check mcp

# Which briefing `make briefing` prints: CLIENT is an ID, name or alias; USER_ID is u1 or u2.
# (Not "AS" or "USER": make predefines AS as the assembler, and USER is a shell variable.)
CLIENT ?= C001
USER_ID ?= u2

# Write every dataset the app shows into data/raw: the dev clients, dev2, the held-out
# clients and the red-team documents (make eval still scores each dataset on its own)
data:
	$(PYTHON) -m data.build_app_data

# dev2 (held-out round 1, now development data) to data/dev2/, for inspection
dev2:
	$(PYTHON) -m data.generate_dev2

# The held-out dataset, round 2, to data/holdout/ (never used to change anything)
holdout:
	$(PYTHON) -m data.generate_holdout

# Load data/raw/*.csv into briefing.db: stg_ tables as-is, then cleaned typed tables
load:
	$(PYTHON) -m app.load_structured

# Reload from data/raw, then resolve aliases, dedupe, flag stale/conflicting data, chunk docs
unify:
	$(PYTHON) -m app.unify

# Print one briefing as Markdown, e.g.  make briefing CLIENT=Helios USER_ID=u1
briefing:
	$(PYTHON) -m app.orchestrator --client "$(CLIENT)" --user $(USER_ID)

# FastAPI backend on http://localhost:8000 (endpoints in docs/API.md)
api:
	$(PYTHON) -m uvicorn api.main:app --reload --port 8000

# React frontend on http://localhost:5173 (first time: npm --prefix web install)
web:
	npm --prefix web run dev

# Unit tests in tests/
test:
	$(PYTHON) -m pytest

# The scorecard on the dev, dev2 and held-out golden sets, then the quality metrics
# report, mock LLM (deterministic, free). Exits non-zero if restricted leakage, injection
# or the red team is above zero. Saves eval/last_run.json for the Evaluations page.
eval:
	$(PYTHON) -m eval.run_eval

# The eval with the entitlement filter switched off (in the eval process only):
# Restricted leakage must FAIL and the run must exit non-zero. Proves the check works.
eval-break: export EVAL_BREAK_ENTITLEMENTS = 1
eval-break:
	$(PYTHON) -m eval.run_eval

# The same, then again with the LLM in .env (cached answers cost no requests)
eval-real:
	$(PYTHON) -m eval.run_eval --real

# LLM as judge: a judge model (JUDGE_CHAIN, else LLM_CHAIN) labels each AI-written claim in the
# dev briefings supported, unsupported or contradicted; code counts the labels. One request per
# briefing (cached); saves counts to eval/history/judge.json
eval-judge:
	$(PYTHON) -m eval.judge

# Write the results sections of README.md and docs/EVALUATION.md from the saved eval reports (no number typed by hand)
results:
	$(PYTHON) -m eval.report_md

# Ping each LLM provider (one tiny request each) and print which work
llm-check:
	$(PYTHON) -m app.llm_check

# Replay the demo's AI paths from the cache (0 requests) and print PASS/FAIL per path.
# Fill the cache once with: python -m app.demo_check --generate
demo-check:
	$(PYTHON) -m app.demo_check

# The read-only tools as an MCP server (stdio), e.g. for Claude Desktop
mcp:
	$(PYTHON) -m mcp_server.server
