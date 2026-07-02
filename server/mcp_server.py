"""
MCP Server for AI Task Management System.

Provides tools for projects, ordered tasks/subtasks, and documentation.
All backed by SQLite, accessible by any MCP-compatible AI agent.
"""

import json
import logging
import os
import sys
from typing import Any, Optional

import anyio
from anyio.abc import TaskStatus
from mcp.server import Server
from mcp.server.sse import SseServerTransport
from mcp.server.stdio import stdio_server
from mcp.server.streamable_http import StreamableHTTPServerTransport
from mcp.types import Tool, TextContent, CallToolResult

from db import (
    init_db,
    create_project,
    list_projects,
    get_project,
    update_project,
    delete_project,
    archive_project,
    get_project_progress,
    create_task,
    list_tasks,
    get_task,
    get_task_tree,
    get_task_subtree,
    update_task,
    move_task,
    delete_task,
    get_project_doc,
    upsert_project_doc,
    get_project_doc_meta,
    get_task_doc,
    upsert_task_doc,
    get_task_doc_meta,
    add_comment,
    list_comments,
    delete_comment,
    onboard_agent,
    validate_api_key,
    list_agents,
    log_audit,
    get_audit_log,
    get_project_audit_log,
)
from mcp_enrich import (
    enrich_project,
    enrich_task,
    enrich_task_list,
    enrich_doc_response,
    build_project_snapshot,
    list_projects_enriched,
)
from mcp_instructions import MCP_INSTRUCTIONS
from mcp_response_hints import build_hints
from mcp_tool_descriptions import DOC_TYPE_PROP, STATUS_TASK_PROP, TOOL_DESCRIPTIONS
from mcp_validation import ValidationError, validate_comment_content, validate_doc_content
from mcp_validation import (
    validate_project_create,
    validate_task_create,
    validate_project_update,
    validate_task_update,
    validate_task_delete,
    require_text,
    MIN_REASON_LEN,
)
from mcp_workflows import run_session_context, run_task_begin_work, run_task_record_progress, run_task_complete

server = Server(
    "task-manager",
    version="2.0.0",
    instructions=MCP_INSTRUCTIONS,
)

logger = logging.getLogger("mcp-server")


# API key property used by all mutation tools
_API_KEY_PROP = {
    "type": "string",
    "description": "API key for authentication. Get one via agent_onboard tool.",
}

# Tools that require authentication (read-only tools skip auth)
_MUTATION_TOOLS = {
    "project_create", "project_update", "project_delete",
    "project_archive", "project_restore",
    "task_create", "task_update", "task_move", "task_delete",
    "doc_project_update", "doc_task_update",
    "comment_add",
    "task_begin_work", "task_record_progress", "task_complete",
}

_DESC_PROP = {
    "type": "string",
    "minLength": 40,
    "description": "Required. Goal, scope boundary, and success definition (min 40 chars).",
}

_REASON_PROP = {
    "type": "string",
    "minLength": 20,
    "description": "Required when changing status or deleting. Explain why in plain language.",
}


def _tool(name: str) -> str:
    return TOOL_DESCRIPTIONS[name]


def _ok(
    data: Any,
    tool: Optional[str] = None,
    *,
    warnings: Optional[list[str]] = None,
    next_steps: Optional[list[str]] = None,
) -> CallToolResult:
    body: dict[str, Any] = {"ok": True, "data": data}
    if warnings:
        body["warnings"] = warnings
    if next_steps:
        body["next_steps"] = next_steps
    if tool:
        body["meta"] = {"tool": tool}
    return CallToolResult(
        content=[TextContent(type="text", text=json.dumps(body, indent=2, default=str))]
    )


def _ok_mutation(
    data: Any,
    tool: str,
    *,
    arguments: Optional[dict] = None,
    old: Optional[dict] = None,
    had_initial_spec: bool = False,
    wrote_closure_note: bool = False,
) -> CallToolResult:
    warnings, next_steps = build_hints(
        tool,
        data if isinstance(data, dict) else {},
        arguments=arguments,
        old=old,
        had_initial_spec=had_initial_spec,
        wrote_closure_note=wrote_closure_note,
    )
    return _ok(data, tool=tool, warnings=warnings or None, next_steps=next_steps or None)


