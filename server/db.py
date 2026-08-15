import sqlite3
import uuid
import os
import hashlib
import secrets
import bcrypt
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Optional

DB_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("TM_DB_PATH") or os.path.join(DB_DIR, "task_manager.db")
SCHEMA_PATH = os.path.join(DB_DIR, "schema.sql")


@contextmanager
def get_connection():
    """Context manager for SQLite connections. Auto-commits on success,
    rolls back on exception, and always closes the connection."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    with open(SCHEMA_PATH) as f:
        schema = f.read()
    with get_connection() as conn:
        conn.executescript(schema)
        _ensure_user_id_columns(conn)


def _ensure_user_id_columns(conn: sqlite3.Connection) -> None:
    """Idempotently add user_id columns for databases created before the
    user-management migration. Runs after the base schema so the users table
    always exists by the time any REFERENCES clause is applied."""
    def _has_column(table: str, column: str) -> bool:
        return any(c["name"] == column for c in conn.execute(f"PRAGMA table_info({table})").fetchall())

    if not _has_column("agents", "user_id"):
        conn.execute("ALTER TABLE agents ADD COLUMN user_id TEXT REFERENCES users(id)")
    if not _has_column("projects", "user_id"):
        conn.execute("ALTER TABLE projects ADD COLUMN user_id TEXT NOT NULL DEFAULT ''")
    if not _has_column("agent_audit_log", "user_id"):
        conn.execute("ALTER TABLE agent_audit_log ADD COLUMN user_id TEXT")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_projects_user ON projects(user_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_agents_user ON agents(user_id)")


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------

def _hash_password(password: str) -> str:
    """Hash a plaintext password using bcrypt."""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def _verify_password(password: str, password_hash: str) -> bool:
    """Verify a plaintext password against a bcrypt hash."""
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def _user_from_row(row) -> dict:
    """Shape a users row into a public user dict (never exposes password_hash)."""
    return {
        "id": row["id"],
        "username": row["username"],
        "email": row["email"],
        "role": row["role"],
        "created_at": row["created_at"],
    }


def create_user(username: str, email: str = "", password: Optional[str] = None) -> Optional[dict]:
    """Create a new user. Password is bcrypt-hashed. Returns user dict
    (without password_hash) or None if the username is already taken."""
    if not password:
        raise ValueError("password is required")
    uid = str(uuid.uuid4())
    password_hash = _hash_password(password)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    with get_connection() as conn:
        try:
            conn.execute(
                "INSERT INTO users (id, username, email, password_hash, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (uid, username, email or "", password_hash, now),
            )
        except sqlite3.IntegrityError:
            return None  # username already exists
        row = conn.execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()
    return _user_from_row(row)


def validate_user(username: str, password: str) -> Optional[dict]:
    """Validate username/password credentials. Returns user dict (no
    password_hash) on success, or None on failure."""
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    if not row:
        return None
    if not _verify_password(password, row["password_hash"]):
        return None
    return _user_from_row(row)


def get_user(user_id: str) -> Optional[dict]:
    """Get a single user by id (without password_hash)."""
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return _user_from_row(row) if row else None


def list_users() -> list[dict]:
    """List all users (without password_hash)."""
    with get_connection() as conn:
        rows = conn.execute("SELECT * FROM users ORDER BY created_at ASC").fetchall()
    return [_user_from_row(r) for r in rows]


def _default_user_id() -> Optional[str]:
    """Fallback owning user for legacy callers that do not pass a user_id.
    Returns the first admin user's id, or None if no users exist."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT id FROM users WHERE role = 'admin' ORDER BY created_at ASC LIMIT 1"
        ).fetchone()
    return row["id"] if row else None


# ---------------------------------------------------------------------------
# Projects
# ---------------------------------------------------------------------------

def create_project(name: str, description: str = "", user_id: Optional[str] = None) -> dict:
    if user_id is None:
        user_id = _default_user_id() or ""
    pid = str(uuid.uuid4())
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO projects (id, name, description, user_id, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (pid, name, description, user_id, now, now),
        )
        row = conn.execute("SELECT * FROM projects WHERE id = ?", (pid,)).fetchone()
    return dict(row)


