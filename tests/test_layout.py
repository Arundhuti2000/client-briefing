"""Phase 0 smoke test: every module in the repo layout imports cleanly."""

import importlib

import pytest

MODULES = [
    "data.generate_data",
    "app.db",
    "app.unify",
    "app.retrieval",
    "app.tools",
    "app.orchestrator",
    "app.llm",
    "app.validate",
    "app.audit",
    "eval.run_eval",
    "api.main",
]


@pytest.mark.parametrize("name", MODULES)
def test_module_imports(name):
    importlib.import_module(name)
