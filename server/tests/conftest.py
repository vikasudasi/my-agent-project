"""
Test fixtures for AI Task Management System.

Uses a separate test database (task_manager_test.db) so production data
is never touched during test runs.
"""

import os
import sys
import tempfile

import pytest

# Ensure we can import from server/
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Override DB_PATH to a temp file BEFORE importing db
from db import DB_DIR

TEST_DB_PATH = os.path.join(DB_DIR, "task_manager_test.db")

# Monkey-patch DB_PATH before any db functions are called
import db as db_module
db_module.DB_PATH = TEST_DB_PATH


# ---------------------------------------------------------------------------
# Session-scoped: init schema once, clean up at end
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session", autouse=True)
def _test_db():
    """Initialize the test database schema once per test session."""
    # Ensure a clean slate
    if os.path.exists(TEST_DB_PATH):
        os.remove(TEST_DB_PATH)
    for suffix in ("-wal", "-shm"):
        path = TEST_DB_PATH + suffix
        if os.path.exists(path):
            os.remove(path)

    db_module.init_db()
    yield
    # Clean up after session
    if os.path.exists(TEST_DB_PATH):
        os.remove(TEST_DB_PATH)
    for suffix in ("-wal", "-shm"):
        path = TEST_DB_PATH + suffix
        if os.path.exists(path):
            os.remove(path)


# ---------------------------------------------------------------------------
# Fixtures for sample data
# ---------------------------------------------------------------------------

@pytest.fixture
def project():
    """Create a sample project and yield its dict. Deleted after test."""
    p = db_module.create_project("Test Project", "A project for testing")
    yield p
    db_module.delete_project(p["id"])


@pytest.fixture
def task(project):
    """Create a sample root-level task and yield its dict."""
    t = db_module.create_task(project["id"], "Test Task", "A task for testing")
    yield t
    try:
        db_module.delete_task(t["id"])
    except Exception:
        pass


@pytest.fixture
def subtask(task):
    """Create a sample subtask and yield its dict."""
    s = db_module.create_task(
        task["project_id"], "Sub Task", "A subtask for testing",
        parent_id=task["id"]
    )
    yield s
    try:
        db_module.delete_task(s["id"])
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Auth fixture
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def api_key() -> str:
    """Create a test agent and return its API key for use in CLI tests."""
    agent = db_module.onboard_agent("test-agent", "Test Master")
    assert agent is not None, "Failed to onboard test agent"
    return agent["api_key"]