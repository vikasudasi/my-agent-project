---
name: task-management
description: Manage projects, ordered tasks/subtasks, docs (spec/progress/closure), and comments via the Task Manager MCP server. Use when planning work, tracking progress, writing structured docs, or auditing agent activity. Enable for any multi-step project. Always use MCP tools — not the CLI — unless the user explicitly asks for CLI or MCP is unavailable.
---

# Task Management System

Structured task management for AI agents and humans — projects, ordered task trees, three doc slots per entity (spec / progress / closure), comments, and a full audit trail. All data lives in one SQLite database.

## Use MCP, not the CLI

**Default for agents: MCP tools only.**

| Use MCP when | Use CLI only when |
|---|---|
| Working in Cursor or any MCP-connected IDE | User explicitly requests CLI |
| Creating, updating, or reading tasks/projects | Debugging locally without MCP server |
| Following this skill's workflow | Writing one-off shell scripts the user asked for |

The CLI exists for humans and scripting. **Do not** reach for `python cli.py …` during normal agent work — it bypasses validation hints, workflow tools, and read-path guidance the MCP server provides.

Setup and CLI fallback commands live in [`references/reference.md`](references/reference.md). Worked MCP patterns live in [`references/examples.md`](references/examples.md).

---

## Connect the MCP server

