# AI Task Management System

A **Model Context Protocol (MCP)** server for AI agents to manage projects, ordered tasks/subtasks, and documentation — backed by SQLite with a human-friendly web dashboard.

```
                    ┌──────────────────────┐
AI Agents (Any MCP) │    MCP Server         │ ← SQLite DB
  Claude · GPT      │   (Python)            │ → Web Dashboard
  Cursor · Gemini   │   20 tools            │   (FastAPI)
                    └──────────────────────┘
       ▲                    │
       │ Copy/paste         ▼
   skill/ folder      Local machine
   (portable)
```

## Features

- **Projects** — Initialize, update, track progress
- **Ordered Tasks** — Tasks and subtasks with positional ordering (fractional indexing)
- **6 Statuses** — `pending`, `in_progress`, `completed`, `blocked`, `failed`, `cancelled`
- **Documentation** — Markdown docs for both projects and tasks
- **MCP-native** — Works with any MCP-compatible AI agent
- **Web Dashboard** — FastAPI-based UI for humans to view progress
- **Portable Skill** — Reusable skill folder for any agent to copy

## Quick Start

### 1. Install dependencies

```bash
cd server
pip install -r requirements.txt
```

### 2. Start the MCP server

```bash
python mcp_server.py
```

The server listens on **stdio** — it's designed to be launched as a subprocess by an MCP client (Cursor, Claude Desktop, etc.).

### 3. Start the Dashboard (optional)

```bash
cd dashboard
uvicorn app:app --reload --port 8000
```

Open http://localhost:8000

### 4. Configure your MCP client

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

## Project Structure

```
my-agent-project/
├── server/
│   ├── schema.sql              # Database schema
│   ├── db.py                   # SQLite data access layer
│   ├── mcp_server.py           # MCP server (20 tools)
│   ├── requirements.txt
│   └── dashboard/
│       ├── app.py              # FastAPI web dashboard
│       └── templates/          # Jinja2 HTML templates
│           ├── index.html      # Project list
│           ├── project.html    # Project detail + task tree
│           ├── task_item.html  # Recursive task component
│           └── doc.html        # Documentation editor
├── skill/
│   ├── SKILL.md                # Portable skill (copy to agents)
│   ├── reference.md            # Full API reference
│   └── examples.md             # Usage examples
└── README.md
```

## MCP Tools (20 total)

### Projects (5)
`project_create`, `project_list`, `project_get`, `project_update`, `project_delete`

### Tasks (8)
`task_create`, `task_list`, `task_get`, `task_tree`, `task_subtree`, `task_update`, `task_move`, `task_delete`

### Documentation (4)
`doc_project_get`, `doc_project_update`, `doc_task_get`, `doc_task_update`

## Using the Skill

The `skill/` folder is designed to be portable. Any AI agent can copy it to use this system:

```bash
cp -r skill/ ~/.cursor/skills/task-management/
```

Agents will then automatically know how to create projects, manage ordered tasks, and write documentation.

## License

MIT