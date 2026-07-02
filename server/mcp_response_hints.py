"""Contextual next_steps and warnings for MCP mutation responses."""

from typing import Any, Optional

from db import get_docs_summary, get_project_progress, get_task, get_task_subtask_stats


def build_hints(
    tool: str,
    data: dict[str, Any],
    *,
    arguments: Optional[dict[str, Any]] = None,
    old: Optional[dict[str, Any]] = None,
    wrote_closure_note: bool = False,
) -> tuple[list[str], list[str]]:
    """Return (warnings, next_steps) for a mutation tool response."""
    arguments = arguments or {}
    warnings: list[str] = []
    next_steps: list[str] = []

    if tool == "project_create":
        _hints_project_create(data, next_steps)
    elif tool == "project_update":
        _hints_project_update(data, old, arguments, warnings, next_steps)
    elif tool == "project_archive":
        next_steps.append("Use project_restore to reactivate if work resumes later")
    elif tool == "project_restore":
        pid = data.get("id") or arguments.get("project_id")
        next_steps.append(f"Call project_snapshot on {pid} to review task tree and pick up work")
    elif tool == "task_create":
        _hints_task_create(data, next_steps)
    elif tool == "task_update":
        _hints_task_update(data, old, arguments, wrote_closure_note, warnings, next_steps)
    elif tool == "task_move":
        next_steps.append("Call project_snapshot to verify task tree structure after the move")
    elif tool == "doc_project_update":
        _hints_doc_update("project", arguments, warnings, next_steps)
    elif tool == "doc_task_update":
        _hints_doc_update("task", arguments, warnings, next_steps)
        task_id = arguments.get("task_id")
        if task_id and arguments.get("doc_type", "spec") == "closure":
            task = get_task(task_id)
            if task and task.get("status") != "completed":
                next_steps.append(f"task_update {task_id} status=completed")
    elif tool == "comment_add":
        _hints_comment_add(arguments, next_steps)
    elif tool == "agent_onboard":
        next_steps.extend([
            "Save api_key immediately — it is shown only once",
            "Set TM_API_KEY in the environment for future mutations",
            "Call project_list at session start to find active work",
        ])

    return warnings, next_steps


def _hints_project_create(
    data: dict[str, Any],
    next_steps: list[str],
) -> None:
    pid = data.get("id")
    next_steps.extend([
        "Create root tasks with task_create (description and initial_spec required)",
        f"Call project_snapshot on {pid} after adding tasks to review structure",
    ])


def _hints_project_update(
    data: dict[str, Any],
    old: Optional[dict[str, Any]],
    arguments: dict[str, Any],
    warnings: list[str],
    next_steps: list[str],
) -> None:
    new_status = data.get("status")
    old_status = old.get("status") if old else None
    if new_status == old_status:
        return

    pid = data.get("id") or arguments.get("project_id")
    if new_status == "completed":
        progress = get_project_progress(pid)
        if progress:
            total = progress.get("total_tasks", 0)
            completed = progress.get("completed_tasks", 0)
            if total > completed:
                warnings.append(
                    f"Project marked completed but {total - completed} of {total} tasks are not completed."
                )
        docs = data.get("docs_summary") or get_docs_summary("project", pid)
        if not docs.get("closure", {}).get("exists"):
            warnings.append("No project closure doc — future readers won't see a delivery summary.")
            next_steps.append(f"doc_project_update project_id={pid} doc_type=closure with ## Summary")
    elif new_status == "archived":
        next_steps.append("Use project_restore to reactivate if work resumes later")


def _hints_task_create(
    data: dict[str, Any],
    next_steps: list[str],
) -> None:
    tid = data.get("id")
    is_root = not data.get("parent_id")

    if not is_root:
        next_steps.append("When done, check parent subtask_stats via task_get before marking parent complete")

    next_steps.append(f"task_begin_work task_id={tid} when you start implementation")
    if is_root:
        next_steps.append(f"Decompose with task_create parent_id={tid} if work spans multiple steps")