def list_projects(status: Optional[str] = None, q: Optional[str] = None,
                  user_id: Optional[str] = None) -> list[dict]:
    with get_connection() as conn:
        query = "SELECT * FROM projects WHERE 1=1"
        params: list = []
        if user_id is not None:
            query += " AND user_id = ?"
            params.append(user_id)
        if status:
            query += " AND status = ?"
            params.append(status)
        if q:
            query += " AND (name LIKE ? OR description LIKE ?)"
            like = f"%{q}%"
            params.extend([like, like])
        query += " ORDER BY created_at DESC"
        rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]


def get_project(project_id: str, user_id: Optional[str] = None) -> Optional[dict]:
    with get_connection() as conn:
        if user_id is not None:
            row = conn.execute(
                "SELECT * FROM projects WHERE id = ? AND user_id = ?",
                (project_id, user_id),
            ).fetchone()
        else:
            row = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
    return dict(row) if row else None


def update_project(project_id: str, name: Optional[str] = None,
                   description: Optional[str] = None,
                   status: Optional[str] = None,
                   user_id: Optional[str] = None) -> Optional[dict]:
    with get_connection() as conn:
        if user_id is not None:
            existing = conn.execute(
                "SELECT * FROM projects WHERE id = ? AND user_id = ?",
                (project_id, user_id),
            ).fetchone()
        else:
            existing = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
        if not existing:
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
        row = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
    return dict(row)


def archive_project(project_id: str, user_id: Optional[str] = None) -> Optional[dict]:
    return update_project(project_id, status="archived", user_id=user_id)


def delete_project(project_id: str, user_id: Optional[str] = None) -> bool:
    with get_connection() as conn:
        if user_id is not None:
            cur = conn.execute(
                "DELETE FROM projects WHERE id = ? AND user_id = ?",
                (project_id, user_id),
            )
        else:
            cur = conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
        deleted = cur.rowcount > 0
    return deleted


def list_projects_with_progress(
    status: Optional[str] = None, q: Optional[str] = None,
    user_id: Optional[str] = None,
) -> list[dict]:
    """List projects with task counts in a single query (avoids N+1)."""
    with get_connection() as conn:
        query = (
            "SELECT p.*, "
            "COUNT(t.id) AS total_tasks, "
            "COALESCE(SUM(CASE WHEN t.status = 'completed' THEN 1 ELSE 0 END), 0) "
            "AS completed_tasks "
            "FROM projects p "
            "LEFT JOIN tasks t ON t.project_id = p.id "
            "WHERE 1=1"
        )
        params: list = []
        if user_id is not None:
            query += " AND p.user_id = ?"
            params.append(user_id)
        if status:
            query += " AND p.status = ?"
            params.append(status)
        if q:
            query += " AND (p.name LIKE ? OR p.description LIKE ?)"
            like = f"%{q}%"
            params.extend([like, like])
        query += " GROUP BY p.id ORDER BY p.created_at DESC"
        rows = conn.execute(query, params).fetchall()

    result = []
    for row in rows:
        d = dict(row)
        total = d.get("total_tasks") or 0
        completed = d.get("completed_tasks") or 0
        d["progress_pct"] = round((completed / total * 100)) if total > 0 else 0
        result.append(d)
    return result


def get_project_progress(project_id: str, user_id: Optional[str] = None) -> Optional[dict]:
    with get_connection() as conn:
        if user_id is not None:
            proj = conn.execute(
                "SELECT * FROM projects WHERE id = ? AND user_id = ?",
                (project_id, user_id),
            ).fetchone()
        else:
            proj = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
        if not proj:
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


def _task_owned_by(conn: sqlite3.Connection, task_id: str, user_id: str) -> bool:
    """True if the task's project is owned by user_id."""
    row = conn.execute(
        "SELECT p.user_id FROM tasks t JOIN projects p ON t.project_id = p.id WHERE t.id = ?",
        (task_id,),
    ).fetchone()
    return row is not None and row["user_id"] == user_id


def _entity_owner_user_id(conn: sqlite3.Connection, entity_type: str, entity_id: str) -> Optional[str]:
    """Resolve the owning project's user_id for a project or task entity."""
    if entity_type == "project":
        row = conn.execute("SELECT user_id FROM projects WHERE id = ?", (entity_id,)).fetchone()
    elif entity_type == "task":
        row = conn.execute(
            "SELECT p.user_id FROM tasks t JOIN projects p ON t.project_id = p.id WHERE t.id = ?",
            (entity_id,),
        ).fetchone()
    else:
        return None
    return row["user_id"] if row else None


