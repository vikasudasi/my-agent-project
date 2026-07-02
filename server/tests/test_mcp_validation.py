"""Tests for MCP validation and enrichment."""

import pytest

import db
import mcp_validation as v
from mcp_validation import ValidationError

VALID_SPEC = (
    "## Objective\nBuild the feature\n## Acceptance Criteria\n- [ ] Done\n"
    + ("x" * 50)
)


class TestValidation:
    def test_project_create_requires_description(self):
        with pytest.raises(ValidationError) as exc:
            v.validate_project_create({
                "name": "Test",
                "description": "short",
                "initial_spec": VALID_SPEC,
            })
        assert exc.value.field == "description"

    def test_project_create_requires_initial_spec(self):
        with pytest.raises(ValidationError) as exc:
            v.validate_project_create({
                "name": "Test",
                "description": "A" * 40,
            })
        assert exc.value.field == "initial_spec"
        assert exc.value.remediation

    def test_project_create_valid(self):
        result = v.validate_project_create({
            "name": "My Project",
            "description": "A" * 40,
            "initial_spec": VALID_SPEC,
        })
        assert result["initial_spec"]

    def test_task_create_requires_description(self):
        with pytest.raises(ValidationError):
            v.validate_task_create({
                "title": "Task",
                "description": "too short",
                "initial_spec": VALID_SPEC,
            })

    def test_task_create_requires_initial_spec_for_subtasks(self):
        with pytest.raises(ValidationError) as exc:
            v.validate_task_create({
                "title": "Sub",
                "description": "A" * 40,
                "parent_id": "parent-id",
            })
        assert exc.value.field == "initial_spec"

    def test_spec_requires_sections(self):
        with pytest.raises(ValidationError):
            v.validate_doc_content("A" * 100, "spec")

    def test_spec_valid(self):
        assert v.validate_doc_content(VALID_SPEC, "spec")

    def test_status_change_requires_reason(self, project):
        with pytest.raises(ValidationError):
            v.validate_project_update({"status": "archived"}, project)

    def test_blocked_requires_reason(self, task):
        with pytest.raises(ValidationError):
            v.validate_task_update(
                {"status": "blocked"},
                task,
                has_closure_doc=False,
                has_spec_doc=True,
            )

    def test_failed_requires_reason(self, task):
        with pytest.raises(ValidationError):
            v.validate_task_update(
                {"status": "failed"},
                task,
                has_closure_doc=False,
                has_spec_doc=True,
            )

    def test_in_progress_requires_spec(self, task):
        with pytest.raises(ValidationError) as exc:
            v.validate_task_update(
                {"status": "in_progress"},
                task,
                has_closure_doc=False,
                has_spec_doc=False,
            )
        assert exc.value.code == "TRANSITION_BLOCKED"
        assert exc.value.remediation

    def test_completed_requires_closure(self, task):
        db.upsert_task_doc(task["id"], VALID_SPEC, "spec")
        with pytest.raises(ValidationError) as exc:
            v.validate_task_update(
                {"status": "completed"},
                task,
                has_closure_doc=False,
                has_spec_doc=True,
            )
        assert exc.value.field == "closure_note"

    def test_parent_complete_blocked_with_active_subtasks(self, project):
        parent = db.create_task(project["id"], "Parent", "A" * 40)
        db.upsert_task_doc(parent["id"], VALID_SPEC, "spec")
        child = db.create_task(project["id"], "Child", "A" * 40, parent_id=parent["id"])
        db.upsert_task_doc(child["id"], VALID_SPEC, "spec")
        with pytest.raises(ValidationError) as exc:
            v.validate_subtasks_allow_parent_complete(parent["id"])
        assert exc.value.code == "TRANSITION_BLOCKED"

    def test_parent_complete_allowed_when_subtasks_terminal(self, project):
        parent = db.create_task(project["id"], "Parent", "A" * 40)
        child = db.create_task(project["id"], "Child", "A" * 40, parent_id=parent["id"])
        db.update_task(child["id"], status="cancelled")
        v.validate_subtasks_allow_parent_complete(parent["id"])


class TestEnrichment:
    def test_get_docs_summary(self, project):
        db.upsert_project_doc(project["id"], VALID_SPEC, "spec")
        summary = db.get_docs_summary("project", project["id"])
        assert summary["spec"]["exists"] is True
        assert summary["progress"]["exists"] is False

    def test_subtask_stats_active_count(self, project):
        parent = db.create_task(project["id"], "Parent")
        db.create_task(project["id"], "Pending child", parent_id=parent["id"])
        db.create_task(project["id"], "Done child", parent_id=parent["id"])
        done = db.list_tasks(project["id"], parent_id=parent["id"])[1]
        db.update_task(done["id"], status="completed")
        stats = db.get_task_subtask_stats(parent["id"])
        assert stats["subtask_count"] == 2
        assert stats["subtasks_active"] == 1
        assert stats["subtasks_terminal"] == 1

    def test_get_task_tree_recursive(self, project):
        parent = db.create_task(project["id"], "Parent")
        child = db.create_task(project["id"], "Child", parent_id=parent["id"])
        grandchild = db.create_task(project["id"], "Grand", parent_id=child["id"])
        tree = db.get_task_tree(parent["id"])
        assert tree["id"] == parent["id"]
        assert len(tree["children"]) == 1
        assert tree["children"][0]["id"] == child["id"]
        assert len(tree["children"][0]["children"]) == 1
        assert tree["children"][0]["children"][0]["id"] == grandchild["id"]

    def test_count_comments(self, task):
        db.add_comment("task", task["id"], "Hello world comment here")
        assert db.count_comments("task", task["id"]) == 1
