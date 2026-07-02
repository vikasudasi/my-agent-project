# Task Management — Reference

> **Agents:** use **MCP tools** (see [SKILL.md](../SKILL.md)). The CLI section below is for humans, debugging, and explicit user-requested scripting only.

## Setup

### Prerequisites

- Python 3.10+
- Dependencies: `mcp`, `fastapi`, `uvicorn`, `jinja2`, `anyio`

### Installation

```bash
pip install mcp fastapi uvicorn jinja2 anyio
```

### Running the MCP Server (stdio)

The MCP server communicates over **stdio** — it's designed to be launched as a subprocess by the MCP client.

```bash
cd path/to/server
python mcp_server.py
```

### Running the MCP Server (HTTP/SSE)

For remote agents or MCP clients that support SSE transport (instead of spawning a subprocess):

```bash
cd path/to/server
python mcp_server.py --http --port 8000
```

Three endpoints are exposed:

| Endpoint | Purpose |
|---|---|
| `GET /sse` | Client connects here to receive server-sent events |
| `POST /messages?session_id=...` | Client posts JSON-RPC messages |
| `POST /mcp` | **Streamable HTTP** — stateless, JSON-only (no persistent connection) |

### Streamable HTTP

The `POST /mcp` endpoint implements **Streamable HTTP** (stateless, JSON-only mode).

Unlike SSE transport (which requires a long-lived connection and two endpoints), Streamable HTTP lets standard HTTP clients make MCP requests with plain POST/Response cycles:

```bash
# Example: list projects via curl
curl -X POST http://localhost:8000/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/call",
    "params": {
      "name": "project_list",
      "arguments": {}
    }
  }'
```

Each request is self-contained — the initialize/initialized handshake happens automatically within the same request cycle. No persistent SSE connection or session ID management is required.

**Use Streamable HTTP when:**
- Your client can't maintain a long-lived SSE connection
- You want to use standard HTTP tooling (curl, requests, httpx)
- You need simpler deployment in serverless/container environments

**Use SSE transport when:**
- Your MCP client (Cursor, Claude Desktop) has native SSE support
- You need streaming notifications from server to client
- You want persistent session state across requests

### Running with Docker

Build and run the all-in-one container (MCP HTTP/SSE server + SQLite):

```bash
# Build
docker build -t task-manager .

# Run with persistent volume
docker run -d -p 8000:8000 -v tm-data:/data --name tm task-manager

# Agents connect at http://<host>:8000/sse
```

See the repo root `Dockerfile` and `README.md` for full details.

### Running the Dashboard (Optional)

The web dashboard runs on **port 8000** and shares the same SQLite database:

```bash
cd path/to/server/dashboard
uvicorn app:app --reload --port 8000
```

Then open http://localhost:8000 in a browser.

### Configuring in Cursor

To use this MCP server in Cursor, add to your `.cursor/mcp.json`:

**stdio mode (local):**
```json
{
  "mcpServers": {
    "task-manager": {
      "command": "python",
      "args": ["path/to/server/mcp_server.py"]
    }
  }
}
```

**SSE mode (remote):**
```json
{
  "mcpServers": {
    "task-manager": {
      "type": "sse",
      "url": "http://your-server:8000/sse"
    }
  }
}
```

**Streamable HTTP mode (remote):**
```json
{
  "mcpServers": {
    "task-manager": {
      "type": "sse",
      "url": "http://your-server:8000/mcp"
    }
  }
}
```

Note: Some MCP clients do not distinguish between SSE and Streamable HTTP in their config — both use `"type": "sse"` with different URL paths. For explicit Streamable HTTP support, check your client's documentation. Some clients accept `"type": "streamable-http"` or `"transport": "streamable-http"`.

### Configuring in Claude Desktop

**stdio mode (local):**
```json
{
  "mcpServers": {
    "task-manager": {
      "command": "python",
      "args": ["path/to/server/mcp_server.py"]
    }
  }
}
```

