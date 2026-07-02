"""Read-path hints and enrichment for MCP read tool responses."""

import re
from datetime import datetime, timezone
from typing import Any, Optional

from db import (
    get_agent_resumed_tasks_in_project,
    get_docs_summary,
    get_task_subtree,
    list_comments,
)

STALE_SPEC_DAYS = 30


def _parse_ts(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def enrich_docs_summary(
    summary: dict[str, Any], *, task_status: Optional[str] = None
) -> dict[str, Any]:
    """Add needs_update / is_stale flags to docs_summary entries."""
    enriched: dict[str, Any] = {}
    for doc_type, info in summary.items():
        entry = dict(info)
        if doc_type == "progress" and task_status == "in_progress":
            entry["needs_update"] = not info.get("exists")
        if doc_type == "spec" and info.get("exists"):
            updated = _parse_ts(info.get("updated_at"))
            if updated:
                age_days = (datetime.now(timezone.utc) - updated).days
                if age_days > STALE_SPEC_DAYS:
                    entry["is_stale"] = True
                if task_status == "in_progress" and not summary.get("progress", {}).get("exists"):
                    entry["needs_progress"] = True
        enriched[doc_type] = entry
    return enriched


def _flatten_task_tree(nodes: list[dict]) -> list[dict]:
    flat: list[dict] = []
    for node in nodes:
        flat.append(node)
        children = node.get("children") or []
        if children:
            flat.extend(_flatten_task_tree(children))
    return flat


def build_blocked_tasks_summary(project_id: str) -> list[dict[str, Any]]:
    """Blocked tasks with latest blocker comment for read-path surfacing."""
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
            "description": task.get("description") or "",
            "latest_comment": latest_blocker,
        })
    return blocked


def task_is_yours(task_id: str, agent_name: str, project_id: str) -> bool:
    yours = {t["id"] for t in get_agent_resumed_tasks_in_project(agent_name, project_id)}
    return task_id in yours


def spec_content_warnings(content: str, *, exists: bool) -> list[str]:
    warnings: list[str] = []
    if not exists:
        warnings.append("No spec doc exists — write one before starting implementation.")
        return warnings
    if not re.search(r"##\s+Objective", content, re.IGNORECASE):
        warnings.append("Spec is missing a '## Objective' section.")
    if not re.search(r"##\s+Acceptance\s+Criteria", content, re.IGNORECASE):
        warnings.append("Spec is missing a '## Acceptance Criteria' section.")
    return warnings


def build_read_hints(
    tool: str,
    data: Any,
    *,
    arguments: Optional[dict[str, Any]] = None,
    agent_name: Optional[str] = None,
) -> tuple[list[str], list[str]]:
    arguments = arguments or {}
    warnings: list[str] = []
    next_steps: list[str] = []

    if tool == "project_get" and isinstance(data, dict):
        pid = data.get("id") or arguments.get("project_id")
        by_status = data.get("by_status") or {}
        if by_status.get("blocked", 0) > 0:
            warnings.append(f"{by_status['blocked']} blocked task(s) in this project.")
            next_steps.append(f"project_snapshot project_id={pid} to see blocked_tasks with comments")
        if data.get("total_tasks", 0) == 0:
            next_steps.append(f"task_create on project {pid} to add work items")
        elif by_status.get("in_progress", 0) or by_status.get("pending", 0):
            next_steps.append(f"session_context project_id={pid} to pick a task")

    elif tool == "project_snapshot" and isinstance(data, dict):
        pid = data.get("id") or arguments.get("project_id")
        blocked = data.get("blocked_tasks") or []
        if blocked:
            warnings.append(f"{len(blocked)} blocked task(s) — review blocked_tasks before starting new work.")
        yours = [t for t in (data.get("available_tasks") or []) if t.get("is_yours")]
        if not yours:
            next_steps.append(f"session_context project_id={pid} with api_key to find your tasks")
        in_progress = (data.get("by_status") or {}).get("in_progress", 0)
        if in_progress:
            next_steps.append("Pick a task from the tree or session_context, then task_begin_work")

    elif tool == "project_list" and isinstance(data, list):
        if not data:
            next_steps.append("project_create to start a new project")
        else:
            next_steps.append("session_context (no project_id) or project_get on a chosen project")

    elif tool == "task_get" and isinstance(data, dict):
        tid = data.get("id") or arguments.get("task_id")
        status = data.get("status")
        docs = data.get("docs_summary") or {}
        if status == "in_progress" and docs.get("progress", {}).get("needs_update"):
            warnings.append("No progress doc — log session findings with task_record_progress.")
        if docs.get("spec", {}).get("needs_progress"):
            warnings.append("Task is in_progress but has no progress doc.")
        if docs.get("spec", {}).get("is_stale"):
            warnings.append("Spec has not been updated in over 30 days — confirm scope is still valid.")
        if not docs.get("spec", {}).get("exists"):
            warnings.append("No spec doc — define scope before implementing.")
            next_steps.insert(0, f"doc_task_update task_id={tid} doc_type=spec")
        if status == "blocked":
            next_steps.append("Review recent_comments and resolve blocker, then task_update status=in_progress")
        elif status in ("pending", "in_progress"):
            next_steps.append(f"task_begin_work task_id={tid}" if status == "pending" else f"task_record_progress task_id={tid}")
        elif status == "completed":
            next_steps.append(f"task_get task_id={tid} parent or pick next task via session_context")

    elif tool == "task_list" and isinstance(data, list):
        pid = arguments.get("project_id")
        yours = [t for t in data if t.get("is_yours")]
        if yours:
            if len(yours) == 1:
                next_steps.append(f"task_begin_work task_id={yours[0]['id']}  # your task")
            else:
                next_steps.append("Pick your task (is_yours: true) and call task_begin_work")
        elif data:
            next_steps.append(
                f"session_context project_id={pid} with task_id to focus, or task_begin_work on chosen task"
            )
        else:
            next_steps.append(f"task_create on project {pid}")

    elif tool in ("doc_task_get", "doc_project_get") and isinstance(data, dict):
        doc_type = data.get("doc_type", "spec")
        entity_key = "task_id" if tool == "doc_task_get" else "project_id"
        eid = data.get(entity_key) or arguments.get(entity_key)
        if doc_type == "spec":
            warnings.extend(spec_content_warnings(data.get("content", ""), exists=data.get("exists", False)))
            if not data.get("exists"):
                update_tool = "doc_task_update" if tool == "doc_task_get" else "doc_project_update"
                next_steps.append(f"{update_tool} {entity_key}={eid} doc_type=spec")
            elif data.get("char_count", 0) < 80:
                warnings.append("Spec doc is very short — ensure objective and acceptance criteria are complete.")
        elif doc_type == "progress" and not data.get("exists"):
            warnings.append("No progress doc yet for this entity.")
        elif doc_type == "closure" and not data.get("exists"):
            next_steps.append(
                f"doc_task_update task_id={eid} doc_type=closure before task_complete"
                if tool == "doc_task_get"
                else f"doc_project_update project_id={eid} doc_type=closure when project completes"
            )

    return warnings, next_steps
