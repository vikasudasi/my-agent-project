"""
Integration tests for cli.py — the command-line interface.

Tests JSON output format, error handling, and shell-scripting
conventions (entity ID on stderr).
"""

import json
import os
import subprocess
import sys

import pytest

CLI_PATH = None
_PYTEST_API_KEY = None


def _run(*args: str, env: dict | None = None) -> subprocess.CompletedProcess:
    """Run a CLI command and return the CompletedProcess."""
    cmd = [sys.executable, str(CLI_PATH)] + list(args)
    full_env = None
    if env:
        full_env = {**os.environ, **env}
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=10,
        env=full_env,
    )


def _run_auth(*args: str) -> subprocess.CompletedProcess:
    """Run a CLI mutation command with the pytest API key."""
    return _run(*args, env={"TM_API_KEY": _PYTEST_API_KEY})


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session", autouse=True)
def _find_cli():
    """Find the path to cli.py and create a test agent for mutation tests."""
    import os
    global CLI_PATH
    CLI_PATH = os.path.join(os.path.dirname(__file__), "..", "cli.py")

    # Onboard a unique agent per session (onboard doesn't require auth)
    global _PYTEST_API_KEY
    import time
    agent_name = f"pytest-agent-{int(time.time())}"
    result = _run("agent", "onboard", "--name", agent_name, "--master", "Test")
    if result.returncode == 0:
        import json
        _PYTEST_API_KEY = json.loads(result.stdout)["api_key"]
    else:
        # Fallback: try env var
        _PYTEST_API_KEY = os.environ.get("TM_API_KEY", "")


@pytest.fixture
def project_id() -> str:
    """Create a project via CLI, yield its ID, delete it."""
    result = _run_auth("project", "create", "CLI Test Project", "--desc", "Created by CLI tests")
    data = json.loads(result.stdout)
    pid = data["id"]
    yield pid
    _run_auth("project", "delete", pid)


@pytest.fixture
def task_id(project_id) -> str:
    """Create a task via CLI, yield its ID."""
    result = _run_auth("task", "create", project_id, "CLI Test Task")
    data = json.loads(result.stdout)
    tid = data["id"]
    yield tid


# ======================================================================
# JSON Output Format
# ======================================================================

class TestJsonOutput:
    def test_project_create_output(self):
        result = _run_auth("project", "create", "JSON Test")
        data = json.loads(result.stdout)
        assert "id" in data
        assert data["name"] == "JSON Test"
        assert data["status"] == "active"
        _run_auth("project", "delete", data["id"])

    def test_project_list_output(self):
        result = _run("project", "list")
        data = json.loads(result.stdout)
        assert isinstance(data, list)

    def test_project_get_output(self, project_id):
        result = _run("project", "get", project_id)
        data = json.loads(result.stdout)
        assert data["id"] == project_id
        assert "total_tasks" in data
        assert "progress_pct" in data

    def test_project_update_output(self, project_id):
        result = _run_auth("project", "update", project_id, "--status", "completed")
        data = json.loads(result.stdout)
        assert data["status"] == "completed"

    def test_project_delete_output(self):
        result = _run_auth("project", "create", "Delete Me")
        data = json.loads(result.stdout)
        pid = data["id"]
        result = _run_auth("project", "delete", pid)
        data = json.loads(result.stdout)
        assert data["deleted"] is True

    def test_task_create_output(self, project_id):
        result = _run_auth("task", "create", project_id, "Task from CLI")
        data = json.loads(result.stdout)
        assert data["title"] == "Task from CLI"
        assert data["project_id"] == project_id
        assert data["status"] == "pending"

    def test_task_list_output(self, project_id, task_id):
        result = _run("task", "list", project_id)
        data = json.loads(result.stdout)
        assert isinstance(data, list)
        ids = [t["id"] for t in data]
        assert task_id in ids

    def test_task_get_output(self, task_id):
        result = _run("task", "get", task_id)
        data = json.loads(result.stdout)
        assert data["id"] == task_id

    def test_task_update_output(self, task_id):
        result = _run_auth("task", "update", task_id, "--status", "completed")
        data = json.loads(result.stdout)
        assert data["status"] == "completed"

    def test_task_delete_output(self, project_id):
        result = _run_auth("task", "create", project_id, "Delete via CLI")
        data = json.loads(result.stdout)
        tid = data["id"]
        result = _run_auth("task", "delete", tid)
        data = json.loads(result.stdout)
        assert data["deleted"] is True

    def test_doc_project_get_output(self, project_id):
        result = _run("doc", "project", "get", project_id)
        data = json.loads(result.stdout)
        assert data["project_id"] == project_id
        assert "content" in data

    def test_doc_project_set_output(self, project_id):
        result = _run_auth("doc", "project", "set", project_id, "# Hello from CLI")
        data = json.loads(result.stdout)
        assert data["updated"] is True

    def test_doc_task_get_output(self, task_id):
        result = _run("doc", "task", "get", task_id)
        data = json.loads(result.stdout)
        assert data["task_id"] == task_id

    def test_doc_task_set_output(self, task_id):
        result = _run_auth("doc", "task", "set", task_id, "# Task doc from CLI")
        data = json.loads(result.stdout)
        assert data["updated"] is True

    def test_db_init_output(self):
        result = _run("db", "path")
        data = json.loads(result.stdout)
        assert "db_path" in data

    def test_pretty_flag(self, project_id):
        """--pretty should produce valid, indented JSON."""
        result = _run("project", "get", project_id, "--pretty")
        data = json.loads(result.stdout)
        assert data["id"] == project_id
        assert "\n" in result.stdout


