---
name: task-management
description: Manage projects, ordered tasks/subtasks, docs (spec/progress/closure), and comments via CLI or MCP. Use when initializing a project, creating or reordering tasks, tracking progress, writing documentation, or auditing work. Enable this skill for any multi-step project that benefits from structured task management. Prefer the CLI path for simplicity (no server process needed).
---

# Task Management System

Manage projects, ordered tasks (with subtasks), documentation (spec/progress/closure), comments, and audit trails — all backed by SQLite.
Works **via CLI** (no server needed), **via MCP** (for IDE integration), or **via Web Dashboard**.

## Access Modes

| Mode | How to use | Server needed? |
|---|---|---|
| **CLI** | `python cli.py <command>` | **No** — direct SQLite access |
| **MCP (stdio)** | Via MCP client (Cursor, Claude Desktop) | Yes — `python mcp_server.py` |
| **MCP (HTTP/SSE)** | Connect remote agents via SSE at `http://<host>:8000/sse` | Yes — `python mcp_server.py --http --port 8000` |
| **Docker** | Deploy all-in-one container with persistent DB | Yes — `docker run -p 8000:8000 task-manager` |
| **Web** | Browser at localhost:8000 | Yes — `cd dashboard && uvicorn app:app --reload --port 8000` |

All modes share the same database (`task_manager.db`) — you can switch freely.

---

## 🔑 Agent Onboarding (Required Before First Use)

Every agent must register before making any changes. This creates an identity recorded in the audit log.

### 1. Register your agent

```bash
python cli.py agent onboard --name "my-agent-name" --master "Your Name"
```

Returns:
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

### 3. Authenticate every session

```bash
export TM_API_KEY="tm_<your-key-here>"
```

You can also pass it per-command with `--api-key "tm_..."`.

### 4. Verify

```bash
python cli.py agent list --pretty
```

### 5. Lost your key?

Ask an admin to reissue it from the dashboard at **/admin/agents**.

---

## 🧠 Agent Workflow Discipline

Follow these rules **every session** to keep the system useful.

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
| Changing plans | Update the **progress** doc, not the spec |
| Completing a task | Write a closure doc, then mark complete |

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

# Create ordered tasks with spec docs
TASK_ID=$(python cli.py task create <project_id> "Research libraries" 2>&1 >/dev/null)
python cli.py doc task set $TASK_ID "# Spec\n## Objective\n..." --type spec

# Check progress
python cli.py project get <project_id>
```

Every command outputs **JSON** to stdout. The entity `id` is also printed to stderr:

```bash
PROJECT_ID=$(python cli.py project create "My App" 2>&1 >/dev/null)
```

---

## Status Meanings

| Status | Meaning |
|---|---|
| `pending` | Not started yet |
| `in_progress` | Actively being worked on |
| `completed` | Finished successfully |
| `blocked` | Waiting on something else |
| `failed` | Attempted but didn't work |
| `cancelled` | No longer needed |

## Task Ordering

Tasks use fractional indexing. When creating or moving:
- **Omit** `--after` → task goes to the end of the sibling list
- **Set** `--after <task_id>` → task goes right after that sibling
- The system handles the math — no renumbering needed

---

## 📚 Progressive Disclosure

This skill is structured so the most important information is right here. For deeper detail, refer to these companion files:

| File | When to Read | Relative Path |
|------|-------------|---------------|
| **CLI & API Reference** | When you need every parameter, tool signature, schema detail, or setup instruction | [`references/reference.md`](references/reference.md) |
| **Usage Examples** | When you want worked examples of common patterns (feature building, bugfixing, session start, shell scripting, full lifecycle with docs and comments) | [`references/examples.md`](references/examples.md) |

### Tips

- **Session start**: Run `export TM_API_KEY="..."` then `python cli.py project list` to see what exists.
- **Auth**: Set `TM_API_KEY` env var at session start. The `--api-key` flag overrides it per-command.
- **First time**: Run `python cli.py agent onboard --name "X" --master "Y"` before making any changes.
- **Save your key**: Store the onboarding response in `~/.my-agent/onboarding.json` (never in the repo).
- **Capture IDs**: The entity ID is printed to stderr: `ID=$(python cli.py create ... 2>&1 >/dev/null)`
- **Pretty output**: Add `--pretty` or `-p` for indented JSON (easier for human reading).
- **Update as you go**: Keep statuses current — the web dashboard reflects changes in real-time.
- **Three doc types**: Use `--type spec` for plans, `--type progress` for work logs, `--type closure` for summaries.
- **Comments for timeline**: Use comments for quick updates, docs for structured information.
- **Never overwrite a spec**: Write progress docs alongside it instead.
- **Web dashboard**: Run the dashboard to see task trees, doc tabs, and comment feeds in a browser.