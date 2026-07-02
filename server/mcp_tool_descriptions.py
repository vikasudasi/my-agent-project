"""Workflow-oriented MCP tool descriptions injected at list_tools time."""

TOOL_DESCRIPTIONS: dict[str, str] = {
    "agent_onboard": (
        "Register this agent before any mutations. Returns api_key once — save it immediately "
        "and pass it on all mutation tools (or set TM_API_KEY). Call once per agent identity."
    ),
    "agent_list": (
        "List registered agents. Use to verify onboarding or see who has access. Requires auth."
    ),
    "audit_log_get": (
        "Read mutation history for a project or task. Use at session start to see what changed "
        "since your last visit. Set scope=project_with_tasks on a project to include all task activity."
    ),
    "comment_add": (
        "Append a timestamped note to a project or task timeline. Use for quick updates, blockers, "
        "decisions, and questions — not for structured deliverables (use doc_*_update instead). "
        "Prefer comment_type=blocker when reporting impediments."
    ),
    "comment_list": (
        "Read recent comments on a project or task. Call at session start before working on a task "
        "to recover context. Use since to fetch only comments after your last session."
    ),
    "doc_project_get": (
        "Read a project markdown doc. Use doc_type=spec at planning time; progress during work; "
        "closure when the project finishes. Check exists=false before assuming a doc is written."
    ),
    "doc_project_update": (
        "Write or replace a project markdown doc. spec: set at creation (## Objective, "
        "## Acceptance Criteria) — write once. progress: session work log. closure: final summary "
        "(## Summary). Never put progress updates in spec."
    ),
    "doc_task_get": (
        "Read a task markdown doc. Call with doc_type=spec before starting implementation. "
        "Use progress for current state and closure for delivery summary. Default doc_type is spec."
    ),
    "doc_task_update": (
        "Write or replace a task markdown doc. spec: plan at creation (## Objective, "
        "## Acceptance Criteria). progress: update each work session with findings and status. "
        "closure: write before marking completed (## Summary). Do not overwrite spec with progress."
    ),
    "project_archive": (
        "Soft-delete a project when work is done or paused. Preferred over project_delete. "
        "Requires reason. Restorable via project_restore."
    ),
    "project_create": (
        "Start a new project. Provide a meaningful description (40+ chars) and initial_spec when "
        "possible. Next: create root tasks with task_create, then decompose with parent_id subtasks."
    ),
    "project_delete": (
        "Permanently delete a project and all tasks, docs, and comments. Last resort — prefer "
        "project_archive. Requires reason."
    ),
    "project_get": (
        "Get one project's metadata, progress stats, and docs_summary. Lighter than project_snapshot; "
        "use when you only need counts and doc flags, not the full task tree."
    ),
    "project_list": (
        "First call at session start. Lists projects with optional progress stats. Use to find "
        "active work before opening a project_snapshot."
    ),
    "project_restore": (
        "Reactivate an archived project when resuming paused work. Next: project_snapshot "
        "to review task tree and pick up where you left off."
    ),
    "project_snapshot": (
        "Primary session-start view for a project: progress, docs summary, full task tree, and "
        "recent activity. Prefer this over multiple task_list/task_get calls. Pick your next "
        "pending or in_progress task from the tree, then doc_task_get its spec."
    ),
    "project_update": (
        "Update project name, description, or status. reason required when changing status "
        "(recorded as a comment). Use status=completed only when all work is truly done."
    ),
    "task_create": (
        "Add a task or subtask. Decompose large work with parent_id instead of flat lists. "
        "Root and non-trivial tasks should include initial_spec. Use after_task_id to order "
        "siblings. Next: set in_progress when starting, or create child subtasks."
    ),
    "task_delete": (
        "Permanently delete a task and its subtasks. Prefer task_update status=cancelled when "
        "work is no longer needed. Requires reason."
    ),
    "task_get": (
        "Get one task with docs_summary, subtask_stats, parent, and created_by. Use before "
        "task_update to check closure doc status or subtask completion on parents."
    ),
    "task_list": (
        "List tasks in a project with optional status or parent filter. Includes doc flags and "
        "subtask stats by default. For full hierarchy prefer task_subtree or project_snapshot."
    ),
    "task_move": (
        "Reorder or reparent a task. Use after_task_id to insert between siblings; parent_id "
        "(empty string for root) to move in the tree. Use when plan structure changes mid-project."
    ),
    "task_subtree": (
        "Get the full nested task tree for a project. Use at session start to see structure and "
        "status distribution. project_snapshot includes this plus docs and activity."
    ),
    "task_tree": (
        "Get one task and all nested descendants. Use to inspect a subtree before working on or "
        "completing a parent task."
    ),
    "task_update": (
        "Change task fields or lifecycle status. Starting work: status=in_progress (after reading "
        "spec). Blocked: status=blocked + blocker_reason. Done: write closure doc first, then "
        "status=completed (or closure_note if no doc yet). No longer needed: status=cancelled. "
        "Prefer task_begin_work, task_record_progress, and task_complete for the standard workflow."
    ),
    "session_context": (
        "Session-start tool scoped to one project. Without project_id: returns project list "
        "so you can choose which project to work on. With project_id: returns snapshot, "
        "suggested next task, blocked tasks, and checklist for that project only — never "
        "auto-selects a project for you."
    ),
    "task_begin_work": (
        "Start working on a task in one call: returns spec, recent comments, checklist, and sets "
        "status=in_progress if pending. Call after session_context for your chosen project. "
        "Read-only on blocked/completed tasks."
    ),
    "task_record_progress": (
        "Record session progress in one call: upserts progress doc and optionally adds a timeline "
        "comment. Use during work instead of separate doc_task_update + comment_add calls."
    ),
    "task_complete": (
        "Finish a task in one call: writes closure doc (closure markdown or closure_note) and marks "
        "completed. Warns on incomplete subtasks. Prefer over doc_task_update + task_update."
    ),
}

# Enriched property descriptions for high-impact schema fields.
DOC_TYPE_PROP = {
    "type": "string",
    "enum": ["spec", "progress", "closure"],
    "description": (
        "spec: plan (write once). progress: work log (update during sessions). "
        "closure: delivery summary (write before completing). Default: spec."
    ),
}

STATUS_TASK_PROP = {
    "type": "string",
    "enum": ["pending", "in_progress", "completed", "blocked", "failed", "cancelled"],
    "description": (
        "pending=not started; in_progress=active work; blocked=waiting (needs blocker_reason); "
        "completed=done (needs closure doc/note); failed=attempted unsuccessfully; cancelled=not needed."
    ),
}