**SSE mode (remote):**
```json
{
  "mcpServers": {
    "task-manager": {
      "type": "sse",
      "url": "http://your-server:8000/sse"
    }
  }
}
```

### MCP resources (pin in host)

Static read-only resources — no `api_key` required:

| URI | Content |
|-----|---------|
| `taskmgr://reference/playbook` | Agent playbook (lifecycle + tools) |
| `taskmgr://templates/spec` | Spec / `initial_spec` template |
| `taskmgr://templates/progress` | Progress doc template |
| `taskmgr://templates/closure` | Closure doc template |

List via `resources/list`; read via `resources/read`.

### MCP credentials in Cursor

Pass `TM_API_KEY` through the MCP server env block so mutations work after context resets:

```json
{
  "mcpServers": {
    "task-manager": {
      "command": "python3",
      "args": ["/absolute/path/to/server/mcp_server.py"],
      "env": {
        "TM_API_KEY": "tm_<your-key>"
      }
    }
  }
}
```

Store the key in `~/.config/task-manager/credentials.json` as backup. **Never commit** `mcp.json` with secrets.

### Workflow tools (preferred over granular calls)

| Tool | Purpose |
|------|---------|
| `session_context` | Session start — project list or `available_tasks`, optional `task_id` focus |
| `task_begin_work` | Start task — spec + comments + set `in_progress` (requires spec doc) |
| `task_record_progress` | Upsert progress doc + optional comment |
| `task_complete` | Write closure + mark completed (blocks if active subtasks) |

Read tools return `warnings` and `next_steps`. Validation errors include `remediation`.

### Strict validation (always on)

- `initial_spec` required on `project_create` and all `task_create` (incl. subtasks)
- `in_progress` requires spec; `blocked`/`failed`/`completed` have required fields (see SKILL.md)
- Parent cannot complete while subtasks are active

## CLI Usage (fallback — not for normal agent work)

The CLI wraps the same database directly — no server process needed. **Agents should use MCP instead.** Every command outputs **JSON** to stdout and echoes the entity ID to stderr for easy shell scripting.

### Capturing IDs in Shell

```bash
# Redirect: stderr → stdout, stdout → /dev/null to get the ID
PROJECT_ID=$(python cli.py project create "My App" 2>&1 >/dev/null)

# Or use --pretty to read it in the JSON
python cli.py project list --pretty
```

### Projects

| Action | CLI Command |
|---|---|
| Create | `python cli.py project create <name> [--desc "..."]` |
| List | `python cli.py project list` |
| Get | `python cli.py project get <project_id>` |
| Update | `python cli.py project update <project_id> [--name] [--desc] [--status]` |
| Delete | `python cli.py project delete <project_id>` |

### Tasks

| Action | CLI Command |
|---|---|
| Create | `python cli.py task create <project_id> <title> [--desc] [--parent] [--after]` |
| List | `python cli.py task list <project_id> [--status] [--parent]` |
| Get | `python cli.py task get <task_id>` |
| Tree | `python cli.py task tree <task_id>` |
| Subtree | `python cli.py task subtree <project_id>` |
| Update | `python cli.py task update <task_id> [--title] [--desc] [--status]` |
| Move | `python cli.py task move <task_id> [--after] [--parent]` |
| Delete | `python cli.py task delete <task_id>` |

### Documentation

| Action | CLI Command |
|---|---|
| Get project doc | `python cli.py doc project get <project_id> [--type spec\|progress\|closure]` |
| Set project doc | `python cli.py doc project set <project_id> "<markdown>" [--type spec\|progress\|closure]` |
| Get task doc | `python cli.py doc task get <task_id> [--type spec\|progress\|closure]` |
| Set task doc | `python cli.py doc task set <task_id> "<markdown>" [--type spec\|progress\|closure]` |

### Comments

| Action | CLI Command |
|---|---|
| Add a comment | `python cli.py comment add <entity_type> <entity_id> "<text>" [--author "<name>"]` |
| List comments | `python cli.py comment list <entity_type> <entity_id>` |
| Delete comment | `python cli.py comment delete <comment_id>` |