# ======================================================================
# Error Handling
# ======================================================================

class TestErrorHandling:
    def test_project_get_not_found(self):
        result = _run("project", "get", "nonexistent-id")
        assert result.returncode == 1
        data = json.loads(result.stderr)
        assert "error" in data

    def test_task_get_not_found(self):
        result = _run("task", "get", "nonexistent-id")
        assert result.returncode == 1
        data = json.loads(result.stderr)
        assert "error" in data

    def test_task_create_invalid_project(self):
        result = _run("task", "create", "nonexistent", "Task")
        assert result.returncode == 1
        data = json.loads(result.stderr)
        assert "error" in data

    def test_project_delete_not_found(self):
        result = _run("project", "delete", "nonexistent")
        assert result.returncode == 1
        data = json.loads(result.stderr)
        assert "error" in data

    def test_task_delete_not_found(self):
        result = _run("task", "delete", "nonexistent")
        assert result.returncode == 1
        data = json.loads(result.stderr)
        assert "error" in data

    def test_project_update_not_found(self):
        result = _run("project", "update", "nonexistent", "--name", "Nope")
        assert result.returncode == 1
        data = json.loads(result.stderr)
        assert "error" in data

    def test_task_update_not_found(self):
        result = _run("task", "update", "nonexistent", "--status", "completed")
        assert result.returncode == 1
        data = json.loads(result.stderr)
        assert "error" in data


# ======================================================================
# Shell Scripting Convention
# ======================================================================

class TestShellCapture:
    def test_project_create_id_on_stderr(self):
        """Entity ID should be printed to stderr for shell capture."""
        result = _run_auth("project", "create", "Shell Capture")
        data = json.loads(result.stdout)
        stderr_lines = result.stderr.strip().split("\n")
        assert stderr_lines[-1] == data["id"]
        _run_auth("project", "delete", data["id"])

    def test_task_create_id_on_stderr(self, project_id):
        """Task ID should be printed to stderr for shell capture."""
        result = _run_auth("task", "create", project_id, "Shell Capture Task")
        data = json.loads(result.stdout)
        stderr_lines = result.stderr.strip().split("\n")
        assert stderr_lines[-1] == data["id"]


# ======================================================================
# Edge Cases
# ======================================================================

class TestCLIEdgeCases:
    def test_help_does_not_error(self):
        result = _run("--help")
        assert result.returncode == 0

    def test_project_help(self):
        result = _run("project", "--help")
        assert result.returncode == 0

    def test_task_help(self):
        result = _run("task", "--help")
        assert result.returncode == 0