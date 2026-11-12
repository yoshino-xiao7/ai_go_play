PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS projects (
 id TEXT PRIMARY KEY, name TEXT NOT NULL, aspect_ratio TEXT NOT NULL DEFAULT 'free',
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL, deleted_at TEXT,
 revision INTEGER NOT NULL DEFAULT 0, cover_version_id TEXT
);
CREATE TABLE IF NOT EXISTS canvases (
 project_id TEXT PRIMARY KEY REFERENCES projects(id) ON DELETE CASCADE,
 nodes TEXT NOT NULL DEFAULT '[]', edges TEXT NOT NULL DEFAULT '[]',
 viewport TEXT NOT NULL DEFAULT '{"x":0,"y":0,"zoom":1}'
);
CREATE TABLE IF NOT EXISTS screenplays (
 project_id TEXT PRIMARY KEY REFERENCES projects(id) ON DELETE CASCADE,
 revision INTEGER NOT NULL DEFAULT 1, document TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS blobs (
 hash TEXT PRIMARY KEY, path TEXT NOT NULL UNIQUE, size INTEGER NOT NULL,
 created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS assets (
 id TEXT PRIMARY KEY, name TEXT NOT NULL, type TEXT NOT NULL,
 tags TEXT NOT NULL DEFAULT '[]', source TEXT NOT NULL DEFAULT 'upload',
 created_at TEXT NOT NULL, deleted_at TEXT, current_version_id TEXT
);
CREATE TABLE IF NOT EXISTS versions (
 id TEXT PRIMARY KEY, asset_id TEXT NOT NULL REFERENCES assets(id) ON DELETE CASCADE,
 blob_hash TEXT NOT NULL REFERENCES blobs(hash), filename TEXT NOT NULL,
 size INTEGER NOT NULL, width INTEGER, height INTEGER, duration REAL, mime TEXT NOT NULL,
 created_at TEXT NOT NULL, missing INTEGER NOT NULL DEFAULT 0,
 preview_status TEXT NOT NULL DEFAULT 'pending', preview_error TEXT
);
CREATE TABLE IF NOT EXISTS subjects (
 id TEXT PRIMARY KEY, name TEXT NOT NULL, description TEXT NOT NULL DEFAULT '',
 version_id TEXT NOT NULL REFERENCES versions(id) ON DELETE RESTRICT,
 kind TEXT NOT NULL DEFAULT 'character', image_version_ids TEXT NOT NULL DEFAULT '[]',
 voice_version_id TEXT REFERENCES versions(id) ON DELETE RESTRICT,
 voice_name TEXT NOT NULL DEFAULT '', voice_transcript TEXT NOT NULL DEFAULT '',
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS subject_media (
 subject_id TEXT NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
 version_id TEXT NOT NULL REFERENCES versions(id) ON DELETE RESTRICT,
 PRIMARY KEY(subject_id,version_id)
);
CREATE TABLE IF NOT EXISTS project_assets (
 project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
 asset_id TEXT NOT NULL REFERENCES assets(id) ON DELETE CASCADE,
 added_at TEXT NOT NULL, PRIMARY KEY(project_id, asset_id)
);
CREATE TABLE IF NOT EXISTS tasks (
 id TEXT PRIMARY KEY, kind TEXT NOT NULL, version_id TEXT REFERENCES versions(id) ON DELETE CASCADE,
 status TEXT NOT NULL DEFAULT 'pending', attempts INTEGER NOT NULL DEFAULT 0, error TEXT,
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL, filename TEXT, message TEXT,
 requires_file INTEGER NOT NULL DEFAULT 0, can_retry INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS events (
 id INTEGER PRIMARY KEY AUTOINCREMENT, type TEXT NOT NULL, data TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS requests (
 key TEXT NOT NULL, route TEXT NOT NULL, payload_hash TEXT NOT NULL, response TEXT NOT NULL,
 created_at TEXT NOT NULL, PRIMARY KEY(key, route)
);
CREATE INDEX IF NOT EXISTS idx_versions_asset ON versions(asset_id);
CREATE INDEX IF NOT EXISTS idx_versions_blob ON versions(blob_hash);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_project_assets_asset ON project_assets(asset_id);
CREATE INDEX IF NOT EXISTS idx_subjects_version ON subjects(version_id);
CREATE INDEX IF NOT EXISTS idx_subjects_updated ON subjects(updated_at DESC,id);
CREATE INDEX IF NOT EXISTS idx_subject_media_version ON subject_media(version_id);