def create_task(project_id: str, title: str, description: str = "",
                parent_id: Optional[str] = None,
                after_task_id: Optional[str] = None,
                user_id: Optional[str] = None) -> Optional[dict]:
    with get_connection() as conn:
        if user_id is not None:
            proj = conn.execute(
                "SELECT id FROM projects WHERE id = ? AND user_id = ?",
                (project_id, user_id),
            ).fetchone()
        else:
            proj = conn.execute("SELECT id FROM projects WHERE id = ?", (project_id,)).fetchone()
        if not proj:
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
        row = conn.execute("SELECT * FROM tasks WHERE id = ?", (tid,)).fetchone()
    return dict(row)


def list_tasks(project_id: str, status: Optional[str] = None,
               parent_id: Optional[str] = None,
               user_id: Optional[str] = None) -> list[dict]:
    with get_connection() as conn:
        if user_id is not None:
            owned = conn.execute(
                "SELECT 1 FROM projects WHERE id = ? AND user_id = ?",
                (project_id, user_id),
            ).fetchone()
            if not owned:
                return []

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
    return [dict(r) for r in rows]


def get_task(task_id: str, user_id: Optional[str] = None) -> Optional[dict]:
    with get_connection() as conn:
        if user_id is not None:
            row = conn.execute(
                "SELECT t.* FROM tasks t JOIN projects p ON t.project_id = p.id "
                "WHERE t.id = ? AND p.user_id = ?",
                (task_id, user_id),
            ).fetchone()
        else:
            row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    return dict(row) if row else None


def get_task_tree(task_id: str, user_id: Optional[str] = None) -> Optional[dict]:
    """Get a task with its full recursive subtree of nested children."""
    task = get_task(task_id, user_id=user_id)
    if not task:
        return None
    full = get_task_subtree(task["project_id"], user_id=user_id)

    def _find_node(nodes: list[dict], tid: str) -> Optional[dict]:
        for node in nodes:
            if node["id"] == tid:
                return node
            if node.get("children"):
                found = _find_node(node["children"], tid)
                if found:
                    return found
        return None

    return _find_node(full, task_id)


def get_task_subtree(project_id: str, user_id: Optional[str] = None) -> list[dict]:
    """Get hierarchical task tree for an entire project."""
    with get_connection() as conn:
        if user_id is not None:
            owned = conn.execute(
                "SELECT 1 FROM projects WHERE id = ? AND user_id = ?",
                (project_id, user_id),
            ).fetchone()
            if not owned:
                return []
        rows = conn.execute(
            "SELECT * FROM tasks WHERE project_id = ? ORDER BY rank ASC", (project_id,)
        ).fetchall()

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
                status: Optional[str] = None,
                user_id: Optional[str] = None) -> Optional[dict]:
    with get_connection() as conn:
        if user_id is not None:
            existing = conn.execute(
                "SELECT t.* FROM tasks t JOIN projects p ON t.project_id = p.id "
                "WHERE t.id = ? AND p.user_id = ?",
                (task_id, user_id),
            ).fetchone()
        else:
            existing = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if not existing:
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
        row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    return dict(row)


# Sentinel to distinguish "not provided" from "explicitly None"
_UNSET = "___UNSET___"


def move_task(task_id: str, after_task_id: Optional[str] = None,
              parent_id: Optional[str] = _UNSET,
              user_id: Optional[str] = None) -> Optional[dict]:
    with get_connection() as conn:
        if user_id is not None:
            task = conn.execute(
                "SELECT t.* FROM tasks t JOIN projects p ON t.project_id = p.id "
                "WHERE t.id = ? AND p.user_id = ?",
                (task_id, user_id),
            ).fetchone()
        else:
            task = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if not task:
            return None

        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        if parent_id is _UNSET:
            new_parent = task["parent_id"]
        else:
            new_parent = parent_id  # None means "make root level"

        if after_task_id:
            rank = _rank_after(conn, task["project_id"], after_task_id, new_parent)
        else:
            rank = _next_rank(conn, task["project_id"], new_parent)

        conn.execute(
            "UPDATE tasks SET parent_id = ?, rank = ?, updated_at = ? WHERE id = ?",
            (new_parent, rank, now, task_id),
        )
        row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    return dict(row)


