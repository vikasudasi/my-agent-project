---
name: task-management
description: Manage projects, ordered tasks/subtasks, and documentation via a local MCP server. Use when initializing a project, creating or reordering tasks, tracking progress, or writing documentation for tasks and projects. Enable this skill when working on any multi-step project that benefits from structured task management.
---

# Task Management System

This skill connects to a local **MCP server** that provides project and task management backed by SQLite. Any MCP-compatible AI agent can use it to organize, track, and document its work.

## Quick Start

1. Ensure the MCP server is running (see [reference.md](reference.md) for setup).
2. Use the commands below to manage your work.

## Available Commands

### Projects

| Command | What it does |
|---|---|
| `project_create(name, description)` | Create a new project. Returns a `project_id`. |
| `project_list()` | List all projects with current status. |
| `project_get(project_id)` | Get project details, task counts, and progress %. |
| `project_update(project_id, name?, description?, status?)` | Update project fields. Status: `active`, `archived`, `completed`. |
| `project_delete(project_id)` | Delete a project and all its tasks. |

### Tasks (Ordered + Subtasks)

| Command | What it does |
|---|---|
| `task_create(project_id, title, description?, parent_id?, after_task_id?)` | Create a task. Use `parent_id` for subtasks. Use `after_task_id` to place it after a specific sibling. |
| `task_list(project_id, status?, parent_id?)` | List tasks in order, optionally filtered. |
| `task_get(task_id)` | Get a single task's details. |
| `task_tree(task_id)` | Get a task and its full subtree of children. |
| `task_subtree(project_id)` | Get the whole project as a nested task tree. |
| `task_update(task_id, title?, description?, status?)` | Update task fields. Status: `pending`, `in_progress`, `completed`, `blocked`, `failed`, `cancelled`. |
| `task_move(task_id, after_task_id?, parent_id?)` | Reorder a task or reparent it. Set `parent_id=""` to make it a root task. |
| `task_delete(task_id)` | Delete a task (cascades to subtasks). |

### Documentation

| Command | What it does |
|---|---|
| `doc_project_get(project_id)` | Get project documentation (markdown). |
| `doc_project_update(project_id, content)` | Write project documentation (markdown). |
| `doc_task_get(task_id)` | Get task documentation (markdown). |
| `doc_task_update(task_id, content)` | Write task documentation (markdown). |

## Workflow Pattern

Here's a typical workflow for an AI agent starting a new project:

```
1. project_create("Build Authentication System", "JWT-based auth with login/signup")
   → Returns: project_id = "abc-123"

2. task_create("abc-123", "Research auth libraries",
               after_task_id=null)   → Task 1
   task_create("abc-123", "Design database schema",
               after_task_id="<task_1_id>")   → Task 2 (after Task 1)
   task_create("abc-123", "Implement JWT middleware",
               after_task_id="<task_2_id>")   → Task 3 (after Task 2)

3. task_create("abc-123", "Schema for users table",
               parent_id="<task_2_id>")   → Subtask of Task 2

4. task_update("<task_1_id>", status="completed")   → Mark done

5. doc_project_update("abc-123", "# Auth System\n## Design\n...")
   → Write documentation as you work
```

## Task Ordering

Tasks maintain their order via fractional indexing. When creating or moving:

- **Omit** `after_task_id` → appends at the end of the sibling list
- **Set** `after_task_id` → places directly after that sibling
- The system handles the math — no need to renumber

## Status Meanings

| Status | Meaning |
|---|---|
| `pending` | Not started yet |
| `in_progress` | Actively being worked on |
| `completed` | Finished successfully |
| `blocked` | Waiting on something else |
| `failed` | Attempted but didn't work |
| `cancelled` | No longer needed |

## Tips

- **Start each session** by calling `project_list()` to see what's pending, then `task_subtree(project_id)` to see what needs doing.
- **Update status** as you complete work — the dashboard will reflect it in real-time.
- **Use docs** to accumulate knowledge: design decisions, API references, lessons learned.
- **Create subtasks** to break down complex tasks into manageable steps.

For complete API details and setup instructions, see [reference.md](reference.md).
For examples of common workflows, see [examples.md](examples.md).