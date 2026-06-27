import sqlite3
import uuid
import os
from datetime import datetime, timezone
from typing import Optional

DB_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(DB_DIR, "task_manager.db")
SCHEMA_PATH = os.path.join(DB_DIR, "schema.sql")


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    with open(SCHEMA_PATH) as f:
        schema = f.read()
    conn = get_connection()
    conn.executescript(schema)
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Projects
# ---------------------------------------------------------------------------

def create_project(name: str, description: str = "") -> dict:
    pid = str(uuid.uuid4())
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    conn = get_connection()
    conn.execute(
        "INSERT INTO projects (id, name, description, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
        (pid, name, description, now, now),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM projects WHERE id = ?", (pid,)).fetchone()
    conn.close()
    return dict(row)


def list_projects() -> list[dict]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM projects ORDER BY created_at DESC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_project(project_id: str) -> Optional[dict]:
    conn = get_connection()
    row = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def update_project(project_id: str, name: Optional[str] = None,
                   description: Optional[str] = None,
                   status: Optional[str] = None) -> Optional[dict]:
    conn = get_connection()
    existing = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
    if not existing:
        conn.close()
        return None

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    fields = {"updated_at": now}
    if name is not None:
        fields["name"] = name
    if description is not None:
        fields["description"] = description
    if status is not None:
        fields["status"] = status

    set_clause = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [project_id]
    conn.execute(f"UPDATE projects SET {set_clause} WHERE id = ?", values)
    conn.commit()
    row = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
    conn.close()
    return dict(row)


def delete_project(project_id: str) -> bool:
    conn = get_connection()
    cur = conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
    conn.commit()
    deleted = cur.rowcount > 0
    conn.close()
    return deleted


def get_project_progress(project_id: str) -> Optional[dict]:
    conn = get_connection()
    proj = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
    if not proj:
        conn.close()
        return None

    total = conn.execute(
        "SELECT COUNT(*) FROM tasks WHERE project_id = ?", (project_id,)
    ).fetchone()[0]
    completed = conn.execute(
        "SELECT COUNT(*) FROM tasks WHERE project_id = ? AND status = 'completed'",
        (project_id,),
    ).fetchone()[0]
    by_status = conn.execute(
        "SELECT status, COUNT(*) as cnt FROM tasks WHERE project_id = ? GROUP BY status",
        (project_id,),
    ).fetchall()
    conn.close()

    return {
        **dict(proj),
        "total_tasks": total,
        "completed_tasks": completed,
        "progress_pct": round((completed / total * 100)) if total > 0 else 0,
        "by_status": {r["status"]: r["cnt"] for r in by_status},
    }


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------

def _next_rank(conn: sqlite3.Connection, project_id: str, parent_id: Optional[str] = None) -> float:
    """Get a rank value that places a task at the end of its sibling list."""
    if parent_id:
        row = conn.execute(
            "SELECT MAX(rank) FROM tasks WHERE project_id = ? AND parent_id = ?",
            (project_id, parent_id),
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT MAX(rank) FROM tasks WHERE project_id = ? AND parent_id IS NULL",
            (project_id,),
        ).fetchone()
    max_rank = row[0]
    return (max_rank + 1.0) if max_rank is not None else 1.0


def _rank_after(conn: sqlite3.Connection, project_id: str,
                after_task_id: str, parent_id: Optional[str] = None) -> float:
    """Compute rank to place a task after a given sibling."""
    after = conn.execute("SELECT rank FROM tasks WHERE id = ?", (after_task_id,)).fetchone()
    if not after:
        return _next_rank(conn, project_id, parent_id)

    after_rank = after["rank"]
    # Find the next sibling after `after_task_id`
    if parent_id:
        next_task = conn.execute(
            "SELECT MIN(rank) FROM tasks WHERE project_id = ? AND parent_id = ? AND rank > ?",
            (project_id, parent_id, after_rank),
        ).fetchone()
    else:
        next_task = conn.execute(
            "SELECT MIN(rank) FROM tasks WHERE project_id = ? AND parent_id IS NULL AND rank > ?",
            (project_id, after_rank),
        ).fetchone()

    next_rank = next_task[0]
    if next_rank is None:
        return after_rank + 1.0
    return (after_rank + next_rank) / 2.0


def create_task(project_id: str, title: str, description: str = "",
                parent_id: Optional[str] = None,
                after_task_id: Optional[str] = None) -> Optional[dict]:
    conn = get_connection()
    proj = conn.execute("SELECT id FROM projects WHERE id = ?", (project_id,)).fetchone()
    if not proj:
        conn.close()
        return None

    tid = str(uuid.uuid4())
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    if after_task_id:
        rank = _rank_after(conn, project_id, after_task_id, parent_id)
    else:
        rank = _next_rank(conn, project_id, parent_id)

    conn.execute(
        "INSERT INTO tasks (id, project_id, parent_id, title, description, rank, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (tid, project_id, parent_id, title, description, rank, now, now),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM tasks WHERE id = ?", (tid,)).fetchone()
    conn.close()
    return dict(row)


def list_tasks(project_id: str, status: Optional[str] = None,
               parent_id: Optional[str] = None) -> list[dict]:
    conn = get_connection()
    query = "SELECT * FROM tasks WHERE project_id = ?"
    params: list = [project_id]

    if status:
        query += " AND status = ?"
        params.append(status)
    if parent_id is not None:
        query += " AND parent_id = ?"
        params.append(parent_id)
    else:
        query += " AND parent_id IS NULL"

    query += " ORDER BY rank ASC"
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_task(task_id: str) -> Optional[dict]:
    conn = get_connection()
    row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_task_tree(task_id: str) -> Optional[dict]:
    """Get a task with its full subtree of nested children."""
    conn = get_connection()
    task = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    if not task:
        conn.close()
        return None

    task_dict = dict(task)
    children = conn.execute(
        "SELECT * FROM tasks WHERE parent_id = ? ORDER BY rank ASC", (task_id,)
    ).fetchall()
    task_dict["children"] = [dict(c) for c in children]
    conn.close()
    return task_dict


def get_task_subtree(project_id: str) -> list[dict]:
    """Get hierarchical task tree for an entire project."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM tasks WHERE project_id = ? ORDER BY rank ASC", (project_id,)
    ).fetchall()
    conn.close()

    tasks_by_id: dict[str, dict] = {}
    roots: list[dict] = []

    for r in rows:
        d = dict(r)
        d["children"] = []
        tasks_by_id[d["id"]] = d

    for d in tasks_by_id.values():
        if d["parent_id"] and d["parent_id"] in tasks_by_id:
            tasks_by_id[d["parent_id"]]["children"].append(d)
        else:
            roots.append(d)

    return roots


def update_task(task_id: str, title: Optional[str] = None,
                description: Optional[str] = None,
                status: Optional[str] = None) -> Optional[dict]:
    conn = get_connection()
    existing = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    if not existing:
        conn.close()
        return None

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    fields = {"updated_at": now}
    if title is not None:
        fields["title"] = title
    if description is not None:
        fields["description"] = description
    if status is not None:
        fields["status"] = status

    set_clause = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [task_id]
    conn.execute(f"UPDATE tasks SET {set_clause} WHERE id = ?", values)
    conn.commit()
    row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    conn.close()
    return dict(row)


def move_task(task_id: str, after_task_id: Optional[str] = None,
              parent_id: Optional[str] = None) -> Optional[dict]:
    conn = get_connection()
    task = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    if not task:
        conn.close()
        return None

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    new_parent = parent_id if parent_id is not None else task["parent_id"]

    if after_task_id:
        rank = _rank_after(conn, task["project_id"], after_task_id, new_parent)
    else:
        rank = _next_rank(conn, task["project_id"], new_parent)

    conn.execute(
        "UPDATE tasks SET parent_id = ?, rank = ?, updated_at = ? WHERE id = ?",
        (new_parent, rank, now, task_id),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    conn.close()
    return dict(row)


def delete_task(task_id: str) -> bool:
    conn = get_connection()
    cur = conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
    conn.commit()
    deleted = cur.rowcount > 0
    conn.close()
    return deleted


# ---------------------------------------------------------------------------
# Documentation
# ---------------------------------------------------------------------------

def get_project_doc(project_id: str) -> Optional[str]:
    conn = get_connection()
    row = conn.execute(
        "SELECT content FROM project_docs WHERE project_id = ?", (project_id,)
    ).fetchone()
    conn.close()
    return row["content"] if row else ""


def upsert_project_doc(project_id: str, content: str) -> bool:
    conn = get_connection()
    proj = conn.execute("SELECT id FROM projects WHERE id = ?", (project_id,)).fetchone()
    if not proj:
        conn.close()
        return False

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    doc_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO project_docs (id, project_id, content, updated_at) VALUES (?, ?, ?, ?) "
        "ON CONFLICT(project_id) DO UPDATE SET content = excluded.content, updated_at = excluded.updated_at",
        (doc_id, project_id, content, now),
    )
    conn.commit()
    conn.close()
    return True


def get_task_doc(task_id: str) -> Optional[str]:
    conn = get_connection()
    row = conn.execute(
        "SELECT content FROM task_docs WHERE task_id = ?", (task_id,)
    ).fetchone()
    conn.close()
    return row["content"] if row else ""


def upsert_task_doc(task_id: str, content: str) -> bool:
    conn = get_connection()
    t = conn.execute("SELECT id FROM tasks WHERE id = ?", (task_id,)).fetchone()
    if not t:
        conn.close()
        return False

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    doc_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO task_docs (id, task_id, content, updated_at) VALUES (?, ?, ?, ?) "
        "ON CONFLICT(task_id) DO UPDATE SET content = excluded.content, updated_at = excluded.updated_at",
        (doc_id, task_id, content, now),
    )
    conn.commit()
    conn.close()
    return True