def delete_task(task_id: str, user_id: Optional[str] = None) -> bool:
    with get_connection() as conn:
        if user_id is not None:
            if not _task_owned_by(conn, task_id, user_id):
                return False
        cur = conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        deleted = cur.rowcount > 0
    return deleted


# ---------------------------------------------------------------------------
# Documentation
# ---------------------------------------------------------------------------

def get_project_doc(project_id: str, doc_type: str = "spec",
                    user_id: Optional[str] = None) -> Optional[str]:
    meta = get_project_doc_meta(project_id, doc_type, user_id=user_id)
    return meta["content"] if meta else ""


def get_project_doc_meta(project_id: str, doc_type: str = "spec",
                         user_id: Optional[str] = None) -> Optional[dict]:
    with get_connection() as conn:
        if user_id is not None:
            row = conn.execute(
                "SELECT d.content, d.updated_at FROM project_docs d "
                "JOIN projects p ON d.project_id = p.id "
                "WHERE d.project_id = ? AND d.doc_type = ? AND p.user_id = ?",
                (project_id, doc_type, user_id),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT content, updated_at FROM project_docs WHERE project_id = ? AND doc_type = ?",
                (project_id, doc_type),
            ).fetchone()
    if not row or not row["content"]:
        return None
    return dict(row)


def get_task_doc(task_id: str, doc_type: str = "spec",
                 user_id: Optional[str] = None) -> Optional[str]:
    meta = get_task_doc_meta(task_id, doc_type, user_id=user_id)
    return meta["content"] if meta else ""


def get_task_doc_meta(task_id: str, doc_type: str = "spec",
                      user_id: Optional[str] = None) -> Optional[dict]:
    with get_connection() as conn:
        if user_id is not None:
            row = conn.execute(
                "SELECT d.content, d.updated_at FROM task_docs d "
                "JOIN tasks t ON d.task_id = t.id "
                "JOIN projects p ON t.project_id = p.id "
                "WHERE d.task_id = ? AND d.doc_type = ? AND p.user_id = ?",
                (task_id, doc_type, user_id),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT content, updated_at FROM task_docs WHERE task_id = ? AND doc_type = ?",
                (task_id, doc_type),
            ).fetchone()
    if not row or not row["content"]:
        return None
    return dict(row)


def build_project_docs_hub(project_id: str, doc_type: str = "spec",
                           user_id: Optional[str] = None) -> dict:
    """Project doc + task tree with docs attached for read-only hub."""
    with get_connection() as conn:
        if user_id is not None:
            owned = conn.execute(
                "SELECT 1 FROM projects WHERE id = ? AND user_id = ?",
                (project_id, user_id),
            ).fetchone()
            if not owned:
                return {"project_doc": None, "task_tree": []}

        proj_row = conn.execute(
            "SELECT content, updated_at FROM project_docs WHERE project_id = ? AND doc_type = ?",
            (project_id, doc_type),
        ).fetchone()
        task_doc_rows = conn.execute(
            "SELECT t.id, d.content, d.updated_at "
            "FROM tasks t "
            "LEFT JOIN task_docs d ON d.task_id = t.id AND d.doc_type = ? "
            "WHERE t.project_id = ?",
            (doc_type, project_id),
        ).fetchall()

    docs_by_task: dict[str, dict] = {}
    for r in task_doc_rows:
        if r["content"]:
            docs_by_task[r["id"]] = {"content": r["content"], "updated_at": r["updated_at"]}

    tree = get_task_subtree(project_id, user_id=user_id)
    _attach_docs_to_tree(tree, docs_by_task)

    return {
        "project_doc": dict(proj_row) if proj_row and proj_row["content"] else None,
        "task_tree": tree,
    }


def _attach_docs_to_tree(tasks: list[dict], docs_by_task: dict[str, dict]) -> None:
    for t in tasks:
        t["doc"] = docs_by_task.get(t["id"])
        if t.get("children"):
            _attach_docs_to_tree(t["children"], docs_by_task)


