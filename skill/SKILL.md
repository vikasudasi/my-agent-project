---
name: task-management
description: Manage projects, ordered tasks/subtasks, and documentation via CLI or MCP. Use when initializing a project, creating or reordering tasks, tracking progress, or writing documentation for tasks and projects. Enable this skill when working on any multi-step project that benefits from structured task management. Prefer the CLI path for simplicity (no server process needed).
---

# Task Management System

Manage projects, ordered tasks (with subtasks), documentation (spec/progress/closure), and comments — all backed by SQLite.
Works **via CLI** (zero setup), **via MCP** (for IDE integration), or **via Web Dashboard**.

## Access Modes

| Mode | How to use | Server needed? |
|---|---|---|
| **CLI** | `python cli.py <command>` | **No** — direct SQLite access |
| **MCP** | Via MCP client (Cursor, Claude Desktop) | Yes — `python mcp_server.py` |
| **Web** | Browser at localhost:8000 | Yes — `cd dashboard && uvicorn app:app --reload --port 8000` |

All modes share the same `server/task_manager.db` — you can switch freely.

---

## 🔑 Agent Onboarding (Required Before First Use)

Every agent must register before making any changes. This creates an identity that's recorded in the audit log.

### 1. Register your agent

```bash
python cli.py agent onboard --name "my-agent-name" --master "Your Name"
```

This returns:
```json
{
  "agent_id": "uuid",
  "agent_name": "my-agent-name",
  "master_name": "Your Name",
  "api_key": "tm_<64-hex-chars>",
  "created_at": "..."
}
```

### 2. Save your credentials

Save the returned JSON to a local file **outside this repo** (e.g. `~/.my-agent/onboarding.json`). This file is **never committed to git**.

Example file structure:
```json
{
  "agent_name": "my-agent-name",
  "master_name": "Your Name",
  "api_key": "tm_...",
  "agent_id": "uuid..."
}
```

### 3. Authenticate every session

Set your API key as an environment variable at the start of each session:

```bash
export TM_API_KEY="tm_<your-key-here>"
```

All subsequent CLI commands will use this key automatically. You can also pass it per-command with `--api-key`:

```bash
python cli.py task create <id> "Title" --api-key "tm_..."
```

### 4. Verify you're authenticated

```bash
python cli.py agent list --pretty
```

This lists all registered agents. If you get an auth error, your key is missing or invalid.

### 5. Lost your key?

Ask an admin to reissue it from the dashboard at **/admin/agents**. The old key will stop working immediately.

### Audit Trail

Every mutation (create, update, delete) is logged with your `agent_name` and `master_name`. View the audit log:

```bash
python cli.py agent audit task <task_id>
python cli.py agent audit project <project_id>
python cli.py agent audit-log --agent "my-agent-name"
```

### Dashboard Access

The web dashboard at `localhost:8000` uses separate credentials. Default login: **admin / admin**. Change the password at **/admin/settings**.

---

## 🧠 Agent Workflow Discipline

This is the most important section. Follow these rules **every session** to keep the system useful.

### Before Starting Any Work

```bash
# 1. See what exists
python cli.py project list --pretty

# 2. Check current project's task tree
python cli.py task subtree <project_id> --pretty

# 3. Read the spec doc for the task you plan to work on
python cli.py doc task get <task_id> --type spec --pretty

# 4. Check recent comments for context
python cli.py comment list task <task_id> --pretty
```

### While Working

| Trigger | Action |
|---------|--------|
| Starting a task | `task update <id> --status in_progress` |
| Making progress | Write a progress doc: `doc task set <id> "..." --type progress` |
| Hitting a blocker | Comment why: `comment add task <id> "Blocked because..."` |
| Discovery/decision | Add a comment with the reasoning |
| Changing plans | Update the **progress** doc, not the spec (spec is immutable plan) |
| Completing a task | Write a closure doc, then mark complete |

### After Completing a Task

```bash
# 1. Write closure doc (what was done, decisions, outcomes)
python cli.py doc task set <task_id> "# Closure\n## Summary\n..." --type closure

# 2. Mark completed
python cli.py task update <task_id> --status completed

# 3. Add a summary comment
python cli.py comment add task <task_id> "Completed: delivered X, Y, Z" --author "agent"
```

### Documentation Lifecycle

Every task and project has **three document slots**:

| Doc Type | When to Write | Purpose | Example Content |
|----------|--------------|---------|-----------------|
| **spec** | At creation (plan) | What needs to be done, acceptance criteria | Objective, Scope, Acceptance Criteria checklist |
| **progress** | During work | What's being done, what's working/pending | Current status, findings, blockers, decisions |
| **closure** | On completion | Summary of what was delivered | What was built, key decisions, outcomes, metrics |

**Rules:**
- **Spec is written once** at creation. If requirements change, add a comment explaining why.
- **Progress is updated** as you work. It can be overwritten each session with the latest state.
- **Closure is written** once when the task is done. It should summarize the full delivery.
- Each doc type is independent — writing progress doesn't overwrite the spec.

