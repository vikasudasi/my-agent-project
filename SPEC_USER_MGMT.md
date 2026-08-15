# Task Management System — User Management Overhaul

## Current Architecture

```
agents (id, name, master_name, api_key_hash, role, active)
projects (id, name, description, status, created_at, updated_at)   ← NO user scope
tasks (id, project_id, parent_id, title, description, status, rank, ...)
```

**Problems:**
- No `users` table — agents are standalone, not owned by anyone
- `master_name` is just a text label (not a FK), leading to 10+ different spellings (vik, Vik, vikasudasi, Vikas Udasi…)
- Projects/tasks have no owner — everything is globally visible
- 27 agents from repeated re-onboardings, all active, most unused
- Dashboard has hardcoded `admin/admin`
- Auth flow: API key → agent lookup → no user context

**Goal:** Self-serve user signup → onboard agents → scope everything to user.

---

## Target Architecture

```
users (id, username, email, password_hash, role, created_at)
agents (id, user_id→users, name, api_key_hash, role, active)    ← user_id added
projects (…, user_id→users)                                      ← user_id added
tasks unchanged (scope via project.user_id)
```

**Auth flow:** `Authorization: Bearer <agent_key>` → agent lookup → user lookup → user-scoped CRUD.

---

## Phases

### Phase 1: Schema + Migration
- Add `users` table with `id, username, email, password_hash, role(admin|user), created_at`
- Add `user_id TEXT REFERENCES users(id)` to `agents` table
- Add `user_id TEXT NOT NULL REFERENCES users(id)` to `projects` table
- Create admin user: `username=vikasudasi, email=vikasudasi@gmail.com, role=admin`
- Migrate hermes agent (`agent:hermes`): set user_id → admin
- Migrate all 110 projects: set user_id → admin
- Delete all other 26 agents (non-hermes)
- Migration script: `server/migrate_user_management.py`

### Phase 2: User Management APIs (db.py + MCP tools)
- `db.create_user(username, email, password)` → returns user (password hashed with bcrypt)
- `db.validate_user(username, password)` → returns user or None
- `db.get_user(user_id)` → user dict
- `db.create_agent(user_id, name)` → new agent owned by user (api key generated)
- `db.list_user_agents(user_id)` → user's agents
- `db.reissue_agent_key(agent_id, user_id)` → reissue (must own agent)
- Remove `db.onboard_agent()` (global, not user-scoped) — keep for backward compat during migration
- New MCP tools: `user_signup`, `user_login`, `agent_create`, `agent_list_my` (user-scoped), `agent_reissue`
- Remove MCP tool: `agent_onboard` (replaced by user_signup → agent_create)

### Phase 3: User-Scoped Data Access
- All project APIs filter by `user_id`:
  - `list_projects()` → takes `user_id`, returns only user's projects
  - `get_project()` → takes `user_id`, 404 if not owned
  - All mutation tools verify project ownership
- Task APIs inherit user scope via `project.user_id`
- `agent_list` (admin) → shows all agents with user info
- Audit log: add `user_id` references for filtering
- Session context: `available_tasks` scoped to user

### Phase 4: Dashboard Overhaul
- Replace hardcoded `admin/admin` with real user login
- Login page (username + password)
- Session-based auth (signed cookies or JWT)
- Dashboard shows only logged-in user's projects/agents
- Admin role sees all (future)

### Phase 5: Tests + Cleanup
- Update all test fixtures for user-scoped data
- `test_mcp_workflows.py` — add user context to test setup
- `test_mcp_validation.py` — verify user-scoped access control
- `test_db.py` — user CRUD, auth tests
- `test_dashboard_ui.py` — login flow tests
- Remove `agent_onboard` tests, add `user_signup` + `agent_create` tests

---

## Detailed Specs

### users table schema:
```sql
CREATE TABLE users (
    id TEXT PRIMARY KEY,
    username TEXT NOT NULL UNIQUE,
    email TEXT NOT NULL DEFAULT '',
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'user' CHECK(role IN ('admin', 'user')),
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
```

### agents table change:
```sql
-- ADD column
ALTER TABLE agents ADD COLUMN user_id TEXT REFERENCES users(id);
-- Migrate: UPDATE agents SET user_id = '<admin_id>' WHERE name = 'hermes';
-- Delete: DELETE FROM agents WHERE user_id IS NULL;
```

