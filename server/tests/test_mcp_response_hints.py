"""Tests for MCP mutation response hints."""

import db
from conftest import VALID_SPEC
from mcp_response_hints import build_hints


class TestProjectCreateHints:
    def test_project_create_suggests_tasks(self):
        project = db.create_project("Hint Project", "A" * 40)
        try:
            enriched = {**project, "docs_summary": db.get_docs_summary("project", project["id"])}
            warnings, next_steps = build_hints("project_create", enriched)
            assert not warnings
            assert any("task_create" in s for s in next_steps)
            assert any("project_snapshot" in s for s in next_steps)
        finally:
            db.delete_project(project["id"])


class TestTaskUpdateHints:
    def test_in_progress_suggests_progress_doc(self, task):
        warnings, next_steps = build_hints(
            "task_update",
            {**task, "status": "in_progress", "docs_summary": db.get_docs_summary("task", task["id"])},
            old={**task, "status": "pending"},
            arguments={"task_id": task["id"], "status": "in_progress"},
        )
        assert not warnings
        assert any("progress" in s for s in next_steps)

    def test_completed_without_closure_warns(self, task):
        db.update_task(task["id"], status="in_progress")
        warnings, next_steps = build_hints(
            "task_update",
            {
                **task,
                "status": "completed",
                "docs_summary": db.get_docs_summary("task", task["id"]),
                "subtask_stats": db.get_task_subtask_stats(task["id"]),
            },
            old={**task, "status": "in_progress"},
            arguments={"task_id": task["id"], "status": "completed"},
        )
        assert any("closure" in w.lower() for w in warnings)
        assert any("doc_task_update" in s for s in next_steps)

    def test_completed_subtask_suggests_parent_check(self, subtask):
        db.upsert_task_doc(subtask["id"], VALID_SPEC, "spec")
        db.update_task(subtask["id"], status="in_progress")
        parent = db.get_task(subtask["parent_id"])
        warnings, next_steps = build_hints(
            "task_update",
            {
                **subtask,
                "status": "completed",
                "parent_id": parent["id"],
                "docs_summary": db.get_docs_summary("task", subtask["id"]),
                "subtask_stats": db.get_task_subtask_stats(subtask["id"]),
            },
            old={**subtask, "status": "in_progress"},
            arguments={"task_id": subtask["id"], "status": "completed"},
        )
        assert any(parent["id"] in s for s in next_steps)


class TestDocUpdateHints:
    def test_spec_update_warns_once(self, task):
        warnings, next_steps = build_hints(
            "doc_task_update",
            {},
            arguments={"task_id": task["id"], "doc_type": "spec"},
        )
        assert any("once" in w.lower() for w in warnings)
        assert any("in_progress" in s for s in next_steps)

    def test_closure_suggests_complete(self, task):
        _, next_steps = build_hints(
            "doc_task_update",
            {},
            arguments={"task_id": task["id"], "doc_type": "closure"},
        )
        assert any("status=completed" in s for s in next_steps)


class TestCommentHints:
    def test_blocker_comment_suggests_status_update(self, task):
        _, next_steps = build_hints(
            "comment_add",
            {},
            arguments={
                "entity_type": "task",
                "entity_id": task["id"],
                "comment_type": "blocker",
            },
        )
        assert any("blocked" in s for s in next_steps)