Configure once in `.cursor/mcp.json` (stdio) or point at HTTP/SSE. See [reference — Setup](references/reference.md#setup).

**Pin these read-only resources** every session (host “attach resource” UI):

| URI | Purpose |
|-----|---------|
| `taskmgr://reference/playbook` | Full lifecycle rules and tool guidance |
| `taskmgr://templates/spec` | `initial_spec` skeleton |
| `taskmgr://templates/progress` | Progress doc skeleton |
| `taskmgr://templates/closure` | Closure doc skeleton |

Server instructions at connect time mirror the playbook; pinned resources survive context resets better than chat memory.

---

## API key — persist once, verify every session

Mutations require an agent identity. **Context resets wipe chat memory — not your credential file.**

### One-time onboarding

1. Call MCP tool **`agent_onboard`** with `name` and `master_name` (only when no saved key exists).
2. Copy the returned `api_key` immediately — it is shown **once**.
3. Persist to a file **outside this repo** (never commit):

```json
{
  "agent_name": "my-agent-name",
  "master_name": "Your Name",
  "api_key": "tm_<64-hex-chars>",
  "onboarded_at": "2026-07-02T12:00:00Z"
}
```

**Recommended path:** `~/.config/task-manager/credentials.json` (mode `600`).

### Wire the key into the environment

Pick **one** (in order of preference):

1. **MCP server `env` in `.cursor/mcp.json`** (local dev, file gitignored):

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

2. **Shell profile** — `export TM_API_KEY=tm_…` in `~/.bashrc` / `~/.zshrc`.
3. **Per-call** — pass `api_key` on each mutation tool (last resort; easy to forget).

Add to **global gitignore** (user machine, not this repo): `credentials.json`, `**/task-manager/credentials.json`, `.cursor/mcp.json` if it contains secrets.

### Session-start auth ritual (after every context reset)

Do this **before any mutation**:

```
1. If TM_API_KEY is not set → read ~/.config/task-manager/credentials.json
2. Call agent_list with api_key → must return ok
3. If auth fails → STOP. Tell the user. Do NOT silently re-onboard (creates duplicate agents).
4. Pass api_key on mutations OR rely on TM_API_KEY in MCP server env
```

**Never** store the key in: repo files, task docs, comments, chat, skill files, or committed config.

### Lost key?

Human reissues from dashboard **/admin/agents** — do not run `agent_onboard` again for the same identity.

---

## Session workflow (MCP)

Read before write. Use composite tools first.

### 1. Orient

```
session_context                          → list projects, pick one
session_context project_id=<id>          → available_tasks, snapshot, blocked_tasks
                                         → pass api_key for is_yours on your tasks
session_context project_id=<id> task_id=<id>  → focused spec + recent comments
```

Read tools (`task_get`, `project_snapshot`, `task_list`) return **warnings**, **next_steps**, and inline **recent_comments** — no need to chain `comment_list` after `task_get`.

### 2. Start work

```
task_begin_work task_id=<id> api_key=…
```

Sets `in_progress` if pending, returns spec + comments + checklist. **Fails without a spec doc.**

### 3. During work

| Situation | MCP tool |
|-----------|----------|
| Session findings | `task_record_progress` (progress doc + optional comment) |
| Quick note / blocker | `comment_add` |
| Blocked | `task_update` `status=blocked` + `blocker_reason` |
| Failed attempt | `task_update` `status=failed` + `failure_reason` |
| Reorder / reparent | `task_move` |
| Fine-grained read | `doc_task_get`, `comment_list`, `audit_log_get` |

### 4. Finish

```
task_complete task_id=<id> closure_note=… api_key=…
```

Writes closure doc and marks completed. **Blocks if active subtasks remain.**

Granular alternative: `doc_task_update` `doc_type=closure` → `task_update` `status=completed`.

---

## Strict rules (always enforced)

There is no “lenient mode”. Validation errors include **`remediation`** steps.

| Rule | Detail |
|------|--------|
| **initial_spec required** | `project_create` and every `task_create` (including subtasks). Min 80 chars, `## Objective`, `## Acceptance Criteria`. |
| **Spec before work** | `task_begin_work` and `status=in_progress` require a spec doc. |
| **Parent completion** | Cannot complete a parent while any subtask is pending / in_progress / blocked. |
| **blocked** | Requires `blocker_reason` (min 20 chars). |
| **failed** | Requires `failure_reason`. |
| **completed** | Requires closure doc or `closure_note` with `## Summary`. |
| **Deletes** | Require `reason`. Prefer `project_archive` / `status=cancelled`. |

Use pinned `taskmgr://templates/*` resources when writing specs, progress, and closure content.

---

## Documentation lifecycle

Three independent doc slots per project and task:

| Doc | When | Purpose |
|-----|------|---------|
| **spec** | At creation (`initial_spec`) | Objective + acceptance criteria. **Write once.** |
| **progress** | Each work session | Current status, findings, blockers. Overwritable. |
| **closure** | On completion | `## Summary` of what was delivered. |

- Requirements changed → `comment_add` explaining why; **do not overwrite spec**.
- Progress updates go in **progress**, never in spec.

### Comments vs docs

| Comments | Docs |
|----------|------|
| Quick timeline notes, blockers, questions | Structured deliverables that survive the project |
| Append-only | spec / progress / closure slots |

---

## Status values

```
pending → in_progress → completed | blocked | failed | cancelled
```

| Status | Notes |
|--------|-------|
| `pending` | Not started |
| `in_progress` | Active — spec required |
| `blocked` | Waiting — `blocker_reason` required |
| `failed` | Attempted unsuccessfully — `failure_reason` required |
| `completed` | Done — closure required; parents blocked until subtasks terminal |
| `cancelled` | No longer needed — prefer over `task_delete` |

---

## Multi-agent projects

Several agents may share one project. Each picks **their** task from `available_tasks`:

- Pass `api_key` on `session_context` and read tools → `is_yours` marks tasks you most recently set `in_progress`.
- Do not assume exclusive ownership of a project.
- Call `task_begin_work` only on the task you intend to own this session.

---

## MCP tool map (quick reference)

| Goal | Tool |
|------|------|
| Register (once) | `agent_onboard` |
| Session orient | `session_context` |
| Start task | `task_begin_work` |
| Log session work | `task_record_progress` |
| Finish task | `task_complete` |
| Create project/task | `project_create`, `task_create` |
| Full project view | `project_snapshot` |
| Single task detail | `task_get` |
| Read/write docs | `doc_task_get`, `doc_task_update`, `doc_project_*` |
| Timeline | `comment_add`, `comment_list` |
| History | `audit_log_get` |

Full signatures and schemas: [`references/reference.md`](references/reference.md#mcp-tools).

---

## Other access modes (secondary)

| Mode | When |
|------|------|
| **Web dashboard** | Human visibility — login `admin`/`admin`, port 8000 |
| **CLI** | User-requested scripting or MCP unavailable — see reference |
| **Docker** | Remote MCP over HTTP — see reference |

All modes share `server/task_manager.db`.

---

## Progressive disclosure

| File | Read when |
|------|-----------|
| [`references/examples.md`](references/examples.md) | Worked MCP flows (feature build, session start, full lifecycle) |
| [`references/reference.md`](references/reference.md) | Setup, every tool parameter, CLI fallback, Docker |

### Session checklist (copy mentally each reset)

- [ ] Credentials file or `TM_API_KEY` available; `agent_list` succeeds
- [ ] Playbook resource pinned (`taskmgr://reference/playbook`)
- [ ] `session_context` before creating anything new
- [ ] `task_begin_work` before code changes
- [ ] `task_record_progress` before ending session
- [ ] `task_complete` when acceptance criteria met
- [ ] Never put API keys in repo, docs, or comments
