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
- **Documentation** — Markdown docs for both projects and tasks
- **CLI** — Zero-dependency command-line interface (argparse, no extra packages)
- **MCP-native** — Works with any MCP-compatible AI agent
- **Web Dashboard** — FastAPI-based UI for humans to view progress
- **Portable Skill** — Reusable skill folder for any agent to copy

## Project Structure

```
my-agent-project/
├── server/
│   ├── schema.sql              # Database schema
│   ├── db.py                   # SQLite data access layer
│   ├── cli.py                  # Zero-dep CLI (argparse)
│   ├── mcp_server.py           # MCP server (17 tools)
│   ├── requirements.txt
│   └── dashboard/
│       ├── app.py              # FastAPI web dashboard
│       └── templates/          # Jinja2 HTML templates
├── skill/
│   ├── SKILL.md                # Portable skill (copy to agents)
│   ├── reference.md            # Full API + CLI reference
│   └── examples.md             # Usage examples
└── README.md
```

## CLI Commands (17 total)

### Projects
`python cli.py project create/list/get/update/delete`

### Tasks
`python cli.py task create/list/get/tree/subtree/update/move/delete`

### Documentation
`python cli.py doc project get/set` · `python cli.py doc task get/set`

### Database
`python cli.py db init` · `python cli.py db path`

## MCP Tools (17 total)

Same operations, accessible via MCP protocol. See [skill/reference.md](skill/reference.md) for details.

## Using the Skill

The `skill/` folder is portable. Any agent can copy it:

```bash
cp -r skill/ ~/.cursor/skills/task-management/
```

The skill documents both CLI and MCP paths.

## License

MIT