# Usage Examples

All examples show both **CLI commands** (no server needed) and **MCP tool calls** (for IDE integration).

---

## Example 1: Building a Feature

An agent planning to build a user authentication feature:

**CLI (simplest):**
```bash
# 1. Create the project
python cli.py project create "User Authentication" \
  --desc "JWT-based auth with login, signup, password reset"

# 2. Create phases (ordered top-level tasks)
python cli.py task create PROJ_ID "Phase 1: Research & Design"
python cli.py task create PROJ_ID "Phase 2: Implementation" --after TASK_1
python cli.py task create PROJ_ID "Phase 3: Testing" --after TASK_2

# 3. Add subtasks to Phase 1
python cli.py task create PROJ_ID "Compare auth libraries" --parent TASK_1
python cli.py task create PROJ_ID "Design DB schema" --parent TASK_1

# 4. Update status as work progresses
python cli.py task update TASK_1_SUB_1 --status completed
python cli.py task update TASK_1_SUB_2 --status completed

# 5. Write documentation
python cli.py doc project set PROJ_ID "
# Auth System Design
## Database
- users table with email, password_hash, created_at
- refresh_tokens table
## API
- POST /auth/signup
- POST /auth/login
- POST /auth/refresh
"
```

**MCP equivalent:**
```
1. project_create("User Authentication", "...")
   → project_id: "proj-abc"
2. task_create("proj-abc", "Phase 1: Research & Design")
3. task_create("proj-abc", "Phase 2: Implementation", after_task_id="task-1")
4. task_create("proj-abc", "Compare auth libraries", parent_id="task-1")
5. task_update("task-1-sub-1", status="completed")
6. doc_project_update("proj-abc", "# Auth System Design\n...")
```

---

## Example 2: Organizing Work Sequentially

When tasks must be done in order, use `--after`:

**CLI:**
```bash
# Capture task IDs as we go
TASK_A=$(python cli.py task create PROJ_ID "Build REST API" 2>&1 >/dev/null)
TASK_B=$(python cli.py task create PROJ_ID "Build Frontend" --after $TASK_A 2>&1 >/dev/null)
TASK_C=$(python cli.py task create PROJ_ID "Integration Tests" --after $TASK_B 2>&1 >/dev/null)
```

**Resulting order:** `Build REST API` → `Build Frontend` → `Integration Tests`

---

## Example 3: Tracking a Bugfix

**CLI:**
```bash
# Create a bugfix task with subtasks
BUG=$(python cli.py task create PROJ_ID "Fix login crash on empty password" 2>&1 >/dev/null)

python cli.py task create PROJ_ID "Reproduce the bug" --parent $BUG
python cli.py task create PROJ_ID "Find root cause" --parent $BUG
python cli.py task create PROJ_ID "Implement fix" --parent $BUG
python cli.py task create PROJ_ID "Add regression test" --parent $BUG

# Mark progress
python cli.py task update BUG_SUB_1 --status completed
python cli.py task update BUG_SUB_2 --status in_progress

# Document the root cause
python cli.py doc task set BUG_SUB_2 "
# Root cause analysis
Empty password bypassed validation because...
## Fix
Added null/empty check before password comparison in...
"
```

---

## Example 4: Moving Tasks Between Parents

**CLI:**
```bash
# Move task from root level to be a subtask of task-1
python cli.py task move TASK_3 --after TASK_1 --parent TASK_1

# Move a deep subtask up to root level
python cli.py task move DEEP_SUB --parent ""

# Reorder within the same parent (move task-c after task-a)
python cli.py task move TASK_C --after TASK_A
```

---

## Example 5: Session Start Pattern

Start each working session with:

**CLI:**
```bash
# See what projects exist
python cli.py project list --pretty

# Pick a project and see its full task tree
python cli.py task subtree PROJ_ID --pretty

# Find what's currently active and what's blocked
python cli.py task list PROJ_ID --status in_progress --pretty
python cli.py task list PROJ_ID --status blocked --pretty

# Check overall progress
python cli.py project get PROJ_ID --pretty
```

---

## Example 6: Shell Scripting with the CLI

The CLI is designed for agents. Here's how to chain commands in a shell:

```bash
#!/bin/bash
# Full automated workflow

# Initialize DB if needed
python cli.py db init

# Create project and capture ID
PROJ=$(python cli.py project create "My Feature" 2>&1 >/dev/null)

# Create task chain
T1=$(python cli.py task create "$PROJ" "Step 1" 2>&1 >/dev/null)
T2=$(python cli.py task create "$PROJ" "Step 2" --after "$T1" 2>&1 >/dev/null)
T3=$(python cli.py task create "$PROJ" "Step 3" --after "$T2" 2>&1 >/dev/null)

# Create subtask under Step 2
python cli.py task create "$PROJ" "Subtask 2a" --parent "$T2"

# Mark Step 1 done
python cli.py task update "$T1" --status completed

# Write project docs
python cli.py doc project set "$PROJ" "# My Feature\n\nImplementation plan..."

# Show final state
python cli.py task subtree "$PROJ" --pretty
```

---

## Example 7: Full Lifecycle

```
1. Initialize:  python cli.py project create + doc project set
2. Break down:  python cli.py task create (top-level phases)
3. Detail:      python cli.py task create --parent (subtasks)
4. Execute:     python cli.py task update --status (as work happens)
5. Document:    python cli.py doc task set (capture knowledge)
6. Complete:    python cli.py project update --status completed
```
