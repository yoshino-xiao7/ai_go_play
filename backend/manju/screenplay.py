"""Project screenplay validation and revisioned storage."""

from __future__ import annotations

import json

from .store import DomainError, Store, encode, now


MAX_DOCUMENT_BYTES = 4 * 1024**2


def _text_fields(source: object, fields: dict[str, int]) -> dict[str, str]:
    if not isinstance(source, dict):
        raise ValueError("剧本条目必须是对象。")
    result = {}
    for field, limit in fields.items():
        value = source.get(field)
        if not isinstance(value, str) or len(value) > limit:
            raise ValueError(f"剧本字段 {field} 必须是长度不超过 {limit} 的文本。")
        result[field] = value
    return result


def encode_screenplay(document: object) -> str:
    """Validate the shared API/archive format without altering manuscript text."""
    settings = _text_fields(document, {
        "title": 250, "audience": 1000, "hooks": 8000, "genre": 1000,
        "logline": 8000, "synopsis": 120_000,
    })
    characters = document.get("characters")
    episodes = document.get("episodes")
    if not isinstance(characters, list) or len(characters) > 200:
        raise ValueError("角色列表必须是数组，最多 200 项。")
    if not isinstance(episodes, list) or len(episodes) > 500:
        raise ValueError("分集列表必须是数组，最多 500 项。")
    character_entries = [_text_fields(item, {"name": 250, "bio": 40_000}) for item in characters]
    episode_entries = []
    episode_ids = set()
    for item in episodes:
        episode = _text_fields(item, {"id": 100, "title": 250, "outline": 40_000, "script": 240_000})
        identifier = episode["id"]
        if not identifier.strip() or identifier in episode_ids:
            raise ValueError("每集须有唯一的非空标识。")
        episode_ids.add(identifier)
        episode_entries.append(episode)

    serialized = encode({**settings, "characters": character_entries, "episodes": episode_entries})
    if len(serialized.encode("utf-8")) > MAX_DOCUMENT_BYTES:
        raise ValueError("剧本整体大小不能超过 4 MiB。")
    return serialized


def get_screenplay(store: Store, project_id: str, *, include_deleted: bool = False) -> dict:
    with store.lock:
        store.project(project_id, include_deleted=include_deleted)
        row = store.conn.execute("SELECT revision,document FROM screenplays WHERE project_id=?", (project_id,)).fetchone()
        if row is None:
            return {"revision": 0, "document": None}
        return {"revision": row["revision"], "document": json.loads(row["document"])}


def save_screenplay(store: Store, project_id: str, payload: dict) -> dict:
    revision = payload.get("revision")
    if type(revision) is not int or revision < 0:
        raise DomainError(422, "剧本修订号必须是非负整数。", "invalid_revision")
    try:
        document = encode_screenplay(payload.get("document"))
    except UnicodeError as error:
        raise DomainError(422, "剧本包含无效的 Unicode 文本。", "invalid_screenplay") from error
    except ValueError as error:
        raise DomainError(422, str(error), "invalid_screenplay") from error

    with store.tx():
        store.project(project_id, include_deleted=False)
        row = store.conn.execute("SELECT revision FROM screenplays WHERE project_id=?", (project_id,)).fetchone()
        current_revision = row["revision"] if row else 0
        if revision != current_revision:
            raise DomainError(409, "剧本已在其他页面更新，请先重新载入。", "revision_conflict", revision=current_revision)
        revision += 1
        store.conn.execute(
            """INSERT INTO screenplays(project_id,revision,document) VALUES(?,?,?)
               ON CONFLICT(project_id) DO UPDATE SET revision=excluded.revision,document=excluded.document""",
            (project_id, revision, document),
        )
        store.conn.execute("UPDATE projects SET updated_at=? WHERE id=?", (now(), project_id))
        store.emit("screenplay.updated", {"project_id": project_id, "revision": revision})
    return {"revision": revision, "document": json.loads(document)}
