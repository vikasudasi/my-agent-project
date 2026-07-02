"""MCP server instructions injected into agent context at connection time."""

MCP_INSTRUCTIONS = """
Task Management System for AI Agents — use these MCP tools to plan, track, and document work.

## Authentication
- Register once with agent_onboard (returns api_key — save it immediately).
- Pass api_key on every mutation, or set TM_API_KEY in the environment.

## Session start (read before write)
Before creating or changing anything:
1. project_list — see active projects and progress.
2. project_snapshot — full view: task tree, docs summary, recent activity (preferred over piecemeal reads).
3. doc_task_get (doc_type=spec) — read the spec for the task you will work on.
4. comment_list — check recent context on that task or project.

## Planning and task structure
- Create projects with project_create: meaningful description (40+ chars) and initial_spec when possible.
- Decompose work with task_create: use parent_id for subtasks; use after_task_id for ordering.
- Root and non-trivial tasks should include initial_spec with ## Objective and ## Acceptance Criteria.
- Prefer a task tree over one flat list — humans and future agents navigate hierarchies better.

## While working
| Situation | Tool / action |
|-----------|---------------|
| Starting work | task_update status=in_progress |
| Findings, decisions, session state | doc_task_update doc_type=progress |
| Blocked | task_update status=blocked + blocker_reason; comment_add with details |
| Quick note or question | comment_add (append-only timeline) |
| Requirements changed | comment_add explaining why — do not overwrite spec |
| Reorder or reparent | task_move |

## Documentation lifecycle
Each project and task has three independent doc slots:
- spec — written at creation; defines objective and acceptance criteria. Write once.
- progress — updated during work; current status, findings, blockers.
- closure — written at completion; ## Summary of what was delivered.

Never put progress updates in the spec doc. Use doc_task_update with the correct doc_type.

## Completing work
1. doc_task_update doc_type=closure (include ## Summary).
2. task_update status=completed (use closure_note if no closure doc yet).
3. If this was a subtask, check parent subtask_stats via task_get or project_snapshot before marking the parent complete.

## Comments vs docs
- Comments: quick updates, blockers, questions, links — timestamped timeline.
- Docs: structured information that must survive the project (specs, progress reports, delivery summaries).

## Status values
pending → in_progress → completed | blocked | failed | cancelled
- blocked: always explain why (blocker_reason).
- failed: note what was attempted and why it did not work (comment_add).
- cancelled: prefer over task_delete when work is no longer needed.

## Destructive actions
- Prefer project_archive over project_delete; prefer status=cancelled over task_delete.
- Deletes require a reason and are permanent.

## Audit trail
Every mutation is logged with your agent identity. Write descriptions, reasons, and docs so other agents and humans can continue your work without re-discovery.
""".strip()
