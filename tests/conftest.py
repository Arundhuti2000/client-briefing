"""Shared test fixtures."""

import os

os.environ["LLM_CHAIN"] = "mock"  # tests never call a real model, whatever .env says

import pytest  # noqa: E402

from app import load_structured, unify  # noqa: E402
from data import generate_data as gd  # noqa: E402


@pytest.fixture(scope="session")
def generated(tmp_path_factory):
    """Write the raw files and load them into SQLite once, in a temp folder.
    Same steps as `make data` + `make load`; tests never touch data/."""
    out_dir = tmp_path_factory.mktemp("data")
    gd.generate(out_dir)
    load_structured.load(out_dir)
    return out_dir


@pytest.fixture(scope="session")
def unified(tmp_path_factory):
    """Same as `make data` + `make unify`, in a separate temp folder (unify changes the tables)."""
    out_dir = tmp_path_factory.mktemp("unified")
    gd.generate(out_dir)
    unify.run(out_dir)
    return out_dir
