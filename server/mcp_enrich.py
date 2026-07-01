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
)


def enrich_project(project: dict) -> dict:
    pid = project["id"]
    progress = get_project_progress(pid)
    if progress:
        project = {**project, **{
            k: progress[k] for k in (
                "total_tasks", "completed_tasks", "progress_pct", "by_status"
            ) if k in progress
        }}
    project["docs_summary"] = get_docs_summary("project", pid)
    return project


def enrich_task(task: dict, include_parent: bool = True) -> dict:
    tid = task["id"]
    task["docs_summary"] = get_docs_summary("task", tid)
    task["subtask_stats"] = get_task_subtask_stats(tid)
    task["comment_count"] = count_comments("task", tid)
    creator = get_task_creator(tid)
    if creator:
        task["created_by"] = creator
    if include_parent and task.get("parent_id"):
        parent = get_task(task["parent_id"])
        if parent:
            task["parent"] = {"id": parent["id"], "title": parent["title"]}
    return task


def enrich_task_list(tasks: list[dict]) -> list[dict]:
    return [enrich_task(t, include_parent=False) for t in tasks]


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


def build_project_snapshot(project_id: str, include_recent_activity: bool = True) -> Optional[dict]:
    progress = get_project_progress(project_id)
    if not progress:
        return None
    snapshot: dict[str, Any] = {
        **progress,
        "docs_summary": get_docs_summary("project", project_id),
        "task_tree": get_task_subtree(project_id),
    }
    if include_recent_activity:
        entries = get_project_audit_log(project_id, limit=10)
        snapshot["recent_activity"] = entries
    return snapshot


def list_projects_enriched(
    status: Optional[str] = None, q: Optional[str] = None, include_progress: bool = True
) -> list[dict]:
    projects = list_projects(status=status, q=q)
    if not include_progress:
        return projects
    return [enrich_project(p) for p in projects]
