"""Tests for MCP validation and enrichment."""

import os
import pytest

import db
import mcp_validation as v
from mcp_validation import ValidationError


class TestValidation:
    def test_project_create_requires_description(self):
        with pytest.raises(ValidationError) as exc:
            v.validate_project_create({"name": "Test", "description": "short"})
        assert exc.value.field == "description"

    def test_project_create_valid(self):
        result = v.validate_project_create({
            "name": "My Project",
            "description": "A" * 40,
        })
        assert result["name"] == "My Project"

    def test_task_create_requires_description(self):
        with pytest.raises(ValidationError):
            v.validate_task_create({
                "title": "Task",
                "description": "too short",
            })

    def test_spec_requires_sections(self):
        with pytest.raises(ValidationError):
            v.validate_doc_content("A" * 100, "spec")

    def test_spec_valid(self):
        content = "## Objective\nDo thing\n## Acceptance Criteria\n- [ ] done"
        assert v.validate_doc_content(content + "x" * 50, "spec")

    def test_status_change_requires_reason(self, project):
        with pytest.raises(ValidationError):
            v.validate_project_update({"status": "archived"}, project)

    def test_blocked_requires_reason(self, task):
        with pytest.raises(ValidationError):
            v.validate_task_update(
                {"status": "blocked"},
                task,
                has_closure_doc=False,
            )


class TestEnrichment:
    def test_get_docs_summary(self, project):
        db.upsert_project_doc(project["id"], "## Objective\nx\n## Acceptance Criteria\n- [ ]", "spec")
        summary = db.get_docs_summary("project", project["id"])
        assert summary["spec"]["exists"] is True
        assert summary["progress"]["exists"] is False

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
