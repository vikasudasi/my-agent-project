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