def upsert_task_doc(task_id: str, content: str, doc_type: str = "spec",
                    user_id: Optional[str] = None) -> bool:
    with get_connection() as conn:
        if user_id is not None:
            t = conn.execute(
                "SELECT t.id FROM tasks t JOIN projects p ON t.project_id = p.id "
                "WHERE t.id = ? AND p.user_id = ?",
                (task_id, user_id),
            ).fetchone()
        else:
            t = conn.execute("SELECT id FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if not t:
            return False

        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        doc_id = str(uuid.uuid4())
        conn.execute(
            "INSERT INTO task_docs (id, task_id, doc_type, content, updated_at) VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(task_id, doc_type) DO UPDATE SET content = excluded.content, updated_at = excluded.updated_at",
            (doc_id, task_id, doc_type, content, now),
        )
    return True


def upsert_project_doc(project_id: str, content: str, doc_type: str = "spec",
                       user_id: Optional[str] = None) -> bool:
    with get_connection() as conn:
        if user_id is not None:
            proj = conn.execute(
                "SELECT id FROM projects WHERE id = ? AND user_id = ?",
                (project_id, user_id),
            ).fetchone()
        else:
            proj = conn.execute("SELECT id FROM projects WHERE id = ?", (project_id,)).fetchone()
        if not proj:
            return False

        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        doc_id = str(uuid.uuid4())
        conn.execute(
            "INSERT INTO project_docs (id, project_id, doc_type, content, updated_at) VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(project_id, doc_type) DO UPDATE SET content = excluded.content, updated_at = excluded.updated_at",
            (doc_id, project_id, doc_type, content, now),
        )
    return True


# ---------------------------------------------------------------------------
# Comments
# ---------------------------------------------------------------------------

def add_comment(entity_type: str, entity_id: str, content: str,
                author: str = "", user_id: Optional[str] = None) -> Optional[dict]:
    cid = str(uuid.uuid4())
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    with get_connection() as conn:
        if user_id is not None:
            owner = _entity_owner_user_id(conn, entity_type, entity_id)
            if owner != user_id:
                return None
        conn.execute(
            "INSERT INTO comments (id, entity_type, entity_id, author, content, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (cid, entity_type, entity_id, author, content, now),
        )
        row = conn.execute("SELECT * FROM comments WHERE id = ?", (cid,)).fetchone()
    return dict(row)


def list_comments(
    entity_type: str,
    entity_id: str,
    limit: Optional[int] = None,
    since: Optional[str] = None,
    user_id: Optional[str] = None,
) -> list[dict]:
    with get_connection() as conn:
        if user_id is not None:
            owner = _entity_owner_user_id(conn, entity_type, entity_id)
            if owner != user_id:
                return []

        query = (
            "SELECT * FROM comments WHERE entity_type = ? AND entity_id = ?"
        )
        params: list = [entity_type, entity_id]
        if since:
            query += " AND created_at >= ?"
            params.append(since)
        query += " ORDER BY created_at ASC"
        if limit:
            query += " LIMIT ?"
            params.append(limit)
        rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]


def delete_comment(comment_id: str, user_id: Optional[str] = None) -> bool:
    with get_connection() as conn:
        if user_id is not None:
            comment = conn.execute(
                "SELECT entity_type, entity_id FROM comments WHERE id = ?", (comment_id,)
            ).fetchone()
            if not comment:
                return False
            owner = _entity_owner_user_id(conn, comment["entity_type"], comment["entity_id"])
            if owner != user_id:
                return False
        cur = conn.execute("DELETE FROM comments WHERE id = ?", (comment_id,))
        deleted = cur.rowcount > 0
    return deleted


def count_comments(entity_type: str, entity_id: str) -> int:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT COUNT(*) FROM comments WHERE entity_type = ? AND entity_id = ?",
            (entity_type, entity_id),
        ).fetchone()
    return row[0]


def get_task_subtask_stats(task_id: str) -> dict:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT status, COUNT(*) as cnt FROM tasks WHERE parent_id = ? GROUP BY status",
            (task_id,),
        ).fetchall()
    by_status = {r["status"]: r["cnt"] for r in rows}
    total = sum(by_status.values())
    completed = by_status.get("completed", 0)
    terminal = sum(by_status.get(s, 0) for s in ("completed", "cancelled", "failed"))
    return {
        "subtask_count": total,
        "subtasks_completed": completed,
        "subtasks_terminal": terminal,
        "subtasks_active": total - terminal,
    }


