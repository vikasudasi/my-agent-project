# Task Orchestrator SDK

Sequential subtask orchestration for headless CLI agents (e.g. Cursor CLI with TM MCP).

The SDK does **not** inline task specs into prompts. Each step passes only a **task ID** and tells the agent to fetch context from the task manager itself.

## Install

```bash
cd sdk
pip install -e .
```

## Prerequisites

1. Task manager DB initialized: `cd server && python3 cli.py db init`
2. Agent onboarded: `python3 cli.py agent onboard --name orchestrator --master "You"`
3. `export TM_API_KEY=tm_...` (needed when `status_mode: sdk` or parent auto-complete)
4. Headless agent (Cursor CLI) configured with task manager MCP — same as interactive use

## Quick start

```bash
# Preview work units (no agent invocation)
task-orchestrator plan --task <ROOT_TASK_ID> --config examples/orchestrator.yaml --pretty

# Dry run — writes prompts to .tm-runs/ without calling cursor
task-orchestrator run --task <ROOT_TASK_ID> --config examples/orchestrator.yaml --dry-run --pretty

# Full run
task-orchestrator run --task <ROOT_TASK_ID> --config examples/orchestrator.yaml --pretty
```

Or without installing:

```bash
cd sdk
python3 -m task_orchestrator run --task <ROOT_TASK_ID> --config examples/orchestrator.yaml
```

## How it works

1. Load YAML config (`repeat_instructions`, agent command, policies).
2. Fetch task tree via TM CLI (`task tree <id>`).
3. Walk subtasks depth-first by `rank` (skips `completed` / `cancelled`).
4. For each subtask: build minimal prompt → invoke headless agent → save log under `.tm-runs/<run_id>/`.
5. Verify task reached `completed` in TM (when `status_mode: agent`).

## Config reference

| Key | Default | Description |
|-----|---------|-------------|
| `policies.traversal` | `depth_first` | `depth_first`, `direct_children`, or `flatten` |
| `policies.status_mode` | `agent` | `agent` = worker updates TM; `sdk` = orchestrator sets status |
| `policies.on_failure` | `stop` | `stop`, `pause`, or `continue` |
| `policies.verify_completion` | `true` | After exit 0, require `task.status == completed` |
| `agent.command` | `cursor` | Headless agent binary |
| `agent.args` | see example | Args before prompt |
| `repeat_instructions` | — | Injected on every step |

## Logs

Each run creates `.tm-runs/<run_id>/`:

- `manifest.json` — planned units
- `step_<task_id>.log` — prompt, stdout, stderr, exit code
- `summary.json` — final run status

## Tests

```bash
cd sdk
pip install -e ".[dev]"
pytest tests/ -v
```

## Phase 2 (not yet)

Server-side `execution_runs` tables and MCP `run_log_append` for dashboard visibility.
