"""
MCP Server for AI Task Management System.

Provides tools for projects, ordered tasks/subtasks, and documentation.
All backed by SQLite, accessible by any MCP-compatible AI agent.
"""

import json
import logging
import os
import sqlite3
import sys
from typing import Any, Optional

import bcrypt
import anyio
from anyio.abc import TaskStatus
from mcp.server import Server
from mcp.server.sse import SseServerTransport
from mcp.server.stdio import stdio_server
from mcp.server.streamable_http import StreamableHTTPServerTransport
from mcp.types import Tool, TextContent, CallToolResult, Resource
from mcp.server.lowlevel.helper_types import ReadResourceContents

from db import (
    DB_PATH,
    init_db,
    create_user,
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
    validate_api_key,
    create_agent,
    list_agents,
    list_user_agents,
    reissue_agent_key,
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
)
from mcp_instructions import MCP_INSTRUCTIONS
from mcp_resources import list_static_resources, read_static_resource
from mcp_read_hints import build_read_hints
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
    "description": "API key for authentication. Prefer Authorization: Bearer *** header via MCP client config. Get one via user_signup then agent_create.",
}

_API_KEY_OPTIONAL_PROP = {
    "type": "string",
    "description": "Optional. When valid, enables is_yours on task read responses.",
}

# Tools that require authentication (read-only tools skip auth)
_MUTATION_TOOLS = {
    "project_create", "project_update", "project_delete",
    "project_archive", "project_restore",
    "task_create", "task_update", "task_move", "task_delete",
    "doc_project_update", "doc_task_update",
    "comment_add",
    "task_begin_work", "task_record_progress", "task_complete",
    "agent_create", "agent_reissue",
}
def _bearer_token_from_request() -> Optional[str]:
    """Extract bearer token from the incoming HTTP request's Authorization header."""
    try:
        ctx = server.request_context
        req = ctx.request
        if req is not None:
            auth = req.headers.get("authorization", "")
            if auth.lower().startswith("bearer "):
                return auth[7:].strip()
    except (LookupError, AttributeError):
        pass
    return None


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

_INITIAL_SPEC_PROP = {
    "type": "string",
    "minLength": 80,
    "description": "Required. Markdown with ## Objective and ## Acceptance Criteria.",
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
    wrote_closure_note: bool = False,
) -> CallToolResult:
    warnings, next_steps = build_hints(
        tool,
        data if isinstance(data, dict) else {},
        arguments=arguments,
        old=old,
        wrote_closure_note=wrote_closure_note,
    )
    return _ok(data, tool=tool, warnings=warnings or None, next_steps=next_steps or None)


def _optional_agent(arguments: dict) -> tuple[Optional[dict], Optional[CallToolResult]]:
    """Resolve the authenticated agent, erroring on invalid/missing API key."""
    api_key = arguments.get("api_key") or _bearer_token_from_request() or os.environ.get("TM_API_KEY")
    if not api_key:
        return None, None
    agent = validate_api_key(api_key)
    if not agent:
        return None, _err("Invalid API key.", code="AUTH_INVALID")
    return agent, None


def _ok_read(
    data: Any,
    tool: str,
    *,
    arguments: Optional[dict] = None,
    agent_name: Optional[str] = None,
) -> CallToolResult:
    warnings, next_steps = build_read_hints(
        tool, data, arguments=arguments, agent_name=agent_name
    )
    return _ok(data, tool=tool, warnings=warnings or None, next_steps=next_steps or None)


