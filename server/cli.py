#!/usr/bin/env python3
"""
CLI for AI Task Management System.

Zero-dependency CLI wrapping db.py. Every command outputs JSON by default
(agent-friendly). Use --pretty (-p) for human-readable tables.

Usage:
    python cli.py db init
    python cli.py user signup --email me@example.com --password s3cret
    python cli.py user login --email me@example.com --password s3cret
    python cli.py agent create --name my-agent
    python cli.py agent list
    python cli.py agent reissue --id <agent_id>
    python cli.py project create "Name" --desc "..."
    python cli.py project list
    python cli.py task create <project_id> "Title" --after <task_id>
    python cli.py task list <project_id> --status pending
    python cli.py doc project set <project_id> "# content"
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from typing import Optional

# Ensure we can import db.py from the same directory
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from db import (
    init_db,
    DB_PATH,
    create_user,
    validate_user,
    list_users,
    create_agent,
    list_user_agents,
    reissue_agent_key,
    create_project,
    list_projects,
    get_project,
    update_project,
    delete_project,
    get_project_progress,
    create_task,
    list_tasks,
    get_task,
    get_task_tree,
    get_task_subtree,
    update_task,
    move_task,
    delete_task,
    get_project_doc,
    upsert_project_doc,
    get_task_doc,
    upsert_task_doc,
    add_comment,
    list_comments,
    delete_comment,
    validate_api_key,
    log_audit,
    get_audit_log,
    get_audit_log_by_agent,
)

# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

def out(data: object, pretty: bool = False) -> None:
    """Print result to stdout as JSON (agent-friendly)."""
    if isinstance(data, dict) and "error" in data:
        print(json.dumps(data), file=sys.stderr)
        sys.exit(1)

    if pretty:
        print(json.dumps(data, indent=2, default=str))
    else:
        # Compact JSON — this is what agents parse
        print(json.dumps(data, default=str))

    # If the result is a dict with an "id" field, also echo the id
    # on a separate line so shell scripts can capture it easily
    if isinstance(data, dict) and "id" in data:
        print(data["id"], file=sys.stderr)


def err(msg: str) -> None:
    print(json.dumps({"error": msg}), file=sys.stderr)
    sys.exit(1)


# ---------------------------------------------------------------------------
# Auth helper
# ---------------------------------------------------------------------------

def _get_api_key(args) -> Optional[str]:
    """Get API key from --api-key flag or TM_API_KEY env var."""
    key = getattr(args, "api_key", None)
    if key:
        return key
    return os.environ.get("TM_API_KEY")


def require_auth(args) -> dict:
    """Validate API key and return agent info (with user_id). Exits on failure."""
    api_key = _get_api_key(args)
    if not api_key:
        err("Authentication required. Provide --api-key or set TM_API_KEY environment variable.")
    agent = validate_api_key(api_key)
    if not agent:
        err("Invalid API key. Use 'user signup' + 'agent create' to get a key, "
            "or 'agent reissue' to rotate.")
    return agent


# ---------------------------------------------------------------------------
# Subcommand builders
# ---------------------------------------------------------------------------

def cmd_db_init(_args):
    init_db()
    out({"ok": True, "db_path": DB_PATH})


def cmd_db_path(_args):
    out({"db_path": DB_PATH})


# ---- User commands ----

def cmd_user_signup(args):
    """Create a new user. Username defaults to email local part if omitted."""
    if not args.password:
        err("Password is required")
    username = args.username or (
        args.email.split("@")[0] if "@" in args.email else ""
    )
    if not username:
        err("Username is required (or provide --username)")
    result = create_user(username, email=args.email, password=args.password)
    if not result:
        err(f"Username '{username}' already exists")
    out(result, pretty=args.pretty)


def cmd_user_login(args):
    """Validate user credentials by email + password."""
    users = list_users()
    match = next((u for u in users if u.get("email") == args.email), None)
    if not match:
        err(f"User with email '{args.email}' not found")
    user = validate_user(match["username"], args.password)
    if not user:
        err("Invalid password")
    out(user, pretty=args.pretty)


# ---- Agent commands ----

def cmd_agent_create(args):
    """Create a new agent under the authenticated user."""
    agent = require_auth(args)
    user_id = agent.get("user_id")
    if not user_id:
        err("Authenticated agent has no user scope — please migrate your account")
    result = create_agent(user_id, args.name)
    if not result:
        err(f"Agent '{args.name}' already exists or user not found")
    out({
        "agent_id": result["id"],
        "agent_name": result["name"],
        "master_name": result.get("master_name"),
        "user_id": result.get("user_id"),
        "api_key": result["api_key"],
        "created_at": result.get("created_at"),
    }, pretty=args.pretty)


def cmd_agent_list(args):
    """List agents owned by the authenticated user."""
    agent = require_auth(args)
    user_id = agent.get("user_id")
    if not user_id:
        err("Authenticated agent has no user scope")
    agents = list_user_agents(user_id)
    out(agents, pretty=args.pretty)


def cmd_agent_reissue(args):
    """Reissue the API key for an agent owned by the authenticated user."""
    agent = require_auth(args)
    user_id = agent.get("user_id")
    if not user_id:
        err("Authenticated agent has no user scope")
    result = reissue_agent_key(args.agent_id, user_id)
    if not result:
        err(f"Agent '{args.agent_id}' not found or not owned by you")
    out({
        "agent_id": result["id"],
        "agent_name": result["name"],
        "api_key": result["api_key"],
    }, pretty=args.pretty)


def cmd_agent_audit(args):
    agent = require_auth(args)
    entries = get_audit_log(args.entity_type, args.entity_id)
    out(entries, pretty=args.pretty)


def cmd_agent_audit_log(args):
    agent = require_auth(args)
    if args.agent_name:
        entries = get_audit_log_by_agent(args.agent_name)
    else:
        entries = get_audit_log(args.entity_type, args.entity_id) if args.entity_type else []
    out(entries, pretty=args.pretty)


# ---- Project commands ----

def cmd_project_create(args):
    agent = require_auth(args)
    user_id = agent.get("user_id")
    result = create_project(args.name, args.desc or "", user_id=user_id)
    if not result:
        err("Failed to create project")
    log_audit(agent["name"], agent["master_name"], "project", result["id"],
              "created", user_id=user_id)
    out(result, pretty=args.pretty)


def cmd_project_list(args):
    agent = require_auth(args)
    user_id = agent.get("user_id")
    projects = list_projects(user_id=user_id)
    enriched = []
    for p in projects:
        progress = get_project_progress(p["id"], user_id=user_id)
        enriched.append(progress if progress else p)
    out(enriched, pretty=args.pretty)


def cmd_project_get(args):
    agent = require_auth(args)
    user_id = agent.get("user_id")
    result = get_project_progress(args.project_id, user_id=user_id)
    if not result:
        err(f"Project '{args.project_id}' not found")
    out(result, pretty=args.pretty)


def cmd_project_update(args):
    agent = require_auth(args)
    user_id = agent.get("user_id")
    old = get_project(args.project_id, user_id=user_id)
    result = update_project(
        args.project_id,
        name=args.name,
        description=args.desc,
        status=args.status,
        user_id=user_id,
    )
    if not result:
        err(f"Project '{args.project_id}' not found")
    if old:
        for field in ("name", "description", "status"):
            old_val = old.get(field)
            new_val = result.get(field)
            if old_val != new_val:
                log_audit(agent["name"], agent["master_name"], "project", args.project_id,
                          "updated", field, str(old_val) if old_val else None,
                          str(new_val) if new_val else None, user_id=user_id)
    out(result, pretty=args.pretty)


def cmd_project_delete(args):
    agent = require_auth(args)
    user_id = agent.get("user_id")
    success = delete_project(args.project_id, user_id=user_id)
    if not success:
        err(f"Project '{args.project_id}' not found")
    log_audit(agent["name"], agent["master_name"], "project", args.project_id,
              "deleted", user_id=user_id)
    out({"deleted": True})


# ---- Task commands ----

def cmd_task_create(args):
    agent = require_auth(args)
    user_id = agent.get("user_id")
    result = create_task(
        args.project_id,
        args.title,
        description=args.desc or "",
        parent_id=args.parent,
        after_task_id=args.after,
        user_id=user_id,
    )
    if not result:
        err(f"Project '{args.project_id}' not found")
    log_audit(agent["name"], agent["master_name"], "task", result["id"],
              "created", user_id=user_id)
    out(result, pretty=args.pretty)


def cmd_task_list(args):
    agent = require_auth(args)
    user_id = agent.get("user_id")
    result = list_tasks(
        args.project_id,
        status=args.status,
        parent_id=args.parent,
        user_id=user_id,
    )
    out(result, pretty=args.pretty)


def cmd_task_get(args):
    agent = require_auth(args)
    user_id = agent.get("user_id")
    result = get_task(args.task_id, user_id=user_id)
    if not result:
        err(f"Task '{args.task_id}' not found")
    out(result, pretty=args.pretty)


def cmd_task_tree(args):
    agent = require_auth(args)
    user_id = agent.get("user_id")
    result = get_task_tree(args.task_id, user_id=user_id)
    if not result:
        err(f"Task '{args.task_id}' not found")
    out(result, pretty=args.pretty)


def cmd_task_subtree(args):
    agent = require_auth(args)
    user_id = agent.get("user_id")
    result = get_task_subtree(args.project_id, user_id=user_id)
    out(result, pretty=args.pretty)


def cmd_task_update(args):
    agent = require_auth(args)
    user_id = agent.get("user_id")
    old = get_task(args.task_id, user_id=user_id)
    result = update_task(
        args.task_id,
        title=args.title,
        description=args.desc,
        status=args.status,
        user_id=user_id,
    )
    if not result:
        err(f"Task '{args.task_id}' not found")
    if old:
        for field in ("title", "description", "status"):
            old_val = old.get(field)
            new_val = result.get(field)
            if old_val != new_val:
                action = "status_changed" if field == "status" else "updated"
                log_audit(agent["name"], agent["master_name"], "task", args.task_id,
                          action, field, str(old_val) if old_val else None,
                          str(new_val) if new_val else None, user_id=user_id)
    out(result, pretty=args.pretty)


def cmd_task_move(args):
    agent = require_auth(args)
    user_id = agent.get("user_id")
    parent = args.parent if args.parent is not None else None
    if args.parent == "":
        parent = None
    old = get_task(args.task_id, user_id=user_id)
    result = move_task(
        args.task_id,
        after_task_id=args.after,
        parent_id=parent,
        user_id=user_id,
    )
    if not result:
        err(f"Task '{args.task_id}' not found")
    if old:
        if old.get("parent_id") != result.get("parent_id"):
            log_audit(agent["name"], agent["master_name"], "task", args.task_id,
                      "moved", "parent_id", old.get("parent_id"),
                      result.get("parent_id"), user_id=user_id)
    out(result, pretty=args.pretty)


def cmd_task_delete(args):
    agent = require_auth(args)
    user_id = agent.get("user_id")
    success = delete_task(args.task_id, user_id=user_id)
    if not success:
        err(f"Task '{args.task_id}' not found")
    log_audit(agent["name"], agent["master_name"], "task", args.task_id,
              "deleted", user_id=user_id)
    out({"deleted": True})


# ---- Doc commands ----

def cmd_doc_project_get(args):
    agent = require_auth(args)
    user_id = agent.get("user_id")
    content = get_project_doc(args.project_id, args.type, user_id=user_id)
    out({"project_id": args.project_id, "doc_type": args.type, "content": content},
        pretty=args.pretty)


def cmd_doc_project_set(args):
    agent = require_auth(args)
    user_id = agent.get("user_id")
    ok = upsert_project_doc(args.project_id, args.content, args.type, user_id=user_id)
    if not ok:
        err(f"Project '{args.project_id}' not found")
    log_audit(agent["name"], agent["master_name"], "project", args.project_id,
              "doc_updated", f"doc_{args.type}", user_id=user_id)
    out({"updated": True, "doc_type": args.type})


def cmd_doc_task_get(args):
    agent = require_auth(args)
    user_id = agent.get("user_id")
    content = get_task_doc(args.task_id, args.type, user_id=user_id)
    out({"task_id": args.task_id, "doc_type": args.type, "content": content},
        pretty=args.pretty)


def cmd_doc_task_set(args):
    agent = require_auth(args)
    user_id = agent.get("user_id")
    ok = upsert_task_doc(args.task_id, args.content, args.type, user_id=user_id)
    if not ok:
        err(f"Task '{args.task_id}' not found")
    log_audit(agent["name"], agent["master_name"], "task", args.task_id,
              "doc_updated", f"doc_{args.type}", user_id=user_id)
    out({"updated": True, "doc_type": args.type})


# ---- Comment handlers ----

def cmd_comment_add(args):
    agent = require_auth(args)
    user_id = agent.get("user_id")
    result = add_comment(args.entity_type, args.entity_id, args.content, args.author,
                         user_id=user_id)
    if not result:
        err(f"Entity '{args.entity_id}' not found or not accessible")
    log_audit(agent["name"], agent["master_name"], args.entity_type, args.entity_id,
              "comment_added", user_id=user_id)
    out(result, pretty=args.pretty)


def cmd_comment_list(args):
    agent = require_auth(args)
    user_id = agent.get("user_id")
    result = list_comments(args.entity_type, args.entity_id, user_id=user_id)
    out(result, pretty=args.pretty)


def cmd_comment_delete(args):
    agent = require_auth(args)
    user_id = agent.get("user_id")
    ok = delete_comment(args.comment_id, user_id=user_id)
    if not ok:
        err(f"Comment '{args.comment_id}' not found")
    log_audit(agent["name"], agent["master_name"], "comment", args.comment_id,
              "deleted", user_id=user_id)
    out({"deleted": True})


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    # Parent parser with shared flags — added to every subparser
    parent = argparse.ArgumentParser(add_help=False)
    parent.add_argument("--pretty", "-p", action="store_true",
                        help="Pretty-print JSON output (default: compact JSON for agents)")
    parent.add_argument("--api-key", help="API key for authentication (or set TM_API_KEY env var)")

    parser = argparse.ArgumentParser(
        prog="tm",
        description="AI Task Management CLI — manage projects, ordered tasks, and docs.",
    )

    sub = parser.add_subparsers(dest="entity", required=True)

    # ---- db ----
    db_p = sub.add_parser("db", help="Database utilities")
    db_sub = db_p.add_subparsers(dest="action", required=True)
    db_sub.add_parser("init", parents=[parent], help="Initialize the database (create tables)")
    db_sub.add_parser("path", parents=[parent], help="Show the database file path")

    # ---- user ----
    user_p = sub.add_parser("user", help="User management")
    user_sub = user_p.add_subparsers(dest="action", required=True)

    u_signup = user_sub.add_parser("signup", parents=[parent],
                                    help="Create a new user account")
    u_signup.add_argument("--email", required=True, help="Email address")
    u_signup.add_argument("--password", required=True, help="Password")
    u_signup.add_argument("--username", help="Username (defaults to email local part)")

    u_login = user_sub.add_parser("login", parents=[parent],
                                   help="Validate user credentials by email + password")
    u_login.add_argument("--email", required=True, help="Email address")
    u_login.add_argument("--password", required=True, help="Password")

    # ---- project ----
    proj_p = sub.add_parser("project", help="Manage projects")
    proj_sub = proj_p.add_subparsers(dest="action", required=True)

    p_create = proj_sub.add_parser("create", parents=[parent], help="Create a new project")
    p_create.add_argument("name", help="Project name")
    p_create.add_argument("--desc", help="Project description")

    proj_sub.add_parser("list", parents=[parent], help="List all projects")

    p_get = proj_sub.add_parser("get", parents=[parent], help="Get project details + progress")
    p_get.add_argument("project_id", help="Project ID")

    p_upd = proj_sub.add_parser("update", parents=[parent], help="Update project fields")
    p_upd.add_argument("project_id", help="Project ID")
    p_upd.add_argument("--name", help="New project name")
    p_upd.add_argument("--desc", help="New description")
    p_upd.add_argument("--status", choices=["active", "archived", "completed"],
                       help="New status")

    p_del = proj_sub.add_parser("delete", parents=[parent], help="Delete a project")
    p_del.add_argument("project_id", help="Project ID")

    # ---- task ----
    task_p = sub.add_parser("task", help="Manage tasks")
    task_sub = task_p.add_subparsers(dest="action", required=True)

    t_create = task_sub.add_parser("create", parents=[parent], help="Create a task")
    t_create.add_argument("project_id", help="Project ID")
    t_create.add_argument("title", help="Task title")
    t_create.add_argument("--desc", help="Task description")
    t_create.add_argument("--parent", help="Parent task ID (for subtasks)")
    t_create.add_argument("--after", help="Place after this sibling task ID")

    t_list = task_sub.add_parser("list", parents=[parent], help="List tasks in a project")
    t_list.add_argument("project_id", help="Project ID")
    t_list.add_argument("--status",
                        choices=["pending", "in_progress", "completed",
                                 "blocked", "failed", "cancelled"],
                        help="Filter by status")
    t_list.add_argument("--parent", help="List children of this parent task")

    t_get = task_sub.add_parser("get", parents=[parent], help="Get a single task")
    t_get.add_argument("task_id", help="Task ID")

    t_tree = task_sub.add_parser("tree", parents=[parent], help="Get task with its subtree")
    t_tree.add_argument("task_id", help="Task ID")

    t_subtree = task_sub.add_parser("subtree", parents=[parent],
                                     help="Get full task hierarchy for a project")
    t_subtree.add_argument("project_id", help="Project ID")

    t_upd = task_sub.add_parser("update", parents=[parent], help="Update a task")
    t_upd.add_argument("task_id", help="Task ID")
    t_upd.add_argument("--title", help="New title")
    t_upd.add_argument("--desc", help="New description")
    t_upd.add_argument("--status",
                       choices=["pending", "in_progress", "completed",
                                "blocked", "failed", "cancelled"],
                       help="New status")

    t_move = task_sub.add_parser("move", parents=[parent], help="Move/reorder a task")
    t_move.add_argument("task_id", help="Task ID")
    t_move.add_argument("--after", help="Place after this sibling")
    t_move.add_argument("--parent", help="New parent ID. Empty string '' for root level")

    t_del = task_sub.add_parser("delete", parents=[parent], help="Delete a task")
    t_del.add_argument("task_id", help="Task ID")

    # ---- doc ----
    doc_p = sub.add_parser("doc", help="Manage documentation (spec/progress/closure)")
    doc_sub = doc_p.add_subparsers(dest="doc_type", required=True)

    # doc project
    doc_proj_p = doc_sub.add_parser("project", help="Project documentation")
    doc_proj_sub = doc_proj_p.add_subparsers(dest="action", required=True)

    doc_proj_get = doc_proj_sub.add_parser("get", parents=[parent], help="Get project docs")
    doc_proj_get.add_argument("project_id", help="Project ID")
    doc_proj_get.add_argument("--type", dest="type",
                              choices=["spec", "progress", "closure"], default="spec",
                              help="Doc type: spec (default), progress, closure")

    doc_proj_set = doc_proj_sub.add_parser("set", parents=[parent],
                                            help="Set project docs (markdown)")
    doc_proj_set.add_argument("project_id", help="Project ID")
    doc_proj_set.add_argument("content", help="Markdown content (use quotes)")
    doc_proj_set.add_argument("--type", dest="type",
                              choices=["spec", "progress", "closure"], default="spec",
                              help="Doc type: spec (default), progress, closure")

    # doc task
    doc_task_p = doc_sub.add_parser("task", help="Task documentation")
    doc_task_sub = doc_task_p.add_subparsers(dest="action", required=True)

    doc_task_get = doc_task_sub.add_parser("get", parents=[parent], help="Get task docs")
    doc_task_get.add_argument("task_id", help="Task ID")
    doc_task_get.add_argument("--type", dest="type",
                              choices=["spec", "progress", "closure"], default="spec",
                              help="Doc type: spec (default), progress, closure")

    doc_task_set = doc_task_sub.add_parser("set", parents=[parent],
                                            help="Set task docs (markdown)")
    doc_task_set.add_argument("task_id", help="Task ID")
    doc_task_set.add_argument("content", help="Markdown content (use quotes)")
    doc_task_set.add_argument("--type", dest="type",
                              choices=["spec", "progress", "closure"], default="spec",
                              help="Doc type: spec (default), progress, closure")

    # ---- comment ----
    comment_p = sub.add_parser("comment", help="Add and view comments")
    comment_sub = comment_p.add_subparsers(dest="action", required=True)

    c_add = comment_sub.add_parser("add", parents=[parent], help="Add a comment")
    c_add.add_argument("entity_type", choices=["project", "task"],
                       help="Entity type")
    c_add.add_argument("entity_id", help="Entity ID")
    c_add.add_argument("content", help="Comment text")
    c_add.add_argument("--author", default="", help="Comment author name")

    c_list = comment_sub.add_parser("list", parents=[parent], help="List comments")
    c_list.add_argument("entity_type", choices=["project", "task"],
                        help="Entity type")
    c_list.add_argument("entity_id", help="Entity ID")

    c_del = comment_sub.add_parser("delete", parents=[parent],
                                    help="Delete a comment")
    c_del.add_argument("comment_id", help="Comment ID")

    # ---- agent ----
    agent_p = sub.add_parser("agent", help="Agent management & audit")
    agent_sub = agent_p.add_subparsers(dest="action", required=True)

    a_create = agent_sub.add_parser("create", parents=[parent],
                                     help="Create a new agent under your user account")
    a_create.add_argument("--name", required=True, help="Agent name")

    agent_sub.add_parser("list", parents=[parent], help="List your agents")

    a_reissue = agent_sub.add_parser("reissue", parents=[parent],
                                      help="Reissue an agent API key")
    a_reissue.add_argument("--id", dest="agent_id", required=True, help="Agent ID")

    a_audit = agent_sub.add_parser("audit", parents=[parent],
                                    help="View audit log for a task or project")
    a_audit.add_argument("entity_type", choices=["task", "project"],
                         help="Entity type")
    a_audit.add_argument("entity_id", help="Entity ID")

    a_audit_log = agent_sub.add_parser("audit-log", parents=[parent],
                                        help="View audit log by agent name")
    a_audit_log.add_argument("--agent", dest="agent_name", help="Filter by agent name")

    return parser


# ---------------------------------------------------------------------------
# Main dispatch
# ---------------------------------------------------------------------------

def main():
    parser = build_parser()
    args = parser.parse_args()

    # Dispatch map: (entity, action, doc_type?) -> handler
    handlers = {
        ("db", "init"): cmd_db_init,
        ("db", "path"): cmd_db_path,
        ("user", "signup"): cmd_user_signup,
        ("user", "login"): cmd_user_login,
        ("project", "create"): cmd_project_create,
        ("project", "list"): cmd_project_list,
        ("project", "get"): cmd_project_get,
        ("project", "update"): cmd_project_update,
        ("project", "delete"): cmd_project_delete,
        ("task", "create"): cmd_task_create,
        ("task", "list"): cmd_task_list,
        ("task", "get"): cmd_task_get,
        ("task", "tree"): cmd_task_tree,
        ("task", "subtree"): cmd_task_subtree,
        ("task", "update"): cmd_task_update,
        ("task", "move"): cmd_task_move,
        ("task", "delete"): cmd_task_delete,
        ("doc", "project", "get"): cmd_doc_project_get,
        ("doc", "project", "set"): cmd_doc_project_set,
        ("doc", "task", "get"): cmd_doc_task_get,
        ("doc", "task", "set"): cmd_doc_task_set,
        ("comment", "add"): cmd_comment_add,
        ("comment", "list"): cmd_comment_list,
        ("comment", "delete"): cmd_comment_delete,
        ("agent", "create"): cmd_agent_create,
        ("agent", "list"): cmd_agent_list,
        ("agent", "reissue"): cmd_agent_reissue,
        ("agent", "audit"): cmd_agent_audit,
        ("agent", "audit-log"): cmd_agent_audit_log,
    }

    # Doc subcommands need to key on (entity, doc_type, action)
    if args.entity == "doc":
        key = ("doc", args.doc_type, args.action)
    else:
        key = (args.entity, args.action)

    handler = handlers.get(key)
    if not handler:
        parser.print_help()
        sys.exit(1)

    handler(args)


if __name__ == "__main__":
    main()