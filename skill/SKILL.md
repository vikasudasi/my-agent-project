---
name: task-management
description: Manage projects, ordered tasks/subtasks, and documentation via CLI or MCP. Use when initializing a project, creating or reordering tasks, tracking progress, or writing documentation for tasks and projects. Enable this skill when working on any multi-step project that benefits from structured task management. Prefer the CLI path for simplicity (no server process needed).
---

# Task Management System

Manage projects, ordered tasks (with subtasks), and documentation — all backed by SQLite.
Works **via CLI** (zero setup) or **via MCP** (for IDE integration).

## Access Modes

| Mode | How to use | Server needed? |
|---|---|---|
| **CLI** | `python cli.py <command>` | **No** — direct SQLite access |
| **MCP** | Via MCP client (Cursor, Claude Desktop) | Yes — `python mcp_server.py` |
| **Web** | Browser at localhost:8000 | Yes — `cd dashboard && uvicorn app:app --reload --port 8000` |

All modes share the same `server/task_manager.db` — you can switch freely.

## Quick Start (CLI — no server needed)

```bash
cd path/to/server

# Initialize the database (first time only)
python cli.py db init

# Create a project
python cli.py project create "Build Auth System" --desc "JWT-based auth"
# → Returns project_id (printed to stderr so scripts can capture it)

# Create ordered tasks
python cli.py task create <project_id> "Research libraries"
python cli.py task create <project_id> "Implement JWT" --after <task_id>

# Check progress
python cli.py project get <project_id>
```

Every command outputs **JSON** to stdout. The entity `id` is also printed to stderr so shell scripts can capture it:

```bash
PROJECT_ID=$(python cli.py project create "My App" 2>&1 >/dev/null)
```

## Available Commands

### Projects

| Action | CLI command |
|---|---|
| Create | `python cli.py project create "Name" --desc "..."` |
| List | `python cli.py project list` |
| Get (with progress) | `python cli.py project get <project_id>` |
| Update | `python cli.py project update <project_id> --status completed` |
| Delete | `python cli.py project delete <project_id>` |

### Tasks (Ordered + Subtasks)

| Action | CLI command |
|---|---|
| Create | `python cli.py task create <project_id> "Title" --desc "..." --after <tid> --parent <tid>` |
| List | `python cli.py task list <project_id> [--status pending] [--parent <tid>]` |
| Get | `python cli.py task get <task_id>` |
| Tree (task + children) | `python cli.py task tree <task_id>` |
| Subtree (full project) | `python cli.py task subtree <project_id>` |
| Update | `python cli.py task update <task_id> --status in_progress --title "New"` |
| Move | `python cli.py task move <task_id> --after <tid> --parent <tid>` |
| Delete | `python cli.py task delete <task_id>` |

### Documentation

| Action | CLI command |
|---|---|
| Get project docs | `python cli.py doc project get <project_id>` |
| Set project docs | `python cli.py doc project set <project_id> "# Markdown..."` |
| Get task docs | `python cli.py doc task get <task_id>` |
| Set task docs | `python cli.py doc task set <task_id> "# Markdown..."` |

### Database

| Action | CLI command |
|---|---|
| Initialize | `python cli.py db init` |
| Show DB path | `python cli.py db path` |

## Workflow Pattern (CLI)

Here's a typical session for an AI agent:

```bash
# 1. Start fresh — see what exists
python cli.py project list

# 2. Create a project
python cli.py project create "Authentication System" --desc "JWT-based auth"

# 3. Create ordered top-level tasks
python cli.py task create PROJECT_ID "Research auth libraries"
python cli.py task create PROJECT_ID "Design database schema" --after TASK_1_ID
python cli.py task create PROJECT_ID "Implement middleware" --after TASK_2_ID

# 4. Add subtasks to a task
python cli.py task create PROJECT_ID "Compare Passport vs JWT" --parent TASK_1_ID

# 5. Update status as work progresses
python cli.py task update TASK_1_ID --status completed
python cli.py task update TASK_3_ID --status in_progress

# 6. Write documentation
python cli.py doc project set PROJECT_ID "# Auth System\n## Design\nJWT with refresh tokens..."

# 7. Check overall progress
python cli.py project get PROJECT_ID
```

## Task Ordering

Tasks use fractional indexing. When creating or moving:

- **Omit** `--after` → task goes to the end of the sibling list
- **Set** `--after <task_id>` → task goes right after that sibling
- The system handles the math — no renumbering needed

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

- **Session start**: Run `python cli.py project list` then `python cli.py task subtree <project_id>` to see where you left off.
- **Capture IDs**: The entity ID is printed to stderr: `ID=$(python cli.py create ... 2>&1 >/dev/null)`
- **Pretty output**: Add `--pretty` or `-p` for indented JSON (useful for human reading).
- **Update as you go**: Keep statuses current — the web dashboard reflects changes in real-time.
- **Use docs**: Accumulate design decisions, API references, and lessons learned in markdown docs.

For the full API reference including all parameters, see [reference.md](reference.md).
For complete worked examples, see [examples.md](examples.md).