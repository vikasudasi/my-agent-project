"""Validation helpers for MCP tool contracts."""

import os
import re
from typing import Optional

MIN_NAME_LEN = 3
MIN_DESCRIPTION_LEN = 40
MIN_COMMENT_LEN = 10
MIN_REASON_LEN = 20
MIN_SPEC_LEN = 80
MIN_PROGRESS_LEN = 50
MIN_CLOSURE_LEN = 80

STRICT = os.environ.get("TM_STRICT", "").lower() in ("1", "true", "yes")


class ValidationError(Exception):
    def __init__(self, message: str, field: Optional[str] = None, code: str = "VALIDATION_ERROR"):
        super().__init__(message)
        self.message = message
        self.field = field
        self.code = code


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


def validate_project_create(args: dict) -> dict:
    name = require_text(args.get("name", ""), "name", MIN_NAME_LEN, "Project name")
    description = require_text(
        args.get("description", ""), "description", MIN_DESCRIPTION_LEN, "Project description"
    )
    initial_spec = args.get("initial_spec")
    if initial_spec:
        initial_spec = validate_doc_content(initial_spec, "spec", "initial_spec")
    elif STRICT:
        raise ValidationError(
            "initial_spec is required when TM_STRICT is enabled",
            field="initial_spec",
        )
    return {"name": name, "description": description, "initial_spec": initial_spec}


def validate_task_create(args: dict) -> dict:
    title = require_text(args.get("title", ""), "title", MIN_NAME_LEN, "Task title")
    description = require_text(
        args.get("description", ""), "description", MIN_DESCRIPTION_LEN, "Task description"
    )
    parent_id = args.get("parent_id") or None
    initial_spec = args.get("initial_spec")
    if initial_spec:
        initial_spec = validate_doc_content(initial_spec, "spec", "initial_spec")
    elif STRICT and not parent_id:
        raise ValidationError(
            "initial_spec is required for root tasks when TM_STRICT is enabled",
            field="initial_spec",
        )
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


def validate_task_update(args: dict, old: dict, has_closure_doc: bool) -> dict:
    extras: dict = {}
    new_status = args.get("status")
    if args.get("title") is not None:
        require_text(args["title"], "title", MIN_NAME_LEN, "Task title")
    if args.get("description") is not None:
        require_text(args["description"], "description", MIN_DESCRIPTION_LEN, "Task description")

    if new_status and new_status != old.get("status"):
        if new_status == "blocked":
            extras["blocker_reason"] = require_text(
                args.get("blocker_reason", ""), "blocker_reason", MIN_REASON_LEN,
                "Blocker reason",
            )
        if new_status == "completed":
            closure_note = args.get("closure_note")
            if not has_closure_doc:
                if not closure_note and not STRICT:
                    pass  # warn only in non-strict
                else:
                    extras["closure_note"] = require_text(
                        closure_note or "", "closure_note", MIN_REASON_LEN,
                        "Closure note (required when no closure doc exists)",
                    ) if not has_closure_doc else None
            if STRICT and not has_closure_doc and not args.get("closure_note"):
                raise ValidationError(
                    "closure_note or an existing closure doc is required to mark completed",
                    field="closure_note",
                )
    return extras


def validate_task_delete(args: dict) -> str:
    return require_text(args.get("reason", ""), "reason", MIN_REASON_LEN, "Delete reason")


def validate_comment_content(content: str) -> str:
    return require_text(content, "content", MIN_COMMENT_LEN, "Comment content")
