# Usage Examples

## Example 1: Building a Feature

An agent planning to build a user authentication feature:

```
1. project_create("User Authentication", "JWT-based auth with login, signup, password reset")
   → project_id: "proj-abc"

2. task_create("proj-abc", "Phase 1: Research & Design")
   task_create("proj-abc", "Phase 2: Implementation")
   task_create("proj-abc", "Phase 3: Testing")

3. task_create("proj-abc", "Compare auth libraries", parent_id="task-1")
   task_create("proj-abc", "Design DB schema", parent_id="task-1")
   task_create("proj-abc", "Design API endpoints", parent_id="task-1")

4. task_update("task-1", status="in_progress")

5. task_update("task-1-sub-1", status="completed")  // Research done
   task_update("task-1-sub-2", status="completed")  // Schema done
   task_update("task-1-sub-3", status="in_progress") // API design ongoing

6. doc_project_update("proj-abc", "
# Auth System Design
## Database
- users table with email, password_hash, created_at
- refresh_tokens table
## API
- POST /auth/signup
- POST /auth/login
- POST /auth/refresh
")
```

## Example 2: Organizing Work Sequentially

When tasks have dependencies, use `after_task_id`:

```
// Must build API before frontend
task_create("proj-xyz", "Build REST API")      → task-a
task_create("proj-xyz", "Build Frontend", 
            after_task_id="task-a")             → task-b (after API)
task_create("proj-xyz", "Integration Tests",
            after_task_id="task-b")             → task-c (after frontend)
```

## Example 3: Tracking a Bugfix

```
1. task_create("proj-abc", "Fix login crash on empty password")

2. task_create("proj-abc", "Reproduce the bug", parent_id="bug-task")
   task_create("proj-abc", "Find root cause", parent_id="bug-task")
   task_create("proj-abc", "Implement fix", parent_id="bug-task")
   task_create("proj-abc", "Add regression test", parent_id="bug-task")

3. task_update("bug-task-sub-1", status="completed")  // Reproduced
   task_update("bug-task-sub-2", status="completed")  // Found cause
   task_update("bug-task-sub-3", status="in_progress") // Fixing

4. doc_task_update("bug-task", "
# Root cause analysis
Empty password bypassed validation because...
## Fix
Added null/empty check before password comparison in...
")
```

## Example 4: Moving Tasks Between Parents

```
// Move task from root level to be a subtask
task_move("task-3", after_task_id="task-1", parent_id="task-1")

// Move task to root level
task_move("deep-subtask", parent_id="")

// Reorder within same parent
task_move("task-c", after_task_id="task-a")  // task-c moves after task-a
```

## Example 5: Session Start Pattern

Start each working session with:

```
1. project_list()     → see what needs attention
2. task_subtree("proj-abc")  → see where you left off
3. task_list("proj-abc", status="in_progress")  → what's currently being worked on
4. task_list("proj-abc", status="blocked")  → what's stuck
```

Then pick up where you left off, update statuses, and move forward.

## Example 6: Full Lifecycle

```
1. Initialize: project + doc
2. Break down: top-level tasks (phases/milestones)
3. Detail: subtasks within each phase
4. Execute: update status as work happens
5. Document: write docs while knowledge is fresh
6. Complete: mark project completed when done
```