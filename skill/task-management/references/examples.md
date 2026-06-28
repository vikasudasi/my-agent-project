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

# Read the spec for the task you're about to work on
python cli.py doc task get TASK_ID --type spec --pretty

# Check recent comments for context on this task
python cli.py comment list task TASK_ID --pretty

# Check overall project progress
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

## Example 7: Full Lifecycle with Documentation Types and Comments

This example walks through the complete spec → in_progress → progress doc → closure → completed flow with the three doc types and comments.

**CLI:**
```bash
# ──────────────────────────────────────────────
# 1. INIT — Create the project and write its spec
# ──────────────────────────────────────────────
PROJ=$(python cli.py project create "Payment Gateway Integration" \
  --desc "Stripe integration for checkout flow" 2>&1 >/dev/null)

python cli.py doc project set "$PROJ" "
# Payment Gateway — Project Spec
## Goals
- Accept credit card payments via Stripe
- Support refunds and partial refunds
- Webhook handler for payment events

## Success Criteria
- 99.9% uptime for checkout
- < 2s payment processing latency
" --type spec

# ──────────────────────────────────────────────
# 2. PLAN — Create tasks with dependencies
# ──────────────────────────────────────────────
T1=$(python cli.py task create "$PROJ" "Phase 1: Stripe API Setup" 2>&1 >/dev/null)
T2=$(python cli.py task create "$PROJ" "Phase 2: Checkout UI" --after "$T1" 2>&1 >/dev/null)
T3=$(python cli.py task create "$PROJ" "Phase 3: Webhook Handler" --after "$T2" 2>&1 >/dev/null)

# Add subtasks
SUB_1A=$(python cli.py task create "$PROJ" "Get API keys & configure SDK" --parent "$T1" 2>&1 >/dev/null)
SUB_1B=$(python cli.py task create "$PROJ" "Implement charge endpoint" --parent "$T1" 2>&1 >/dev/null)

# Write spec for the first task
python cli.py doc task set "$SUB_1A" "
# API Key Setup — Task Spec
## Steps
1. Create Stripe account (test mode)
2. Store secret key in env config
3. Initialize Stripe SDK on app startup
## Dependencies
- Access to Stripe dashboard
" --type spec

# ──────────────────────────────────────────────
# 3. EXECUTE — Start work and document progress
# ──────────────────────────────────────────────

# Start the first subtask
python cli.py task update "$SUB_1A" --status in_progress

# Log a decision as a comment
python cli.py comment add task "$SUB_1A" \
  "Using Stripe's test keys for dev, will rotate to live keys in staging deployment." \
  --author "agent"

# After completing the subtask, write a progress doc
python cli.py task update "$SUB_1A" --status completed

python cli.py doc task set "$SUB_1A" "
# API Key Setup — Progress
## What was done
- Created Stripe test account (acct_test_...)
- Configured STRIPE_SECRET_KEY in .env.example
- Initialized stripe SDK with verify_ssl_certs=False in dev
## Decisions
- Using django-stripe library instead of raw SDK for idempotency
- Keys stored in Vault for production, .env for dev
## Current state
- [x] Account setup
- [x] SDK initialization
- [x] Environment config
- [ ] Production key rotation (deferred to deployment phase)
" --type progress

# Log the completion
python cli.py comment add task "$SUB_1A" \
  "Completed. Production key rotation deferred to deployment — added to deployment checklist." \
  --author "agent"

# ──────────────────────────────────────────────
# 4. HANDLE BLOCKERS — Document the issue
# ──────────────────────────────────────────────
python cli.py task update "$SUB_1B" --status in_progress

# Hit a blocker — needs DevOps access
python cli.py task update "$SUB_1B" --status blocked
python cli.py comment add task "$SUB_1B" \
  "BLOCKED: Need DevOps to add STRIPE_WEBHOOK_KEY to production config. Ticket OPS-42 filed." \
  --author "agent"

# ──────────────────────────────────────────────
# 5. COMPLETE — Write the closure doc
# ──────────────────────────────────────────────
python cli.py task update "$T1" --status completed

python cli.py doc task set "$T1" "
# Stripe API Setup — Closure
## Summary
Phase 1 delivered Stripe SDK integration with charge/refund endpoints in test mode.

## What went well
- SDK initialization took < 1 hour
- Test mode verified end-to-end

## What to improve
- Production key rotation should be automated
- Need webhook secret rotation policy

## Lessons learned
- Stripe test clock feature is useful for testing webhooks offline
- Rate limiting: Stripe allows 100 req/s — add client-side throttling for peak load

## Open items
- [ ] Rotate to production keys (blocked on OPS-42)
- [ ] Add Stripe webhook endpoint URL to dashboard
" --type closure

python cli.py comment add task "$T1" \
  "Phase 1 complete. Closure doc written with open items tracked. Ready for Phase 2." \
  --author "agent"

# ──────────────────────────────────────────────
# 6. PROJECT WRAP — Update project status and closure
# ──────────────────────────────────────────────
python cli.py project update "$PROJ" --status completed

python cli.py doc project set "$PROJ" "
# Payment Gateway — Project Closure
## Delivered
- Stripe charge/refund endpoints
- Webhook handler for payment_intent.succeeded
- Checkout UI with card form (Stripe Elements)

## Metrics
- 350ms avg payment processing time
- 0 production incidents during rollout
- 100% test coverage on payment endpoints

## Open items
- [ ] PCI DSS compliance audit (scheduled Q2)
- [ ] Add Apple Pay / Google Pay support (future)
" --type closure

python cli.py comment add project "$PROJ" \
  "Project completed. Final close submitted. All open items tracked in project closure doc." \
  --author "agent"
```

**Resulting lifecycle:**
```
1. project create + doc set --type spec      → Define scope
2. task create (phases + subtasks)            → Break down work
3. doc task set --type spec                   → Plan each task
4. task update --status in_progress           → Start working
5. comment add                                → Log decisions and blockers
6. task update --status completed             → Mark done
7. doc task set --type progress               → Document what happened
8. doc task set --type closure                → Summarize learnings + open items
9. project update --status completed          → Close project
10. doc project set --type closure            → Final project summary
```
