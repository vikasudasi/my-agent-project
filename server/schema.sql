CREATE TABLE IF NOT EXISTS projects (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    status      TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active', 'archived', 'completed')),
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS tasks (
    id          TEXT PRIMARY KEY,
    project_id  TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    parent_id   TEXT REFERENCES tasks(id) ON DELETE CASCADE,
    title       TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    status      TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending', 'in_progress', 'completed', 'blocked', 'failed', 'cancelled')),
    rank        REAL NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Migrate old doc tables to new format (remove old UNIQUE constraints, add doc_type)
DROP TABLE IF EXISTS project_docs;
DROP TABLE IF EXISTS task_docs;

CREATE TABLE IF NOT EXISTS project_docs (
    id          TEXT PRIMARY KEY,
    project_id  TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    doc_type    TEXT NOT NULL DEFAULT 'spec' CHECK(doc_type IN ('spec', 'progress', 'closure')),
    content     TEXT NOT NULL DEFAULT '',
    updated_at  TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(project_id, doc_type)
);

CREATE TABLE IF NOT EXISTS task_docs (
    id          TEXT PRIMARY KEY,
    task_id     TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    doc_type    TEXT NOT NULL DEFAULT 'spec' CHECK(doc_type IN ('spec', 'progress', 'closure')),
    content     TEXT NOT NULL DEFAULT '',
    updated_at  TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(task_id, doc_type)
);

CREATE TABLE IF NOT EXISTS comments (
    id          TEXT PRIMARY KEY,
    entity_type TEXT NOT NULL CHECK(entity_type IN ('project', 'task')),
    entity_id   TEXT NOT NULL,
    author      TEXT NOT NULL DEFAULT '',
    content     TEXT NOT NULL,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_tasks_project ON tasks(project_id);
CREATE INDEX IF NOT EXISTS idx_tasks_parent ON tasks(parent_id);
CREATE INDEX IF NOT EXISTS idx_tasks_rank  ON tasks(project_id, rank);
CREATE INDEX IF NOT EXISTS idx_comments_entity ON comments(entity_type, entity_id);
CREATE INDEX IF NOT EXISTS idx_comments_created ON comments(entity_id, created_at);

-- Agents (for onboarded agents + admin)
CREATE TABLE IF NOT EXISTS agents (
    id           TEXT PRIMARY KEY,
    name         TEXT NOT NULL UNIQUE,
    master_name  TEXT NOT NULL,
    api_key_hash TEXT NOT NULL,
    role         TEXT NOT NULL DEFAULT 'agent' CHECK(role IN ('agent', 'admin')),
    created_at   TEXT NOT NULL DEFAULT (datetime('now')),
    active       INTEGER NOT NULL DEFAULT 1
);

-- Audit log for all mutations (agent_name + master_name attribution)
CREATE TABLE IF NOT EXISTS agent_audit_log (
    id          TEXT PRIMARY KEY,
    agent_name  TEXT NOT NULL,
    master_name TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id   TEXT NOT NULL,
    action      TEXT NOT NULL,
    field       TEXT,
    old_value   TEXT,
    new_value   TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_audit_agent ON agent_audit_log(agent_name);
CREATE INDEX IF NOT EXISTS idx_audit_entity ON agent_audit_log(entity_type, entity_id);
CREATE INDEX IF NOT EXISTS idx_audit_created ON agent_audit_log(created_at);