"""Transactional project and immutable media metadata storage."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import sqlite3
import threading
from typing import Any
import uuid


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id() -> str:
    return uuid.uuid4().hex


def encode(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def fingerprint(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()


class DomainError(Exception):
    def __init__(self, status: int, message: str, code: str = "invalid_request", **extra: Any):
        super().__init__(message)
        self.status = status
        self.detail = {"message": message, "code": code, **extra}


class Store:
    def __init__(self, root: str | Path, config_file: str | Path):
        self.lock = threading.RLock()
        self.media_lock = threading.RLock()
        self.config_file = Path(config_file).expanduser().resolve()
        self.maintenance = False
        self._root_locks = {}
        self.root = Path(root).expanduser().resolve()
        self.reopen(self.root)
        with self.tx():
            self.conn.execute("UPDATE tasks SET status='pending', updated_at=? WHERE status='running'", (now(),))

    def reopen(self, root: str | Path) -> None:
        with self.lock:
            root = Path(root).expanduser().resolve()
            root.mkdir(parents=True, exist_ok=True)
            self._acquire_library_lock(root)
            if hasattr(self, "conn"):
                self.conn.close()
            self.root = root
            for folder in ("blobs", "cache", "temp", "exports"):
                (self.root / folder).mkdir(parents=True, exist_ok=True)
            self.conn = sqlite3.connect(self.root / "library.sqlite", check_same_thread=False, timeout=30)
            self.conn.row_factory = sqlite3.Row
            self.conn.execute("PRAGMA journal_mode=WAL")
            self.conn.execute("PRAGMA foreign_keys=ON")
            self.conn.executescript(Path(__file__).with_name("schema.sql").read_text(encoding="utf-8"))
            task_columns = {row[1] for row in self.conn.execute("PRAGMA table_info(tasks)")}
            for column, definition in {"filename": "TEXT", "message": "TEXT", "requires_file": "INTEGER NOT NULL DEFAULT 0", "can_retry": "INTEGER NOT NULL DEFAULT 1"}.items():
                if column not in task_columns:
                    self.conn.execute(f"ALTER TABLE tasks ADD COLUMN {column} {definition}")
            subject_columns = {row[1] for row in self.conn.execute("PRAGMA table_info(subjects)")}
            for column, definition in {"kind": "TEXT NOT NULL DEFAULT 'character'", "image_version_ids": "TEXT NOT NULL DEFAULT '[]'", "voice_version_id": "TEXT REFERENCES versions(id) ON DELETE RESTRICT", "voice_name": "TEXT NOT NULL DEFAULT ''", "voice_transcript": "TEXT NOT NULL DEFAULT ''"}.items():
                if column not in subject_columns:
                    self.conn.execute(f"ALTER TABLE subjects ADD COLUMN {column} {definition}")
            for row in self.conn.execute("SELECT id,version_id,image_version_ids,voice_version_id FROM subjects").fetchall():
                images = json.loads(row["image_version_ids"]) or [row["version_id"]]
                self.conn.execute("UPDATE subjects SET image_version_ids=? WHERE id=?", (encode(images), row["id"]))
                self._index_subject_media(row["id"], images, row["voice_version_id"])
            # Older builds saved @ references without project membership. Repair
            # that index on open so existing drafts receive deletion protection.
            for canvas in self.conn.execute("SELECT project_id,nodes FROM canvases WHERE instr(nodes, '\"generation\"') > 0 OR instr(nodes, '\"image_history\"') > 0 OR instr(nodes, '\"subject\"') > 0 OR instr(nodes, '\"shot\"') > 0 OR instr(nodes, '\"production_settings\"') > 0 OR instr(nodes, '\"composite\"') > 0 OR instr(nodes, '\"timeline\"') > 0").fetchall():
                for node in json.loads(canvas["nodes"]):
                    for version_id in self.node_version_ids(node, strict=False):
                        self.conn.execute("INSERT OR IGNORE INTO project_assets(project_id,asset_id,added_at) SELECT ?,asset_id,? FROM versions WHERE id=?", (canvas["project_id"], now(), version_id))
            self.conn.commit()

    def _acquire_library_lock(self, root: Path) -> None:
        if root in self._root_locks:
            return
        stream = (root / ".manju.lock").open("a+b")
        try:
            if stream.seek(0, 2) == 0:
                stream.write(b"0")
                stream.flush()
            stream.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            stream.close()
            raise DomainError(409, "该资料库已由另一个工作台服务打开。请使用已启动的服务，或选择另一个资料库。", "library_in_use") from error
        self._root_locks[root] = stream

    def close(self) -> None:
        with self.lock:
            self.conn.close()
            for stream in self._root_locks.values():
                stream.close()
            self._root_locks.clear()

    @contextmanager
    def tx(self, allow_maintenance: bool = False):
        if self.maintenance and not allow_maintenance:
            raise DomainError(423, "资产库正在迁移，请等待迁移完成。", "storage_busy")
        with self.lock:
            if self.maintenance and not allow_maintenance:
                raise DomainError(423, "资产库正在迁移，请等待迁移完成。", "storage_busy")
            self.conn.execute("BEGIN IMMEDIATE")
            try:
                yield self.conn
                self.conn.commit()
            except BaseException:
                self.conn.rollback()
                raise

    def emit(self, event_type: str, data: dict) -> None:
        self.conn.execute("INSERT INTO events(type,data,created_at) VALUES(?,?,?)", (event_type, encode(data), now()))

    def request_result(self, key: str | None, route: str, payload: Any) -> Any:
        if not key:
            return None
        row = self.conn.execute("SELECT * FROM requests WHERE key=? AND route=?", (key, route)).fetchone()
        if row is None:
            return None
        if row["payload_hash"] != fingerprint(payload):
            raise DomainError(409, "同一请求标识已用于其他内容。", "idempotency_conflict")
        return json.loads(row["response"])

    def remember_request(self, key: str | None, route: str, payload: Any, result: Any) -> None:
        if key:
            self.conn.execute("INSERT INTO requests VALUES(?,?,?,?,?)", (key, route, fingerprint(payload), encode(result), now()))

    def project(self, project_id: str, include_deleted: bool = True) -> dict:
        with self.lock:
            row = self.conn.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
            if row is None or (row["deleted_at"] and not include_deleted):
                raise DomainError(404, "项目不存在或已移入回收站。", "project_not_found")
            return dict(row)

    def projects(self, trash: bool = False, search: str = "") -> list[dict]:
        with self.lock:
            return [dict(row) for row in self.conn.execute(
                "SELECT * FROM projects WHERE (deleted_at IS NOT NULL)=? AND name LIKE ? ORDER BY updated_at DESC",
                (int(trash), f"%{search}%"),
            )]

    def create_project(self, name: str, aspect_ratio: str = "free") -> dict:
        name = self.validate_name(name)
        self.validate_aspect(aspect_ratio)
        project_id, timestamp = new_id(), now()
        with self.tx():
            self.conn.execute("INSERT INTO projects(id,name,aspect_ratio,created_at,updated_at) VALUES(?,?,?,?,?)", (project_id, name, aspect_ratio, timestamp, timestamp))
            self.conn.execute("INSERT INTO canvases(project_id) VALUES(?)", (project_id,))
            self.emit("project.created", {"project_id": project_id})
        return self.project(project_id)

    @staticmethod
    def validate_name(name: str) -> str:
        if not isinstance(name, str) or not name.strip() or len(name.strip()) > 250:
            raise DomainError(422, "名称需要包含 1 至 250 个字符。", "invalid_name")
        return name.strip()

    @staticmethod
    def validate_aspect(aspect: str) -> None:
        if aspect not in ("free", "16:9", "9:16"):
            raise DomainError(422, "画幅须为 free、16:9 或 9:16。", "invalid_aspect_ratio")

    def update_project(self, project_id: str, changes: dict) -> dict:
        with self.tx():
            project = self.project(project_id, include_deleted=False)
            if "name" in changes:
                project["name"] = self.validate_name(changes["name"])
            if "aspect_ratio" in changes:
                self.validate_aspect(changes["aspect_ratio"])
                project["aspect_ratio"] = changes["aspect_ratio"]
            if "cover_version_id" in changes:
                cover = changes["cover_version_id"]
                if cover:
                    version = self.version(cover)
                    self._link_asset(project_id, version["asset_id"])
                project["cover_version_id"] = cover
            self.conn.execute("UPDATE projects SET name=?,aspect_ratio=?,cover_version_id=?,updated_at=? WHERE id=?", (project["name"], project["aspect_ratio"], project["cover_version_id"], now(), project_id))
            self.emit("project.updated", {"project_id": project_id})
        return self.project(project_id)

    def duplicate_project(self, project_id: str) -> dict:
        with self.tx():
            project = self.project(project_id, include_deleted=False)
            canvas = self.canvas(project_id)
            for node in canvas["nodes"]:
                data = node.get("data", {})
                data.pop("generation_id", None)
                data.pop("production_render_id", None)
                for entry in data.get("image_history", []):
                    entry.pop("job_id", None)
                draft = data.get("generation")
                if isinstance(draft, dict):
                    for key in ("last_job_id", "pending_submission", "pending_request_id"):
                        draft.pop(key, None)
            duplicate_id, timestamp = new_id(), now()
            self.conn.execute("INSERT INTO projects(id,name,aspect_ratio,created_at,updated_at,cover_version_id) VALUES(?,?,?,?,?,?)", (duplicate_id, project["name"][:247] + " 副本", project["aspect_ratio"], timestamp, timestamp, project["cover_version_id"]))
            self.conn.execute("INSERT INTO canvases VALUES(?,?,?,?)", (duplicate_id, encode(canvas["nodes"]), encode(canvas["edges"]), encode(canvas["viewport"])))
            self.conn.execute("INSERT INTO project_assets SELECT ?,asset_id,? FROM project_assets WHERE project_id=?", (duplicate_id, timestamp, project_id))
            self.emit("project.created", {"project_id": duplicate_id})
        return self.project(duplicate_id)

    def trash_project(self, project_id: str, restore: bool = False) -> dict:
        with self.tx():
            self.project(project_id)
            if not restore:
                self._guard_generations(project_id=project_id)
            self.conn.execute("UPDATE projects SET deleted_at=?,updated_at=? WHERE id=?", (None if restore else now(), now(), project_id))
            self.emit("project.restored" if restore else "project.deleted", {"project_id": project_id})
        return self.project(project_id)

    def purge_project(self, project_id: str) -> dict:
        with self.tx():
            if not self.project(project_id)["deleted_at"]:
                raise DomainError(409, "请先将项目移入回收站。", "project_not_trashed")
            self._guard_generations(project_id=project_id)
            self.conn.execute("DELETE FROM projects WHERE id=?", (project_id,))
            self.emit("project.purged", {"project_id": project_id})
        return {"id": project_id, "deleted": True}

    def canvas(self, project_id: str) -> dict:
        with self.lock:
            project = self.project(project_id)
            row = self.conn.execute("SELECT * FROM canvases WHERE project_id=?", (project_id,)).fetchone()
            return {"revision": project["revision"], "nodes": json.loads(row["nodes"]), "edges": json.loads(row["edges"]), "viewport": json.loads(row["viewport"])}

    def save_canvas(self, project_id: str, payload: dict, *, event_details: dict | None = None, generation_delivery: dict | None = None) -> dict:
        request_id = payload.get("request_id")
        if request_id is not None and (not isinstance(request_id, str) or len(request_id) > 200):
            raise DomainError(422, "请求标识格式不正确。", "invalid_request_id")
        route = f"canvas:{project_id}"
        with self.tx():
            previous = self.request_result(request_id, route, payload)
            if previous is not None:
                return previous
            project = self.project(project_id, include_deleted=False)
            if payload.get("revision") != project["revision"]:
                raise DomainError(409, "画布已在其他页面更新，请重新载入或保留副本。", "revision_conflict", revision=project["revision"], canvas=self.canvas(project_id))
            nodes, edges, viewport = self.validate_canvas(payload)
            old_canvas = self.canvas(project_id)
            old_nodes = {node["id"]: node for node in old_canvas["nodes"]}
            new_nodes = {node["id"]: node for node in nodes}
            locked = {identifier for identifier, node in old_nodes.items() if node.get("data", {}).get("locked") and (identifier not in new_nodes or new_nodes[identifier].get("data", {}).get("locked"))}
            def edge_identity(edge):
                return {key: edge.get(key) for key in ("source", "target", "sourceHandle", "targetHandle", "label", "data")}
            old_edges = {edge["id"]: edge for edge in old_canvas["edges"]}
            new_edges = {edge["id"]: edge for edge in edges}
            for identifier in old_edges.keys() | new_edges.keys():
                before, after = old_edges.get(identifier), new_edges.get(identifier)
                if any(edge and (edge["source"] in locked or edge["target"] in locked) for edge in (before, after)):
                    if before is None or after is None or edge_identity(before) != edge_identity(after):
                        raise DomainError(409, "请先解锁卡片再修改关联线。", "edge_locked")
            for node in nodes:
                if node.get("type") == "subject":
                    self._validate_subject_media(self.normalize_subject(node["data"]["subject"], allow_empty=True, allow_library=True), require_present=False)
                for version_id in self.node_version_ids(node):
                    self._link_asset(project_id, self.version(version_id)["asset_id"])
            revision = project["revision"] + 1
            self.conn.execute("UPDATE canvases SET nodes=?,edges=?,viewport=? WHERE project_id=?", (encode(nodes), encode(edges), encode(viewport), project_id))
            self.conn.execute("UPDATE projects SET revision=?,updated_at=?,cover_version_id=? WHERE id=?", (revision, now(), self._canvas_cover(nodes), project_id))
            result = {"revision": revision, "nodes": nodes, "edges": edges, "viewport": viewport}
            self.remember_request(request_id, route, payload, result)
            if generation_delivery:
                # Commit this receipt with the actual canvas mutation. Recovery
                # may reread outputs but must never reset a user's later choice.
                self.remember_request(generation_delivery["job_id"], "generation-delivery", generation_delivery["version_ids"], {"node_id": generation_delivery["node_id"]})
            self.emit("canvas.updated", {"project_id": project_id, "revision": revision, "previous_revision": project["revision"], "request_id": request_id, **(event_details or {})})
            return result

    def _canvas_cover(self, nodes: list[dict]) -> str | None:
        for node in nodes:
            version_id = node.get("data", {}).get("asset_version_id")
            if version_id:
                row = self.conn.execute("SELECT a.type FROM versions v JOIN assets a ON a.id=v.asset_id WHERE v.id=?", (version_id,)).fetchone()
                if row and row["type"] in ("image", "video"):
                    return version_id
        return None

    @staticmethod
    def node_version_ids(node: dict, *, strict: bool = True) -> set[str]:
        """All immutable media used by a card, including a frozen submission."""
        identifiers = set()
        def invalid(message):
            if strict:
                raise ValueError(message)
        def add(value):
            if not isinstance(value, str) or not value:
                invalid("asset version")
            else:
                identifiers.add(value)
        data = node.get("data", {}) if isinstance(node, dict) else None
        if not isinstance(data, dict):
            invalid("node data")
            return identifiers
        if data.get("asset_version_id") is not None:
            add(data["asset_version_id"])
        composite = data.get("composite")
        if composite is not None:
            if not isinstance(composite, dict) or not isinstance(composite.get("input_versions", []), list):
                invalid("composite source versions")
            elif isinstance(composite, dict):
                for version_id in composite.get("input_versions", []):
                    add(version_id)
        timeline = data.get("timeline")
        if timeline is not None:
            if not isinstance(timeline, dict) or not isinstance(timeline.get("clips", []), list) or node.get("type") != "frame":
                invalid("timeline document")
            else:
                for clip in timeline.get("clips", []):
                    if not isinstance(clip, dict):
                        invalid("timeline clip")
                    elif clip.get("asset_version_id"):
                        add(clip["asset_version_id"])
        shot = data.get("shot")
        if shot is not None:
            if not isinstance(shot, dict) or node.get("type") != "frame":
                invalid("production shot must be a frame")
            elif isinstance(shot, dict):
                for key in ("video_version_id", "audio_version_id"):
                    if shot.get(key):
                        add(shot[key])
        settings = data.get("production_settings")
        if settings is not None:
            if not isinstance(settings, dict) or node.get("type") != "frame":
                invalid("production settings must be a frame")
            elif settings.get("background_audio_version_id"):
                add(settings["background_audio_version_id"])
        subject = data.get("subject")
        if strict and (node.get("type") == "subject" or subject is not None):
            if node.get("type") != "subject":
                invalid("subject snapshot on a non-subject node")
            snapshot = Store.normalize_subject(subject, allow_empty=True, allow_library=True)
            cover = snapshot["image_version_ids"][0] if snapshot["image_version_ids"] else None
            if data.get("kind") != "image" or data.get("asset_version_id") != cover:
                invalid("subject cover must match the first image")
        if isinstance(subject, dict):
            images = subject.get("image_version_ids", [])
            if isinstance(images, list):
                for version_id in images:
                    add(version_id)
            if subject.get("voice_version_id") is not None:
                add(subject["voice_version_id"])
        history = data.get("image_history", [])
        if not isinstance(history, list):
            invalid("image history")
            history = []
        for entry in history:
            if not isinstance(entry, dict):
                invalid("image history entry")
                continue
            add(entry.get("version_id"))
            for key in ("job_id", "created_at"):
                if entry.get(key) is not None and (not isinstance(entry[key], str) or not entry[key]):
                    invalid("image history metadata")
        draft = data.get("generation")
        if draft is None:
            return identifiers
        if not isinstance(draft, dict):
            invalid("generation draft")
            return identifiers
        inputs = [draft]
        pending = draft.get("pending_submission")
        if pending is not None:
            if isinstance(pending, dict):
                inputs.append(pending)
            else:
                invalid("pending generation submission")
        for payload in inputs:
            references = payload.get("references", [])
            if not isinstance(references, list):
                invalid("generation references")
                references = []
            for reference in references:
                if not isinstance(reference, dict):
                    invalid("generation reference")
                    continue
                add(reference.get("version_id"))
            if payload.get("edit_base_version_id") is not None:
                add(payload["edit_base_version_id"])
            if payload.get("mask_version_id") is not None:
                add(payload["mask_version_id"])
        return identifiers

    @staticmethod
    def validate_canvas(payload: dict) -> tuple:
        nodes, edges = payload.get("nodes", []), payload.get("edges", [])
        viewport = payload.get("viewport", {"x": 0, "y": 0, "zoom": 1})
        if not isinstance(nodes, list) or not isinstance(edges, list) or len(nodes) > 20000 or len(edges) > 50000:
            raise DomainError(422, "画布节点或关系格式不正确。", "invalid_canvas")
        try:
            identifiers = {node["id"] for node in nodes}
            nodes_by_id = {node["id"]: node for node in nodes}
            if len(identifiers) != len(nodes) or any(not isinstance(identifier, str) or not identifier for identifier in identifiers):
                raise ValueError("duplicate node id")
            for node in nodes:
                if node.get("type", "media") not in ("media", "text", "group", "frame", "subject"):
                    raise ValueError("node type")
                if not isinstance(node.get("data", {}), dict):
                    raise ValueError("node data")
                Store.node_version_ids(node)
                position = node["position"]
                if any(not math.isfinite(float(position[key])) for key in ("x", "y")):
                    raise ValueError("position")
                parent = node.get("parentId")
                visited = {node["id"]}
                while parent:
                    if parent not in identifiers or parent in visited:
                        raise ValueError("parent cycle")
                    visited.add(parent)
                    parent = nodes_by_id[parent].get("parentId")
            for edge in edges:
                role = edge.get("data", {}).get("role", "pending")
                if role not in ("pending", "reference", "relation"):
                    raise ValueError("edge role")
                if role == "reference":
                    source = nodes_by_id[edge["source"]]
                    target = nodes_by_id[edge["target"]]
                    if target.get("type") != "media" or target.get("data", {}).get("kind") not in ("image", "video", "audio"):
                        raise ValueError("reference target")
            edge_ids = {edge["id"] for edge in edges}
            if len(edge_ids) != len(edges):
                raise ValueError("duplicate edge")
            if any(edge["source"] not in identifiers or edge["target"] not in identifiers for edge in edges):
                raise ValueError("missing endpoint")
            if any(not math.isfinite(float(viewport[key])) for key in ("x", "y", "zoom")) or float(viewport["zoom"]) <= 0:
                raise ValueError("viewport")
            encode(payload)
        except (ValueError, TypeError, KeyError, StopIteration) as error:
            raise DomainError(422, "画布包含无效坐标、节点、分组或连线。", "invalid_canvas") from error
        return nodes, edges, viewport

    def blob_path(self, digest: str) -> Path:
        with self.lock:
            row = self.conn.execute("SELECT path FROM blobs WHERE hash=?", (digest,)).fetchone()
            relative = row["path"] if row else f"blobs/{digest[:2]}/{digest}"
            path = (self.root / relative).resolve()
            if not path.is_relative_to(self.root):
                raise DomainError(500, "资产路径超出存储目录。", "invalid_storage_path")
            return path

    def version(self, version_id: str) -> dict:
        with self.lock:
            row = self.conn.execute("SELECT * FROM versions WHERE id=?", (version_id,)).fetchone()
            if row is None:
                raise DomainError(404, "资产版本不存在。", "version_not_found")
            value = dict(row)
            value["hash"] = value.pop("blob_hash")
            path = self.blob_path(value["hash"])
            value["path"] = str(path)
            value["missing"] = not path.is_file()
            return value

    def asset(self, asset_id: str, details: bool = True) -> dict:
        with self.lock:
            row = self.conn.execute("SELECT * FROM assets WHERE id=?", (asset_id,)).fetchone()
            if row is None:
                raise DomainError(404, "资产不存在。", "asset_not_found")
            value = dict(row)
            value["tags"] = json.loads(value["tags"])
            ids = [row["id"] for row in self.conn.execute("SELECT id FROM versions WHERE asset_id=? ORDER BY created_at DESC,id", (asset_id,))]
            value["version_count"] = len(ids)
            value["version"] = self.version(value["current_version_id"]) if value["current_version_id"] else None
            if details:
                value["versions"] = [self.version(version_id) for version_id in ids]
                value["references"] = self.references(asset_id)
                value["subject_references"] = self.subject_references(asset_id)
            return value

    def subject_references(self, asset_id: str) -> list[dict]:
        with self.lock:
            rows = self.conn.execute("SELECT DISTINCT s.id,s.name,s.description,s.kind,s.version_id,s.created_at,s.updated_at FROM subjects s JOIN subject_media sm ON sm.subject_id=s.id JOIN versions v ON v.id=sm.version_id WHERE v.asset_id=? ORDER BY s.updated_at DESC,s.id", (asset_id,)).fetchall()
            return [{**dict(row), "asset_id": asset_id, "referenced_version_ids": [value[0] for value in self.conn.execute("SELECT sm.version_id FROM subject_media sm JOIN versions v ON v.id=sm.version_id WHERE sm.subject_id=? AND v.asset_id=? ORDER BY sm.version_id", (row["id"], asset_id))]} for row in rows]

    def subject(self, subject_id: str) -> dict:
        with self.lock:
            row = self.conn.execute("SELECT * FROM subjects WHERE id=?", (subject_id,)).fetchone()
            if row is None:
                raise DomainError(404, "主体条目不存在。", "subject_not_found")
            value = dict(row)
            value["image_version_ids"] = json.loads(value["image_version_ids"])
            value["images"] = [self.version(version_id) for version_id in value["image_version_ids"]]
            value["version"] = self.version(value["version_id"])
            value["asset_id"] = value["version"]["asset_id"]
            value["voice"] = self.version(value["voice_version_id"]) if value["voice_version_id"] else None
            return value

    def subjects(self, search: str = "", offset: int = 0, limit: int = 60, kind: str | None = None) -> dict:
        if kind is not None and kind not in ("character", "scene", "prop"):
            raise DomainError(422, "主体类型须为 character、scene 或 prop。", "invalid_subject_kind")
        pattern = f"%{search}%"
        where = "(name LIKE ? OR description LIKE ?)" + (" AND kind=?" if kind else "")
        params = [pattern, pattern] + ([kind] if kind else [])
        with self.lock:
            total = self.conn.execute(f"SELECT COUNT(*) FROM subjects WHERE {where}", params).fetchone()[0]
            rows = self.conn.execute(f"SELECT id FROM subjects WHERE {where} ORDER BY updated_at DESC,id LIMIT ? OFFSET ?", [*params, limit, offset]).fetchall()
            return {"items": [self.subject(row["id"]) for row in rows], "total": total}

    @staticmethod
    def _subject_description(value) -> str:
        if not isinstance(value, str) or len(value) > 6000:
            raise DomainError(422, "主体描述须为不超过 6000 字的文本。", "invalid_subject_description")
        return value.strip()

    @staticmethod
    def normalize_subject(payload, *, allow_empty: bool = False, allow_library: bool = False) -> dict:
        fields = {"kind", "name", "description", "image_version_ids", "voice_version_id", "voice_name", "voice_transcript"}
        if not isinstance(payload, dict) or set(payload) - (fields | ({"library_id"} if allow_library else set())):
            raise DomainError(422, "主体资料包含无效字段。", "invalid_subject")
        kind = payload.get("kind", "character")
        if kind not in ("character", "scene", "prop"):
            raise DomainError(422, "主体类型须为 character、scene 或 prop。", "invalid_subject_kind")
        images = payload.get("image_version_ids", [])
        minimum = 0 if allow_empty else 1
        if not isinstance(images, list) or not minimum <= len(images) <= 12 or any(not isinstance(value, str) or not value.strip() or len(value) > 200 for value in images) or len(set(images)) != len(images):
            raise DomainError(422, f"主体需要 {minimum} 至 12 张不重复的固定版本图片。", "invalid_subject_images")
        voice_id = payload.get("voice_version_id")
        if voice_id is not None and (not isinstance(voice_id, str) or not voice_id.strip() or len(voice_id) > 200):
            raise DomainError(422, "请选择有效的固定音频版本。", "invalid_subject_voice")
        result = {"kind": kind, "name": Store.validate_name(payload.get("name")), "description": Store._subject_description(payload.get("description", "")), "image_version_ids": list(images), "voice_version_id": voice_id}
        for key, limit in (("voice_name", 250), ("voice_transcript", 6000)):
            value = payload.get(key, "")
            if not isinstance(value, str) or len(value) > limit:
                raise DomainError(422, f"{key} 须为不超过 {limit} 字的文本。", "invalid_subject_voice")
            result[key] = value.strip()
        if kind != "character" and (voice_id or result["voice_name"] or result["voice_transcript"]):
            raise DomainError(422, "只有人物主体可以设置音色和音频文本；请先清空音色资料。", "subject_voice_character_only")
        if allow_library and "library_id" in payload:
            identifier = payload["library_id"]
            if not isinstance(identifier, str) or not identifier.strip() or len(identifier) > 200:
                raise DomainError(422, "主体库来源标识无效。", "invalid_subject_library")
            result["library_id"] = identifier
        return result

    def _validate_subject_media(self, subject: dict, *, require_present: bool = True) -> None:
        media = [(value, "image") for value in subject["image_version_ids"]]
        if subject["voice_version_id"]:
            media.append((subject["voice_version_id"], "audio"))
        for version_id, kind in media:
            version = self.version(version_id)
            asset = self.asset(version["asset_id"], details=False)
            if asset["deleted_at"]:
                raise DomainError(409, "请先恢复回收站中的主体素材。", "asset_trashed", version_id=version_id)
            if asset["type"] != kind or not version["mime"].startswith(kind + "/"):
                raise DomainError(422, "主体图片必须引用图片版本；音色必须引用音频版本。", "subject_image_required" if kind == "image" else "subject_audio_required", version_id=version_id)
            if require_present and version["missing"]:
                raise DomainError(409, "主体素材原件缺失，请先修复该版本。", "subject_image_missing" if kind == "image" else "subject_audio_missing", version_id=version_id)

    def _index_subject_media(self, subject_id: str, images: list[str], voice_id: str | None) -> None:
        self.conn.execute("DELETE FROM subject_media WHERE subject_id=?", (subject_id,))
        for version_id in set(images) | ({voice_id} if voice_id else set()):
            self.conn.execute("INSERT INTO subject_media(subject_id,version_id) VALUES(?,?)", (subject_id, version_id))

    def create_subject(self, payload: dict, request_id: str | None = None) -> dict:
        values = dict(payload)
        legacy = "version_id" in values
        if legacy:
            version_id = values.pop("version_id")
            if not isinstance(version_id, str) or not version_id:
                raise DomainError(422, "请选择固定的图片版本保存主体。", "invalid_subject_version")
            if "image_version_ids" in values and (not isinstance(values["image_version_ids"], list) or not values["image_version_ids"] or values["image_version_ids"][0] != version_id):
                raise DomainError(422, "兼容图片版本须与第一张主体图片一致。", "subject_cover_mismatch")
            values.setdefault("image_version_ids", [version_id])
        subject = self.normalize_subject(values)
        version_id = subject["image_version_ids"][0]
        if request_id is not None and (not isinstance(request_id, str) or not request_id.strip() or len(request_id) > 200):
            raise DomainError(422, "请求标识须为 1 至 200 个字符。", "invalid_request_id")
        normalized = {"name": subject["name"], "description": subject["description"], "version_id": version_id} if set(payload) <= {"name", "description", "version_id"} else subject
        with self.tx():
            previous = self.request_result(request_id, "subjects:create", normalized)
            if previous is not None:
                return previous if "image_version_ids" in previous else self.subject(previous["id"])
            self._validate_subject_media(subject)
            subject_id, timestamp = new_id(), now()
            self.conn.execute("INSERT INTO subjects(id,name,description,version_id,kind,image_version_ids,voice_version_id,voice_name,voice_transcript,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)", (subject_id, subject["name"], subject["description"], version_id, subject["kind"], encode(subject["image_version_ids"]), subject["voice_version_id"], subject["voice_name"], subject["voice_transcript"], timestamp, timestamp))
            self._index_subject_media(subject_id, subject["image_version_ids"], subject["voice_version_id"])
            result = self.subject(subject_id)
            self.remember_request(request_id, "subjects:create", normalized, result)
            self.emit("subject.created", {"subject_id": subject_id, "asset_id": result["asset_id"], "version_id": version_id})
            return result

    def update_subject(self, subject_id: str, changes: dict) -> dict:
        if "version_id" in changes:
            raise DomainError(422, "请使用 image_version_ids 调整主体图片及主图；不能直接修改兼容字段 version_id。", "subject_version_immutable")
        with self.tx():
            previous = self.subject(subject_id)
            values = {key: previous[key] for key in ("name", "description", "kind", "image_version_ids", "voice_version_id", "voice_name", "voice_transcript")}
            subject = self.normalize_subject({**values, **changes})
            self._validate_subject_media(subject)
            self.conn.execute("UPDATE subjects SET name=?,description=?,kind=?,version_id=?,image_version_ids=?,voice_version_id=?,voice_name=?,voice_transcript=?,updated_at=? WHERE id=?", (subject["name"], subject["description"], subject["kind"], subject["image_version_ids"][0], encode(subject["image_version_ids"]), subject["voice_version_id"], subject["voice_name"], subject["voice_transcript"], now(), subject_id))
            self._index_subject_media(subject_id, subject["image_version_ids"], subject["voice_version_id"])
            self.emit("subject.updated", {"subject_id": subject_id, "asset_id": self.version(subject["image_version_ids"][0])["asset_id"]})
            return self.subject(subject_id)

    def delete_subject(self, subject_id: str) -> dict:
        with self.tx():
            subject = self.subject(subject_id)
            self.conn.execute("DELETE FROM subjects WHERE id=?", (subject_id,))
            self.emit("subject.deleted", {"subject_id": subject_id, "asset_id": subject["asset_id"]})
        return {"id": subject_id, "deleted": True}

    def references(self, asset_id: str) -> list[dict]:
        rows = self.conn.execute("SELECT p.* FROM projects p JOIN project_assets pa ON pa.project_id=p.id WHERE pa.asset_id=? ORDER BY p.updated_at DESC", (asset_id,)).fetchall()
        result = []
        version_ids = {row["id"] for row in self.conn.execute("SELECT id FROM versions WHERE asset_id=?", (asset_id,))}
        for row in rows:
            canvas = self.canvas(row["id"])
            nodes = [node["id"] for node in canvas["nodes"] if self.node_version_ids(node, strict=False) & version_ids]
            result.append({"id": row["id"], "project_id": row["id"], "name": row["name"], "deleted_at": row["deleted_at"], "node_ids": nodes, "node_count": len(nodes)})
        return result

    def assets(self, search: str = "", media_type: str = "", tag: str = "", source: str = "", project_id: str | None = None, trash: bool = False, offset: int = 0, limit: int = 60) -> dict:
        clauses, params = ["(a.deleted_at IS NOT NULL)=?"], [int(trash)]
        if search:
            clauses.append("(a.name LIKE ? OR EXISTS(SELECT 1 FROM json_each(a.tags) WHERE value LIKE ?))")
            params.extend([f"%{search}%", f"%{search}%"])
        if media_type:
            clauses.append("a.type=?")
            params.append(media_type)
        if source:
            clauses.append("a.source=?")
            params.append(source)
        if tag:
            clauses.append("EXISTS(SELECT 1 FROM json_each(a.tags) WHERE value=?)")
            params.append(tag)
        if project_id:
            clauses.append("EXISTS(SELECT 1 FROM project_assets pa WHERE pa.asset_id=a.id AND pa.project_id=?)")
            params.append(project_id)
        where = " AND ".join(clauses)
        with self.lock:
            total = self.conn.execute(f"SELECT COUNT(*) FROM assets a WHERE {where}", params).fetchone()[0]
            rows = self.conn.execute(f"SELECT a.id FROM assets a WHERE {where} ORDER BY a.created_at DESC,a.id LIMIT ? OFFSET ?", [*params, limit, offset]).fetchall()
            return {"items": [self.asset(row["id"], details=False) for row in rows], "total": total}

    def _link_asset(self, project_id: str, asset_id: str) -> None:
        asset = self.conn.execute("SELECT deleted_at FROM assets WHERE id=?", (asset_id,)).fetchone()
        if asset and asset["deleted_at"]:
            raise DomainError(409, "请先恢复回收站中的资产。", "asset_trashed")
        self.conn.execute("INSERT OR IGNORE INTO project_assets VALUES(?,?,?)", (project_id, asset_id, now()))

    def link_asset(self, project_id: str, asset_id: str) -> dict:
        with self.tx():
            self.project(project_id, include_deleted=False)
            asset = self.asset(asset_id, details=False)
            if asset["deleted_at"]:
                raise DomainError(409, "请先恢复回收站中的资产。", "asset_trashed")
            self._link_asset(project_id, asset_id)
            self.emit("project.assets_updated", {"project_id": project_id, "asset_id": asset_id})
        return asset

    def unlink_asset(self, project_id: str, asset_id: str, remove_nodes: bool = False) -> dict:
        with self.tx():
            self.project(project_id, include_deleted=False)
            self.asset(asset_id, details=False)
            self._guard_generations(project_id=project_id, asset_id=asset_id)
            canvas = self.canvas(project_id)
            version_ids = {row[0] for row in self.conn.execute("SELECT id FROM versions WHERE asset_id=?", (asset_id,))}
            # A timeline is stored in one hidden canvas document. Removing that
            # entire node to unlink one asset would erase unrelated editing.
            timeline_clips = [clip.get("id") for node in canvas["nodes"]
                              if isinstance(node.get("data", {}).get("timeline"), dict)
                              for clip in node["data"]["timeline"].get("clips", [])
                              if clip.get("asset_version_id") in version_ids]
            if timeline_clips:
                raise DomainError(409, "多轨剪辑仍在使用此素材，请先在时间线移除相关片段。", "timeline_referenced", clip_ids=timeline_clips)
            removed = {node["id"] for node in canvas["nodes"] if self.node_version_ids(node, strict=False) & version_ids}
            if removed and not remove_nodes:
                raise DomainError(409, "画布仍使用此资产，可同时移除相关卡片。", "asset_in_canvas", node_ids=sorted(removed))
            nodes = [node for node in canvas["nodes"] if node["id"] not in removed]
            edges = [edge for edge in canvas["edges"] if edge["source"] not in removed and edge["target"] not in removed]
            revision = canvas["revision"] + 1
            self.conn.execute("UPDATE canvases SET nodes=?,edges=? WHERE project_id=?", (encode(nodes), encode(edges), project_id))
            self.conn.execute("UPDATE projects SET revision=?,updated_at=?,cover_version_id=? WHERE id=?", (revision, now(), self._canvas_cover(nodes), project_id))
            self.conn.execute("DELETE FROM project_assets WHERE project_id=? AND asset_id=?", (project_id, asset_id))
            self.emit("canvas.updated", {"project_id": project_id, "revision": revision})
            self.emit("project.assets_updated", {"project_id": project_id, "asset_id": asset_id})
        return {"removed": True, "canvas": self.canvas(project_id)}

    def ingest(self, staged: Path, filename: str, metadata: dict, digest: str, project_id: str | None = None, asset_id: str | None = None, request_id: str | None = None, source: str = "upload") -> dict:
        payload = {"hash": digest, "filename": filename, "project_id": project_id, "asset_id": asset_id, "source": source}
        explicit_asset = asset_id is not None
        with self.tx():
            previous = self.request_result(request_id, "upload", payload)
            if previous is not None:
                return previous
            if project_id:
                self.project(project_id, include_deleted=False)
            if asset_id:
                asset = self.asset(asset_id, details=False)
                if asset["deleted_at"]:
                    raise DomainError(409, "请先恢复资产再添加版本。", "asset_trashed")
                if asset["type"] != metadata["type"]:
                    raise DomainError(422, "新版本必须保持同一媒体类型。", "version_type_mismatch")
            else:
                existing = self.conn.execute("SELECT a.id FROM assets a JOIN versions v ON v.asset_id=a.id WHERE v.blob_hash=? AND a.deleted_at IS NULL ORDER BY CASE WHEN a.current_version_id=v.id THEN 0 ELSE 1 END,a.created_at LIMIT 1", (digest,)).fetchone()
                if existing:
                    asset_id = existing["id"]
                else:
                    asset_id = new_id()
                    self.conn.execute("INSERT INTO assets(id,name,type,source,created_at) VALUES(?,?,?,?,?)", (asset_id, filename, metadata["type"], source, now()))
            target = self.blob_path(digest)
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.exists():
                temporary = target.with_name(f".{digest}.{new_id()}.part")
                try:
                    shutil.copyfile(staged, temporary)
                    os.replace(temporary, target)
                finally:
                    temporary.unlink(missing_ok=True)
            self.conn.execute("INSERT OR IGNORE INTO blobs VALUES(?,?,?,?)", (digest, target.relative_to(self.root).as_posix(), metadata["size"], now()))
            existing_version = self.conn.execute("SELECT id FROM versions WHERE asset_id=? AND blob_hash=?", (asset_id, digest)).fetchone()
            if existing_version:
                version_id = existing_version["id"]
                if explicit_asset:
                    self.conn.execute("UPDATE assets SET current_version_id=? WHERE id=?", (version_id, asset_id))
            else:
                version_id = new_id()
                self.conn.execute("INSERT INTO versions(id,asset_id,blob_hash,filename,size,width,height,duration,mime,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)", (version_id, asset_id, digest, filename, metadata["size"], metadata.get("width"), metadata.get("height"), metadata.get("duration"), metadata["mime"], now()))
                self.conn.execute("UPDATE assets SET current_version_id=? WHERE id=?", (version_id, asset_id))
                timestamp = now()
                self.conn.execute("INSERT INTO tasks(id,kind,version_id,created_at,updated_at) VALUES(?,?,?,?,?)", (new_id(), "preview", version_id, timestamp, timestamp))
            if project_id:
                self._link_asset(project_id, asset_id)
            result = self.asset(asset_id)
            result["imported_version_id"] = version_id
            self.remember_request(request_id, "upload", payload, result)
            self.emit("asset.updated", {"asset_id": asset_id, "version_id": version_id, "project_id": project_id})
            return result

    def update_asset(self, asset_id: str, changes: dict) -> dict:
        with self.tx():
            asset = self.asset(asset_id, details=False)
            name = self.validate_name(changes.get("name", asset["name"]))
            tags = changes.get("tags", asset["tags"])
            if not isinstance(tags, list) or len(tags) > 50 or any(not isinstance(tag, str) or not tag.strip() or len(tag) > 80 for tag in tags):
                raise DomainError(422, "标签须为最多 50 个短文本。", "invalid_tags")
            current_version = changes.get("current_version_id", asset["current_version_id"])
            if self.version(current_version)["asset_id"] != asset_id:
                raise DomainError(422, "版本属于其他资产。", "version_mismatch")
            self.conn.execute("UPDATE assets SET name=?,tags=?,current_version_id=? WHERE id=?", (name, encode(list(dict.fromkeys(tag.strip() for tag in tags))), current_version, asset_id))
            self.emit("asset.updated", {"asset_id": asset_id})
        return self.asset(asset_id)

    def _guard_generations(self, project_id: str | None = None, asset_id: str | None = None) -> None:
        self._guard_production(project_id=project_id, asset_id=asset_id)
        self._guard_orchestration(project_id=project_id, asset_id=asset_id)
        if not self.conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='generation_jobs'").fetchone():
            return
        active = "('pending','submitting','queued','running','collecting','unknown')"
        if asset_id:
            query = f"SELECT DISTINCT j.id,j.project_id,j.status FROM generation_jobs j JOIN generation_inputs i ON i.job_id=j.id JOIN versions v ON v.id=i.version_id WHERE v.asset_id=? AND j.status IN {active}"
            rows = self.conn.execute(query + (" AND j.project_id=?" if project_id else ""), (asset_id, project_id) if project_id else (asset_id,)).fetchall()
        else:
            rows = self.conn.execute(f"SELECT id,project_id,status FROM generation_jobs WHERE project_id=? AND status IN {active}", (project_id,)).fetchall()
        if rows:
            raise DomainError(409, "仍有生成任务在使用这些内容，请先等待完成或取消任务。", "generation_in_progress", generations=[dict(row) for row in rows])

    def _guard_production(self, project_id: str | None = None, asset_id: str | None = None) -> None:
        if not self.conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='production_renders'").fetchone():
            return
        if asset_id:
            query = "SELECT DISTINCT r.id,r.project_id,r.status FROM production_renders r JOIN production_inputs i ON i.render_id=r.id JOIN versions v ON v.id=i.version_id WHERE v.asset_id=? AND r.status IN ('pending','running')"
            rows = self.conn.execute(query + (" AND r.project_id=?" if project_id else ""), (asset_id, project_id) if project_id else (asset_id,)).fetchall()
        else:
            rows = self.conn.execute("SELECT id,project_id,status FROM production_renders WHERE project_id=? AND status IN ('pending','running')", (project_id,)).fetchall()
        if rows:
            raise DomainError(409, "成片任务仍在使用这些素材，请等待完成。", "production_in_progress", renders=[dict(row) for row in rows])

    def _guard_orchestration(self, project_id: str | None = None, asset_id: str | None = None) -> None:
        if not self.conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='canvas_runs'").fetchone():
            return
        if asset_id:
            query = "SELECT DISTINCT r.id,r.project_id,r.status FROM canvas_runs r JOIN canvas_run_inputs i ON i.run_id=r.id JOIN versions v ON v.id=i.version_id WHERE v.asset_id=? AND r.status IN ('pending','running','cancelling')"
            rows = self.conn.execute(query + (" AND r.project_id=?" if project_id else ""), (asset_id, project_id) if project_id else (asset_id,)).fetchall()
        else:
            rows = self.conn.execute("SELECT id,project_id,status FROM canvas_runs WHERE project_id=? AND status IN ('pending','running','cancelling')", (project_id,)).fetchall()
        if rows:
            raise DomainError(409, "画布编排任务仍在使用这些内容，请先等待完成或取消。", "orchestration_in_progress", runs=[dict(row) for row in rows])

    def trash_asset(self, asset_id: str, restore: bool = False) -> dict:
        with self.tx():
            asset = self.asset(asset_id)
            if not restore:
                self._guard_generations(asset_id=asset_id)
            if not restore and asset["subject_references"]:
                raise DomainError(409, "素材仍被主体库引用，请先移除条目中的图片或音色引用。", "subject_referenced", subjects=asset["subject_references"])
            if not restore and asset["references"]:
                raise DomainError(409, "资产仍被项目引用，请先从这些项目移除。", "asset_referenced", references=asset["references"])
            self.conn.execute("UPDATE assets SET deleted_at=? WHERE id=?", (None if restore else now(), asset_id))
            self.emit("asset.restored" if restore else "asset.deleted", {"asset_id": asset_id})
        return self.asset(asset_id)

    def purge_asset(self, asset_id: str) -> dict:
        with self.tx():
            asset = self.asset(asset_id)
            if not asset["deleted_at"]:
                raise DomainError(409, "请先将资产移入回收站。", "asset_not_trashed")
            self._guard_generations(asset_id=asset_id)
            if asset["subject_references"]:
                raise DomainError(409, "素材仍被主体库引用，请先移除条目中的图片或音色引用。", "subject_referenced", subjects=asset["subject_references"])
            if asset["references"]:
                raise DomainError(409, "资产仍被项目引用。", "asset_referenced", references=asset["references"])
            version_ids = [version["id"] for version in asset["versions"]]
            hashes = {version["hash"] for version in asset["versions"]}
            self.conn.execute("DELETE FROM assets WHERE id=?", (asset_id,))
            self.emit("asset.purged", {"asset_id": asset_id})
        # Commit references first, so a failed database commit can never remove an
        # original that a rolled-back asset still needs. Leftover files are safe.
        with self.tx():
            for digest in hashes:
                count = self.conn.execute("SELECT COUNT(*) FROM versions WHERE blob_hash=?", (digest,)).fetchone()[0]
                if count == 0:
                    try:
                        self.blob_path(digest).unlink(missing_ok=True)
                    except OSError:
                        continue
                    self.conn.execute("DELETE FROM blobs WHERE hash=?", (digest,))
            for version_id in version_ids:
                shutil.rmtree(self.root / "cache" / version_id, ignore_errors=True)
        return {"id": asset_id, "deleted": True}

    def repair(self, asset_id: str, version_id: str, staged: Path, digest: str) -> dict:
        with self.tx():
            version = self.version(version_id)
            if version["asset_id"] != asset_id or digest != version["hash"]:
                raise DomainError(409, "文件内容与所选版本不同。请通过“添加版本”保存修改后的文件。", "repair_hash_mismatch")
            target = self.blob_path(digest)
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_name(f".{digest}.{new_id()}.part")
            try:
                shutil.copyfile(staged, temporary)
                os.replace(temporary, target)
            finally:
                temporary.unlink(missing_ok=True)
            self.conn.execute("UPDATE versions SET missing=0,preview_status='pending',preview_error=NULL WHERE blob_hash=?", (digest,))
            for row in self.conn.execute("SELECT id FROM versions WHERE blob_hash=?", (digest,)).fetchall():
                timestamp = now()
                self.conn.execute("INSERT INTO tasks(id,kind,version_id,created_at,updated_at) VALUES(?,?,?,?,?)", (new_id(), "preview", row["id"], timestamp, timestamp))
            self.emit("asset.updated", {"asset_id": asset_id, "version_id": version_id})
        return self.asset(asset_id)

    def tasks(self) -> list[dict]:
        with self.lock:
            tasks = [dict(row) for row in self.conn.execute("SELECT * FROM tasks ORDER BY created_at DESC LIMIT 500")]
            for task in tasks:
                task["requires_file"] = bool(task["requires_file"])
                task["can_retry"] = bool(task["can_retry"])
            return tasks

    def record_import_failure(self, filename: str, message: str) -> None:
        with self.tx():
            timestamp, task_id = now(), new_id()
            self.conn.execute("INSERT INTO tasks(id,kind,status,error,filename,message,requires_file,can_retry,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)", (task_id, "import", "failed", message[:2000], filename[:250], f"导入 {filename[:200]} 失败，请重新选择文件上传", 1, 0, timestamp, timestamp))
            self.emit("task.updated", {"task_id": task_id, "status": "failed", "kind": "import", "requires_file": True})

    def retry_task(self, task_id: str) -> dict:
        with self.tx():
            row = self.conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
            if not row:
                raise DomainError(404, "任务不存在。", "task_not_found")
            if row["kind"] != "preview" or row["requires_file"]:
                raise DomainError(409, "此任务需要重新选择原文件并上传。", "file_required", requires_file=True, can_retry=False)
            if row["status"] == "running":
                raise DomainError(409, "任务正在执行。", "task_running")
            self.conn.execute("UPDATE tasks SET status='pending',error=NULL,updated_at=? WHERE id=?", (now(), task_id))
            self.conn.execute("UPDATE versions SET preview_status='pending',preview_error=NULL WHERE id=?", (row["version_id"],))
            self.emit("task.updated", {"task_id": task_id, "status": "pending"})
            return dict(self.conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone())

    def events(self, after: int) -> list[dict]:
        with self.lock:
            return [{"id": row["id"], "type": row["type"], "data": json.loads(row["data"])} for row in self.conn.execute("SELECT * FROM events WHERE id>? ORDER BY id LIMIT 200", (after,))]

    def event_cursor(self) -> int:
        with self.lock:
            return self.conn.execute("SELECT COALESCE(MAX(id),0) FROM events").fetchone()[0]
