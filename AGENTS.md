# AGENTS.md

## Cursor Cloud specific instructions

This repo is the **AI Task Management System** — a Python app with three interfaces that all share one SQLite DB (`server/task_manager.db`):

- **CLI** — `server/cli.py` (pure stdlib, JSON output; add `--pretty`)
- **MCP server** — `server/mcp_server.py` (stdio, or `--http --port <port>`)
- **Web dashboard** — `server/dashboard/app.py` (FastAPI + Jinja2, login `admin`/`admin`)

Standard build/run/test commands live in `README.md` (Development section). Run all commands from the `server/` directory. There is no separate build step and no configured linter.

Non-obvious notes for future agents:

- **Tests:** `cd server && python3 -m pytest`. The CLI integration tests in `tests/test_cli.py` spawn `cli.py` as a subprocess, and that subprocess uses the **real** DB (`server/task_manager.db`), not the isolated test DB. If that DB has never been initialized you'll see `json.decoder.JSONDecodeError` failures. Run `python3 cli.py db init` once first so the CLI subprocess tests pass. `test_db.py` / `test_mcp_validation.py` use an isolated test DB and don't need this.
- **Port conflict:** both the dashboard and the MCP HTTP server default to port `8000`. To run them simultaneously, put one on a different port, e.g. `python3 mcp_server.py --http --port 8001`.
- **CLI mutations require auth:** onboard an agent first (`python3 cli.py agent onboard --name <n> --master <m>`) and pass the returned key via the `TM_API_KEY` env var. `agent onboard` and `db init` need no auth.
- **DB path override:** set `TM_DB_PATH` to point the CLI/server at a different SQLite file.
- Dependencies install to the user site (`~/.local`); invoke tools via `python3 -m ...` / `python3 <script>.py` so PATH doesn't matter.
