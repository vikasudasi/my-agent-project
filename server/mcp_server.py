"""
MCP Server for AI Task Management System.

Provides tools for projects, ordered tasks/subtasks, and documentation.
All backed by SQLite, accessible by any MCP-compatible AI agent.
"""

import json
import sys
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent, CallToolResult

from db import (
    init_db,
    create_project,
    list_projects,
    get_project,
    update_project,
    delete_project,
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
    get_task_doc,
    upsert_task_doc,
    add_comment,
    list_comments,
    delete_comment,
)

server = Server("task-manager", version="1.0.0",
                instructions="Task Management System for AI Agents. "
                             "Manage projects, ordered tasks/subtasks, and documentation.")


# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------

def _ok(data: Any) -> CallToolResult:
    return CallToolResult(
        content=[TextContent(type="text", text=json.dumps(data, indent=2, default=str))]
    )


def _err(msg: str) -> CallToolResult:
    return CallToolResult(
        content=[TextContent(type="text", text=json.dumps({"error": msg}))],
        isError=True,
    )


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        # ---- Projects ----
        Tool(
            name="project_create",
            description="Create a new project. Returns the created project with its id.",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Project name"},
                    "description": {"type": "string", "description": "Optional project description"},
                },
                "required": ["name"],
            },
        ),
        Tool(
            name="project_list",
            description="List all projects with their current status.",
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
        Tool(
            name="project_get",
            description="Get project details including task progress statistics.",
            inputSchema={
                "type": "object",
                "properties": {
                    "project_id": {"type": "string", "description": "Project ID"},
                },
                "required": ["project_id"],
            },
        ),
        Tool(
            name="project_update",
            description="Update a project's name, description, or status.",
            inputSchema={
                "type": "object",
                "properties": {
                    "project_id": {"type": "string", "description": "Project ID"},
                    "name": {"type": "string", "description": "New project name"},
                    "description": {"type": "string", "description": "New description"},
                    "status": {
                        "type": "string",
                        "enum": ["active", "archived", "completed"],
                        "description": "New status",
                    },
                },
                "required": ["project_id"],
            },
        ),
        Tool(
            name="project_delete",
            description="Delete a project and all its tasks and documentation.",
            inputSchema={
                "type": "object",
                "properties": {
                    "project_id": {"type": "string", "description": "Project ID"},
                },
                "required": ["project_id"],
            },
        ),
        # ---- Tasks ----
        Tool(
            name="task_create",
            description="Create a task in a project. Can be a subtask (via parent_id) "
                        "and can be placed after a specific sibling (via after_task_id).",
            inputSchema={
                "type": "object",
                "properties": {
                    "project_id": {"type": "string", "description": "Project ID"},
                    "title": {"type": "string", "description": "Task title"},
                    "description": {"type": "string", "description": "Optional task description"},
                    "parent_id": {"type": "string", "description": "Parent task ID for subtasks"},
                    "after_task_id": {
                        "type": "string",
                        "description": "Place this task after this sibling task ID. "
                                       "Omit to append at the end.",
                    },
                },
                "required": ["project_id", "title"],
            },
        ),
        Tool(
            name="task_list",
            description="List top-level tasks in a project, optionally filtered by status.",
            inputSchema={
                "type": "object",
                "properties": {
                    "project_id": {"type": "string", "description": "Project ID"},
                    "status": {
                        "type": "string",
                        "enum": ["pending", "in_progress", "completed", "blocked", "failed", "cancelled"],
                        "description": "Filter by status",
                    },
                    "parent_id": {
                        "type": "string",
                        "description": "If provided, list children of this task instead of root tasks",
                    },
                },
                "required": ["project_id"],
            },
        ),
        Tool(
            name="task_get",
            description="Get a single task's details.",
            inputSchema={
                "type": "object",
                "properties": {
                    "task_id": {"type": "string", "description": "Task ID"},
                },
                "required": ["task_id"],
            },
        ),
        Tool(
            name="task_tree",
            description="Get a task and its full subtree of nested children.",
            inputSchema={
                "type": "object",
                "properties": {
                    "task_id": {"type": "string", "description": "Task ID"},
                },
                "required": ["task_id"],
            },
        ),
        Tool(
            name="task_subtree",
            description="Get the full hierarchical task tree for an entire project.",
            inputSchema={
                "type": "object",
                "properties": {
                    "project_id": {"type": "string", "description": "Project ID"},
                },
                "required": ["project_id"],
            },
        ),
        Tool(
            name="task_update",
            description="Update a task's title, description, or status.",
            inputSchema={
                "type": "object",
                "properties": {
                    "task_id": {"type": "string", "description": "Task ID"},
                    "title": {"type": "string", "description": "New title"},
                    "description": {"type": "string", "description": "New description"},
                    "status": {
                        "type": "string",
                        "enum": ["pending", "in_progress", "completed", "blocked", "failed", "cancelled"],
                        "description": "New status",
                    },
                },
                "required": ["task_id"],
            },
        ),
        Tool(
            name="task_move",
            description="Move a task to a new position or reparent it. "
                        "Use after_task_id to reorder among siblings.",
            inputSchema={
                "type": "object",
                "properties": {
                    "task_id": {"type": "string", "description": "Task ID to move"},
                    "after_task_id": {
                        "type": "string",
                        "description": "Place this task after this sibling. "
                                       "Omit to move to the end of the sibling list.",
                    },
                    "parent_id": {
                        "type": "string",
                        "description": "New parent task ID. Omit to keep current parent. "
                                       "Set to empty string to make it a root-level task.",
                    },
                },
                "required": ["task_id"],
            },
        ),
        Tool(
            name="task_delete",
            description="Delete a task. Will cascade to delete all subtasks too.",
            inputSchema={
                "type": "object",
                "properties": {
                    "task_id": {"type": "string", "description": "Task ID"},
                },
                "required": ["task_id"],
            },
        ),
        # ---- Documentation ----
        Tool(
            name="doc_project_get",
            description="Get the markdown documentation for a project. Specify doc_type: spec (default), progress, or closure.",
            inputSchema={
                "type": "object",
                "properties": {
                    "project_id": {"type": "string", "description": "Project ID"},
                    "doc_type": {
                        "type": "string",
                        "enum": ["spec", "progress", "closure"],
                        "description": "Doc type: spec (plan), progress (work log), closure (summary). Default: spec.",
                    },
                },
                "required": ["project_id"],
            },
        ),
        Tool(
            name="doc_project_update",
            description="Update the markdown documentation for a project. Specify doc_type: spec (default), progress, or closure.",
            inputSchema={
                "type": "object",
                "properties": {
                    "project_id": {"type": "string", "description": "Project ID"},
                    "content": {"type": "string", "description": "Markdown content"},
                    "doc_type": {
                        "type": "string",
                        "enum": ["spec", "progress", "closure"],
                        "description": "Doc type: spec (plan), progress (work log), closure (summary). Default: spec.",
                    },
                },
                "required": ["project_id", "content"],
            },
        ),
        Tool(
            name="doc_task_get",
            description="Get the markdown documentation for a task. Specify doc_type: spec (default), progress, or closure.",
            inputSchema={
                "type": "object",
                "properties": {
                    "task_id": {"type": "string", "description": "Task ID"},
                    "doc_type": {
                        "type": "string",
                        "enum": ["spec", "progress", "closure"],
                        "description": "Doc type: spec (plan), progress (work log), closure (summary). Default: spec.",
                    },
                },
                "required": ["task_id"],
            },
        ),
        Tool(
            name="doc_task_update",
            description="Update the markdown documentation for a task. Specify doc_type: spec (default), progress, or closure.",
            inputSchema={
                "type": "object",
                "properties": {
                    "task_id": {"type": "string", "description": "Task ID"},
                    "content": {"type": "string", "description": "Markdown content"},
                    "doc_type": {
                        "type": "string",
                        "enum": ["spec", "progress", "closure"],
                        "description": "Doc type: spec (plan), progress (work log), closure (summary). Default: spec.",
                    },
                },
                "required": ["task_id", "content"],
            },
        ),
        # ---- Comments ----
        Tool(
            name="comment_add",
            description="Add a comment to a project or task. Comments are append-only and timestamped.",
            inputSchema={
                "type": "object",
                "properties": {
                    "entity_type": {
                        "type": "string",
                        "enum": ["project", "task"],
                        "description": "Entity type to comment on",
                    },
                    "entity_id": {"type": "string", "description": "Entity ID"},
                    "content": {"type": "string", "description": "Comment text"},
                    "author": {"type": "string", "description": "Optional author name"},
                },
                "required": ["entity_type", "entity_id", "content"],
            },
        ),
        Tool(
            name="comment_list",
            description="List all comments for a project or task, ordered by creation time.",
            inputSchema={
                "type": "object",
                "properties": {
                    "entity_type": {
                        "type": "string",
                        "enum": ["project", "task"],
                        "description": "Entity type",
                    },
                    "entity_id": {"type": "string", "description": "Entity ID"},
                },
                "required": ["entity_type", "entity_id"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> CallToolResult:
    try:
        if name == "project_create":
            result = create_project(arguments["name"], arguments.get("description", ""))
            return _ok(result)

        elif name == "project_list":
            result = list_projects()
            return _ok(result)

        elif name == "project_get":
            result = get_project_progress(arguments["project_id"])
            if not result:
                return _err(f"Project '{arguments['project_id']}' not found")
            return _ok(result)

        elif name == "project_update":
            result = update_project(
                arguments["project_id"],
                name=arguments.get("name"),
                description=arguments.get("description"),
                status=arguments.get("status"),
            )
            if not result:
                return _err(f"Project '{arguments['project_id']}' not found")
            return _ok(result)

        elif name == "project_delete":
            ok = delete_project(arguments["project_id"])
            if not ok:
                return _err(f"Project '{arguments['project_id']}' not found")
            return _ok({"deleted": True})

        elif name == "task_create":
            parent_id = arguments.get("parent_id")
            after_id = arguments.get("after_task_id")
            result = create_task(
                arguments["project_id"],
                arguments["title"],
                arguments.get("description", ""),
                parent_id=parent_id,
                after_task_id=after_id,
            )
            if not result:
                return _err(f"Project '{arguments['project_id']}' not found")
            return _ok(result)

        elif name == "task_list":
            result = list_tasks(
                arguments["project_id"],
                status=arguments.get("status"),
                parent_id=arguments.get("parent_id"),
            )
            return _ok(result)

        elif name == "task_get":
            result = get_task(arguments["task_id"])
            if not result:
                return _err(f"Task '{arguments['task_id']}' not found")
            return _ok(result)

        elif name == "task_tree":
            result = get_task_tree(arguments["task_id"])
            if not result:
                return _err(f"Task '{arguments['task_id']}' not found")
            return _ok(result)

        elif name == "task_subtree":
            result = get_task_subtree(arguments["project_id"])
            return _ok(result)

        elif name == "task_update":
            result = update_task(
                arguments["task_id"],
                title=arguments.get("title"),
                description=arguments.get("description"),
                status=arguments.get("status"),
            )
            if not result:
                return _err(f"Task '{arguments['task_id']}' not found")
            return _ok(result)

        elif name == "task_move":
            after = arguments.get("after_task_id")
            parent = arguments.get("parent_id")
            # Allow empty string to mean "make root level"
            if parent == "":
                parent = None
            result = move_task(arguments["task_id"], after_task_id=after, parent_id=parent)
            if not result:
                return _err(f"Task '{arguments['task_id']}' not found")
            return _ok(result)

        elif name == "task_delete":
            ok = delete_task(arguments["task_id"])
            if not ok:
                return _err(f"Task '{arguments['task_id']}' not found")
            return _ok({"deleted": True})

        elif name == "doc_project_get":
            content = get_project_doc(
                arguments["project_id"],
                doc_type=arguments.get("doc_type", "spec"),
            )
            return _ok({
                "project_id": arguments["project_id"],
                "doc_type": arguments.get("doc_type", "spec"),
                "content": content,
            })

        elif name == "doc_project_update":
            ok = upsert_project_doc(
                arguments["project_id"],
                arguments["content"],
                doc_type=arguments.get("doc_type", "spec"),
            )
            if not ok:
                return _err(f"Project '{arguments['project_id']}' not found")
            return _ok({"updated": True, "doc_type": arguments.get("doc_type", "spec")})

        elif name == "doc_task_get":
            content = get_task_doc(
                arguments["task_id"],
                doc_type=arguments.get("doc_type", "spec"),
            )
            return _ok({
                "task_id": arguments["task_id"],
                "doc_type": arguments.get("doc_type", "spec"),
                "content": content,
            })

        elif name == "doc_task_update":
            ok = upsert_task_doc(
                arguments["task_id"],
                arguments["content"],
                doc_type=arguments.get("doc_type", "spec"),
            )
            if not ok:
                return _err(f"Task '{arguments['task_id']}' not found")
            return _ok({"updated": True, "doc_type": arguments.get("doc_type", "spec")})

        # ---- Comments ----
        elif name == "comment_add":
            result = add_comment(
                arguments["entity_type"],
                arguments["entity_id"],
                arguments["content"],
                author=arguments.get("author", ""),
            )
            return _ok(result)

        elif name == "comment_list":
            result = list_comments(
                arguments["entity_type"],
                arguments["entity_id"],
            )
            return _ok(result)

        else:
            return _err(f"Unknown tool: {name}")

    except Exception as e:
        return _err(f"Error executing {name}: {str(e)}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

async def main():
    init_db()
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


if __name__ == "__main__":
    import anyio
    anyio.run(main)