def get_docs_summary(entity_type: str, entity_id: str) -> dict:
    summary: dict = {}
    for doc_type in ("spec", "progress", "closure"):
        if entity_type == "project":
            meta = get_project_doc_meta(entity_id, doc_type)
        else:
            meta = get_task_doc_meta(entity_id, doc_type)
        summary[doc_type] = {
            "exists": meta is not None,
            "updated_at": meta["updated_at"] if meta else None,
            "char_count": len(meta["content"]) if meta else 0,
        }
    return summary


# ---------------------------------------------------------------------------
# Agent onboarding & auth
# ---------------------------------------------------------------------------

def _hash_key(api_key: str) -> str:
    """SHA-256 hash of an API key."""
    return hashlib.sha256(api_key.encode()).hexdigest()


def _generate_api_key() -> str:
    """Generate a random API key with 'tm_' prefix."""
    return "tm_" + secrets.token_hex(32)


def onboard_agent(name: str, master_name: str,
                  user_id: Optional[str] = None) -> Optional[dict]:
    """DEPRECATED: register a standalone agent without user scope.

    Kept for backward compatibility during the migration window only. New code
    should use ``create_agent(user_id, name)`` instead.
    Returns agent info + plaintext api_key (shown once)."""
    api_key = _generate_api_key()
    key_hash = _hash_key(api_key)
    aid = str(uuid.uuid4())
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    with get_connection() as conn:
        try:
            conn.execute(
                "INSERT INTO agents (id, name, master_name, api_key_hash, user_id, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (aid, name, master_name, key_hash, user_id, now),
            )
        except sqlite3.IntegrityError:
            return None  # Name already exists
        row = conn.execute("SELECT * FROM agents WHERE id = ?", (aid,)).fetchone()
    result = dict(row)
    result["api_key"] = api_key  # Plaintext, shown once
    return result


def create_agent(user_id: str, name: str, master_name: Optional[str] = None) -> Optional[dict]:
    """Create a new agent owned by ``user_id``. Returns agent info + plaintext
    api_key (shown once), or None if the user does not exist or the name is
    already taken. ``master_name`` defaults to the owning user's username."""
    user = get_user(user_id)
    if not user:
        return None

    api_key = _generate_api_key()
    key_hash = _hash_key(api_key)
    aid = str(uuid.uuid4())
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    effective_master = master_name or user["username"]
    with get_connection() as conn:
        try:
            conn.execute(
                "INSERT INTO agents (id, user_id, name, master_name, api_key_hash, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (aid, user_id, name, effective_master, key_hash, now),
            )
        except sqlite3.IntegrityError:
            return None  # Name already exists
        row = conn.execute(
            "SELECT id, user_id, name, master_name, role, created_at, active FROM agents WHERE id = ?",
            (aid,),
        ).fetchone()
    result = dict(row)
    result["api_key"] = api_key  # Plaintext, shown once
    return result


def validate_api_key(api_key: str) -> Optional[dict]:
    """Validate an API key. Returns an enriched dict with user context, or None
    if the key is invalid/inactive.

    Return shape: {id, name, master_name, role, user_id, user_name, user_role}.
    """
    key_hash = _hash_key(api_key)
    with get_connection() as conn:
        row = conn.execute(
            "SELECT a.id, a.name, a.master_name, a.role, a.user_id, "
            "u.username AS user_name, u.role AS user_role "
            "FROM agents a LEFT JOIN users u ON a.user_id = u.id "
            "WHERE a.api_key_hash = ? AND a.active = 1",
            (key_hash,),
        ).fetchone()
    return dict(row) if row else None


