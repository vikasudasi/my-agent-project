#!/usr/bin/env python3
"""One-time migration: user-management foundation.

Migrates an existing task_manager.db to the user-scoped schema:

  1. Creates the ``users`` table (idempotent).
  2. Adds ``user_id`` columns to ``agents``, ``projects`` and ``agent_audit_log``.
  3. Creates the admin user (username=vikasudasi, email=vikasudasi@gmail.com,
     role=admin) with a bcrypt-hashed password.
  4. Migrates the ``hermes`` agent to the admin user.
  5. Migrates all projects to the admin user.
  6. Deletes every agent that has no owning user (the non-hermes stragglers).
  7. Enforces NOT NULL on ``projects.user_id`` (the column is added as
     ``TEXT NOT NULL DEFAULT ''``, then every row is backfilled, so no NULLs
     can remain).

Admin password is read from the ``TM_ADMIN_PASSWORD`` environment variable, or
prompted for interactively (with confirmation) when unset.

Usage:
    TM_ADMIN_PASSWORD='...' python3 migrate_user_management.py
    # or
    python3 migrate_user_management.py   # prompts for password
"""

import os
import sys
import getpass
import sqlite3
import uuid
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import bcrypt  # noqa: E402

DB_PATH = os.environ.get("TM_DB_PATH") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "task_manager.db"
)

ADMIN_USERNAME = "vikasudasi"
ADMIN_EMAIL = "vikasudasi@gmail.com"
ADMIN_ROLE = "admin"
HERMES_AGENT_NAME = "hermes"


def _hash_password(password: str) -> str:
    """Hash a plaintext password using bcrypt."""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def _get_admin_password() -> str:
    """Resolve the admin password from TM_ADMIN_PASSWORD or an interactive prompt."""
    pw = os.environ.get("TM_ADMIN_PASSWORD")
    if pw:
        print("Using TM_ADMIN_PASSWORD from environment.")
        return pw
    print("TM_ADMIN_PASSWORD not set.")
    pw = getpass.getpass(f"Enter password for admin user '{ADMIN_USERNAME}': ")
    if not pw:
        print("ERROR: password cannot be empty.", file=sys.stderr)
        sys.exit(1)
    confirm = getpass.getpass("Confirm password: ")
    if pw != confirm:
        print("ERROR: passwords do not match.", file=sys.stderr)
        sys.exit(1)
    return pw


def _has_column(conn: sqlite3.Connection, table: str, column: str) -> bool:
    cols = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(c[1] == column for c in cols)


def main() -> int:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")

    try:
        # 1. Create users table (idempotent)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id            TEXT PRIMARY KEY,
                username      TEXT NOT NULL UNIQUE,
                email         TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                role          TEXT NOT NULL DEFAULT 'user' CHECK(role IN ('admin', 'user')),
                created_at    TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """
        )

        # 2. Add user_id columns (idempotent)
        if not _has_column(conn, "agents", "user_id"):
            conn.execute("ALTER TABLE agents ADD COLUMN user_id TEXT REFERENCES users(id)")
            print("Added agents.user_id column.")
        else:
            print("agents.user_id already present.")

        if not _has_column(conn, "projects", "user_id"):
            conn.execute("ALTER TABLE projects ADD COLUMN user_id TEXT NOT NULL DEFAULT ''")
            print("Added projects.user_id column (NOT NULL DEFAULT '').")
        else:
            print("projects.user_id already present.")

        if not _has_column(conn, "agent_audit_log", "user_id"):
            conn.execute("ALTER TABLE agent_audit_log ADD COLUMN user_id TEXT")
            print("Added agent_audit_log.user_id column.")
        else:
            print("agent_audit_log.user_id already present.")

        # 3. Create admin user (idempotent; password only prompted when creating)
        admin = conn.execute(
            "SELECT id FROM users WHERE username = ?", (ADMIN_USERNAME,)
        ).fetchone()
        if admin:
            admin_id = admin["id"]
            print(f"Admin user '{ADMIN_USERNAME}' already exists ({admin_id}).")
        else:
            admin_id = str(uuid.uuid4())
            password_hash = _hash_password(_get_admin_password())
            now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
            conn.execute(
                "INSERT INTO users (id, username, email, password_hash, role, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (admin_id, ADMIN_USERNAME, ADMIN_EMAIL, password_hash, ADMIN_ROLE, now),
            )
            print(f"Created admin user '{ADMIN_USERNAME}' ({admin_id}).")

        # 4. Migrate hermes agent -> admin user
        hermes = conn.execute(
            "SELECT id, user_id FROM agents WHERE name = ?", (HERMES_AGENT_NAME,)
        ).fetchone()
        if not hermes:
            print(f"WARNING: agent '{HERMES_AGENT_NAME}' not found; skipping agent migration.")
        elif hermes["user_id"] == admin_id:
            print(f"Agent '{HERMES_AGENT_NAME}' already owned by admin.")
        else:
            conn.execute("UPDATE agents SET user_id = ? WHERE id = ?", (admin_id, hermes["id"]))
            print(f"Migrated agent '{HERMES_AGENT_NAME}' -> admin user.")

        # 5. Migrate all projects -> admin user
        total_projects = conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0]
        conn.execute(
            "UPDATE projects SET user_id = ? WHERE user_id IS NULL OR user_id = ''",
            (admin_id,),
        )
        print(f"Migrated {total_projects} projects -> admin user.")

        # 6. Delete all agents without an owning user (non-hermes stragglers)
        deleted = conn.execute("DELETE FROM agents WHERE user_id IS NULL").rowcount
        print(f"Deleted {deleted} agents with no owning user.")

        # 7. projects.user_id is NOT NULL DEFAULT '' already; verify no NULLs remain
        null_projects = conn.execute(
            "SELECT COUNT(*) FROM projects WHERE user_id IS NULL"
        ).fetchone()[0]
        if null_projects:
            print(f"WARNING: {null_projects} projects still have NULL user_id.", file=sys.stderr)
        else:
            print("projects.user_id has no NULL values (NOT NULL enforced).")

        # Indexes
        conn.execute("CREATE INDEX IF NOT EXISTS idx_projects_user ON projects(user_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_agents_user ON agents(user_id)")

        conn.commit()
        print("Migration complete.")
        return 0
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
