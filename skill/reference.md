# Task Management — Reference

## Setup

### Prerequisites

- Python 3.10+
- Dependencies: `mcp`, `fastapi`, `uvicorn`, `jinja2`, `anyio`

### Installation

```bash
pip install mcp fastapi uvicorn jinja2 anyio
```

### Running the MCP Server

The MCP server communicates over **stdio** — it's designed to be launched as a subprocess by the MCP client.

```bash
cd path/to/server
python mcp_server.py
```

### Running the Dashboard (Optional)

The web dashboard runs on **port 8000** and shares the same SQLite database:

```bash
cd path/to/server/dashboard
uvicorn app:app --reload --port 8000
```

Then open http://localhost:8000 in a browser.

### Configuring in Cursor

To use this MCP server in Cursor, add to your `.cursor/mcp.json`:

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

### Configuring in Claude Desktop

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

## Database

The system uses SQLite. The database file is `server/task_manager.db`.

### Schema Overview

- **projects** — `id`, `name`, `description`, `status`, timestamps
- **tasks** — `id`, `project_id`, `parent_id`, `title`, `description`, `status`, `rank` (for ordering), timestamps
- **project_docs** — `project_id`, `content` (markdown), `updated_at`
- **task_docs** — `task_id`, `content` (markdown), `updated_at`

### Rank-based Ordering

Tasks use fractional indexing. Each task has a `rank` (float). To insert task C between tasks A (rank=100) and B (rank=200), the server computes rank = (100+200)/2 = 150. No renumbering needed.

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
- `name` (string, required) — Project name
- `description` (string, optional) — Description

**Returns:** The created project object.

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
- `description` (string, optional)
- `parent_id` (string, optional) — Set for subtasks
- `after_task_id` (string, optional) — Positional placement

**Returns:** The created task object.

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
- `title` (string, optional)
- `description` (string, optional)
- `status` (enum, optional) — `pending` | `in_progress` | `completed` | `blocked` | `failed` | `cancelled`

**Returns:** Updated task object.

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

**Returns:** `{ "project_id": "...", "content": "# Markdown..." }`

---

#### `doc_project_update`

**Parameters:**
- `project_id` (string, required)
- `content` (string, required) — Full markdown content

**Returns:** `{ "updated": true }`

#### `doc_task_get`

**Parameters:**
- `task_id` (string, required)

**Returns:** `{ "task_id": "...", "content": "# Markdown..." }`

#### `doc_task_update`

**Parameters:**
- `task_id` (string, required)
- `content` (string, required) — Full markdown content

**Returns:** `{ "updated": true }`