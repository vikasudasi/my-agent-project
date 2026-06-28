# AI Task Management System

Three ways to use it — **CLI** (simplest, no server), **MCP** (IDE integration), or **Web Dashboard** (for humans).

```
                    ┌──────────────────────────────┐
                    │        Three Access Modes      │
                    │                                │
  CLI              │  MCP (Cursor/Claude)          │  Web Dashboard
  python cli.py    │  python mcp_server.py          │  localhost:8000
  (no server!)     │  (server required)             │  (server required)
                    │                                │
                    └──────────┬───────────────────┘
                               │
                               ▼
                    ┌──────────────────────┐
                    │     SQLite DB         │
                    │  task_manager.db      │
                    └──────────────────────┘
```

**All modes share the same database** — you can use the CLI from a terminal, check the dashboard in a browser, and let an IDE agent use MCP, all at the same time.

## Quick Start (CLI — Zero Setup)

The CLI needs **zero dependencies** — just Python 3.10+:

```bash
cd server

# Initialize the database (first time only)
python cli.py db init

# Create a project
python cli.py project create "Build Auth System" --desc "JWT-based auth"

# Create tasks
python cli.py task create PROJ_ID "Research"
python cli.py task create PROJ_ID "Implement" --after TASK_ID

# Check progress
python cli.py project get PROJ_ID --pretty
```

Every command outputs **JSON** (agent-friendly). Add `--pretty` for human reading.

## Quick Start (MCP — for IDE agents)

### 1. Install dependencies

```bash
cd server
pip install -r requirements.txt
```

### 2. Start the MCP server

```bash
python mcp_server.py
```

### 3. Configure your MCP client

**Cursor** — add to `.cursor/mcp.json`:

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

**Claude Desktop** — add to `claude_desktop_config.json`:

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

### HTTP/SSE Transport

The MCP server also supports **HTTP with SSE transport** for clients that can't run a local subprocess (e.g. remote agents, web-based MCP clients):

```bash
cd server
python mcp_server.py --http --port 8000
```

Two endpoints are exposed:

| Endpoint | Purpose |
|---|---|
| `GET /sse` | Client connects here to receive server-sent events |
| `POST /messages?session_id=...` | Client posts JSON-RPC messages |

**Client config** (for MCP clients that support SSE):

```json
{
  "mcpServers": {
    "task-manager": {
      "type": "sse",
      "url": "http://localhost:8000/sse"
    }
  }
}
```

Test with the [MCP Inspector](https://github.com/modelcontextprotocol/inspector):

```bash
npx @modelcontextprotocol/inspector http://localhost:8000/sse
```

## Docker (Server Deployment)

Build and run a self-contained Docker image that serves the MCP server over HTTP/SSE,
with the SQLite database persisted on a volume.

```bash
# Build the image
docker build -t task-manager .

# Run with persistent database volume
docker run -d \
  --name task-manager \
  -p 8000:8000 \
  -v tm-data:/data \
  task-manager
```

Agents connect to `http://<your-server>:8000/sse`.

### Environment Variables

| Variable | Default | Description |
|---|---|---|
| `TM_DB_PATH` | `/data/task_manager.db` | Path to the SQLite database file |

### Docker Compose

Create `docker-compose.yml`:

```yaml
version: "3.8"
services:
  task-manager:
    build: .
    container_name: task-manager
    ports:
      - "8000:8000"
    volumes:
      - tm-data:/data
    restart: unless-stopped

volumes:
  tm-data:
```

Then:

```bash
docker compose up -d
```

## Quick Start (Web Dashboard)

```bash
cd server/dashboard
uvicorn app:app --reload --port 8000
```

Open http://localhost:8000

## Features

- **Projects** — Initialize, update, track progress
- **Ordered Tasks** — Tasks and subtasks with positional ordering (fractional indexing)
- **6 Statuses** — `pending`, `in_progress`, `completed`, `blocked`, `failed`, `cancelled`
- **Documentation** — Markdown docs (spec/progress/closure) for both projects and tasks
- **Comments** — Append-only, timestamped comments on projects and tasks
- **Agent Management** — Onboard agents with scoped API keys
- **Audit Log** — Every mutation is logged with agent identity and field diffs
- **CLI** — Zero-dependency command-line interface (argparse, no extra packages)
- **MCP-native** — Works with any MCP-compatible AI agent (Cursor, Claude Desktop, etc.)
- **Web Dashboard** — FastAPI-based UI for humans to view progress
- **Portable Skill** — Reusable skill folder for any agent to copy

## Project Structure

```
my-agent-project/
├── Dockerfile                # Docker image for MCP server (HTTP/SSE)
├── .dockerignore
├── server/
│   ├── schema.sql              # Database schema
│   ├── db.py                   # SQLite data access layer
│   ├── cli.py                  # Zero-dep CLI (argparse)
│   ├── mcp_server.py           # MCP server (stdio + HTTP/SSE)
│   ├── requirements.txt
│   ├── dashboard/
│   │   ├── app.py              # FastAPI web dashboard
│   │   └── templates/          # Jinja2 HTML templates
│   └── tests/
│       ├── conftest.py
│       ├── test_cli.py
│       └── test_db.py
├── skill/
│   └── task-management/
│       ├── SKILL.md                # Portable skill (copy to agents)
│       └── references/
│           ├── reference.md        # Full API + CLI reference
│           └── examples.md         # Usage examples
└── README.md
```

## CLI Commands (26 total)

### Projects (5)
`python cli.py project create/list/get/update/delete`

### Tasks (8)
`python cli.py task create/list/get/tree/subtree/update/move/delete`

### Documentation (4)
`python cli.py doc project get/set` · `python cli.py doc task get/set`

### Comments (3)
`python cli.py comment add/list/delete`

### Agent Management (4)
`python cli.py agent onboard/list/audit/audit-log`

### Database (2)
`python cli.py db init` · `python cli.py db path`

## MCP Tools (22 total)

Same operations as the CLI, accessible via MCP protocol:

| Category | Tools |
|---|---|
| **Projects** (5) | `project_create`, `project_list`, `project_get`, `project_update`, `project_delete` |
| **Tasks** (8) | `task_create`, `task_list`, `task_get`, `task_tree`, `task_subtree`, `task_update`, `task_move`, `task_delete` |
| **Docs** (4) | `doc_project_get`, `doc_project_update`, `doc_task_get`, `doc_task_update` |
| **Comments** (2) | `comment_add`, `comment_list` |
| **Agent & Audit** (3) | `agent_onboard`, `agent_list`, `audit_log_get` |

See [skill/task-management/references/reference.md](skill/task-management/references/reference.md) for details.

## Using the Skill

The `skill/task-management/` folder is portable. Any agent can copy it:

```bash
cp -r skill/task-management/ ~/.cursor/skills/task-management/
```

The skill documents both CLI and MCP paths.

## License

MIT