def list_agents() -> list[dict]:
    """List all registered agents (excluding api_key_hash) with user context."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT a.id, a.name, a.master_name, a.role, a.created_at, a.active, a.user_id, "
            "u.username AS user_name, u.role AS user_role "
            "FROM agents a LEFT JOIN users u ON a.user_id = u.id ORDER BY a.created_at DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def list_user_agents(user_id: str) -> list[dict]:
    """List all agents owned by ``user_id`` (excluding api_key_hash)."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT id, user_id, name, master_name, role, created_at, active "
            "FROM agents WHERE user_id = ? ORDER BY created_at DESC",
            (user_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_agent(agent_id: str) -> Optional[dict]:
    """Get a single agent by ID (excluding api_key_hash)."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT a.id, a.name, a.master_name, a.role, a.created_at, a.active, a.user_id, "
            "u.username AS user_name, u.role AS user_role "
            "FROM agents a LEFT JOIN users u ON a.user_id = u.id WHERE a.id = ?",
            (agent_id,),
        ).fetchone()
    return dict(row) if row else None


def reissue_agent_key(agent_id: str, user_id: str) -> Optional[dict]:
    """Reissue an API key for an agent owned by ``user_id``. Invalidates the
    old key and returns the new plaintext key once. Returns None if the agent
    does not exist or is not owned by ``user_id``."""
    api_key = _generate_api_key()
    key_hash = _hash_key(api_key)
    with get_connection() as conn:
        existing = conn.execute(
            "SELECT id FROM agents WHERE id = ? AND user_id = ?", (agent_id, user_id)
        ).fetchone()
        if not existing:
            return None
        conn.execute("UPDATE agents SET api_key_hash = ? WHERE id = ?", (key_hash, agent_id))
        row = conn.execute(
            "SELECT id, user_id, name, master_name, role, created_at, active FROM agents WHERE id = ?",
            (agent_id,),
        ).fetchone()
    result = dict(row)
    result["api_key"] = api_key  # Plaintext, shown once
    return result


def reissue_api_key(agent_id: str) -> Optional[dict]:
    """DEPRECATED: reissue a key without user scope. Prefer
    ``reissue_agent_key(agent_id, user_id)``. Returns new plaintext key once."""
    api_key = _generate_api_key()
    key_hash = _hash_key(api_key)
    with get_connection() as conn:
        existing = conn.execute("SELECT id FROM agents WHERE id = ?", (agent_id,)).fetchone()
        if not existing:
            return None
        conn.execute("UPDATE agents SET api_key_hash = ? WHERE id = ?", (key_hash, agent_id))
        row = conn.execute(
            "SELECT id, name, master_name, role, created_at, active FROM agents WHERE id = ?",
            (agent_id,),
        ).fetchone()
    result = dict(row)
    result["api_key"] = api_key  # Plaintext, shown once
    return result


# ---------------------------------------------------------------------------
# Audit logging
# ---------------------------------------------------------------------------

def log_audit(agent_name: str, master_name: str, entity_type: str,
              entity_id: str, action: str, field: Optional[str] = None,
              old_value: Optional[str] = None,
              new_value: Optional[str] = None,
              user_id: Optional[str] = None) -> None:
    """Record a mutation in the audit log."""
    aid = str(uuid.uuid4())
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO agent_audit_log (id, agent_name, master_name, entity_type, "
            "entity_id, action, field, old_value, new_value, user_id, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (aid, agent_name, master_name, entity_type, entity_id,
             action, field, old_value, new_value, user_id, now),
        )


def get_audit_log(entity_type: str, entity_id: str) -> list[dict]:
    """Get audit log entries for a specific entity."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM agent_audit_log WHERE entity_type = ? AND entity_id = ? "
            "ORDER BY created_at DESC",
            (entity_type, entity_id),
        ).fetchall()
    return [dict(r) for r in rows]


def get_audit_log_by_agent(agent_name: str, limit: int = 100) -> list[dict]:
    """Get audit log entries for a specific agent."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM agent_audit_log WHERE agent_name = ? "
            "ORDER BY created_at DESC LIMIT ?",
            (agent_name, limit),
        ).fetchall()
    return [dict(r) for r in rows]


def get_audit_log_by_agent_paginated(
    agent_name: str, limit: int = 50, offset: int = 0
) -> dict:
    """Get paginated audit log entries for a specific agent."""
    with get_connection() as conn:
        total = conn.execute(
            "SELECT COUNT(*) FROM agent_audit_log WHERE agent_name = ?",
            (agent_name,),
        ).fetchone()[0]
        rows = conn.execute(
            "SELECT * FROM agent_audit_log WHERE agent_name = ? "
            "ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (agent_name, limit, offset),
        ).fetchall()
    page = (offset // limit) + 1 if limit else 1
    pages = max(1, (total + limit - 1) // limit) if limit else 1
    return {
        "entries": [dict(r) for r in rows],
        "total": total,
        "page": page,
        "pages": pages,
        "limit": limit,
    }


def get_project_audit_log(project_id: str, limit: int = 100) -> list[dict]:
    """Audit entries for a project and all its tasks."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT a.*, t.title AS task_title "
            "FROM agent_audit_log a "
            "LEFT JOIN tasks t ON a.entity_type = 'task' AND a.entity_id = t.id "
            "WHERE (a.entity_type = 'project' AND a.entity_id = ?) "
            "   OR (a.entity_type = 'task' AND t.project_id = ?) "
            "ORDER BY a.created_at DESC LIMIT ?",
            (project_id, project_id, limit),
        ).fetchall()
    return [dict(r) for r in rows]


