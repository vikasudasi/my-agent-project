"""Composite MCP workflow tools that encode task-management best practices."""

from typing import Any, Optional

from db import (
    add_comment,
    get_docs_summary,
    get_project_progress,
    get_task,
    get_task_doc_meta,
    get_task_subtask_stats,
    get_task_subtree,
    list_comments,
    list_projects,
    log_audit,
    update_task,
    upsert_task_doc,
)
from mcp_enrich import build_project_snapshot, enrich_task, list_projects_enriched
from mcp_validation import ValidationError, require_text, validate_comment_content, validate_doc_content
from mcp_validation import MIN_REASON_LEN

SESSION_CHECKLIST = [
    "Review spec and recent comments before changing code",
    "Use task_record_progress each session for structured findings",
    "Use comment_add for quick timeline notes and blockers",
    "Use task_complete when acceptance criteria are met",
]

_WORKABLE_STATUSES = frozenset({"pending", "in_progress"})


def _flatten_task_tree(nodes: list[dict]) -> list[dict]:
    flat: list[dict] = []
    for node in nodes:
        flat.append(node)
        children = node.get("children") or []
        if children:
            flat.extend(_flatten_task_tree(children))
    return flat


def suggest_next_task(project_id: str) -> Optional[dict[str, Any]]:
    """Pick the first in_progress task in tree order, else first pending."""
    tree = get_task_subtree(project_id)
    flat = _flatten_task_tree(tree)
    for preferred in ("in_progress", "pending"):
        for task in flat:
            if task.get("status") == preferred:
                docs = get_docs_summary("task", task["id"])
                return {
                    "id": task["id"],
                    "title": task["title"],
                    "status": task["status"],
                    "parent_id": task.get("parent_id"),
                    "has_spec": docs.get("spec", {}).get("exists", False),
                    "reason": f"First {preferred} task in project tree order",
                }
    return None


def pick_focus_project(projects: list[dict]) -> Optional[str]:
    """Choose a project with active work, or the first active project."""
    if not projects:
        return None
    for status_key in ("in_progress", "pending"):
        for project in projects:
            progress = get_project_progress(project["id"])
            if progress and progress.get("by_status", {}).get(status_key, 0) > 0:
                return project["id"]
    return projects[0]["id"]


def run_session_context(
    *,
    project_id: Optional[str] = None,
    project_status: str = "active",
    include_snapshot: bool = True,
    auto_focus: bool = True,
) -> dict[str, Any]:
    status_filter = None if project_status == "all" else project_status
    projects = list_projects_enriched(status=status_filter, include_progress=True)

    focus_id = project_id
    if not focus_id and auto_focus:
        focus_id = pick_focus_project(projects)

    result: dict[str, Any] = {
        "projects": projects,
        "focus_project_id": focus_id,
        "session_checklist": list(SESSION_CHECKLIST),
    }

    if focus_id:
        result["focus_project"] = enrich_project_dict(focus_id)
        if include_snapshot:
            snapshot = build_project_snapshot(focus_id)
            if snapshot:
                result["snapshot"] = snapshot
        suggested = suggest_next_task(focus_id)
        if suggested:
            result["suggested_next_task"] = suggested
        blocked = _blocked_tasks_summary(focus_id)
        if blocked:
            result["blocked_tasks"] = blocked
    else:
        result["session_checklist"].insert(
            0, "No active projects found — create one with project_create"
        )

    return result


def enrich_project_dict(project_id: str) -> Optional[dict[str, Any]]:
    progress = get_project_progress(project_id)
    if not progress:
        return None
    return {
        **progress,
        "docs_summary": get_docs_summary("project", project_id),
    }


def _blocked_tasks_summary(project_id: str) -> list[dict[str, Any]]:
    tree = get_task_subtree(project_id)
    blocked: list[dict[str, Any]] = []
    for task in _flatten_task_tree(tree):
        if task.get("status") != "blocked":
            continue
        comments = list_comments("task", task["id"], limit=3)
        latest_blocker = next(
            (c for c in reversed(comments) if "[blocker]" in c.get("content", "").lower()),
            comments[-1] if comments else None,
        )
        blocked.append({
            "id": task["id"],
            "title": task["title"],
            "latest_comment": latest_blocker,
        })
    return blocked