def _err(
    msg: str,
    code: str = "ERROR",
    field: Optional[str] = None,
    remediation: Optional[list[str]] = None,
) -> CallToolResult:
    error: dict[str, Any] = {"code": code, "message": msg}
    if field:
        error["field"] = field
    if remediation:
        error["remediation"] = remediation
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
                    "initial_spec": _INITIAL_SPEC_PROP,
                    "api_key": _API_KEY_PROP,
                },
                "required": ["name", "description", "initial_spec"],
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
                    "api_key": _API_KEY_OPTIONAL_PROP,
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
                    "api_key": _API_KEY_OPTIONAL_PROP,
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
                "required": ["project_id"],
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
                "required": ["project_id", "reason"],
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
                "required": ["project_id"],
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
                "required": ["project_id", "reason"],
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
                    "initial_spec": _INITIAL_SPEC_PROP,
                    "api_key": _API_KEY_PROP,
                },
                "required": ["project_id", "title", "description", "initial_spec"],
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
                    "api_key": _API_KEY_OPTIONAL_PROP,
                },
                "required": ["project_id"],
            },
        ),
        Tool(
            name="task_get",
            description=_tool("task_get"),
            inputSchema={
                "type": "object",
                "properties": {
                    "task_id": {"type": "string"},
                    "api_key": _API_KEY_OPTIONAL_PROP,
                },
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
                    "failure_reason": {
                        "type": "string",
                        "minLength": 20,
                        "description": "Required when status=failed",
                    },
                    "closure_note": {
                        "type": "string",
                        "minLength": 20,
                        "description": "Required when status=completed and no closure doc exists",
                    },
                    "api_key": _API_KEY_PROP,
                },
                "required": ["task_id"],
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
                "required": ["task_id"],
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
                "required": ["task_id", "reason"],
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
                "required": ["project_id", "content"],
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
                "required": ["task_id", "content"],
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
                "required": ["entity_type", "entity_id", "content"],
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
                    "task_id": {
                        "type": "string",
                        "description": (
                            "Task you will work on this session. Use in shared projects so each "
                            "agent focuses on their own task. Returns focused_task with spec and comments."
                        ),
                    },
                    "api_key": {
                        **_API_KEY_PROP,
                        "description": (
                            "Optional. When provided, sets is_yours on available_tasks entries "
                            "for in_progress tasks you most recently started."
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
                "required": ["task_id"],
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
                "required": ["task_id", "content"],
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
                "required": ["task_id"],
            },
        ),
        Tool(
            name="user_signup",
            description="Create a new user account. Derives a username from your email. Returns the user record. Then call agent_create to onboard an agent.",
            inputSchema={
                "type": "object",
                "properties": {
                    "email": {
                        "type": "string",
                        "description": "Your email address (used to derive a username)",
                    },
                    "password": {
                        "type": "string",
                        "minLength": 8,
                        "description": "Password (min 8 characters, bcrypt-hashed)",
                    },
                },
                "required": ["email", "password"],
            },
        ),
        Tool(
            name="user_login",
            description="Authenticate a user by email and password. Returns the user record on success — use this to verify credentials before creating agents.",
            inputSchema={
                "type": "object",
                "properties": {
                    "email": {"type": "string"},
                    "password": {"type": "string"},
                },
                "required": ["email", "password"],
            },
        ),
        Tool(
            name="agent_create",
            description="Create a new agent for the currently authenticated user. Returns agent info + api_key (shown once). Requires auth — call user_signup first if you don't have an account.",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "minLength": 3, "description": "Unique agent name"},
                    "api_key": _API_KEY_PROP,
                },
                "required": ["name"],
            },
        ),
        Tool(
            name="agent_list_my",
            description="List all agents owned by the currently authenticated user. Returns an empty list if no auth is provided.",
            inputSchema={
                "type": "object",
                "properties": {
                    "api_key": _API_KEY_PROP,
                },
                "required": [],
            },
        ),
        Tool(
            name="agent_reissue",
            description="Reissue the API key for an agent owned by the authenticated user. The old key is invalidated immediately — save the new key.",
            inputSchema={
                "type": "object",
                "properties": {
                    "agent_id": {"type": "string", "description": "ID of the agent to reissue"},
                    "api_key": _API_KEY_PROP,
                },
                "required": ["agent_id"],
            },
        ),
        Tool(
            name="agent_list",
            description=_tool("agent_list"),
            inputSchema={
                "type": "object",
                "properties": {"api_key": _API_KEY_PROP},
                "required": [],
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


@server.list_resources()
async def list_resources() -> list[Resource]:
    return list_static_resources()


@server.read_resource()
async def read_resource(uri: str) -> list[ReadResourceContents]:
    return list(read_static_resource(uri))


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> CallToolResult:
    try:
        agent = None
        if name in _MUTATION_TOOLS:
            api_key = arguments.get("api_key") or _bearer_token_from_request() or os.environ.get("TM_API_KEY")
            if not api_key:
                return _err(
                    "Authentication required. Provide api_key, set Authorization bearer header, or set TM_API_KEY.",
                    code="AUTH_REQUIRED",
                )
            agent = validate_api_key(api_key)
            if not agent:
                return _err("Invalid API key.", code="AUTH_INVALID")

        # ---- Projects ----
        if name == "project_create":
            validated = validate_project_create(arguments)
            result = create_project(validated["name"], validated["description"], user_id=agent["user_id"])
            upsert_project_doc(result["id"], validated["initial_spec"], doc_type="spec", user_id=agent["user_id"])
            log_audit(agent["name"], agent["master_name"], "project", result["id"], "created", user_id=agent.get("user_id"))
            enriched = enrich_project(result)
            return _ok_mutation(enriched, name, arguments=arguments)

        elif name == "project_list":
            status = arguments.get("status", "active")
            status_filter = None if status == "all" else status
            include_progress = arguments.get("include_progress", True)
            agent_ctx, _ = _optional_agent(arguments)
            user_id = agent_ctx["user_id"] if agent_ctx else None
            result = list_projects(
                status=status_filter,
                q=arguments.get("q"),
                user_id=user_id,
            )
            if include_progress:
                result = [enrich_project(p) for p in result]
            return _ok_read(result, name, arguments=arguments)

        elif name == "project_get":
            agent_ctx, auth_err = _optional_agent(arguments)
            if auth_err:
                return auth_err
            agent_name = agent_ctx["name"] if agent_ctx else None
            user_id = agent_ctx["user_id"] if agent_ctx else None
            result = get_project_progress(arguments["project_id"], user_id=user_id)
            if not result:
                return _err(f"Project '{arguments['project_id']}' not found", code="NOT_FOUND")
            result = enrich_project(result, for_read=True)
            if arguments.get("include_recent_activity"):
                result["recent_activity"] = get_project_audit_log(arguments["project_id"], limit=10)
            return _ok_read(result, name, arguments=arguments, agent_name=agent_name)

        elif name == "project_snapshot":
            agent_ctx, auth_err = _optional_agent(arguments)
            if auth_err:
                return auth_err
            agent_name = agent_ctx["name"] if agent_ctx else None
            user_id = agent_ctx["user_id"] if agent_ctx else None
            snapshot = build_project_snapshot(
                arguments["project_id"], for_read=True, agent_name=agent_name,
                user_id=user_id,
            )
            if not snapshot:
                return _err(f"Project '{arguments['project_id']}' not found", code="NOT_FOUND")
            return _ok_read(snapshot, name, arguments=arguments, agent_name=agent_name)

        elif name == "project_update":
            old = get_project(arguments["project_id"], user_id=agent["user_id"])
            if not old:
                return _err(f"Project '{arguments['project_id']}' not found", code="NOT_FOUND")
            reason = validate_project_update(arguments, old)
            result = update_project(
                arguments["project_id"],
                name=arguments.get("name"),
                description=arguments.get("description"),
                status=arguments.get("status"),
                user_id=agent["user_id"],
            )
            if reason and arguments.get("status") and old.get("status") != arguments.get("status"):
                add_comment(
                    "project", arguments["project_id"],
                    f"[status_change] {reason}", author=agent["name"],
                    user_id=agent["user_id"],
                )
            for field in ("name", "description", "status"):
                old_val = old.get(field)
                new_val = result.get(field)
                if old_val != new_val:
                    log_audit(agent["name"], agent["master_name"], "project",
                              arguments["project_id"], "updated", field,
                              str(old_val) if old_val else None,
                              str(new_val) if new_val else None,
                              user_id=agent.get("user_id"))
            return _ok_mutation(
                enrich_project(result), name, arguments=arguments, old=old
            )

        elif name == "project_archive":
            reason = require_text(
                arguments.get("reason", ""), "reason", MIN_REASON_LEN, "Archive reason"
            )
            old = get_project(arguments["project_id"], user_id=agent["user_id"])
            if not old:
                return _err(f"Project '{arguments['project_id']}' not found", code="NOT_FOUND")
            result = archive_project(arguments["project_id"], user_id=agent["user_id"])
            add_comment("project", arguments["project_id"], f"[archived] {reason}", author=agent["name"], user_id=agent["user_id"])
            log_audit(agent["name"], agent["master_name"], "project",
                      arguments["project_id"], "updated", "status", old["status"], "archived",
                      user_id=agent.get("user_id"))
            return _ok_mutation(enrich_project(result), name, arguments=arguments)

        elif name == "project_restore":
            old = get_project(arguments["project_id"], user_id=agent["user_id"])
            if not old:
                return _err(f"Project '{arguments['project_id']}' not found", code="NOT_FOUND")
            result = update_project(arguments["project_id"], status="active", user_id=agent["user_id"])
            log_audit(agent["name"], agent["master_name"], "project",
                      arguments["project_id"], "updated", "status", old["status"], "active",
                      user_id=agent.get("user_id"))
            return _ok_mutation(enrich_project(result), name, arguments=arguments)

        elif name == "project_delete":
            reason = require_text(
                arguments.get("reason", ""), "reason", MIN_REASON_LEN, "Delete reason"
            )
            pid = arguments["project_id"]
            if not get_project(pid, user_id=agent["user_id"]):
                return _err(f"Project '{pid}' not found", code="NOT_FOUND")
            add_comment("project", pid, f"[deleted] {reason}", author=agent["name"], user_id=agent["user_id"])
            delete_project(pid, user_id=agent["user_id"])
            log_audit(agent["name"], agent["master_name"], "project", pid, "deleted", user_id=agent.get("user_id"))
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
                user_id=agent["user_id"],
            )
            if not result:
                return _err(f"Project '{arguments['project_id']}' not found", code="NOT_FOUND")
            upsert_task_doc(result["id"], validated["initial_spec"], doc_type="spec", user_id=agent["user_id"])
            log_audit(agent["name"], agent["master_name"], "task", result["id"], "created", user_id=agent.get("user_id"))
            enriched = enrich_task(result)
            enriched["created_by"] = {
                "agent_name": agent["name"],
                "master_name": agent["master_name"],
            }
            return _ok_mutation(enriched, name, arguments=arguments)

        elif name == "task_list":
            agent_ctx, auth_err = _optional_agent(arguments)
            if auth_err:
                return auth_err
            agent_name = agent_ctx["name"] if agent_ctx else None
            user_id = agent_ctx["user_id"] if agent_ctx else None
            result = list_tasks(
                arguments["project_id"],
                status=arguments.get("status"),
                parent_id=arguments.get("parent_id"),
                user_id=user_id,
            )
            if arguments.get("include_enrichment", True):
                result = enrich_task_list(result, for_read=True, agent_name=agent_name)
            return _ok_read(result, name, arguments=arguments, agent_name=agent_name)

        elif name == "task_get":
            agent_ctx, auth_err = _optional_agent(arguments)
            if auth_err:
                return auth_err
            agent_name = agent_ctx["name"] if agent_ctx else None
            user_id = agent_ctx["user_id"] if agent_ctx else None
            result = get_task(arguments["task_id"], user_id=user_id)
            if not result:
                return _err(f"Task '{arguments['task_id']}' not found", code="NOT_FOUND")
            enriched = enrich_task(
                result, for_read=True, agent_name=agent_name, comment_limit=5
            )
            return _ok_read(enriched, name, arguments=arguments, agent_name=agent_name)

        elif name == "task_tree":
            result = get_task_tree(arguments["task_id"])
            if not result:
                return _err(f"Task '{arguments['task_id']}' not found", code="NOT_FOUND")
            return _ok(result, tool=name)

        elif name == "task_subtree":
            result = get_task_subtree(arguments["project_id"])
            return _ok(result, tool=name)

        elif name == "task_update":
            old = get_task(arguments["task_id"], user_id=agent["user_id"])
            if not old:
                return _err(f"Task '{arguments['task_id']}' not found", code="NOT_FOUND")
            tid = arguments["task_id"]
            has_closure = get_task_doc_meta(tid, "closure") is not None
            has_spec = get_task_doc_meta(tid, "spec") is not None
            extras = validate_task_update(
                arguments, old, has_closure, has_spec_doc=has_spec
            )
            new_status = arguments.get("status")
            if new_status == "blocked" and extras.get("blocker_reason"):
                add_comment(
                    "task", tid,
                    f"[blocker] {extras['blocker_reason']}", author=agent["name"],
                    user_id=agent["user_id"],
                )
            if new_status == "failed" and extras.get("failure_reason"):
                add_comment(
                    "task", tid,
                    f"[failed] {extras['failure_reason']}", author=agent["name"],
                    user_id=agent["user_id"],
                )
            if new_status == "completed" and extras.get("closure_note"):
                upsert_task_doc(tid, f"## Summary\n{extras['closure_note']}", doc_type="closure", user_id=agent["user_id"])
            result = update_task(
                tid,
                title=arguments.get("title"),
                description=arguments.get("description"),
                status=new_status,
                user_id=agent["user_id"],
            )
            for field in ("title", "description", "status"):
                old_val = old.get(field)
                new_val = result.get(field)
                if old_val != new_val:
                    action = "status_changed" if field == "status" else "updated"
                    log_audit(agent["name"], agent["master_name"], "task",
                              tid, action, field,
                              str(old_val) if old_val else None,
                              str(new_val) if new_val else None,
                              user_id=agent.get("user_id"))
            return _ok_mutation(
                enrich_task(result),
                name,
                arguments=arguments,
                old=old,
                wrote_closure_note=bool(extras.get("closure_note")),
            )

        elif name == "task_move":
            parent = arguments.get("parent_id")
            if parent == "":
                parent = None
            old = get_task(arguments["task_id"], user_id=agent["user_id"])
            result = move_task(
                arguments["task_id"],
                after_task_id=arguments.get("after_task_id"),
                parent_id=parent,
                user_id=agent["user_id"],
            )
            if not result:
                return _err(f"Task '{arguments['task_id']}' not found", code="NOT_FOUND")
            if old and old.get("parent_id") != result.get("parent_id"):
                log_audit(agent["name"], agent["master_name"], "task",
                          arguments["task_id"], "moved", "parent_id",
                          old.get("parent_id"), result.get("parent_id"),
                          user_id=agent.get("user_id"))
            return _ok_mutation(enrich_task(result), name, arguments=arguments)

        elif name == "task_delete":
            reason = validate_task_delete(arguments)
            tid = arguments["task_id"]
            if not get_task(tid, user_id=agent["user_id"]):
                return _err(f"Task '{tid}' not found", code="NOT_FOUND")
            add_comment("task", tid, f"[deleted] {reason}", author=agent["name"], user_id=agent["user_id"])
            delete_task(tid, user_id=agent["user_id"])
            log_audit(agent["name"], agent["master_name"], "task", tid, "deleted", user_id=agent.get("user_id"))
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
            payload = enrich_doc_response("project", arguments["project_id"], doc_type, meta)
            return _ok_read(payload, name, arguments=arguments)

        elif name == "doc_project_update":
            doc_type = arguments.get("doc_type", "spec")
            content = validate_doc_content(arguments["content"], doc_type)
            ok = upsert_project_doc(arguments["project_id"], content, doc_type=doc_type, user_id=agent["user_id"])
            if not ok:
                return _err(f"Project '{arguments['project_id']}' not found", code="NOT_FOUND")
            log_audit(agent["name"], agent["master_name"], "project",
                      arguments["project_id"], "doc_updated", f"doc_{doc_type}",
                      user_id=agent.get("user_id"))
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
            payload = enrich_doc_response("task", arguments["task_id"], doc_type, meta)
            return _ok_read(payload, name, arguments=arguments)

        elif name == "doc_task_update":
            doc_type = arguments.get("doc_type", "spec")
            content = validate_doc_content(arguments["content"], doc_type)
            ok = upsert_task_doc(arguments["task_id"], content, doc_type=doc_type, user_id=agent["user_id"])
            if not ok:
                return _err(f"Task '{arguments['task_id']}' not found", code="NOT_FOUND")
            log_audit(agent["name"], agent["master_name"], "task",
                      arguments["task_id"], "doc_updated", f"doc_{doc_type}",
                      user_id=agent.get("user_id"))
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
                user_id=agent["user_id"],
            )
            log_audit(agent["name"], agent["master_name"],
                      arguments["entity_type"], arguments["entity_id"], "comment_added",
                      user_id=agent.get("user_id"))
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
            agent_ctx, auth_err = _optional_agent(arguments)
            if auth_err:
                return auth_err
            agent_name = agent_ctx["name"] if agent_ctx else None
            user_id = agent_ctx["user_id"] if agent_ctx else None

            result = run_session_context(
                project_id=arguments.get("project_id"),
                task_id=arguments.get("task_id"),
                project_status=arguments.get("project_status", "active"),
                include_snapshot=arguments.get("include_snapshot", True),
                agent_name=agent_name,
                user_id=user_id,
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
                chosen_task = arguments.get("task_id")
                available = result.get("available_tasks") or []
                yours = [t for t in available if t.get("is_yours")]
                if chosen_task:
                    next_steps.append(f"task_begin_work task_id={chosen_task}")
                elif len(yours) == 1:
                    next_steps.append(f"task_begin_work task_id={yours[0]['id']}  # resume your task")
                elif available:
                    next_steps.append(
                        "Pick YOUR task from available_tasks (is_yours or descriptions), "
                        "then session_context with task_id and task_begin_work"
                    )
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
                user_id=agent.get("user_id"),
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
                user_id=agent.get("user_id"),
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
                user_id=agent.get("user_id"),
            )
            warnings = payload.pop("warnings", None)
            next_steps = payload.pop("next_steps", None)
            return _ok(payload, tool=name, warnings=warnings, next_steps=next_steps)

        # ---- User & Agent Management ----
        elif name == "user_signup":
            email = arguments["email"].strip().lower()
            if len(arguments.get("password", "")) < 8:
                return _err("Password must be at least 8 characters.", code="INVALID_PARAMS")
            # Check for existing email
            with sqlite3.connect(DB_PATH) as check_conn:
                check_conn.row_factory = sqlite3.Row
                existing = check_conn.execute(
                    "SELECT id FROM users WHERE email = ?", (email,)
                ).fetchone()
            if existing:
                return _err(
                    f"A user with email '{email}' already exists.",
                    code="SV_CONFLICT",
                    remediation="Use user_login instead.",
                )
            # Derive username from email local-part
            base_username = email.split("@")[0]
            username = base_username
            suffix = 1
            with sqlite3.connect(DB_PATH) as un_conn:
                un_conn.row_factory = sqlite3.Row
                while un_conn.execute(
                    "SELECT id FROM users WHERE username = ?", (username,)
                ).fetchone():
                    username = f"{base_username}{suffix}"
                    suffix += 1
            user = create_user(username, email, arguments["password"])
            if not user:
                return _err(
                    f"Could not create user '{username}'.",
                    code="SV_CONFLICT",
                )
            return _ok_mutation(user, name, arguments=arguments)

        elif name == "user_login":
            email = arguments["email"].strip().lower()
            password = arguments["password"]
            with sqlite3.connect(DB_PATH) as conn:
                conn.row_factory = sqlite3.Row
                row = conn.execute(
                    "SELECT * FROM users WHERE email = ?", (email,)
                ).fetchone()
            if not row:
                return _err("Invalid email or password.", code="AUTH_INVALID")
            if not bcrypt.checkpw(
                password.encode("utf-8"), row["password_hash"].encode("utf-8")
            ):
                return _err("Invalid email or password.", code="AUTH_INVALID")
            return _ok_mutation(
                {
                    "id": row["id"],
                    "username": row["username"],
                    "email": row["email"],
                    "role": row["role"],
                    "created_at": row["created_at"],
                },
                name,
                arguments=arguments,
            )

        elif name == "agent_create":
            if len(arguments.get("name", "").strip()) < 3:
                return _err("Agent name must be at least 3 characters.", code="INVALID_PARAMS")
            result = create_agent(
                user_id=agent["user_id"],
                name=arguments["name"].strip(),
            )
            if not result:
                return _err(
                    f"Could not create agent '{arguments['name']}'. "
                    "The name may already be taken.",
                    code="SV_CONFLICT",
                )
            return _ok_mutation(
                {
                    "agent": {
                        "id": result["id"],
                        "name": result["name"],
                        "master_name": result["master_name"],
                        "role": result.get("role", "agent"),
                        "created_at": result.get("created_at"),
                    },
                    "api_key": result["api_key"],
                },
                name,
                arguments=arguments,
                warnings=["Save the api_key now — it will not be shown again."],
            )

        elif name == "agent_list_my":
            agent_ctx, _ = _optional_agent(arguments)
            if not agent_ctx:
                return _ok([], tool=name)
            result = list_user_agents(agent_ctx["user_id"])
            return _ok(result, tool=name)

        elif name == "agent_reissue":
            if "agent_id" not in arguments:
                return _err("agent_id is required.", code="INVALID_PARAMS")
            result = reissue_agent_key(arguments["agent_id"], agent["user_id"])
            if not result:
                return _err(
                    f"Agent '{arguments['agent_id']}' not found or not owned by you.",
                    code="NOT_FOUND",
                )
            return _ok_mutation(
                {
                    "agent": {
                        "id": result["id"],
                        "name": result["name"],
                        "master_name": result["master_name"],
                        "role": result.get("role", "agent"),
                        "created_at": result.get("created_at"),
                    },
                    "api_key": result["api_key"],
                },
                name,
                arguments=arguments,
                warnings=["Save the new api_key now — it will not be shown again."],
            )

        # ---- Agent & Audit ----
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
        return _err(e.message, code=e.code, field=e.field, remediation=e.remediation or None)
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
