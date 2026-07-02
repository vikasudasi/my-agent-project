"""Tests for read-path hints and enrichment."""

import time
from datetime import datetime, timedelta, timezone

import pytest

import db
from conftest import VALID_SPEC
from mcp_enrich import enrich_task, build_project_snapshot
from mcp_read_hints import (
    build_blocked_tasks_summary,
    build_read_hints,
    enrich_docs_summary,
    spec_content_warnings,
)
from mcp_workflows import run_task_begin_work


@pytest.fixture
def agent():
    name = f"read-hints-agent-{int(time.time() * 1000)}"
    a = db.onboard_agent(name, "Test Master")
    assert a is not None
    return a


class TestDocsSummaryEnrichment:
    def test_needs_update_on_in_progress_without_progress(self, task):
        db.update_task(task["id"], status="in_progress")
        summary = db.get_docs_summary("task", task["id"])
        enriched = enrich_docs_summary(summary, task_status="in_progress")
        assert enriched["progress"]["needs_update"] is True

    def test_is_stale_on_old_spec(self, task):
        db.upsert_task_doc(
            task["id"],
            "## Objective\nOld\n## Acceptance Criteria\n- [ ] x" + "y" * 50,
            "spec",
        )
        old = (datetime.now(timezone.utc) - timedelta(days=45)).strftime("%Y-%m-%d %H:%M:%S")
        with db.get_connection() as conn:
            conn.execute(
                "UPDATE task_docs SET updated_at = ? WHERE task_id = ? AND doc_type = 'spec'",
                (old, task["id"]),
            )
        summary = db.get_docs_summary("task", task["id"])
        enriched = enrich_docs_summary(summary, task_status="in_progress")
        assert enriched["spec"].get("is_stale") is True


class TestTaskGetReadEnrichment:
    def test_includes_recent_comments(self, project, task):
        db.add_comment("task", task["id"], "Session context from yesterday here")
        enriched = enrich_task(task, for_read=True, comment_limit=5)
        assert len(enriched["recent_comments"]) >= 1
        assert enriched["recent_comments"][0]["content"]

    def test_is_yours_with_agent(self, project, agent):
        t = db.create_task(project["id"], "Mine", "A" * 40)
        db.upsert_task_doc(t["id"], VALID_SPEC, "spec")
        run_task_begin_work(t["id"], agent_name=agent["name"], master_name=agent["master_name"])
        enriched = enrich_task(t, for_read=True, agent_name=agent["name"])
        assert enriched["is_yours"] is True


class TestProjectSnapshotRead:
    def test_includes_blocked_tasks(self, project):
        blocked = db.create_task(project["id"], "Blocked one", "A" * 40)
        db.update_task(blocked["id"], status="blocked")
        db.add_comment("task", blocked["id"], "[blocker] Waiting on credentials from ops team")
        snap = build_project_snapshot(project["id"], for_read=True)
        assert snap is not None
        assert len(snap["blocked_tasks"]) == 1
        assert snap["blocked_tasks"][0]["latest_comment"] is not None


class TestReadHints:
    def test_task_get_warns_missing_spec(self, project):
        task = db.create_task(project["id"], "No spec task", "A" * 40)
        warnings, next_steps = build_read_hints(
            "task_get",
            {"id": task["id"], "status": "pending", "docs_summary": db.get_docs_summary("task", task["id"])},
            arguments={"task_id": task["id"]},
        )
        assert any("spec" in w.lower() for w in warnings)
        assert any("doc_task_update" in s for s in next_steps)

    def test_doc_task_get_warns_missing_sections(self, task):
        db.upsert_task_doc(task["id"], "Too short without proper headers" + "x" * 60, "spec")
        warnings, _ = build_read_hints(
            "doc_task_get",
            {
                "task_id": task["id"],
                "doc_type": "spec",
                "content": "Too short without proper headers" + "x" * 60,
                "exists": True,
                "char_count": 80,
            },
            arguments={"task_id": task["id"], "doc_type": "spec"},
        )
        assert warnings

    def test_spec_content_warnings(self):
        assert spec_content_warnings("", exists=False)
        assert spec_content_warnings("no headers here" * 10, exists=True)

    def test_task_list_suggests_yours(self, project, agent):
        t = db.create_task(project["id"], "Yours", "A" * 40)
        db.upsert_task_doc(t["id"], VALID_SPEC, "spec")
        run_task_begin_work(t["id"], agent_name=agent["name"], master_name=agent["master_name"])
        from mcp_enrich import enrich_task_list
        tasks = enrich_task_list([t], for_read=True, agent_name=agent["name"])
        _, next_steps = build_read_hints(
            "task_list", tasks, arguments={"project_id": project["id"]}, agent_name=agent["name"]
        )
        assert any("task_begin_work" in s for s in next_steps)

    def test_blocked_tasks_summary(self, project):
        t = db.create_task(project["id"], "Blocked", "A" * 40)
        db.update_task(t["id"], status="blocked")
        items = build_blocked_tasks_summary(project["id"])
        assert any(i["id"] == t["id"] for i in items)
