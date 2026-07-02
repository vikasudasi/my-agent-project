# Usage Examples

**Agents: use MCP tools.** CLI blocks below are **fallback only** (user-requested scripting or no MCP server). See [SKILL.md](../SKILL.md) for session workflow and API key guardrails.

---

## Example 1: Session start (MCP)

After context reset — verify auth, then orient before any writes:

```
1. agent_list api_key=<key>                    → confirm key still valid
2. session_context                             → pick project_id
3. session_context project_id=<id> api_key=<key>
   → available_tasks (is_yours), snapshot, blocked_tasks
4. session_context project_id=<id> task_id=<id> api_key=<key>
   → focused_task with spec + recent_comments
5. task_begin_work task_id=<id> api_key=<key>  → in_progress + checklist
```

Pin `taskmgr://reference/playbook` in the MCP host so lifecycle rules survive context resets.

---

## Example 2: Building a feature (MCP)

An agent building user authentication:

```
1. project_create
     name: "User Authentication"
     description: "JWT-based auth with login, signup, password reset (40+ chars)"
     initial_spec: |
       ## Objective
       Ship JWT auth for login, signup, and password reset.
       ## Acceptance Criteria
       - [ ] Users can register and log in
       - [ ] Password reset email flow works
       - [ ] Integration tests cover happy path
     api_key: <key>

2. task_create — Phase 1 (root), include initial_spec
3. task_create — Phase 2 with after_task_id=phase1
4. task_create — subtask under Phase 1 with parent_id + initial_spec

5. session_context project_id=<id> task_id=<subtask_id>
6. task_begin_work task_id=<subtask_id>
7. task_record_progress — session findings
8. task_complete task_id=<subtask_id> closure_note="Delivered library comparison and design doc"
9. Repeat for siblings; task_complete parent only when all subtasks terminal
```

Use `taskmgr://templates/spec` when drafting `initial_spec` content.

---

## Example 3: Full lifecycle with strict rules (MCP)

```
project_create     → initial_spec required on project
task_create        → initial_spec required on every task/subtask
task_begin_work    → fails without spec (spec written at create time)
task_record_progress → progress doc each session
task_update status=blocked blocker_reason="Waiting on OPS-42 for webhook secret"
task_complete      → closure_note or closure markdown; blocks if children still active
```

**Parent rule:** complete all subtasks (or cancel/fail them) before `task_complete` on the parent.

---

## Example 4: Multi-agent shared project

```
session_context project_id=<id> api_key=<your-key>
→ available_tasks shows is_yours: true on tasks you last set in_progress
→ pick a different pending task than other agents
task_begin_work on YOUR task only
```

---

## CLI fallback examples

The following examples use `python cli.py` for local scripting. **Do not use these during normal MCP agent work** — the CLI does not enforce MCP validation or return workflow hints.

### CLI: Building a feature

```bash
# Requires TM_API_KEY for mutations
export TM_API_KEY="tm_..."

python cli.py project create "User Authentication" \
  --desc "JWT-based auth with login, signup, password reset"
# Note: CLI does not require initial_spec; MCP does — prefer MCP for new work
```

### CLI: Session start

```bash
python cli.py project list --pretty
python cli.py task subtree <project_id> --pretty
python cli.py doc task get <task_id> --type spec --pretty
python cli.py comment list task <task_id> --pretty
```

### CLI: Shell scripting

```bash
#!/bin/bash
export TM_API_KEY="tm_..."
python cli.py db init
PROJ=$(python cli.py project create "My Feature" 2>&1 >/dev/null)
# ... chain commands — see historical patterns below if needed
```

### CLI: Full lifecycle (legacy)

For a long CLI-only walkthrough (spec → progress → closure with comments), see git history of this file or reconstruct using [reference.md](reference.md) CLI tables. **New projects should use MCP** so `initial_spec`, parent-completion rules, and remediation hints apply.

**MCP-equivalent lifecycle:**

```
1. project_create + initial_spec
2. task_create (phases + subtasks, each with initial_spec)
3. task_begin_work
4. comment_add for decisions / blockers
5. task_record_progress each session
6. task_complete per task (closure)
7. project_update status=completed when all tasks done
```
