"""Validation helpers for MCP tool contracts — strict enforcement only."""

import re
from typing import Any, Optional

from db import get_task_subtask_stats

MIN_NAME_LEN = 3
MIN_DESCRIPTION_LEN = 40
MIN_COMMENT_LEN = 10
MIN_REASON_LEN = 20
MIN_SPEC_LEN = 80
MIN_PROGRESS_LEN = 50
MIN_CLOSURE_LEN = 80


class ValidationError(Exception):
    def __init__(
        self,
        message: str,
        field: Optional[str] = None,
        code: str = "VALIDATION_ERROR",
        remediation: Optional[list[str]] = None,
    ):
        super().__init__(message)
        self.message = message
        self.field = field
        self.code = code
        self.remediation = remediation or []


def _trim(value: str) -> str:
    return value.strip() if value else ""


def require_text(value: str, field: str, min_len: int, label: Optional[str] = None) -> str:
    text = _trim(value)
    name = label or field
    if len(text) < min_len:
        raise ValidationError(
            f"{name} must be at least {min_len} characters (got {len(text)})",
            field=field,
        )
    return text


def _spec_remediation(entity: str, entity_id: str) -> list[str]:
    tool = "doc_task_update" if entity == "task" else "doc_project_update"
    key = "task_id" if entity == "task" else "project_id"
    return [
        f"{tool} {key}={entity_id} doc_type=spec with ## Objective and ## Acceptance Criteria",
    ]


def _closure_remediation(task_id: str) -> list[str]:
    return [
        f"doc_task_update task_id={task_id} doc_type=closure with ## Summary",
        f"task_update task_id={task_id} status=completed",
    ]


def validate_subtasks_allow_parent_complete(task_id: str) -> None:
    stats = get_task_subtask_stats(task_id)
    active = stats.get("subtasks_active", 0)
    if active > 0:
        raise ValidationError(
            f"Cannot complete task with {active} active subtask(s) "
            f"({stats.get('subtask_count', 0)} total, {stats.get('subtasks_terminal', 0)} terminal).",
            field="status",
            code="TRANSITION_BLOCKED",
            remediation=[
                "Complete, cancel, or mark failed all subtasks before completing the parent",
                f"task_tree task_id={task_id} to inspect subtask statuses",
            ],
        )


def validate_project_create(args: dict) -> dict:
    name = require_text(args.get("name", ""), "name", MIN_NAME_LEN, "Project name")
    description = require_text(
        args.get("description", ""), "description", MIN_DESCRIPTION_LEN, "Project description"
    )
    initial_spec = args.get("initial_spec")
    if not initial_spec:
        raise ValidationError(
            "initial_spec is required",
            field="initial_spec",
            remediation=_spec_remediation("project", "<new-project-id>"),
        )
    initial_spec = validate_doc_content(initial_spec, "spec", "initial_spec")
    return {"name": name, "description": description, "initial_spec": initial_spec}


def validate_task_create(args: dict) -> dict:
    title = require_text(args.get("title", ""), "title", MIN_NAME_LEN, "Task title")
    description = require_text(
        args.get("description", ""), "description", MIN_DESCRIPTION_LEN, "Task description"
    )
    parent_id = args.get("parent_id") or None
    initial_spec = args.get("initial_spec")
    if not initial_spec:
        raise ValidationError(
            "initial_spec is required for all tasks including subtasks",
            field="initial_spec",
            remediation=_spec_remediation("task", "<new-task-id>"),
        )
    initial_spec = validate_doc_content(initial_spec, "spec", "initial_spec")
    return {
        "title": title,
        "description": description,
        "parent_id": parent_id,
        "initial_spec": initial_spec,
    }


def validate_doc_content(content: str, doc_type: str, field: str = "content") -> str:
    text = _trim(content)
    min_lens = {"spec": MIN_SPEC_LEN, "progress": MIN_PROGRESS_LEN, "closure": MIN_CLOSURE_LEN}
    min_len = min_lens.get(doc_type, MIN_PROGRESS_LEN)
    require_text(text, field, min_len, f"{doc_type} document content")

    if doc_type == "spec":
        if not re.search(r"##\s+Objective", text, re.IGNORECASE):
            raise ValidationError(
                "spec content must include a '## Objective' section",
                field=field,
            )
        if not re.search(r"##\s+Acceptance\s+Criteria", text, re.IGNORECASE):
            raise ValidationError(
                "spec content must include a '## Acceptance Criteria' section",
                field=field,
            )
    elif doc_type == "closure":
        if not re.search(r"##\s+Summary", text, re.IGNORECASE):
            raise ValidationError(
                "closure content must include a '## Summary' section",
                field=field,
            )
    return text


def validate_project_update(args: dict, old: Optional[dict]) -> Optional[str]:
    new_status = args.get("status")
    if new_status and old and new_status != old.get("status"):
        return require_text(
            args.get("reason", ""), "reason", MIN_REASON_LEN,
            "Status change reason",
        )
    if args.get("description") is not None:
        require_text(args["description"], "description", MIN_DESCRIPTION_LEN, "Project description")
    return args.get("reason")


def validate_task_update(
    args: dict,
    old: dict,
    has_closure_doc: bool,
    *,
    has_spec_doc: bool,
) -> dict[str, Any]:
    extras: dict[str, Any] = {}
    new_status = args.get("status")
    task_id = old["id"]

    if args.get("title") is not None:
        require_text(args["title"], "title", MIN_NAME_LEN, "Task title")
    if args.get("description") is not None:
        require_text(args["description"], "description", MIN_DESCRIPTION_LEN, "Task description")

    if new_status and new_status != old.get("status"):
        if new_status == "in_progress" and not has_spec_doc:
            raise ValidationError(
                "Cannot set status=in_progress without a spec doc",
                field="status",
                code="TRANSITION_BLOCKED",
                remediation=_spec_remediation("task", task_id)
                + [f"task_update task_id={task_id} status=in_progress"],
            )

        if new_status == "blocked":
            extras["blocker_reason"] = require_text(
                args.get("blocker_reason", ""), "blocker_reason", MIN_REASON_LEN,
                "Blocker reason",
            )

        if new_status == "failed":
            extras["failure_reason"] = require_text(
                args.get("failure_reason", ""), "failure_reason", MIN_REASON_LEN,
                "Failure reason",
            )

        if new_status == "completed":
            validate_subtasks_allow_parent_complete(task_id)
            if not has_closure_doc and not args.get("closure_note"):
                raise ValidationError(
                    "closure doc or closure_note is required to mark completed",
                    field="closure_note",
                    code="TRANSITION_BLOCKED",
                    remediation=_closure_remediation(task_id),
                )
            if not has_closure_doc:
                extras["closure_note"] = require_text(
                    args.get("closure_note", ""), "closure_note", MIN_REASON_LEN,
                    "Closure note (required when no closure doc exists)",
                )

    return extras


def validate_task_delete(args: dict) -> str:
    return require_text(args.get("reason", ""), "reason", MIN_REASON_LEN, "Delete reason")


def validate_comment_content(content: str) -> str:
    return require_text(content, "content", MIN_COMMENT_LEN, "Comment content")


def validate_task_has_spec(task_id: str, has_spec_doc: bool) -> None:
    if not has_spec_doc:
        raise ValidationError(
            "Cannot begin work without a spec doc",
            field="task_id",
            code="TRANSITION_BLOCKED",
            remediation=_spec_remediation("task", task_id)
            + [f"task_begin_work task_id={task_id}"],
        )
