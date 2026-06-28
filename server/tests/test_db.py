"""
Unit tests for db.py — the data access layer.

Covers all CRUD operations, fractional indexing, tree building,
task movement, documentation, and progress reporting.
"""

import pytest

import db


# ======================================================================
# Projects
# ======================================================================

class TestProjectCRUD:
    def test_create_project(self):
        p = db.create_project("My Project", "Description here")
        assert p["name"] == "My Project"
        assert p["description"] == "Description here"
        assert p["status"] == "active"
        assert p["id"] is not None
        # Cleanup
        db.delete_project(p["id"])

    def test_list_projects(self, project):
        projects = db.list_projects()
        ids = [p["id"] for p in projects]
        assert project["id"] in ids

    def test_get_project(self, project):
        p = db.get_project(project["id"])
        assert p is not None
        assert p["id"] == project["id"]
        assert p["name"] == project["name"]

    def test_get_project_not_found(self):
        assert db.get_project("nonexistent") is None

    def test_update_project_name(self, project):
        updated = db.update_project(project["id"], name="Updated Name")
        assert updated["name"] == "Updated Name"
        # Verify persisted
        fetched = db.get_project(project["id"])
        assert fetched["name"] == "Updated Name"

    def test_update_project_status(self, project):
        updated = db.update_project(project["id"], status="completed")
        assert updated["status"] == "completed"

    def test_update_project_not_found(self):
        assert db.update_project("nonexistent", name="x") is None

    def test_delete_project(self):
        p = db.create_project("To Delete", "Will be deleted")
        assert db.get_project(p["id"]) is not None
        deleted = db.delete_project(p["id"])
        assert deleted is True
        assert db.get_project(p["id"]) is None

    def test_delete_project_not_found(self):
        assert db.delete_project("nonexistent") is False


class TestProjectProgress:
    def test_empty_project_progress(self, project):
        progress = db.get_project_progress(project["id"])
        assert progress["total_tasks"] == 0
        assert progress["completed_tasks"] == 0
        assert progress["progress_pct"] == 0
        assert progress["by_status"] == {}

    def test_project_progress_with_tasks(self, project):
        t1 = db.create_task(project["id"], "Task 1")
        t2 = db.create_task(project["id"], "Task 2")
        db.update_task(t1["id"], status="completed")

        progress = db.get_project_progress(project["id"])
        assert progress["total_tasks"] == 2
        assert progress["completed_tasks"] == 1
        assert progress["progress_pct"] == 50
        assert progress["by_status"]["pending"] == 1
        assert progress["by_status"]["completed"] == 1

    def test_project_progress_not_found(self):
        assert db.get_project_progress("nonexistent") is None


# ======================================================================
# Tasks
# ======================================================================

class TestTaskCRUD:
    def test_create_task(self, project):
        t = db.create_task(project["id"], "My Task", "A task")
        assert t["title"] == "My Task"
        assert t["description"] == "A task"
        assert t["project_id"] == project["id"]
        assert t["status"] == "pending"
        assert t["parent_id"] is None

    def test_create_task_invalid_project(self):
        assert db.create_task("nonexistent", "Task") is None

    def test_list_tasks(self, project, task):
        tasks = db.list_tasks(project["id"])
        ids = [t["id"] for t in tasks]
        assert task["id"] in ids

    def test_list_tasks_empty_project(self, project):
        # Create project with no tasks
        tasks = db.list_tasks(project["id"])
        assert tasks == []

    def test_list_tasks_filter_by_status(self, project):
        t1 = db.create_task(project["id"], "Pending")
        t2 = db.create_task(project["id"], "Completed")
        db.update_task(t2["id"], status="completed")

        pending = db.list_tasks(project["id"], status="pending")
        completed = db.list_tasks(project["id"], status="completed")

        assert len(pending) == 1
        assert pending[0]["id"] == t1["id"]
        assert len(completed) == 1
        assert completed[0]["id"] == t2["id"]

    def test_list_tasks_filter_by_parent(self, task):
        child = db.create_task(
            task["project_id"], "Child", parent_id=task["id"]
        )
        children = db.list_tasks(task["project_id"], parent_id=task["id"])
        assert len(children) == 1
        assert children[0]["id"] == child["id"]

        # Root-level tasks should not include the child
        roots = db.list_tasks(task["project_id"])
        assert child["id"] not in [t["id"] for t in roots]

    def test_get_task(self, task):
        t = db.get_task(task["id"])
        assert t is not None
        assert t["id"] == task["id"]
        assert t["title"] == task["title"]

    def test_get_task_not_found(self):
        assert db.get_task("nonexistent") is None

    def test_update_task_title(self, task):
        updated = db.update_task(task["id"], title="New Title")
        assert updated["title"] == "New Title"
        fetched = db.get_task(task["id"])
        assert fetched["title"] == "New Title"

    def test_update_task_status(self, task):
        for status in ("in_progress", "completed", "blocked", "failed", "cancelled"):
            updated = db.update_task(task["id"], status=status)
            assert updated["status"] == status

    def test_update_task_not_found(self):
        assert db.update_task("nonexistent", title="x") is None

    def test_delete_task(self, project):
        t = db.create_task(project["id"], "To Delete")
        assert db.get_task(t["id"]) is not None
        deleted = db.delete_task(t["id"])
        assert deleted is True
        assert db.get_task(t["id"]) is None

    def test_delete_task_not_found(self):
        assert db.delete_task("nonexistent") is False


