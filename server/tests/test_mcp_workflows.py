"""Tests for composite MCP workflow tools."""

import time

import pytest

import db
from mcp_validation import ValidationError
from mcp_workflows import (
    pick_focus_project,
    run_session_context,
    run_task_begin_work,
    run_task_complete,
    run_task_record_progress,
    suggest_next_task,
)


@pytest.fixture
def agent():
    name = f"workflow-test-agent-{int(time.time() * 1000)}"
    a = db.onboard_agent(name, "Test Master")
    assert a is not None
    return a


class TestSessionContext:
    def test_suggest_next_task_prefers_in_progress(self, project):
        t1 = db.create_task(project["id"], "Pending task")
        t2 = db.create_task(project["id"], "Active task")
        db.update_task(t2["id"], status="in_progress")
        suggested = suggest_next_task(project["id"])
        assert suggested is not None
        assert suggested["id"] == t2["id"]
        assert suggested["status"] == "in_progress"

    def test_session_context_with_project(self, project, task):
        db.update_task(task["id"], status="in_progress")
        result = run_session_context(project_id=project["id"])
        assert result["focus_project_id"] == project["id"]
        assert "snapshot" in result
        assert result["suggested_next_task"]["id"] == task["id"]
        assert result["session_checklist"]

    def test_pick_focus_project_with_active_work(self, project):
        t = db.create_task(project["id"], "Work")
        db.update_task(t["id"], status="in_progress")
        projects = db.list_projects(status="active")
        assert pick_focus_project(projects) == project["id"]


class TestTaskBeginWork:
    def test_sets_pending_to_in_progress(self, project, agent):
        task = db.create_task(project["id"], "Begin me", "A" * 40)
        result = run_task_begin_work(
            task["id"],
            agent_name=agent["name"],
            master_name=agent["master_name"],
        )
        assert result["task"]["status"] == "in_progress"
        assert "checklist" in result
        assert result["spec"]["exists"] is False
        assert result["warnings"]

    def test_rejects_completed_task(self, project, agent, task):
        db.update_task(task["id"], status="completed")
        with pytest.raises(ValidationError) as exc:
            run_task_begin_work(
                task["id"],
                agent_name=agent["name"],
                master_name=agent["master_name"],
            )
        assert exc.value.code == "INVALID_STATUS"


class TestTaskRecordProgress:
    def test_writes_progress_doc(self, project, agent, task):
        db.update_task(task["id"], status="in_progress")
        content = "## Status\nWorking on it now. " + ("x" * 40)
        result = run_task_record_progress(
            task["id"],
            content,
            agent_name=agent["name"],
            master_name=agent["master_name"],
            comment="Quick update from session today",
        )
        assert result["progress_updated"] is True
        assert result["comment"] is not None
        meta = db.get_task_doc_meta(task["id"], "progress")
        assert meta is not None
        assert "Working on it" in meta["content"]


class TestTaskComplete:
    def test_completes_with_closure_note(self, project, agent, task):
        db.update_task(task["id"], status="in_progress")
        result = run_task_complete(
            task["id"],
            agent_name=agent["name"],
            master_name=agent["master_name"],
            closure_note="Delivered the feature successfully with tests passing",
        )
        assert result["task"]["status"] == "completed"
        assert result["closure_written"] is True
        closure = db.get_task_doc_meta(task["id"], "closure")
        assert closure is not None
        assert "## Summary" in closure["content"]

    def test_warns_on_incomplete_subtasks(self, project, agent, task, subtask):
        db.update_task(task["id"], status="in_progress")
        result = run_task_complete(
            task["id"],
            agent_name=agent["name"],
            master_name=agent["master_name"],
            closure_note="Closed parent even though child still open here",
        )
        assert any("subtasks" in w for w in result.get("warnings", []))
