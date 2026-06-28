#!/usr/bin/env python3
"""
CLI for AI Task Management System.

Zero-dependency CLI wrapping db.py. Every command outputs JSON by default
(agent-friendly). Use --pretty (-p) for human-readable tables.

Usage:
    python cli.py project create "Name" --desc "..."
    python cli.py project list
    python cli.py task create <project_id> "Title" --after <task_id>
    python cli.py task list <project_id> --status pending
    python cli.py doc project set <project_id> "# content"
    python cli.py db init
    python cli.py db path
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone

# Ensure we can import db.py from the same directory
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from db import (
    init_db,
    DB_PATH,
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
# Subcommand builders
# ---------------------------------------------------------------------------

def cmd_db_init(_args):
    init_db()
    out({"ok": True, "db_path": DB_PATH})


def cmd_db_path(_args):
    out({"db_path": DB_PATH})


def cmd_project_create(args):
    result = create_project(args.name, args.desc or "")
    if not result:
        err("Failed to create project")
    out(result, pretty=args.pretty)


def cmd_project_list(args):
    projects = list_projects()
    # Enrich with progress
    enriched = []
    for p in projects:
        progress = get_project_progress(p["id"])
        enriched.append(progress if progress else p)
    out(enriched, pretty=args.pretty)


def cmd_project_get(args):
    result = get_project_progress(args.project_id)
    if not result:
        err(f"Project '{args.project_id}' not found")
    out(result, pretty=args.pretty)


def cmd_project_update(args):
    result = update_project(
        args.project_id,
        name=args.name,
        description=args.desc,
        status=args.status,
    )
    if not result:
        err(f"Project '{args.project_id}' not found")
    out(result, pretty=args.pretty)


def cmd_project_delete(args):
    success = delete_project(args.project_id)
    if not success:
        err(f"Project '{args.project_id}' not found")
    out({"deleted": True})


def cmd_task_create(args):
    result = create_task(
        args.project_id,
        args.title,
        description=args.desc or "",
        parent_id=args.parent,
        after_task_id=args.after,
    )
    if not result:
        err(f"Project '{args.project_id}' not found")
    out(result, pretty=args.pretty)


def cmd_task_list(args):
    result = list_tasks(
        args.project_id,
        status=args.status,
        parent_id=args.parent,
    )
    out(result, pretty=args.pretty)


def cmd_task_get(args):
    result = get_task(args.task_id)
    if not result:
        err(f"Task '{args.task_id}' not found")
    out(result, pretty=args.pretty)


def cmd_task_tree(args):
    result = get_task_tree(args.task_id)
    if not result:
        err(f"Task '{args.task_id}' not found")
    out(result, pretty=args.pretty)


def cmd_task_subtree(args):
    result = get_task_subtree(args.project_id)
    out(result, pretty=args.pretty)


def cmd_task_update(args):
    result = update_task(
        args.task_id,
        title=args.title,
        description=args.desc,
        status=args.status,
    )
    if not result:
        err(f"Task '{args.task_id}' not found")
    out(result, pretty=args.pretty)


def cmd_task_move(args):
    # Empty string for --parent means "make root level"
    parent = args.parent if args.parent is not None else None
    if args.parent == "":
        parent = None
    result = move_task(
        args.task_id,
        after_task_id=args.after,
        parent_id=parent,
    )
    if not result:
        err(f"Task '{args.task_id}' not found")
    out(result, pretty=args.pretty)


def cmd_task_delete(args):
    success = delete_task(args.task_id)
    if not success:
        err(f"Task '{args.task_id}' not found")
    out({"deleted": True})


def cmd_doc_project_get(args):
    content = get_project_doc(args.project_id, args.type)
    out({"project_id": args.project_id, "doc_type": args.type, "content": content}, pretty=args.pretty)


def cmd_doc_project_set(args):
    ok = upsert_project_doc(args.project_id, args.content, args.type)
    if not ok:
        err(f"Project '{args.project_id}' not found")
    out({"updated": True, "doc_type": args.type})


def cmd_doc_task_get(args):
    content = get_task_doc(args.task_id, args.type)
    out({"task_id": args.task_id, "doc_type": args.type, "content": content}, pretty=args.pretty)


def cmd_doc_task_set(args):
    ok = upsert_task_doc(args.task_id, args.content, args.type)
    if not ok:
        err(f"Task '{args.task_id}' not found")
    out({"updated": True, "doc_type": args.type})


# ---------------------------------------------------------------------------
# Comment handlers
# ---------------------------------------------------------------------------

def cmd_comment_add(args):
    result = add_comment(args.entity_type, args.entity_id, args.content, args.author)
    out(result, pretty=args.pretty)


def cmd_comment_list(args):
    result = list_comments(args.entity_type, args.entity_id)
    out(result, pretty=args.pretty)


def cmd_comment_delete(args):
    ok = delete_comment(args.comment_id)
    if not ok:
        err(f"Comment '{args.comment_id}' not found")
    out({"deleted": True})


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    # Parent parser with shared flags — added to every subparser
    parent = argparse.ArgumentParser(add_help=False)
    parent.add_argument("--pretty", "-p", action="store_true",
                        help="Pretty-print JSON output (default: compact JSON for agents)")

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

    t_subtree = task_sub.add_parser("subtree", parents=[parent], help="Get full task hierarchy for a project")
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

    doc_proj_set = doc_proj_sub.add_parser("set", parents=[parent], help="Set project docs (markdown)")
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

    doc_task_set = doc_task_sub.add_parser("set", parents=[parent], help="Set task docs (markdown)")
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