def get_project_audit_log_paginated(
    project_id: str, limit: int = 50, offset: int = 0
) -> dict:
    """Paginated audit entries for a project and all its tasks."""
    base_where = (
        "(a.entity_type = 'project' AND a.entity_id = ?) "
        "OR (a.entity_type = 'task' AND t.project_id = ?)"
    )
    with get_connection() as conn:
        total = conn.execute(
            f"SELECT COUNT(*) FROM agent_audit_log a "
            f"LEFT JOIN tasks t ON a.entity_type = 'task' AND a.entity_id = t.id "
            f"WHERE {base_where}",
            (project_id, project_id),
        ).fetchone()[0]
        rows = conn.execute(
            f"SELECT a.*, t.title AS task_title "
            f"FROM agent_audit_log a "
            f"LEFT JOIN tasks t ON a.entity_type = 'task' AND a.entity_id = t.id "
            f"WHERE {base_where} "
            f"ORDER BY a.created_at DESC LIMIT ? OFFSET ?",
            (project_id, project_id, limit, offset),
        ).fetchall()
    page = (offset // limit) + 1 if limit else 1
    pages = max(1, (total + limit - 1) // limit) if limit else 1
    return {
        "entries": [dict(r) for r in rows],
        "total": total,
        "page": page,
        "pages": pages,
        "limit": limit,
    }


def get_recent_activity(limit: int = 25) -> list[dict]:
    """Cross-project activity feed from audit log."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT a.*, "
            "p.name AS project_name, "
            "t.title AS task_title, "
            "t.project_id AS task_project_id "
            "FROM agent_audit_log a "
            "LEFT JOIN tasks t ON a.entity_type = 'task' AND a.entity_id = t.id "
            "LEFT JOIN projects p ON "
            "  (a.entity_type = 'project' AND a.entity_id = p.id) "
            "  OR (a.entity_type = 'task' AND t.project_id = p.id) "
            "WHERE a.entity_type IN ('project', 'task') "
            "ORDER BY a.created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_task_last_in_progress_agent(task_id: str) -> Optional[str]:
    """Agent who most recently moved this task to in_progress."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT agent_name FROM agent_audit_log "
            "WHERE entity_type = 'task' AND entity_id = ? "
            "AND action = 'status_changed' AND field = 'status' AND new_value = 'in_progress' "
            "ORDER BY created_at DESC LIMIT 1",
            (task_id,),
        ).fetchone()
    return row["agent_name"] if row else None


def get_agent_resumed_tasks_in_project(agent_name: str, project_id: str) -> list[dict]:
    """In-progress tasks in a project this agent most recently started working on."""
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT t.* FROM tasks t
            WHERE t.project_id = ? AND t.status = 'in_progress'
            AND (
                SELECT a.agent_name FROM agent_audit_log a
                WHERE a.entity_type = 'task' AND a.entity_id = t.id
                AND a.action = 'status_changed' AND a.field = 'status'
                AND a.new_value = 'in_progress'
                ORDER BY a.created_at DESC LIMIT 1
            ) = ?
            ORDER BY t.rank ASC
            """,
            (project_id, agent_name),
        ).fetchall()
    return [dict(r) for r in rows]


def get_task_creator(task_id: str) -> Optional[dict]:
    """Who created a task (from audit log)."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT agent_name, master_name, created_at FROM agent_audit_log "
            "WHERE entity_type = 'task' AND entity_id = ? AND action = 'created' "
            "ORDER BY created_at ASC LIMIT 1",
            (task_id,),
        ).fetchone()
    return dict(row) if row else None