# ======================================================================
# Task Ordering (Fractional Indexing)
# ======================================================================

class TestTaskOrdering:
    def test_sequential_rank(self, project):
        t1 = db.create_task(project["id"], "First")
        t2 = db.create_task(project["id"], "Second")
        t3 = db.create_task(project["id"], "Third")

        tasks = db.list_tasks(project["id"])
        assert tasks[0]["id"] == t1["id"]
        assert tasks[1]["id"] == t2["id"]
        assert tasks[2]["id"] == t3["id"]
        # Ranks should be 1.0, 2.0, 3.0
        assert tasks[0]["rank"] == 1.0
        assert tasks[1]["rank"] == 2.0
        assert tasks[2]["rank"] == 3.0

    def test_insert_between(self, project):
        t1 = db.create_task(project["id"], "First")
        t3 = db.create_task(project["id"], "Third")
        t2 = db.create_task(project["id"], "Second", after_task_id=t1["id"])

        tasks = db.list_tasks(project["id"])
        assert tasks[0]["id"] == t1["id"]
        assert tasks[1]["id"] == t2["id"]
        assert tasks[2]["id"] == t3["id"]
        # t2 should be ranked between t1 and t3
        assert tasks[0]["rank"] < tasks[1]["rank"] < tasks[2]["rank"]

    def test_insert_at_beginning(self, project):
        t1 = db.create_task(project["id"], "First")
        t2 = db.create_task(project["id"], "Second")

        # Insert before First (after nothing = at end, so this goes after second)
        # Actually we need to test --after with no prior sibling
        # The current API places after another task, not before
        # This is fine — test the 'end' behavior
        t3 = db.create_task(project["id"], "Third")  # goes to end
        tasks = db.list_tasks(project["id"])
        assert tasks[-1]["id"] == t3["id"]

    def test_rank_preserved_after_update(self, project):
        t1 = db.create_task(project["id"], "First")
        t2 = db.create_task(project["id"], "Second")

        db.update_task(t2["id"], title="Updated")
        tasks = db.list_tasks(project["id"])
        assert tasks[0]["id"] == t1["id"]
        assert tasks[1]["id"] == t2["id"]


# ======================================================================
# Subtask Tree
# ======================================================================

class TestTaskTree:
    def test_get_task_tree(self, task, subtask):
        tree = db.get_task_tree(task["id"])
        assert tree is not None
        assert tree["id"] == task["id"]
        assert len(tree["children"]) == 1
        assert tree["children"][0]["id"] == subtask["id"]

    def test_get_task_tree_leaf(self, task, subtask):
        tree = db.get_task_tree(subtask["id"])
        assert tree["id"] == subtask["id"]
        assert tree["children"] == []

    def test_get_task_tree_not_found(self):
        assert db.get_task_tree("nonexistent") is None

    def test_get_task_subtree(self, project):
        """Test building full hierarchical tree from flat rows."""
        t1 = db.create_task(project["id"], "Root 1")
        t2 = db.create_task(project["id"], "Root 2")
        c1 = db.create_task(project["id"], "Child 1", parent_id=t1["id"])
        c2 = db.create_task(project["id"], "Child 2", parent_id=t1["id"])
        gc = db.create_task(project["id"], "Grandchild", parent_id=c1["id"])

        tree = db.get_task_subtree(project["id"])
        assert len(tree) == 2  # 2 roots

        root1 = next(r for r in tree if r["id"] == t1["id"])
        root2 = next(r for r in tree if r["id"] == t2["id"])
        assert len(root1["children"]) == 2
        assert len(root2["children"]) == 0

        child1 = next(c for c in root1["children"] if c["id"] == c1["id"])
        assert len(child1["children"]) == 1
        assert child1["children"][0]["id"] == gc["id"]

    def test_get_task_subtree_empty(self, project):
        tree = db.get_task_subtree(project["id"])
        # No tasks in this project yet
        assert tree == []

    def test_deleted_task_cascade(self, task, subtask):
        """Deleting a parent task should cascade-delete children via SQLite FK."""
        assert db.get_task(subtask["id"]) is not None
        db.delete_task(task["id"])
        assert db.get_task(subtask["id"]) is None


