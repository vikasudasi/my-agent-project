#!/usr/bin/env python3
"""Migrate a project from local SQLite to a remote task-manager MCP server."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import urllib.error
import urllib.request
from collections import defaultdict
from pathlib import Path
from typing import Any

DEFAULT_DB = Path(__file__).parent / "task_manager.db"
DEFAULT_MCP_URL = "http://taskman.visualdna.com:8001/mcp"
ONBOARDING_PATH = Path.home() / ".my-agent" / "onboarding.json"


class McpClient:
    def __init__(self, url: str, api_key: str | None = None):
        self.url = url.rstrip("/")
        self.api_key = api_key
        self._req_id = 0

    def call(self, name: str, arguments: dict | None = None) -> Any:
        self._req_id += 1
        args = dict(arguments or {})
        if self.api_key and name != "agent_onboard":
            args.setdefault("api_key", self.api_key)

        payload = {
            "jsonrpc": "2.0",
            "id": self._req_id,
            "method": "tools/call",
            "params": {"name": name, "arguments": args},
        }
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            self.url,
            data=body,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                raw = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"MCP HTTP {e.code}: {e.read().decode()}") from e

        if "error" in raw:
            raise RuntimeError(f"MCP error: {raw['error']}")

        result = raw.get("result", {})
        if result.get("isError"):
            text = result["content"][0]["text"]
            data = json.loads(text)
            raise RuntimeError(data.get("error", text))

        text = result["content"][0]["text"]
        return json.loads(text)


def load_local_project(conn: sqlite3.Connection, project_id: str) -> dict:
    project = conn.execute(
        "SELECT * FROM projects WHERE id = ?", (project_id,)
    ).fetchone()
    if not project:
        raise SystemExit(f"Project {project_id} not found in local DB")
    return dict(project)


def load_tasks(conn: sqlite3.Connection, project_id: str) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM tasks WHERE project_id = ? ORDER BY rank",
        (project_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def ordered_tasks(tasks: list[dict]) -> list[dict]:
    by_parent: dict[str | None, list[dict]] = defaultdict(list)
    for task in tasks:
        by_parent[task["parent_id"]].append(task)
    for siblings in by_parent.values():
        siblings.sort(key=lambda t: t["rank"])

    ordered: list[dict] = []

    def walk(parent_id: str | None) -> None:
        for task in by_parent.get(parent_id, []):
            ordered.append(task)
            walk(task["id"])

    walk(None)
    return ordered


def load_task_docs(conn: sqlite3.Connection, task_ids: list[str]) -> dict[str, dict[str, str]]:
    if not task_ids:
        return {}
    placeholders = ",".join("?" * len(task_ids))
    rows = conn.execute(
        f"SELECT task_id, doc_type, content FROM task_docs WHERE task_id IN ({placeholders})",
        task_ids,
    ).fetchall()
    out: dict[str, dict[str, str]] = defaultdict(dict)
    for row in rows:
        out[row["task_id"]][row["doc_type"]] = row["content"]
    return out


def load_project_docs(conn: sqlite3.Connection, project_id: str) -> dict[str, str]:
    rows = conn.execute(
        "SELECT doc_type, content FROM project_docs WHERE project_id = ?",
        (project_id,),
    ).fetchall()
    return {row["doc_type"]: row["content"] for row in rows}


def load_comments(conn: sqlite3.Connection, entity_type: str, entity_ids: list[str]) -> list[dict]:
    if not entity_ids:
        return []
    placeholders = ",".join("?" * len(entity_ids))
    rows = conn.execute(
        f"""SELECT * FROM comments
            WHERE entity_type = ? AND entity_id IN ({placeholders})
            ORDER BY created_at""",
        [entity_type, *entity_ids],
    ).fetchall()
    return [dict(r) for r in rows]


def migrate(
    *,
    project_id: str,
    db_path: Path,
    mcp_url: str,
    api_key: str,
    dry_run: bool = False,
) -> dict:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    project = load_local_project(conn, project_id)
    tasks = load_tasks(conn, project_id)
    task_docs = load_task_docs(conn, [t["id"] for t in tasks])
    project_docs = load_project_docs(conn, project_id)
    task_comments = load_comments(conn, "task", [t["id"] for t in tasks])
    project_comments = load_comments(conn, "project", [project_id])

    summary = {
        "source_project_id": project_id,
        "tasks": len(tasks),
        "task_docs": sum(len(v) for v in task_docs.values()),
        "project_docs": len(project_docs),
        "comments": len(task_comments) + len(project_comments),
        "dry_run": dry_run,
    }

    if dry_run:
        print(json.dumps(summary, indent=2))
        return summary

    client = McpClient(mcp_url, api_key)

    # Avoid duplicate if re-run
    existing = client.call("project_list")
    for p in existing:
        if p.get("name") == project["name"]:
            raise SystemExit(
                f"Remote already has project '{project['name']}' (id={p['id']}). "
                "Delete it first or use a different name."
            )

    created_project = client.call(
        "project_create",
        {"name": project["name"], "description": project["description"]},
    )
    new_project_id = created_project["id"]
    summary["new_project_id"] = new_project_id

    for doc_type, content in project_docs.items():
        if content.strip():
            client.call(
                "doc_project_update",
                {"project_id": new_project_id, "content": content, "doc_type": doc_type},
            )

    id_map: dict[str, str] = {}
    last_sibling: dict[str | None, str | None] = {None: None}

    for task in ordered_tasks(tasks):
        parent_key = task["parent_id"]
        args: dict[str, Any] = {
            "project_id": new_project_id,
            "title": task["title"],
        }
        if task["description"]:
            args["description"] = task["description"]
        if parent_key and parent_key in id_map:
            args["parent_id"] = id_map[parent_key]
        if last_sibling.get(parent_key):
            args["after_task_id"] = last_sibling[parent_key]

        created = client.call("task_create", args)
        new_id = created["id"]
        id_map[task["id"]] = new_id
        last_sibling[parent_key] = new_id

        if task["status"] != "pending":
            client.call(
                "task_update",
                {"task_id": new_id, "status": task["status"]},
            )

        for doc_type, content in task_docs.get(task["id"], {}).items():
            if content.strip():
                client.call(
                    "doc_task_update",
                    {"task_id": new_id, "content": content, "doc_type": doc_type},
                )

    for comment in project_comments:
        client.call(
            "comment_add",
            {
                "entity_type": "project",
                "entity_id": new_project_id,
                "content": comment["content"],
                "author": comment["author"] or "migration",
            },
        )

    for comment in task_comments:
        new_entity = id_map.get(comment["entity_id"])
        if not new_entity:
            continue
        client.call(
            "comment_add",
            {
                "entity_type": "task",
                "entity_id": new_entity,
                "content": comment["content"],
                "author": comment["author"] or "migration",
            },
        )

    # Verify
    remote = client.call("project_get", {"project_id": new_project_id})
    summary["remote_progress"] = {
        "total_tasks": remote.get("total_tasks"),
        "completed_tasks": remote.get("completed_tasks"),
        "progress_pct": remote.get("progress_pct"),
    }
    summary["id_map_path"] = str(
        Path.home() / ".my-agent" / f"migration-{project_id[:8]}-id-map.json"
    )
    Path(summary["id_map_path"]).write_text(json.dumps(id_map, indent=2))

    print(json.dumps(summary, indent=2))
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project_id", help="Local project UUID to migrate")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--mcp-url", default=DEFAULT_MCP_URL)
    parser.add_argument("--api-key", help="TM API key (or set TM_API_KEY / ~/.my-agent/onboarding.json)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    api_key = args.api_key
    if not api_key and ONBOARDING_PATH.exists():
        api_key = json.loads(ONBOARDING_PATH.read_text()).get("api_key")
    if not api_key:
        import os

        api_key = os.environ.get("TM_API_KEY")
    if not api_key and not args.dry_run:
        raise SystemExit("API key required. Run agent_onboard on remote MCP or pass --api-key.")

    migrate(
        project_id=args.project_id,
        db_path=args.db,
        mcp_url=args.mcp_url,
        api_key=api_key or "",
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()