def _err(msg: str, code: str = "ERROR", field: Optional[str] = None) -> CallToolResult:
    error: dict[str, Any] = {"code": code, "message": msg}
    if field:
        error["field"] = field
    return CallToolResult(
        content=[TextContent(type="text", text=json.dumps({"ok": False, "error": error}))],
        isError=True,
    )


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="project_create",
            description=_tool("project_create"),
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "minLength": 3,
                        "description": "Short unique project name",
                    },
                    "description": _DESC_PROP,
                    "initial_spec": {
                        "type": "string",
                        "minLength": 80,
                        "description": "Recommended. Markdown with ## Objective and ## Acceptance Criteria",
                    },
                    "api_key": _API_KEY_PROP,
                },
                "required": ["name", "description", "api_key"],
            },
        ),
        Tool(
            name="project_list",
            description=_tool("project_list"),
            inputSchema={
                "type": "object",
                "properties": {
                    "status": {
                        "type": "string",
                        "enum": ["active", "archived", "completed", "all"],
                        "description": "Filter by status (default: active)",
                    },
                    "q": {"type": "string", "description": "Search name or description"},
                    "include_progress": {
                        "type": "boolean",
                        "description": "Include task progress stats (default: true)",
                    },
                },
            },
        ),
        Tool(
            name="project_get",
            description=_tool("project_get"),
            inputSchema={
                "type": "object",
                "properties": {
                    "project_id": {"type": "string"},
                    "include_recent_activity": {
                        "type": "boolean",
                        "description": "Include last 10 audit entries (default: false)",
                    },
                },
                "required": ["project_id"],
            },
        ),
        Tool(
            name="project_snapshot",
            description=_tool("project_snapshot"),
            inputSchema={
                "type": "object",
                "properties": {
                    "project_id": {"type": "string"},
                },
                "required": ["project_id"],
            },
        ),
        Tool(
            name="project_update",
            description=_tool("project_update"),
            inputSchema={
                "type": "object",
                "properties": {
                    "project_id": {"type": "string"},
                    "name": {"type": "string", "minLength": 3},
                    "description": _DESC_PROP,
                    "status": {
                        "type": "string",
                        "enum": ["active", "archived", "completed"],
                        "description": "Prefer archived over delete",
                    },
                    "reason": _REASON_PROP,
                    "api_key": _API_KEY_PROP,
                },
                "required": ["project_id", "api_key"],
            },
        ),
        Tool(
            name="project_archive",
            description=_tool("project_archive"),
            inputSchema={
                "type": "object",
                "properties": {
                    "project_id": {"type": "string"},
                    "reason": _REASON_PROP,
                    "api_key": _API_KEY_PROP,
                },
                "required": ["project_id", "reason", "api_key"],
            },
        ),
        Tool(
            name="project_restore",
            description=_tool("project_restore"),
            inputSchema={
                "type": "object",
                "properties": {
                    "project_id": {"type": "string"},
                    "api_key": _API_KEY_PROP,
                },
                "required": ["project_id", "api_key"],
            },
        ),
        Tool(
            name="project_delete",
            description=_tool("project_delete"),
            inputSchema={
                "type": "object",
                "properties": {
                    "project_id": {"type": "string"},
                    "reason": _REASON_PROP,
                    "api_key": _API_KEY_PROP,
                },
                "required": ["project_id", "reason", "api_key"],
            },
        ),
        Tool(
            name="task_create",
            description=_tool("task_create"),
            inputSchema={
                "type": "object",
                "properties": {
                    "project_id": {"type": "string"},
                    "title": {
                        "type": "string",
                        "minLength": 3,
                        "description": "Action-oriented title",
                    },
                    "description": _DESC_PROP,
                    "parent_id": {"type": "string", "description": "Parent task ID for subtasks"},
                    "after_task_id": {"type": "string", "description": "Insert after this sibling"},
                    "initial_spec": {
                        "type": "string",
                        "minLength": 80,
                        "description": "Markdown spec with ## Objective and ## Acceptance Criteria",
                    },
                    "api_key": _API_KEY_PROP,
                },
                "required": ["project_id", "title", "description", "api_key"],
            },
        ),
        Tool(
            name="task_list",
            description=_tool("task_list"),
            inputSchema={
                "type": "object",
                "properties": {
                    "project_id": {"type": "string"},
                    "status": STATUS_TASK_PROP,
                    "parent_id": {"type": "string", "description": "List children of this task"},
                    "include_enrichment": {
                        "type": "boolean",
                        "description": "Include docs_summary and subtask_stats (default: true)",
                    },
                },
                "required": ["project_id"],
            },
        ),
        Tool(
            name="task_get",
            description=_tool("task_get"),
            inputSchema={
                "type": "object",
                "properties": {"task_id": {"type": "string"}},
                "required": ["task_id"],
            },
        ),
        Tool(
            name="task_tree",
            description=_tool("task_tree"),
            inputSchema={
                "type": "object",
                "properties": {"task_id": {"type": "string"}},
                "required": ["task_id"],
            },
        ),
        Tool(
            name="task_subtree",
            description=_tool("task_subtree"),
            inputSchema={
                "type": "object",
                "properties": {"project_id": {"type": "string"}},
                "required": ["project_id"],
            },
        ),
        Tool(
            name="task_update",
            description=_tool("task_update"),
            inputSchema={
                "type": "object",
                "properties": {
                    "task_id": {"type": "string"},
                    "title": {"type": "string", "minLength": 3},
                    "description": _DESC_PROP,
                    "status": STATUS_TASK_PROP,
                    "blocker_reason": {
                        "type": "string",
                        "minLength": 20,
                        "description": "Required when status=blocked",
                    },
                    "closure_note": {
                        "type": "string",
                        "minLength": 20,
                        "description": "Required when status=completed and no closure doc exists",
                    },
                    "api_key": _API_KEY_PROP,
                },
                "required": ["task_id", "api_key"],
            },
        ),
        Tool(
            name="task_move",
            description=_tool("task_move"),
            inputSchema={
                "type": "object",
                "properties": {
                    "task_id": {"type": "string"},
                    "after_task_id": {"type": "string"},
                    "parent_id": {
                        "type": "string",
                        "description": "New parent. Empty string = root level.",
                    },
                    "api_key": _API_KEY_PROP,
                },
                "required": ["task_id", "api_key"],
            },
        ),
        Tool(
            name="task_delete",
            description=_tool("task_delete"),
            inputSchema={
                "type": "object",
                "properties": {
                    "task_id": {"type": "string"},
                    "reason": _REASON_PROP,
                    "api_key": _API_KEY_PROP,
                },
                "required": ["task_id", "reason", "api_key"],
            },
        ),
        Tool(
            name="doc_project_get",
            description=_tool("doc_project_get"),
            inputSchema={
                "type": "object",
                "properties": {
                    "project_id": {"type": "string"},
                    "doc_type": DOC_TYPE_PROP,
                },
                "required": ["project_id"],
            },
        ),
        Tool(
            name="doc_project_update",
            description=_tool("doc_project_update"),
            inputSchema={
                "type": "object",
                "properties": {
                    "project_id": {"type": "string"},
                    "content": {"type": "string", "minLength": 50},
                    "doc_type": DOC_TYPE_PROP,
                    "api_key": _API_KEY_PROP,
                },
                "required": ["project_id", "content", "api_key"],
            },
        ),
        Tool(
            name="doc_task_get",
            description=_tool("doc_task_get"),
            inputSchema={
                "type": "object",
                "properties": {
                    "task_id": {"type": "string"},
                    "doc_type": DOC_TYPE_PROP,
                },
                "required": ["task_id"],
            },
        ),
        Tool(
            name="doc_task_update",
            description=_tool("doc_task_update"),
            inputSchema={
                "type": "object",
                "properties": {
                    "task_id": {"type": "string"},
                    "content": {"type": "string", "minLength": 50},
                    "doc_type": DOC_TYPE_PROP,
                    "api_key": _API_KEY_PROP,
                },
                "required": ["task_id", "content", "api_key"],
            },
        ),
        Tool(
            name="comment_add",
            description=_tool("comment_add"),
            inputSchema={
                "type": "object",
                "properties": {
                    "entity_type": {"type": "string", "enum": ["project", "task"]},
                    "entity_id": {"type": "string"},
                    "content": {"type": "string", "minLength": 10},
                    "author": {"type": "string", "description": "Defaults to agent name"},
                    "comment_type": {
                        "type": "string",
                        "enum": ["note", "blocker", "decision", "question"],
                    },
                    "api_key": _API_KEY_PROP,
                },
                "required": ["entity_type", "entity_id", "content", "api_key"],
            },
        ),
        Tool(
            name="comment_list",
            description=_tool("comment_list"),
            inputSchema={
                "type": "object",
                "properties": {
                    "entity_type": {"type": "string", "enum": ["project", "task"]},
                    "entity_id": {"type": "string"},
                    "limit": {"type": "integer", "description": "Max comments to return"},
                    "since": {"type": "string", "description": "ISO timestamp — only comments after this time"},
                },
                "required": ["entity_type", "entity_id"],
            },
        ),
        Tool(
            name="session_context",
            description=_tool("session_context"),
            inputSchema={
                "type": "object",
                "properties": {
                    "project_id": {
                        "type": "string",
                        "description": (
                            "Project to load session context for. Omit only to list projects "
                            "and choose one — full context is never returned without this."
                        ),
                    },
                    "project_status": {
                        "type": "string",
                        "enum": ["active", "archived", "completed", "all"],
                        "description": "Filter when listing projects without project_id (default: active)",
                    },
                    "include_snapshot": {
                        "type": "boolean",
                        "description": "Include full project snapshot when project_id is set (default: true)",
                    },
                },
            },
        ),
        Tool(
            name="task_begin_work",
            description=_tool("task_begin_work"),
            inputSchema={
                "type": "object",
                "properties": {
                    "task_id": {"type": "string"},
                    "comment_limit": {
                        "type": "integer",
                        "description": "Max recent comments to include (default: 10)",
                    },
                    "comment_since": {
                        "type": "string",
                        "description": "ISO timestamp — only comments after this time",
                    },
                    "api_key": _API_KEY_PROP,
                },
                "required": ["task_id", "api_key"],
            },
        ),
        Tool(
            name="task_record_progress",
            description=_tool("task_record_progress"),
            inputSchema={
                "type": "object",
                "properties": {
                    "task_id": {"type": "string"},
                    "content": {
                        "type": "string",
                        "minLength": 50,
                        "description": "Progress doc markdown (session findings and status)",
                    },
                    "comment": {
                        "type": "string",
                        "minLength": 10,
                        "description": "Optional timeline comment to add alongside progress doc",
                    },
                    "comment_type": {
                        "type": "string",
                        "enum": ["note", "blocker", "decision", "question"],
                    },
                    "api_key": _API_KEY_PROP,
                },
                "required": ["task_id", "content", "api_key"],
            },
        ),
        Tool(
            name="task_complete",
            description=_tool("task_complete"),
            inputSchema={
                "type": "object",
                "properties": {
                    "task_id": {"type": "string"},
                    "closure": {
                        "type": "string",
                        "minLength": 80,
                        "description": "Full closure markdown with ## Summary (preferred)",
                    },
                    "closure_note": {
                        "type": "string",
                        "minLength": 20,
                        "description": "Short summary if full closure markdown not provided",
                    },
                    "api_key": _API_KEY_PROP,
                },
                "required": ["task_id", "api_key"],
            },
        ),
        Tool(
            name="agent_onboard",
            description=_tool("agent_onboard"),
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "master_name": {"type": "string"},
                },
                "required": ["name", "master_name"],
            },
        ),
        Tool(
            name="agent_list",
            description=_tool("agent_list"),
            inputSchema={
                "type": "object",
                "properties": {"api_key": _API_KEY_PROP},
                "required": ["api_key"],
            },
        ),
        Tool(
            name="audit_log_get",
            description=_tool("audit_log_get"),
            inputSchema={
                "type": "object",
                "properties": {
                    "entity_type": {"type": "string", "enum": ["task", "project"]},
                    "entity_id": {"type": "string"},
                    "scope": {
                        "type": "string",
                        "enum": ["entity", "project_with_tasks"],
                        "description": "project_with_tasks only valid when entity_type=project",
                    },
                    "limit": {"type": "integer", "description": "Max entries (default: 50)"},
                },
                "required": ["entity_type", "entity_id"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> CallToolResult:
    try:
        agent = None
        if name in _MUTATION_TOOLS:
            api_key = arguments.get("api_key") or os.environ.get("TM_API_KEY")
            if not api_key:
                return _err(
                    "Authentication required. Provide api_key or set TM_API_KEY.",
                    code="AUTH_REQUIRED",
                )
            agent = validate_api_key(api_key)
            if not agent:
                return _err("Invalid API key. Use agent_onboard to register.", code="AUTH_INVALID")

        # ---- Projects ----
        if name == "project_create":
            validated = validate_project_create(arguments)
            result = create_project(validated["name"], validated["description"])
            if validated.get("initial_spec"):
                upsert_project_doc(result["id"], validated["initial_spec"], doc_type="spec")
            log_audit(agent["name"], agent["master_name"], "project", result["id"], "created")
            enriched = enrich_project(result)
            return _ok_mutation(
                enriched,
                name,
                arguments=arguments,
                had_initial_spec=bool(validated.get("initial_spec")),
            )

        elif name == "project_list":
            status = arguments.get("status", "active")
            status_filter = None if status == "all" else status
            include_progress = arguments.get("include_progress", True)
            result = list_projects_enriched(
                status=status_filter,
                q=arguments.get("q"),
                include_progress=include_progress,
            )
            return _ok(result, tool=name)

        elif name == "project_get":
            result = get_project_progress(arguments["project_id"])
            if not result:
                return _err(f"Project '{arguments['project_id']}' not found", code="NOT_FOUND")
            result = enrich_project(result)
            if arguments.get("include_recent_activity"):
                result["recent_activity"] = get_project_audit_log(arguments["project_id"], limit=10)
            return _ok(result, tool=name)

        elif name == "project_snapshot":
            snapshot = build_project_snapshot(arguments["project_id"])
            if not snapshot:
                return _err(f"Project '{arguments['project_id']}' not found", code="NOT_FOUND")
            return _ok(snapshot, tool=name)

        elif name == "project_update":
            old = get_project(arguments["project_id"])
            if not old:
                return _err(f"Project '{arguments['project_id']}' not found", code="NOT_FOUND")
            reason = validate_project_update(arguments, old)
            result = update_project(
                arguments["project_id"],
                name=arguments.get("name"),
                description=arguments.get("description"),
                status=arguments.get("status"),
            )
            if reason and arguments.get("status") and old.get("status") != arguments.get("status"):
                add_comment(
                    "project", arguments["project_id"],
                    f"[status_change] {reason}", author=agent["name"],
                )
            for field in ("name", "description", "status"):
                old_val = old.get(field)
                new_val = result.get(field)
                if old_val != new_val:
                    log_audit(agent["name"], agent["master_name"], "project",
                              arguments["project_id"], "updated", field,
                              str(old_val) if old_val else None,
                              str(new_val) if new_val else None)
            return _ok_mutation(
                enrich_project(result), name, arguments=arguments, old=old
            )

        elif name == "project_archive":
            reason = require_text(
                arguments.get("reason", ""), "reason", MIN_REASON_LEN, "Archive reason"
            )
            old = get_project(arguments["project_id"])
            if not old:
                return _err(f"Project '{arguments['project_id']}' not found", code="NOT_FOUND")
            result = archive_project(arguments["project_id"])
            add_comment("project", arguments["project_id"], f"[archived] {reason}", author=agent["name"])
            log_audit(agent["name"], agent["master_name"], "project",
                      arguments["project_id"], "updated", "status", old["status"], "archived")
            return _ok_mutation(enrich_project(result), name, arguments=arguments)

        elif name == "project_restore":
            old = get_project(arguments["project_id"])
            if not old:
                return _err(f"Project '{arguments['project_id']}' not found", code="NOT_FOUND")
            result = update_project(arguments["project_id"], status="active")
            log_audit(agent["name"], agent["master_name"], "project",
                      arguments["project_id"], "updated", "status", old["status"], "active")
            return _ok_mutation(enrich_project(result), name, arguments=arguments)

        elif name == "project_delete":
            reason = require_text(
                arguments.get("reason", ""), "reason", MIN_REASON_LEN, "Delete reason"
            )
            pid = arguments["project_id"]
            if not get_project(pid):
                return _err(f"Project '{pid}' not found", code="NOT_FOUND")
            add_comment("project", pid, f"[deleted] {reason}", author=agent["name"])
            delete_project(pid)
            log_audit(agent["name"], agent["master_name"], "project", pid, "deleted")
            return _ok(
                {"deleted": True, "project_id": pid},
                tool=name,
                warnings=["Project and all tasks, docs, and comments were permanently deleted."],
            )
        elif name == "task_create":
            validated = validate_task_create(arguments)
            result = create_task(
                arguments["project_id"],
                validated["title"],
                validated["description"],
                parent_id=validated.get("parent_id"),
                after_task_id=arguments.get("after_task_id"),
            )
            if not result:
                return _err(f"Project '{arguments['project_id']}' not found", code="NOT_FOUND")
            if validated.get("initial_spec"):
                upsert_task_doc(result["id"], validated["initial_spec"], doc_type="spec")
            log_audit(agent["name"], agent["master_name"], "task", result["id"], "created")
            enriched = enrich_task(result)
            enriched["created_by"] = {
                "agent_name": agent["name"],
                "master_name": agent["master_name"],
            }
            return _ok_mutation(
                enriched,
                name,
                arguments=arguments,
                had_initial_spec=bool(validated.get("initial_spec")),
            )

        elif name == "task_list":
            result = list_tasks(
                arguments["project_id"],
                status=arguments.get("status"),
                parent_id=arguments.get("parent_id"),
            )
            if arguments.get("include_enrichment", True):
                result = enrich_task_list(result)
            return _ok(result, tool=name)

        elif name == "task_get":
            result = get_task(arguments["task_id"])
            if not result:
                return _err(f"Task '{arguments['task_id']}' not found", code="NOT_FOUND")
            return _ok(enrich_task(result), tool=name)

        elif name == "task_tree":
            result = get_task_tree(arguments["task_id"])
            if not result:
                return _err(f"Task '{arguments['task_id']}' not found", code="NOT_FOUND")
            return _ok(result, tool=name)

        elif name == "task_subtree":
            result = get_task_subtree(arguments["project_id"])
            return _ok(result, tool=name)

        elif name == "task_update":
            old = get_task(arguments["task_id"])
            if not old:
                return _err(f"Task '{arguments['task_id']}' not found", code="NOT_FOUND")
            has_closure = get_task_doc_meta(arguments["task_id"], "closure") is not None
            extras = validate_task_update(arguments, old, has_closure)
            new_status = arguments.get("status")
            if new_status == "blocked" and extras.get("blocker_reason"):
                add_comment(
                    "task", arguments["task_id"],
                    f"[blocker] {extras['blocker_reason']}", author=agent["name"],
                )
            if new_status == "completed" and extras.get("closure_note"):
                upsert_task_doc(arguments["task_id"], f"## Summary\n{extras['closure_note']}", doc_type="closure")
            result = update_task(
                arguments["task_id"],
                title=arguments.get("title"),
                description=arguments.get("description"),
                status=new_status,
            )
            for field in ("title", "description", "status"):
                old_val = old.get(field)
                new_val = result.get(field)
                if old_val != new_val:
                    action = "status_changed" if field == "status" else "updated"
                    log_audit(agent["name"], agent["master_name"], "task",
                              arguments["task_id"], action, field,
                              str(old_val) if old_val else None,
                              str(new_val) if new_val else None)
            return _ok_mutation(
                enrich_task(result),
                name,
                arguments=arguments,
                old=old,
                wrote_closure_note=bool(extras.get("closure_note")),
            )
            after = arguments.get("after_task_id")
            parent = arguments.get("parent_id")
            if parent == "":
                parent = None
            old = get_task(arguments["task_id"])
            result = move_task(arguments["task_id"], after_task_id=after, parent_id=parent)
            if not result:
                return _err(f"Task '{arguments['task_id']}' not found", code="NOT_FOUND")
            if old and old.get("parent_id") != result.get("parent_id"):
                log_audit(agent["name"], agent["master_name"], "task",
                          arguments["task_id"], "moved", "parent_id",
                          old.get("parent_id"), result.get("parent_id"))
            return _ok_mutation(enrich_task(result), name, arguments=arguments)

        elif name == "task_delete":
            reason = validate_task_delete(arguments)
            tid = arguments["task_id"]
            if not get_task(tid):
                return _err(f"Task '{tid}' not found", code="NOT_FOUND")
            add_comment("task", tid, f"[deleted] {reason}", author=agent["name"])
            delete_task(tid)
            log_audit(agent["name"], agent["master_name"], "task", tid, "deleted")
            return _ok(
                {"deleted": True, "task_id": tid},
                tool=name,
                warnings=["Task and its subtasks were permanently deleted."],
            )
        elif name == "doc_project_get":
            doc_type = arguments.get("doc_type", "spec")
            meta = get_project_doc_meta(arguments["project_id"], doc_type=doc_type)
            if not get_project(arguments["project_id"]):
                return _err(f"Project '{arguments['project_id']}' not found", code="NOT_FOUND")
            return _ok(enrich_doc_response("project", arguments["project_id"], doc_type, meta), tool=name)

        elif name == "doc_project_update":
            doc_type = arguments.get("doc_type", "spec")
            content = validate_doc_content(arguments["content"], doc_type)
            ok = upsert_project_doc(arguments["project_id"], content, doc_type=doc_type)
            if not ok:
                return _err(f"Project '{arguments['project_id']}' not found", code="NOT_FOUND")
            log_audit(agent["name"], agent["master_name"], "project",
                      arguments["project_id"], "doc_updated", f"doc_{doc_type}")
            meta = get_project_doc_meta(arguments["project_id"], doc_type)
            doc_payload = {
                "updated": True,
                "project_id": arguments["project_id"],
                "doc_type": doc_type,
                "updated_at": meta["updated_at"] if meta else None,
                "char_count": len(content),
            }
            return _ok_mutation(doc_payload, name, arguments=arguments)

        elif name == "doc_task_get":
            doc_type = arguments.get("doc_type", "spec")
            if not get_task(arguments["task_id"]):
                return _err(f"Task '{arguments['task_id']}' not found", code="NOT_FOUND")
            meta = get_task_doc_meta(arguments["task_id"], doc_type=doc_type)
            return _ok(enrich_doc_response("task", arguments["task_id"], doc_type, meta), tool=name)

        elif name == "doc_task_update":
            doc_type = arguments.get("doc_type", "spec")
            content = validate_doc_content(arguments["content"], doc_type)
            ok = upsert_task_doc(arguments["task_id"], content, doc_type=doc_type)
            if not ok:
                return _err(f"Task '{arguments['task_id']}' not found", code="NOT_FOUND")
            log_audit(agent["name"], agent["master_name"], "task",
                      arguments["task_id"], "doc_updated", f"doc_{doc_type}")
            meta = get_task_doc_meta(arguments["task_id"], doc_type)
            doc_payload = {
                "updated": True,
                "task_id": arguments["task_id"],
                "doc_type": doc_type,
                "updated_at": meta["updated_at"] if meta else None,
                "char_count": len(content),
            }
            return _ok_mutation(doc_payload, name, arguments=arguments)
        elif name == "comment_add":
            content = validate_comment_content(arguments["content"])
            comment_type = arguments.get("comment_type")
            if comment_type:
                content = f"[{comment_type}] {content}"
            author = arguments.get("author") or agent["name"]
            result = add_comment(
                arguments["entity_type"],
                arguments["entity_id"],
                content,
                author=author,
            )
            log_audit(agent["name"], agent["master_name"],
                      arguments["entity_type"], arguments["entity_id"], "comment_added")
            return _ok_mutation(result, name, arguments=arguments)

        elif name == "comment_list":
            result = list_comments(
                arguments["entity_type"],
                arguments["entity_id"],
                limit=arguments.get("limit"),
                since=arguments.get("since"),
            )
            return _ok(result, tool=name)

        # ---- Workflow tools ----
        elif name == "session_context":
            result = run_session_context(
                project_id=arguments.get("project_id"),
                project_status=arguments.get("project_status", "active"),
                include_snapshot=arguments.get("include_snapshot", True),
            )
            next_steps: list[str] = []
            if result["mode"] == "select_project":
                if result["projects"]:
                    next_steps.append(
                        "Pick the project you will work on, then call session_context with project_id"
                    )
                else:
                    next_steps.append("project_create to start a new project")
            else:
                suggested = result.get("suggested_next_task")
                if suggested:
                    next_steps.append(f"task_begin_work task_id={suggested['id']}")
                else:
                    next_steps.append(f"task_create on project {result['project_id']} to add work items")
            return _ok(result, tool=name, next_steps=next_steps)

        elif name == "task_begin_work":
            payload = run_task_begin_work(
                arguments["task_id"],
                agent_name=agent["name"],
                master_name=agent["master_name"],
                comment_limit=arguments.get("comment_limit", 10),
                comment_since=arguments.get("comment_since"),
            )
            warnings = payload.pop("warnings", [])
            next_steps = ["Call task_record_progress when you have session findings"]
            if not payload["spec"]["exists"]:
                next_steps.insert(0, f"doc_task_update task_id={arguments['task_id']} doc_type=spec")
            return _ok(payload, tool=name, warnings=warnings or None, next_steps=next_steps)

        elif name == "task_record_progress":
            payload = run_task_record_progress(
                arguments["task_id"],
                arguments["content"],
                agent_name=agent["name"],
                master_name=agent["master_name"],
                comment=arguments.get("comment"),
                comment_type=arguments.get("comment_type"),
            )
            return _ok(
                payload,
                tool=name,
                next_steps=[f"task_complete task_id={arguments['task_id']} when acceptance criteria are met"],
            )

        elif name == "task_complete":
            payload = run_task_complete(
                arguments["task_id"],
                agent_name=agent["name"],
                master_name=agent["master_name"],
                closure=arguments.get("closure"),
                closure_note=arguments.get("closure_note"),
            )
            warnings = payload.pop("warnings", None)
            next_steps = payload.pop("next_steps", None)
            return _ok(payload, tool=name, warnings=warnings, next_steps=next_steps)

        # ---- Agent & Audit ----
        elif name == "agent_onboard":
            result = onboard_agent(arguments["name"], arguments["master_name"])
            if not result:
                return _err(f"Agent '{arguments['name']}' already exists.", code="CONFLICT")
            return _ok_mutation(
                {
                    "agent_id": result["id"],
                    "agent_name": result["name"],
                    "master_name": result["master_name"],
                    "api_key": result["api_key"],
                    "created_at": result["created_at"],
                },
                name,
            )

        elif name == "agent_list":
            return _ok(list_agents(), tool=name)

        elif name == "audit_log_get":
            scope = arguments.get("scope", "entity")
            limit = arguments.get("limit", 50)
            if scope == "project_with_tasks" and arguments["entity_type"] == "project":
                entries = get_project_audit_log(arguments["entity_id"], limit=limit)
            else:
                entries = get_audit_log(arguments["entity_type"], arguments["entity_id"])[:limit]
            return _ok(entries, tool=name)

        else:
            return _err(f"Unknown tool: {name}", code="UNKNOWN_TOOL")

    except ValidationError as e:
        return _err(e.message, code=e.code, field=e.field)
    except Exception as e:
        return _err(f"Error executing {name}: {str(e)}", code="INTERNAL_ERROR")


# ---------------------------------------------------------------------------
# Entry point — stdio (default)
# ---------------------------------------------------------------------------

async def main():
    init_db()
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


# ---------------------------------------------------------------------------
# Entry point — HTTP / SSE
# ---------------------------------------------------------------------------

_HTTP_DOC = """
Start the MCP server over HTTP (SSE transport).

The server exposes two endpoints:
  GET  /sse       — Client connects here to receive server-sent events
  POST /messages  — Client posts JSON-RPC messages here (session_id query param)

Use the MCP Inspector to test:
  npx @modelcontextprotocol/inspector

Or configure any MCP-compatible client with the SSE URL.
"""


def create_starlette_app() -> "Starlette":
    """Build the Starlette ASGI app with SSE + Streamable HTTP transports and CORS."""
    from starlette.applications import Starlette
    from starlette.middleware import Middleware
    from starlette.middleware.cors import CORSMiddleware
    from starlette.responses import PlainTextResponse
    from starlette.routing import Route

    sse = SseServerTransport("/messages")

    async def handle_sse(request):
        async with sse.connect_sse(
            request.scope, request.receive, request._send
        ) as (read_stream, write_stream):
            await server.run(
                read_stream,
                write_stream,
                server.create_initialization_options(),
            )

    async def handle_messages(request):
        await sse.handle_post_message(
            request.scope, request.receive, request._send
        )

    async def handle_mcp_streamable(request):
        """Handle a single MCP request via Streamable HTTP (JSON-only, stateless).
        
        Each POST is self-contained — initialize handshake, tool call, and
        response all happen within one request/response cycle.
        """
        http_transport = StreamableHTTPServerTransport(
            mcp_session_id=None,
            is_json_response_enabled=True,
        )

        async def run_server(*, task_status: TaskStatus[None]):
            async with http_transport.connect() as (read_stream, write_stream):
                task_status.started()
                try:
                    await server.run(
                        read_stream,
                        write_stream,
                        server.create_initialization_options(),
                        stateless=True,
                    )
                except BaseException:
                    logger.exception("Streamable HTTP session crashed")

        try:
            async with anyio.create_task_group() as tg:
                await tg.start(run_server)
                await http_transport.handle_request(
                    request.scope, request.receive, request._send
                )
                await http_transport.terminate()
        except BaseExceptionGroup:
            logger.exception("Unhandled TaskGroup exception in Streamable HTTP handler")
            return PlainTextResponse(
                content='{"error":"Internal server error"}',
                status_code=500,
                media_type="application/json",
            )

    return Starlette(
        debug=False,
        middleware=[
            Middleware(
                CORSMiddleware,
                allow_origins=["*"],
                allow_methods=["*"],
                allow_headers=["*"],
            ),
        ],
        routes=[
            Route("/sse", endpoint=handle_sse),
            Route("/messages", endpoint=handle_messages, methods=["POST"]),
            Route("/mcp", endpoint=handle_mcp_streamable, methods=["POST"]),
        ],
    )


async def main_http(host: str = "0.0.0.0", port: int = 8000):
    """Run the MCP server over HTTP.
    
    Exposes:
      GET  /sse, POST /messages  — SSE transport
      POST /mcp                  — Streamable HTTP (stateless, JSON-only)
    """
    import uvicorn

    init_db()
    app = create_starlette_app()
    config = uvicorn.Config(app, host=host, port=port, log_level="info")
    server_uv = uvicorn.Server(config)
    await server_uv.serve()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse
    import anyio

    parser = argparse.ArgumentParser(
        description="Task Manager MCP Server — stdio, HTTP/SSE, or Streamable HTTP"
    )
    parser.add_argument(
        "--http", action="store_true",
        help="Run over HTTP instead of stdio. "
             "Exposes: GET /sse, POST /messages (SSE), POST /mcp (Streamable HTTP)"
    )
    parser.add_argument(
        "--host", default="0.0.0.0",
        help="Host to bind (default: 0.0.0.0, only with --http)"
    )
    parser.add_argument(
        "--port", type=int, default=8000,
        help="Port to bind (default: 8000, only with --http)"
    )
    args = parser.parse_args()

    if args.http:
        anyio.run(main_http, args.host, args.port)
    else:
        anyio.run(main)
