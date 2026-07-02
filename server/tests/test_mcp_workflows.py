"""Tests for composite MCP workflow tools."""

import time

import pytest

import db
from conftest import VALID_SPEC
from mcp_validation import ValidationError
from mcp_workflows import (
    list_available_tasks,
    run_session_context,
    run_task_begin_work,
    run_task_complete,
    run_task_record_progress,
)


@pytest.fixture
def agent():
    name = f"workflow-test-agent-{int(time.time() * 1000)}"
    a = db.onboard_agent(name, "Test Master")
    assert a is not None
    return a


class TestSessionContext:
    def test_without_project_id_lists_for_selection(self, project):
        result = run_session_context()
        assert result["mode"] == "select_project"
        assert "projects" in result
        assert any(p["id"] == project["id"] for p in result["projects"])
        assert "project_id" not in result
        assert "snapshot" not in result

    def test_lists_all_workable_tasks(self, project):
        t1 = db.create_task(project["id"], "Pending task")
        t2 = db.create_task(project["id"], "Active task")
        db.update_task(t2["id"], status="in_progress")
        available = list_available_tasks(project["id"])
        ids = {t["id"] for t in available}
        assert t1["id"] in ids
        assert t2["id"] in ids
        assert all(t["status"] in ("pending", "in_progress") for t in available)

    def test_session_context_with_project_lists_available_tasks(self, project, task):
        db.update_task(task["id"], status="in_progress")
        other = db.create_task(project["id"], "Other pending")
        result = run_session_context(project_id=project["id"])
        assert result["mode"] == "project_session"
        assert "suggested_next_task" not in result
        ids = {t["id"] for t in result["available_tasks"]}
        assert task["id"] in ids
        assert other["id"] in ids

    def test_session_context_with_task_id_focuses(self, project, task):
        db.update_task(task["id"], status="in_progress")
        result = run_session_context(project_id=project["id"], task_id=task["id"])
        assert result["task_id"] == task["id"]
        assert result["focused_task"]["task"]["id"] == task["id"]
        assert "spec" in result["focused_task"]

    def test_task_id_wrong_project_raises(self, project, task):
        other = db.create_project("Other", "A" * 40)
        try:
            with pytest.raises(ValidationError) as exc:
                run_session_context(project_id=other["id"], task_id=task["id"])
            assert exc.value.field == "task_id"
        finally:
            db.delete_project(other["id"])

    def test_available_tasks_include_description(self, project):
        desc = "Implement the payment gateway integration with Stripe"
        task = db.create_task(project["id"], "Payments", desc)
        available = list_available_tasks(project["id"])
        entry = next(t for t in available if t["id"] == task["id"])
        assert entry["description"] == desc

    def test_is_yours_on_available_tasks_with_api_key(self, project, agent):
        task = db.create_task(project["id"], "Agent task", "A" * 40)
        db.upsert_task_doc(task["id"], VALID_SPEC, "spec")
        other = db.create_task(project["id"], "Other task", "B" * 40)
        db.upsert_task_doc(other["id"], VALID_SPEC, "spec")
        run_task_begin_work(
            task["id"],
            agent_name=agent["name"],
            master_name=agent["master_name"],
        )
        result = run_session_context(project_id=project["id"], agent_name=agent["name"])
        assert "my_tasks" not in result
        by_id = {t["id"]: t for t in result["available_tasks"]}
        assert by_id[task["id"]]["is_yours"] is True
        assert by_id[other["id"]]["is_yours"] is False

    def test_is_yours_omitted_without_agent(self, project, task):
        result = run_session_context(project_id=project["id"])
        entry = next(t for t in result["available_tasks"] if t["id"] == task["id"])
        assert "is_yours" not in entry

    def test_session_context_unknown_project_raises(self):
        with pytest.raises(ValidationError) as exc:
            run_session_context(project_id="nonexistent-project-id")
        assert exc.value.code == "NOT_FOUND"
        assert exc.value.field == "project_id"


class TestTaskBeginWork:
    def test_sets_pending_to_in_progress(self, project, agent):
        task = db.create_task(project["id"], "Begin me", "A" * 40)
        db.upsert_task_doc(task["id"], VALID_SPEC, "spec")
        result = run_task_begin_work(
            task["id"],
            agent_name=agent["name"],
            master_name=agent["master_name"],
        )
        assert result["task"]["status"] == "in_progress"
        assert "checklist" in result
        assert result["spec"]["exists"] is True
        assert not result["warnings"]

    def test_rejects_task_without_spec(self, project, agent):
        task = db.create_task(project["id"], "No spec", "A" * 40)
        with pytest.raises(ValidationError) as exc:
            run_task_begin_work(
                task["id"],
                agent_name=agent["name"],
                master_name=agent["master_name"],
            )
        assert exc.value.code == "TRANSITION_BLOCKED"
        assert exc.value.remediation

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
        db.upsert_task_doc(task["id"], VALID_SPEC, "spec")
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

    def test_blocks_parent_with_active_subtasks(self, project, agent, task, subtask):
        db.upsert_task_doc(task["id"], VALID_SPEC, "spec")
        db.upsert_task_doc(subtask["id"], VALID_SPEC, "spec")
        db.update_task(task["id"], status="in_progress")
        with pytest.raises(ValidationError) as exc:
            run_task_complete(
                task["id"],
                agent_name=agent["name"],
                master_name=agent["master_name"],
                closure_note="Closed parent even though child still open here",
            )
        assert exc.value.code == "TRANSITION_BLOCKED"
        assert exc.value.remediation