### When to Write Comments vs Docs

| Use Comments When | Use Docs When |
|------------------|---------------|
| Quick updates during work ("Found a bug, fixing") | Structured progress report ("Milestone 1 done") |
| Questions or discussion | Final delivery summary |
| Noting a blocker | Full design documentation |
| Linking to external resources | Detailed acceptance criteria |
| Status for other team members | Things that need to survive the project |

Comments are **append-only and timestamped** — they form a timeline. Docs are **structured and replaceable** at each stage.

---

## Quick Start (CLI — no server needed)

```bash
cd path/to/server

# Initialize the database (first time only)
python cli.py db init

# Create a project
python cli.py project create "Build Auth System" --desc "JWT-based auth"
# → Returns project_id (printed to stderr so scripts can capture it)

# Create ordered tasks with spec docs
TASK_ID=$(python cli.py task create <project_id> "Research libraries" 2>&1 >/dev/null)
python cli.py doc task set $TASK_ID "# Spec\n## Objective\n..." --type spec

# Create tasks with progress tracking
python cli.py task create <project_id> "Implement JWT" --after <task_id>

# Check progress
python cli.py project get <project_id>
```

Every command outputs **JSON** to stdout. The entity `id` is also printed to stderr so shell scripts can capture it:

```bash
PROJECT_ID=$(python cli.py project create "My App" 2>&1 >/dev/null)
```

---

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

### Documentation (3 Types: spec / progress / closure)

| Action | CLI command |
|---|---|
| Get project doc | `python cli.py doc project get <project_id> [--type spec]` |
| Set project doc | `python cli.py doc project set <project_id> "..." [--type spec]` |
| Get task doc | `python cli.py doc task get <task_id> [--type spec]` |
| Set task doc | `python cli.py doc task set <task_id> "..." [--type spec]` |

Default `--type` is `spec`. Use `--type progress` or `--type closure` for other stages.

### Comments (Append-only Timeline)

| Action | CLI command |
|---|---|
| Add comment | `python cli.py comment add <entity_type> <entity_id> "text" [--author "Name"]` |
| List comments | `python cli.py comment list <entity_type> <entity_id>` |
| Delete comment | `python cli.py comment delete <comment_id>` |

`entity_type` is `project` or `task`.

### Agent & Audit

| Action | CLI command |
|---|---|
| Onboard (register) | `python cli.py agent onboard --name "agent" --master "You"` |
| List agents | `python cli.py agent list` |
| View audit for entity | `python cli.py agent audit task <task_id>` |
| View audit by agent | `python cli.py agent audit-log --agent <name>` |

**Auth**: Most commands require `TM_API_KEY` env var or `--api-key` flag. Onboard and read-only commands skip auth.

### Database

| Action | CLI command |
|---|---|
| Initialize | `python cli.py db init` |
| Show DB path | `python cli.py db path` |

---

## Workflow Pattern (CLI)

Here's a complete session following best practices:

```bash
# 1. Start fresh — see what exists
python cli.py project list
python cli.py task subtree PROJECT_ID

# 2. Pick a task and read its spec
python cli.py task get TASK_ID
python cli.py doc task get TASK_ID --type spec --pretty

# 3. Mark as in_progress and add a progress note
python cli.py task update TASK_ID --status in_progress
python cli.py doc task set TASK_ID "## Current state\nResearching libraries..." --type progress
python cli.py comment add task TASK_ID "Started work on this" --author "agent"

# 4. Complete the task
python cli.py doc task set TASK_ID "# Closure\nDelivered: compared 3 libraries..." --type closure
python cli.py task update TASK_ID --status completed
python cli.py comment add task TASK_ID "Completed: chose JWT library X" --author "agent"
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

- **Session start**: Run `export TM_API_KEY="..."` then `python cli.py project list` to see what exists.
- **Auth**: Set `TM_API_KEY` env var at session start. The `--api-key` flag overrides it per-command.
- **First time**: Run `python cli.py agent onboard --name "X" --master "Y"` before making any changes.
- **Save your key**: Store the onboarding response in `~/.my-agent/onboarding.json` (never in the repo).
- **Capture IDs**: The entity ID is printed to stderr: `ID=$(python cli.py create ... 2>&1 >/dev/null)`
- **Pretty output**: Add `--pretty` or `-p` for indented JSON (useful for human reading).
- **Update as you go**: Keep statuses current — the web dashboard reflects changes in real-time.
- **Three doc types**: Use `--type spec` for plans, `--type progress` for work logs, `--type closure` for summaries.
- **Comments for timeline**: Use comments for quick updates, docs for structured information.
- **Never overwrite a spec**: Write progress docs alongside it instead.
- **Web dashboard**: Run the dashboard to see task trees, doc tabs, and comment feeds in a browser.

For the full API reference including all parameters, see [reference.md](reference.md).
For complete worked examples, see [examples.md](examples.md).