def run_task_begin_work(
    task_id: str,
    *,
    agent_name: str,
    master_name: str,
    comment_limit: int = 10,
    comment_since: Optional[str] = None,
) -> dict[str, Any]:
    task = get_task(task_id)
    if not task:
        raise ValidationError(f"Task '{task_id}' not found", code="NOT_FOUND")

    warnings: list[str] = []
    status = task.get("status")

    if status not in _WORKABLE_STATUSES:
        raise ValidationError(
            f"Cannot begin work on task with status={status}. "
            "Only pending or in_progress tasks can be started.",
            code="INVALID_STATUS",
            field="task_id",
        )

    if status == "pending":
        updated = update_task(task_id, status="in_progress")
        if updated:
            task = updated
            log_audit(agent_name, master_name, "task", task_id, "status_changed", "status", "pending", "in_progress")

    spec_meta = get_task_doc_meta(task_id, "spec")
    if not spec_meta:
        warnings.append("No spec doc — define scope with doc_task_update doc_type=spec before implementing.")

    comments = list_comments("task", task_id, limit=comment_limit, since=comment_since)
    enriched = enrich_task(task)

    checklist = [
        "Read spec content below",
        "Review recent comments for context",
        "Implement against acceptance criteria in the spec",
        "Call task_record_progress when you have session findings",
        "Call task_complete when acceptance criteria are met",
    ]

    return {
        "task": enriched,
        "spec": {
            "exists": spec_meta is not None,
            "content": spec_meta["content"] if spec_meta else "",
            "updated_at": spec_meta["updated_at"] if spec_meta else None,
        },
        "recent_comments": comments,
        "checklist": checklist,
        "warnings": warnings,
    }


def run_task_record_progress(
    task_id: str,
    content: str,
    *,
    agent_name: str,
    master_name: str,
    comment: Optional[str] = None,
    comment_type: Optional[str] = None,
) -> dict[str, Any]:
    task = get_task(task_id)
    if not task:
        raise ValidationError(f"Task '{task_id}' not found", code="NOT_FOUND")

    if task.get("status") not in _WORKABLE_STATUSES | {"blocked"}:
        raise ValidationError(
            f"Cannot record progress on task with status={task.get('status')}",
            code="INVALID_STATUS",
            field="task_id",
        )

    progress_content = validate_doc_content(content, "progress")
    upsert_task_doc(task_id, progress_content, doc_type="progress")
    log_audit(agent_name, master_name, "task", task_id, "doc_updated", "doc_progress")

    added_comment = None
    if comment:
        comment_text = validate_comment_content(comment)
        if comment_type:
            comment_text = f"[{comment_type}] {comment_text}"
        added_comment = add_comment("task", task_id, comment_text, author=agent_name)
        log_audit(agent_name, master_name, "task", task_id, "comment_added")

    meta = get_task_doc_meta(task_id, "progress")
    return {
        "task_id": task_id,
        "progress_updated": True,
        "updated_at": meta["updated_at"] if meta else None,
        "char_count": len(progress_content),
        "comment": added_comment,
    }


def run_task_complete(
    task_id: str,
    *,
    agent_name: str,
    master_name: str,
    closure: Optional[str] = None,
    closure_note: Optional[str] = None,
) -> dict[str, Any]:
    task = get_task(task_id)
    if not task:
        raise ValidationError(f"Task '{task_id}' not found", code="NOT_FOUND")

    if task.get("status") == "completed":
        raise ValidationError("Task is already completed", code="INVALID_STATUS", field="task_id")

    warnings: list[str] = []
    stats = get_task_subtask_stats(task_id)
    total = stats.get("subtask_count", 0)
    done = stats.get("subtasks_completed", 0)
    if total > done:
        warnings.append(
            f"{total - done} of {total} subtasks are not completed — parent may be closing early."
        )

    if closure:
        closure_content = validate_doc_content(closure, "closure")
    elif closure_note:
        note = require_text(closure_note, "closure_note", MIN_REASON_LEN, "Closure note")
        closure_content = f"## Summary\n{note}"
    else:
        existing = get_task_doc_meta(task_id, "closure")
        if not existing:
            raise ValidationError(
                "Provide closure (full markdown) or closure_note to complete the task",
                field="closure",
            )
        closure_content = existing["content"]

    upsert_task_doc(task_id, closure_content, doc_type="closure")
    log_audit(agent_name, master_name, "task", task_id, "doc_updated", "doc_closure")

    old_status = task.get("status")
    result = update_task(task_id, status="completed")
    if not result:
        raise ValidationError(f"Task '{task_id}' not found", code="NOT_FOUND")
    log_audit(agent_name, master_name, "task", task_id, "status_changed", "status", old_status, "completed")

    enriched = enrich_task(result)
    next_steps: list[str] = []
    parent_id = task.get("parent_id")
    if parent_id:
        parent_stats = get_task_subtask_stats(parent_id)
        p_total = parent_stats.get("subtask_count", 0)
        p_done = parent_stats.get("subtasks_completed", 0)
        if p_total and p_done == p_total:
            next_steps.append(f"All subtasks done — consider task_complete task_id={parent_id}")
        else:
            next_steps.append(f"task_get task_id={parent_id} to check remaining subtasks")

    payload: dict[str, Any] = {
        "task": enriched,
        "closure_written": True,
    }
    if warnings:
        payload["warnings"] = warnings
    if next_steps:
        payload["next_steps"] = next_steps
    return payload
