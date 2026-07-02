"""Response enrichment helpers for MCP tools."""

from typing import Any, Optional

from db import (
    count_comments,
    get_docs_summary,
    get_project_doc_meta,
    get_task_doc_meta,
    get_project_progress,
    get_project_audit_log,
    get_task_subtree,
    list_projects,
    get_task,
    get_task_creator,
    get_task_subtask_stats,
    list_comments,
)
from mcp_read_hints import (
    build_blocked_tasks_summary,
    enrich_docs_summary,
    task_is_yours,
)


def enrich_project(project: dict, *, for_read: bool = False) -> dict:
    pid = project["id"]
    progress = get_project_progress(pid)
    if progress:
        project = {**project, **{
            k: progress[k] for k in (
                "total_tasks", "completed_tasks", "progress_pct", "by_status"
            ) if k in progress
        }}
    summary = get_docs_summary("project", pid)
    project["docs_summary"] = enrich_docs_summary(summary) if for_read else summary
    return project


def enrich_task(
    task: dict,
    include_parent: bool = True,
    *,
    for_read: bool = False,
    agent_name: Optional[str] = None,
    comment_limit: int = 0,
) -> dict:
    tid = task["id"]
    summary = get_docs_summary("task", tid)
    task["docs_summary"] = (
        enrich_docs_summary(summary, task_status=task.get("status"))
        if for_read
        else summary
    )
    task["subtask_stats"] = get_task_subtask_stats(tid)
    task["comment_count"] = count_comments("task", tid)
    creator = get_task_creator(tid)
    if creator:
        task["created_by"] = creator
    if include_parent and task.get("parent_id"):
        parent = get_task(task["parent_id"])
        if parent:
            task["parent"] = {"id": parent["id"], "title": parent["title"]}
    if for_read and comment_limit > 0:
        task["recent_comments"] = list_comments("task", tid, limit=comment_limit)
    if for_read and agent_name:
        task["is_yours"] = task_is_yours(tid, agent_name, task["project_id"])
    return task


def enrich_task_list(
    tasks: list[dict],
    *,
    for_read: bool = False,
    agent_name: Optional[str] = None,
) -> list[dict]:
    return [
        enrich_task(t, include_parent=False, for_read=for_read, agent_name=agent_name)
        for t in tasks
    ]


def enrich_doc_response(
    entity_type: str, entity_id: str, doc_type: str, meta: Optional[dict]
) -> dict:
    content = meta["content"] if meta else ""
    return {
        f"{entity_type}_id" if entity_type == "project" else "task_id": entity_id,
        "doc_type": doc_type,
        "content": content,
        "exists": meta is not None,
        "updated_at": meta["updated_at"] if meta else None,
        "char_count": len(content),
    }


def build_project_snapshot(
    project_id: str,
    include_recent_activity: bool = True,
    *,
    for_read: bool = False,
    agent_name: Optional[str] = None,
) -> Optional[dict]:
    progress = get_project_progress(project_id)
    if not progress:
        return None
    snapshot: dict[str, Any] = {
        **progress,
        "docs_summary": enrich_docs_summary(get_docs_summary("project", project_id))
        if for_read
        else get_docs_summary("project", project_id),
        "task_tree": get_task_subtree(project_id),
    }
    if include_recent_activity:
        entries = get_project_audit_log(project_id, limit=10)
        snapshot["recent_activity"] = entries
    if for_read:
        snapshot["blocked_tasks"] = build_blocked_tasks_summary(project_id)
    return snapshot


def list_projects_enriched(
    status: Optional[str] = None, q: Optional[str] = None, include_progress: bool = True
) -> list[dict]:
    projects = list_projects(status=status, q=q)
    if not include_progress:
        return projects
    return [enrich_project(p) for p in projects]
