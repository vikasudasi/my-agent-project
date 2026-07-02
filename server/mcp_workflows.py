"""Composite MCP workflow tools that encode task-management best practices."""

from typing import Any, Optional

from db import (
    add_comment,
    get_agent_resumed_tasks_in_project,
    get_docs_summary,
    get_project_progress,
    get_task,
    get_task_doc_meta,
    get_task_subtask_stats,
    get_task_subtree,
    list_comments,
    log_audit,
    update_task,
    upsert_task_doc,
)
from mcp_enrich import build_project_snapshot, enrich_task, list_projects_enriched
from mcp_read_hints import build_blocked_tasks_summary
from mcp_validation import (
    ValidationError,
    require_text,
    validate_comment_content,
    validate_doc_content,
    validate_subtasks_allow_parent_complete,
    validate_task_has_spec,
    MIN_REASON_LEN,
)

SESSION_CHECKLIST = [
    "Review spec and recent comments before changing code",
    "Use task_record_progress each session for structured findings",
    "Use comment_add for quick timeline notes and blockers",
    "Use task_complete when acceptance criteria are met",
]

PROJECT_SESSION_CHECKLIST = [
    "Multiple agents may work on this project — pick YOUR task from available_tasks",
    "Pass api_key to mark your tasks with is_yours in available_tasks",
    "Pass task_id to focus this session on the task you intend to work on",
    "Call task_begin_work on your chosen task_id before making changes",
    *SESSION_CHECKLIST,
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


def _summarize_task_for_session(task: dict, *, is_yours: Optional[bool] = None) -> dict[str, Any]:
    tid = task["id"]
    docs = get_docs_summary("task", tid)
    summary: dict[str, Any] = {
        "id": tid,
        "title": task["title"],
        "description": task.get("description") or "",
        "status": task["status"],
        "parent_id": task.get("parent_id"),
        "has_spec": docs.get("spec", {}).get("exists", False),
    }
    if is_yours is not None:
        summary["is_yours"] = is_yours
    return summary


def list_available_tasks(
    project_id: str, *, agent_name: Optional[str] = None
) -> list[dict[str, Any]]:
    """All in_progress and pending tasks in tree order — multiple agents pick from this list."""
    yours_ids: set[str] = set()
    if agent_name:
        yours_ids = {
            t["id"] for t in get_agent_resumed_tasks_in_project(agent_name, project_id)
        }

    tree = get_task_subtree(project_id)
    flat = _flatten_task_tree(tree)
    available: list[dict[str, Any]] = []
    for status in ("in_progress", "pending"):
        for task in flat:
            if task.get("status") == status:
                is_yours = task["id"] in yours_ids if agent_name else None
                available.append(_summarize_task_for_session(task, is_yours=is_yours))
    return available


def _build_focused_task(task_id: str, *, comment_limit: int = 10) -> dict[str, Any]:
    spec_meta = get_task_doc_meta(task_id, "spec")
    return {
        "task": enrich_task(get_task(task_id)),
        "spec": {
            "exists": spec_meta is not None,
            "content": spec_meta["content"] if spec_meta else "",
            "updated_at": spec_meta["updated_at"] if spec_meta else None,
        },
        "recent_comments": list_comments("task", task_id, limit=comment_limit),
    }


def run_session_context(
    *,
    project_id: Optional[str] = None,
    task_id: Optional[str] = None,
    project_status: str = "active",
    include_snapshot: bool = True,
    agent_name: Optional[str] = None,
) -> dict[str, Any]:
    """Return project picker list, or session context scoped to a selected project/task."""
    status_filter = None if project_status == "all" else project_status

    if not project_id:
        projects = list_projects_enriched(status=status_filter, include_progress=True)
        checklist = [
            "Choose the project you will work on this session",
            "Call session_context again with that project_id",
            "Pass task_id when you know which task is yours in a shared project",
        ]
        if not projects:
            checklist.insert(0, "No projects found — create one with project_create")
        return {
            "mode": "select_project",
            "projects": projects,
            "session_checklist": checklist,
        }

    project = enrich_project_dict(project_id)
    if not project:
        raise ValidationError(
            f"Project '{project_id}' not found",
            code="NOT_FOUND",
            field="project_id",
        )

    result: dict[str, Any] = {
        "mode": "project_session",
        "project_id": project_id,
        "project": project,
        "available_tasks": list_available_tasks(project_id, agent_name=agent_name),
        "session_checklist": list(PROJECT_SESSION_CHECKLIST),
    }

    if include_snapshot:
        snapshot = build_project_snapshot(project_id, for_read=True)
        if snapshot:
            result["snapshot"] = snapshot

    blocked = build_blocked_tasks_summary(project_id)
    if blocked:
        result["blocked_tasks"] = blocked

    if task_id:
        task = get_task(task_id)
        if not task:
            raise ValidationError(
                f"Task '{task_id}' not found",
                code="NOT_FOUND",
                field="task_id",
            )
        if task["project_id"] != project_id:
            raise ValidationError(
                f"Task '{task_id}' does not belong to project '{project_id}'",
                code="VALIDATION_ERROR",
                field="task_id",
            )
        result["task_id"] = task_id
        result["focused_task"] = _build_focused_task(task_id)

    return result


def enrich_project_dict(project_id: str) -> Optional[dict[str, Any]]:
    progress = get_project_progress(project_id)
    if not progress:
        return None
    return {
        **progress,
        "docs_summary": get_docs_summary("project", project_id),
    }


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

    spec_meta = get_task_doc_meta(task_id, "spec")
    validate_task_has_spec(task_id, spec_meta is not None)

    if status == "pending":
        updated = update_task(task_id, status="in_progress")
        if updated:
            task = updated
            log_audit(agent_name, master_name, "task", task_id, "status_changed", "status", "pending", "in_progress")

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

    validate_subtasks_allow_parent_complete(task_id)

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
    if next_steps:
        payload["next_steps"] = next_steps
    return payload