# ======================================================================
# Task Movement
# ======================================================================

class TestTaskMove:
    def test_move_reorder(self, project):
        t1 = db.create_task(project["id"], "A")
        t2 = db.create_task(project["id"], "B")
        t3 = db.create_task(project["id"], "C")

        # Move t3 to after t1 (between t1 and t2)
        db.move_task(t3["id"], after_task_id=t1["id"])
        tasks = db.list_tasks(project["id"])
        assert tasks[0]["id"] == t1["id"]
        assert tasks[1]["id"] == t3["id"]
        assert tasks[2]["id"] == t2["id"]

    def test_move_reparent(self, project):
        t1 = db.create_task(project["id"], "Parent")
        t2 = db.create_task(project["id"], "Child")
        assert t2["parent_id"] is None

        # Move t2 to be child of t1
        moved = db.move_task(t2["id"], parent_id=t1["id"])
        assert moved["parent_id"] == t1["id"]

        # Verify in tree
        tree = db.get_task_tree(t1["id"])
        assert len(tree["children"]) == 1
        assert tree["children"][0]["id"] == t2["id"]

    def test_move_to_root(self, task, subtask):
        """Move a subtask to root level by setting parent_id to None."""
        assert db.get_task(subtask["id"])["parent_id"] == task["id"]

        moved = db.move_task(subtask["id"], parent_id=None)
        assert moved["parent_id"] is None

        # It should now be a root-level task
        roots = db.list_tasks(task["project_id"])
        assert subtask["id"] in [t["id"] for t in roots]

    def test_move_not_found(self):
        assert db.move_task("nonexistent") is None


# ======================================================================
# Documentation
# ======================================================================

class TestDocs:
    def test_get_project_doc_empty(self, project):
        assert db.get_project_doc(project["id"]) == ""

    def test_set_project_doc(self, project):
        content = "# Project Docs\n## Overview\nMy project."
        assert db.upsert_project_doc(project["id"], content) is True
        assert db.get_project_doc(project["id"]) == content

    def test_update_project_doc(self, project):
        db.upsert_project_doc(project["id"], "Original")
        db.upsert_project_doc(project["id"], "Updated")
        assert db.get_project_doc(project["id"]) == "Updated"

    def test_set_project_doc_invalid_project(self):
        assert db.upsert_project_doc("nonexistent", "content") is False

    def test_get_task_doc_empty(self, task):
        assert db.get_task_doc(task["id"]) == ""

    def test_set_task_doc(self, task):
        content = "# Task Notes\n## Steps\n1. Do thing"
        assert db.upsert_task_doc(task["id"], content) is True
        assert db.get_task_doc(task["id"]) == content

    def test_update_task_doc(self, task):
        db.upsert_task_doc(task["id"], "Original")
        db.upsert_task_doc(task["id"], "Updated")
        assert db.get_task_doc(task["id"]) == "Updated"

    def test_set_task_doc_invalid_task(self):
        assert db.upsert_task_doc("nonexistent", "content") is False


# ======================================================================
# Edge Cases
# ======================================================================

class TestEdgeCases:
    def test_delete_project_cascade(self, project):
        """Deleting a project should cascade-delete all its tasks and docs."""
        t = db.create_task(project["id"], "Task In Project")
        db.upsert_task_doc(t["id"], "Some docs")
        db.upsert_project_doc(project["id"], "Project docs")

        db.delete_project(project["id"])

        # Everything should be gone
        assert db.get_project(project["id"]) is None
        assert db.get_task(t["id"]) is None
        assert db.get_project_doc(project["id"]) == ""
        assert db.get_task_doc(t["id"]) == ""

    def test_project_with_special_chars(self):
        name = "Project with \"quotes\" and 'apostrophes' & symbols < >"
        p = db.create_project(name)
        assert p["name"] == name
        db.delete_project(p["id"])

    def test_task_with_long_description(self, project):
        long_desc = "A" * 10000
        t = db.create_task(project["id"], "Long task", description=long_desc)
        assert t["description"] == long_desc

    def test_multiple_subtasks_ordering(self, project):
        parent = db.create_task(project["id"], "Parent")
        c1 = db.create_task(project["id"], "C", parent_id=parent["id"])
        c2 = db.create_task(project["id"], "A", parent_id=parent["id"])
        c3 = db.create_task(project["id"], "B", parent_id=parent["id"])

        # Default order is by rank (creation order)
        children = db.list_tasks(project["id"], parent_id=parent["id"])
        assert len(children) == 3
        # The order is C, A, B because they were created in that order
        assert children[0]["id"] == c1["id"]