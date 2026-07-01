"""Minimal prompt builder — task ID only; agent fetches context from TM."""

from __future__ import annotations

FETCH_TEMPLATE = """---
Work on task: {task_id}

Before writing any code, fetch full context from the task manager:
- task_get({task_id})
- doc for spec (and progress if present)
- relevant comments

Complete only this task, then update TM accordingly."""


def build_prompt(task_id: str, repeat_instructions: str) -> str:
    """Build per-step prompt: repeat instructions + task pointer."""
    parts: list[str] = []
    if repeat_instructions:
        parts.append(repeat_instructions.rstrip())
    parts.append(FETCH_TEMPLATE.format(task_id=task_id))
    return "\n\n".join(parts)