### Agent Management

| Action | CLI Command |
|---|---|
| Register agent | `python cli.py agent onboard --name "<agent_name>" --master "<user_name>"` |
| List agents | `python cli.py agent list` |
| Audit log for entity | `python cli.py agent audit <entity_type> <entity_id>` |
| Audit log by agent | `python cli.py agent audit-log --agent "<agent_name>"` |

### Database Utilities

| Action | CLI Command |
|---|---|
| Initialize | `python cli.py db init` |
| Show path | `python cli.py db path` |

### All CLI commands accept these global flags:

- `--pretty` / `-p` — Indented JSON (easier for humans to read)
- `--help` / `-h` — Show help for any subcommand

## Database

The system uses SQLite. The database file is `server/task_manager.db`.

### Schema Overview

- **projects** — `id`, `name`, `description`, `status`, timestamps
- **tasks** — `id`, `project_id`, `parent_id`, `title`, `description`, `status`, `rank` (for ordering), timestamps
- **project_docs** — `project_id`, `doc_type` (`spec`/`progress`/`closure`), `content` (markdown), `updated_at`
- **task_docs** — `task_id`, `doc_type` (`spec`/`progress`/`closure`), `content` (markdown), `updated_at`
- **comments** — `id`, `entity_type` (`task`/`project`), `entity_id`, `content`, `author`, `created_at`
- **agents** — `id`, `name`, `master_name`, `api_key` (hashed), `created_at`
- **audit_log** — `id`, `agent_name`, `master_name`, `entity_type`, `entity_id`, `action`, `field`, `old_value`, `new_value`, `created_at`

### Rank-based Ordering

Tasks use fractional indexing. Each task has a `rank` (float). To insert task C between tasks A (rank=100) and B (rank=200), the server computes rank = (100+200)/2 = 150. No renumbering needed.

## MCP tools

All tools return JSON with `{ "ok": true, "data": ... }` on success. Mutations may include `warnings`, `next_steps`; errors include `code`, `field`, `remediation`.

## API Reference

All tools return JSON with this structure:

**Success:**
```json
{
  "id": "...",
  "title": "...",
  "status": "pending",
  ...
}
```

**Error:**
```json
{
  "error": "Project 'xyz' not found"
}
```

### Project Tools

#### `project_create`

**Parameters:**
- `name` (string, required) — Project name (min 3 chars)
- `description` (string, required) — Min 40 chars
- `initial_spec` (string, required) — Markdown spec; min 80 chars, `## Objective`, `## Acceptance Criteria`
- `api_key` (string, required)

**Returns:** Created project with `docs_summary`.

---

#### `project_list`

**Parameters:** None

**Returns:** Array of project objects.

---

#### `project_get`

**Parameters:**
- `project_id` (string, required) — Project ID

**Returns:** Project with `total_tasks`, `completed_tasks`, `progress_pct`, `by_status`.

---

#### `project_update`

**Parameters:**
- `project_id` (string, required)
- `name` (string, optional)
- `description` (string, optional)
- `status` (enum, optional) — `active` | `archived` | `completed`

**Returns:** Updated project object.

---

#### `project_delete`

**Parameters:**
- `project_id` (string, required)

**Returns:** `{ "deleted": true }`

### Task Tools

#### `task_create`

**Parameters:**
- `project_id` (string, required)
- `title` (string, required)
- `description` (string, required) — Min 40 chars
- `initial_spec` (string, required) — Required for subtasks too
- `parent_id` (string, optional) — Set for subtasks
- `after_task_id` (string, optional) — Positional placement
- `api_key` (string, required)

**Returns:** Created task with `docs_summary` and `created_by`.

---

#### `task_list`

**Parameters:**
- `project_id` (string, required)
- `status` (enum, optional) — Filter by status
- `parent_id` (string, optional) — List children of a specific parent

**Returns:** Array of task objects, ordered by rank.

---

#### `task_get`

**Parameters:**
- `task_id` (string, required)

**Returns:** Task object.

---

#### `task_tree`

