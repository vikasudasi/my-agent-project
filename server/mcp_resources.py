"""Static MCP resources — playbook and doc templates for pinning in host context."""

from typing import Iterable

from mcp.server.lowlevel.helper_types import ReadResourceContents
from mcp.types import Resource

from mcp_instructions import MCP_INSTRUCTIONS

MIME_MARKDOWN = "text/markdown"

PLAYBOOK_URI = "taskmgr://reference/playbook"
SPEC_TEMPLATE_URI = "taskmgr://templates/spec"
PROGRESS_TEMPLATE_URI = "taskmgr://templates/progress"
CLOSURE_TEMPLATE_URI = "taskmgr://templates/closure"

STATIC_RESOURCE_URIS = frozenset({
    PLAYBOOK_URI,
    SPEC_TEMPLATE_URI,
    PROGRESS_TEMPLATE_URI,
    CLOSURE_TEMPLATE_URI,
})

_RESOURCE_INDEX = """
## Pinnable MCP resources

Pin these read-only resources in your MCP host for stable session context (no tool call needed):

| URI | Use |
|-----|-----|
| taskmgr://reference/playbook | Full agent playbook (this document) |
| taskmgr://templates/spec | initial_spec / spec doc skeleton |
| taskmgr://templates/progress | progress doc skeleton |
| taskmgr://templates/closure | closure doc skeleton |
"""

PLAYBOOK = MCP_INSTRUCTIONS + _RESOURCE_INDEX

SPEC_TEMPLATE = """# Spec template

Required for `initial_spec` on `project_create` and every `task_create` (including subtasks).
Minimum 80 characters. Must include `## Objective` and `## Acceptance Criteria`.

## Objective

[One clear outcome this task or project must achieve]

## Acceptance Criteria

- [ ] [Verifiable criterion — observable done state]
- [ ] [Another criterion]
- [ ] [Tests, docs, or review requirements if applicable]

## Scope (optional)

[What is in scope and explicitly out of scope]

## Notes (optional)

[Dependencies, links, constraints, or context for future agents]
"""

PROGRESS_TEMPLATE = """# Progress template

Use with `task_record_progress` or `doc_task_update` `doc_type=progress`.
Minimum 50 characters. Update each work session — do not overwrite the spec doc.

## Status

[Current state in one sentence]

## This session

[What you implemented, investigated, or decided]

## Findings

[Important discoveries, risks, or open questions]

## Blockers

[None, or what is blocking progress and who can unblock]

## Next

[Concrete next steps for you or the next agent]
"""

CLOSURE_TEMPLATE = """# Closure template

Use with `task_complete` or `doc_task_update` `doc_type=closure`.
Minimum 80 characters. Must include `## Summary`.

## Summary

[What was delivered and how acceptance criteria were met]

## Verification

[Tests run, manual checks, screenshots, or other evidence]

## Deviations (optional)

[Scope changes or known gaps versus the original spec]

## Follow-ups (optional)

[Tech debt, monitoring, or handoff notes for humans or future agents]
"""

_CONTENT_BY_URI: dict[str, str] = {
    PLAYBOOK_URI: PLAYBOOK,
    SPEC_TEMPLATE_URI: SPEC_TEMPLATE,
    PROGRESS_TEMPLATE_URI: PROGRESS_TEMPLATE,
    CLOSURE_TEMPLATE_URI: CLOSURE_TEMPLATE,
}

_STATIC_RESOURCES: list[Resource] = [
    Resource(
        name="playbook",
        title="Task Manager Agent Playbook",
        uri=PLAYBOOK_URI,
        description="Strict lifecycle rules, session workflow, and tool guidance for agents.",
        mimeType=MIME_MARKDOWN,
    ),
    Resource(
        name="spec-template",
        title="Spec document template",
        uri=SPEC_TEMPLATE_URI,
        description="Markdown skeleton for initial_spec and task/project spec docs.",
        mimeType=MIME_MARKDOWN,
    ),
    Resource(
        name="progress-template",
        title="Progress document template",
        uri=PROGRESS_TEMPLATE_URI,
        description="Markdown skeleton for per-session progress updates.",
        mimeType=MIME_MARKDOWN,
    ),
    Resource(
        name="closure-template",
        title="Closure document template",
        uri=CLOSURE_TEMPLATE_URI,
        description="Markdown skeleton for task/project completion summaries.",
        mimeType=MIME_MARKDOWN,
    ),
]


def list_static_resources() -> list[Resource]:
    return list(_STATIC_RESOURCES)


def read_static_resource(uri: str) -> Iterable[ReadResourceContents]:
    key = str(uri)
    content = _CONTENT_BY_URI.get(key)
    if content is None:
        raise ValueError(f"Unknown resource URI: {key}")
    return [ReadResourceContents(content=content, mime_type=MIME_MARKDOWN)]