### projects table change:
```sql
-- ADD column (NOT NULL requires a default for migration)
ALTER TABLE projects ADD COLUMN user_id TEXT NOT NULL DEFAULT '';
-- Migrate: UPDATE projects SET user_id = '<admin_id>';
```

### Auth chain update:
```
_bearer_token_from_request() → header
arguments.get("api_key") → explicit arg
os.environ.get("TM_API_KEY") → env fallback
→ validate_api_key(key) → {agent_id, agent_name, user_id, user_name, user_role}
→ user_id used for all subsequent DB ops
```

### Model changes in db.py:
- All `create_*`, `list_*`, `get_*`, `update_*`, `delete_*` for projects/tasks take `user_id`
- `validate_api_key()` returns enriched dict with user context
- New CRUD for users, user-scoped agents
- `onboard_agent()` deprecated, kept for migration script only

### MCP tools to ADD:
```yaml
user_signup:
  args: {username, email, password}
  auth: none (public)
user_login:
  args: {username, password}
  auth: none (public) — returns user info + session token
agent_create:
  args: {name}
  auth: user (from header/api_key) — creates agent under authenticated user
  returns: agent info + api_key (plaintext, shown once)
agent_list_my:
  args: {}
  auth: user — lists authenticated user's agents
agent_reissue:
  args: {agent_id}
  auth: user — reissues key for agent owned by user
```

### MCP tools to REMOVE/DEPRECATE:
```yaml
agent_onboard:
  replaced by: user_signup → agent_create
```

### Config update:
- `~/.hermes/config.yaml` — no change needed (same `Authorization: Bearer ${MCP_...}`)
- systemd unit: remove `TM_API_KEY` hardcode? (keep for now as fallback, flag for later)

### Data migration (one-time):
1. Create admin user `vikasudasi` with secure password
2. Migrate hermes agent → admin user
3. Migrate all 110 projects → admin user
4. Delete 26 non-hermes agents
5. Add `user_id` NOT NULL constraint to projects (after migration)

---

## Files to Modify
| File | Changes |
|------|---------|
| `server/schema.sql` | Add users table, ALTER agents/projects |
| `server/db.py` | User CRUD, agent changes, user_id params everywhere |
| `server/mcp_server.py` | New MCP tools, remove agent_onboard, user-scoped auth |
| `server/mcp_workflows.py` | User-scoped session/available_tasks |
| `server/mcp_enrich.py` | User context in enrichments |
| `server/mcp_validation.py` | User-scoped validations |
| `server/mcp_read_hints.py` | May need user-scoped adjustments |
| `server/mcp_response_hints.py` | May need user-scoped adjustments |
| `server/cli.py` | User context for all db calls, replace agent_onboard |
| `server/dashboard/app.py` | Login/logout, user session, scoped views |
| `server/dashboard/templates/` | Login page, user-aware templates |
| `server/tests/test_mcp_workflows.py` | User-scoped test fixtures |
| `server/tests/test_mcp_validation.py` | User-scoped tests |
| `server/tests/test_db.py` | User CRUD tests |
| `server/tests/test_dashboard_ui.py` | Login flow tests |
| `server/tests/conftest.py` | User fixtures |
| `server/migrate_user_management.py` | **NEW** — one-time migration script |

---

## Delegation Plan

### Subagent A (Foundation): Task 1+2 combined
**Deliverable:** `schema.sql` changes, `migrate_user_management.py`, `db.py` user CRUD + auth refactor + user_id params everywhere
**Depends on:** nothing

### Subagent B (MCP Server): Task 3
**Deliverable:** `mcp_server.py` — new MCP tools (signup, login, agent_create, etc.), remove agent_onboard, user_id scoping on all tool handlers
**Depends on:** Subagent A

### Subagent C (MCP Helpers + CLI): Task 4 + CLI
**Deliverable:** `mcp_workflows.py`, `mcp_enrich.py`, `mcp_validation.py`, `mcp_read_hints.py`, `mcp_response_hints.py`, `cli.py` — user context throughout
**Depends on:** Subagent A

### Subagent D (Dashboard): Task 5
**Deliverable:** `dashboard/app.py` + templates — real user login, session management, scoped views
**Depends on:** Subagent A

### Subagent E (Tests): Task 6
**Deliverable:** All test files updated, full suite passing with user-scoped data
**Depends on:** Subagents B, C, D

### Parent (Me): Task 7
**Deliverable:** Execute migration, restart server, smoke test MCP tools + dashboard