def _hints_task_update(
    data: dict[str, Any],
    old: Optional[dict[str, Any]],
    arguments: dict[str, Any],
    wrote_closure_note: bool,
    warnings: list[str],
    next_steps: list[str],
) -> None:
    new_status = data.get("status")
    old_status = old.get("status") if old else None
    if new_status == old_status:
        return

    tid = data.get("id") or arguments.get("task_id")
    docs = data.get("docs_summary") or get_docs_summary("task", tid)

    if new_status == "in_progress":
        next_steps.append(f"doc_task_update task_id={tid} doc_type=progress as you make findings")

    elif new_status == "blocked":
        next_steps.append("Resolve the blocker, then task_update status=in_progress to resume")

    elif new_status == "completed":
        if not docs.get("closure", {}).get("exists"):
            warnings.append(
                "Task marked completed without a closure doc — delivery summary may be missing."
            )
            next_steps.append(f"doc_task_update task_id={tid} doc_type=closure with ## Summary")
        elif wrote_closure_note:
            next_steps.append(
                f"Consider expanding closure via doc_task_update task_id={tid} doc_type=closure"
            )

        stats = data.get("subtask_stats") or get_task_subtask_stats(tid)
        active = stats.get("subtasks_active", 0)
        if active > 0:
            warnings.append(
                f"Task marked completed but {active} subtask(s) are still active."
            )

        parent_id = data.get("parent_id") or (old.get("parent_id") if old else None)
        if parent_id:
            parent_stats = get_task_subtask_stats(parent_id)
            p_total = parent_stats.get("subtask_count", 0)
            p_done = parent_stats.get("subtasks_completed", 0)
            if p_total and p_done == p_total:
                next_steps.append(
                    f"All subtasks done — consider task_update task_id={parent_id} status=completed"
                )
            else:
                next_steps.append(f"task_get task_id={parent_id} to check remaining subtask_stats")

    elif new_status == "failed":
        warnings.append("Record what was attempted and why it failed for future agents.")
        next_steps.append(f"comment_add on task {tid} with failure details")

    elif new_status == "cancelled":
        parent_id = data.get("parent_id") or (old.get("parent_id") if old else None)
        if parent_id:
            next_steps.append(f"task_get task_id={parent_id} to check if parent scope changed")


def _hints_doc_update(
    entity: str,
    arguments: dict[str, Any],
    warnings: list[str],
    next_steps: list[str],
) -> None:
    doc_type = arguments.get("doc_type", "spec")
    entity_id = arguments.get("project_id") if entity == "project" else arguments.get("task_id")
    id_field = "project_id" if entity == "project" else "task_id"
    tool = f"doc_{entity}_update"

    if doc_type == "spec":
        warnings.append("Spec docs should be written once — use doc_type=progress for ongoing updates.")
        if entity == "task":
            next_steps.append(f"task_update task_id={entity_id} status=in_progress when starting work")
    elif doc_type == "progress":
        next_steps.append(
            f"Keep {tool} doc_type=progress updated each session; use comment_add for quick timeline notes"
        )
    elif doc_type == "closure":
        if entity == "task":
            task = get_task(entity_id)
            if task and task.get("status") != "completed":
                next_steps.append(f"task_update task_id={entity_id} status=completed")
        elif entity == "project":
            next_steps.append(f"project_update project_id={entity_id} status=completed when all tasks are done")


def _hints_comment_add(arguments: dict[str, Any], next_steps: list[str]) -> None:
    comment_type = arguments.get("comment_type")
    entity_type = arguments.get("entity_type")
    entity_id = arguments.get("entity_id")

    if comment_type == "blocker":
        if entity_type == "task":
            next_steps.append(f"task_update task_id={entity_id} status=blocked with blocker_reason")
        else:
            next_steps.append("Mark affected tasks blocked via task_update with blocker_reason")
    elif comment_type == "decision":
        next_steps.append(
            f"Update doc_{entity_type}_update doc_type=progress on {entity_id} if the decision affects scope"
        )