**Parameters:**
- `task_id` (string, required)

**Returns:** Task object with `children` array (one level deep).

---

#### `task_subtree`

**Parameters:**
- `project_id` (string, required)

**Returns:** Nested tree of all tasks, where root tasks have `children` arrays.

---

#### `task_update`

**Parameters:**
- `task_id` (string, required)
- `api_key` (string, required)
- `title`, `description` (optional)
- `status` (enum, optional) — `pending` | `in_progress` | `completed` | `blocked` | `failed` | `cancelled`
- `blocker_reason` (string, required when `status=blocked`)
- `failure_reason` (string, required when `status=failed`)
- `closure_note` (string, required when `status=completed` and no closure doc)

**Returns:** Updated task with hints. Prefer `task_begin_work` / `task_complete` for standard flow.

---

#### `session_context`

**Parameters:** `project_id` (optional), `task_id` (optional), `api_key` (optional for `is_yours`)

**Returns:** Project picker or project session with `available_tasks`, `snapshot`, `blocked_tasks`, optional `focused_task`.

---

#### `task_begin_work` / `task_record_progress` / `task_complete`

Composite workflow tools. See [SKILL.md](../SKILL.md). All require `api_key`.

---

#### `task_move`

**Parameters:**
- `task_id` (string, required)
- `after_task_id` (string, optional) — Positional placement; omit to move to end
- `parent_id` (string, optional) — New parent; set to empty string `""` for root level

**Returns:** Updated task object with new rank/parent.

---

#### `task_delete`

**Parameters:**
- `task_id` (string, required)

**Returns:** `{ "deleted": true }`

### Documentation Tools

#### `doc_project_get`

**Parameters:**
- `project_id` (string, required)
- `type` (enum, optional) — `spec` (default), `progress`, or `closure`

**Returns:** `{ "project_id": "...", "doc_type": "...", "content": "# Markdown..." }`

---

#### `doc_project_update`

**Parameters:**
- `project_id` (string, required)
- `content` (string, required) — Full markdown content
- `type` (enum, optional) — `spec` (default), `progress`, or `closure`

**Returns:** `{ "updated": true, "doc_type": "..." }`

#### `doc_task_get`

**Parameters:**
- `task_id` (string, required)
- `type` (enum, optional) — `spec` (default), `progress`, or `closure`

**Returns:** `{ "task_id": "...", "doc_type": "...", "content": "# Markdown..." }`

#### `doc_task_update`

**Parameters:**
- `task_id` (string, required)
- `content` (string, required) — Full markdown content
- `type` (enum, optional) — `spec` (default), `progress`, or `closure`

**Returns:** `{ "updated": true, "doc_type": "..." }`

### Comment Tools

#### `comment_add`

**Parameters:**
- `entity_type` (enum, required) — `project` or `task`
- `entity_id` (string, required)
- `content` (string, required) — Comment body
- `author` (string, optional) — Author name; defaults to authenticated agent

**Returns:** The created comment object.

---

#### `comment_list`

**Parameters:**
- `entity_type` (enum, required) — `project` or `task`
- `entity_id` (string, required)

**Returns:** Array of comment objects ordered by creation time.

---

#### `comment_delete`

**Parameters:**
- `comment_id` (string, required)

**Returns:** `{ "deleted": true }`

### Agent & Audit Tools

#### `agent_onboard`

**Parameters:**
- `name` (string, required) — Agent name
- `master` (string, required) — Master/user name

**Returns:** `{ "agent_id": "...", "agent_name": "...", "master_name": "...", "api_key": "...", "created_at": "..." }`

---

#### `agent_list`

**Parameters:** None (requires auth)

**Returns:** Array of registered agents.

---

#### `agent_audit`

**Parameters:**
- `entity_type` (enum, required) — `task` or `project`
- `entity_id` (string, required)

**Returns:** Array of audit log entries for the entity.

---

#### `agent_audit_log`

**Parameters:**
- `agent_name` (string, optional) — Filter by agent name

**Returns:** Array of audit log entries.