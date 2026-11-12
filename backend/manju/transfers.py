"""Portable project archives and resumable local-library migration."""

from __future__ import annotations

import copy
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import sqlite3
import stat
import tempfile
import time
import zipfile

from .screenplay import encode_screenplay, get_screenplay
from .store import DomainError, Store, encode, new_id, now


ARCHIVE_FORMAT = 1
MAX_ARCHIVE_FILES = 20_000
MAX_ARCHIVE_BYTES = 100 * 1024**3
MAX_MANIFEST_BYTES = 16 * 1024**2
HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")
ACTIVE_MIGRATION_STATES = {"copying", "failed", "switching"}


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, value: dict) -> None:
    if "state" in value:
        value["status"] = value["state"]
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def _read_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise DomainError(409, f"无法读取迁移配置：{error}", "migration_journal_invalid") from error
    if not isinstance(value, dict):
        raise DomainError(409, "迁移配置格式错误", "migration_journal_invalid")
    return value


def _journal_path(store) -> Path:
    return store.config_file.with_suffix(".migration.json")


def recover_migration_state(store) -> None:
    journal = _read_json(_journal_path(store))
    store.maintenance = bool(journal and journal.get("state") in ACTIVE_MIGRATION_STATES)
    if journal and journal.get("state") in {"copying", "switching"}:
        journal["state"] = "failed"
        journal["error"] = "上次迁移被中断，可以继续复制或返回原目录。"
        _write_json(_journal_path(store), journal)


def _canvas_version_ids(canvas: dict) -> set[str]:
    """Include draft-only inputs; they need not already be project members."""
    identifiers = set()
    def add(value):
        if not isinstance(value, str) or not value:
            raise ValueError("invalid canvas version identifier")
        identifiers.add(value)

    for node in canvas.get("nodes", []):
        if not isinstance(node, dict) or not isinstance(node.get("data", {}), dict):
            raise ValueError("invalid canvas node data")
        data = node.get("data", {})
        if node.get("type") == "subject" or "subject" in data or "shot" in data or "production_settings" in data or "composite" in data or "timeline" in data:
            try:
                identifiers.update(Store.node_version_ids(node))
            except DomainError as error:
                raise ValueError(error.detail["message"]) from error
        for key in ("asset_version_id", "previous_image_version_id"):
            if data.get(key) is not None:
                add(data[key])
        history = data.get("image_history", [])
        if not isinstance(history, list):
            raise ValueError("invalid image history")
        for entry in history:
            if not isinstance(entry, dict):
                raise ValueError("invalid image history entry")
            add(entry.get("version_id"))
        draft = data.get("generation")
        if draft is None:
            continue
        if not isinstance(draft, dict):
            raise ValueError("invalid generation draft")
        for key in ("references", "h3_guides"):
            inputs = draft.get(key, [])
            if not isinstance(inputs, list):
                raise ValueError(f"invalid generation draft {key}")
            for item in inputs:
                if not isinstance(item, dict):
                    raise ValueError(f"invalid generation draft {key} entry")
                add(item.get("version_id"))
        if draft.get("edit_base_version_id") is not None:
            add(draft["edit_base_version_id"])
        if draft.get("mask_version_id") is not None:
            add(draft["mask_version_id"])
        order = draft.get("reference_order", [])
        if not isinstance(order, list) or any(not isinstance(value, str) or not value for value in order):
            raise ValueError("invalid generation reference order")
        if draft.get("workflow_id") is not None and (not isinstance(draft["workflow_id"], str) or not draft["workflow_id"]):
            raise ValueError("invalid generation workflow identifier")
    return identifiers


def _portable_canvas(canvas: dict) -> dict:
    """A project archive contains editable drafts, never live service jobs."""
    result = copy.deepcopy(canvas)
    result.pop("request_id", None)
    for node in result.get("nodes", []):
        data = node.get("data", {})
        if isinstance(data.get("subject"), dict):
            data["subject"].pop("library_id", None)
        data.pop("generation_id", None)
        data.pop("production_render_id", None)
        history = data.get("image_history", [])
        if isinstance(history, list):
            for entry in history:
                if isinstance(entry, dict):
                    entry.pop("job_id", None)
        draft = data.get("generation")
        if isinstance(draft, dict):
            for key in ("last_job_id", "pending_submission", "pending_request_id"):
                draft.pop(key, None)
    return result


def project_snapshot(store, project_id: str) -> dict:
    """Read-only project snapshot shared by archive export and canvas sharing.

    Validates that every referenced blob exists and matches its hash, and strips
    live-service state exactly like the portable archive manifest.
    """
    with store.lock:
        project = store.project(project_id)
        canvas = _portable_canvas(store.canvas(project_id))
        member_ids = {
            row[0] for row in store.conn.execute(
                "SELECT asset_id FROM project_assets WHERE project_id = ?", (project_id,)
            )
        }
        try:
            version_ids = _canvas_version_ids(canvas)
        except ValueError as error:
            raise DomainError(422, f"画布生成草稿包含无效引用：{error}", "invalid_canvas_generation") from error
        if project.get("cover_version_id"):
            version_ids.add(project["cover_version_id"])
        for asset_id in member_ids:
            asset_row = store.conn.execute(
                "SELECT current_version_id FROM assets WHERE id = ?", (asset_id,)
            ).fetchone()
            if asset_row and asset_row[0]:
                version_ids.add(asset_row[0])

        versions = []
        for version_id in sorted(version_ids):
            row = store.conn.execute("SELECT * FROM versions WHERE id = ?", (version_id,)).fetchone()
            if row is None:
                raise DomainError(409, "项目含有找不到的资产版本", "missing_version", version_id=version_id)
            version = dict(row)
            path = store.blob_path(version["blob_hash"])
            if not path.is_file() or _hash_file(path) != version["blob_hash"]:
                raise DomainError(409, "项目原件缺失或校验失败，请先修复", "missing_media", version_id=version_id)
            version.pop("preview_status", None)
            version.pop("preview_error", None)
            version.pop("missing", None)
            versions.append(version)
            member_ids.add(version["asset_id"])

        assets = []
        for asset_id in sorted(member_ids):
            row = store.conn.execute("SELECT * FROM assets WHERE id = ?", (asset_id,)).fetchone()
            if row is None:
                raise DomainError(409, "项目资产引用已损坏", "missing_asset", asset_id=asset_id)
            asset = dict(row)
            if asset["current_version_id"] not in version_ids:
                candidates = [version["id"] for version in versions if version["asset_id"] == asset_id]
                asset["current_version_id"] = candidates[-1] if candidates else None
            assets.append(asset)

        screenplay = get_screenplay(store, project_id, include_deleted=True)["document"]
        return {
            "project": project,
            "canvas": canvas,
            "assets": assets,
            "versions": versions,
            "project_assets": sorted(member_ids),
            "screenplay": screenplay,
        }


def export_project(store, project_id: str) -> Path:
    """Hold the read/write lock until a complete immutable archive exists."""
    with store.lock:
        snapshot = project_snapshot(store, project_id)
        blobs = {}
        for version in snapshot["versions"]:
            path = store.blob_path(version["blob_hash"])
            if not path.is_file() or _hash_file(path) != version["blob_hash"]:
                raise DomainError(409, "项目原件缺失或校验失败，请先修复",
                                  "missing_media", version_id=version["id"])
            blobs[version["blob_hash"]] = path

        manifest = {
            "format": ARCHIVE_FORMAT,
            "exported_at": now(),
            "project": snapshot["project"],
            "canvas": snapshot["canvas"],
            "assets": snapshot["assets"],
            "versions": snapshot["versions"],
            "project_assets": snapshot["project_assets"],
        }
        if snapshot["screenplay"] is not None:
            manifest["screenplay"] = snapshot["screenplay"]
        export_dir = store.root / "temp"
        export_dir.mkdir(parents=True, exist_ok=True)
        target = export_dir / f"export-{new_id()}.manju"
        try:
            with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=1) as archive:
                archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False))
                for blob_hash, path in sorted(blobs.items()):
                    archive.write(path, f"blobs/{blob_hash}")
        except Exception:
            target.unlink(missing_ok=True)
            raise
        return target


def _archive_entries(archive: zipfile.ZipFile) -> dict[str, zipfile.ZipInfo]:
    entries = {}
    names = set()
    size = 0
    if len(archive.infolist()) > MAX_ARCHIVE_FILES:
        raise DomainError(413, "项目包文件数超过限制", "archive_too_large")
    for info in archive.infolist():
        name = info.filename
        path = PurePosixPath(name)
        mode = info.external_attr >> 16
        if (
            not name or "\\" in name or ":" in name or path.is_absolute()
            or any(part in {".", ".."} for part in path.parts)
            or str(path) != name or info.is_dir() or stat.S_ISLNK(mode)
            or name.casefold() in names or info.flag_bits & 1
        ):
            raise DomainError(400, "项目包包含不安全或重复的路径", "unsafe_archive")
        if name != "manifest.json" and not re.fullmatch(r"blobs/[0-9a-f]{64}", name):
            raise DomainError(400, "项目包含有未支持的文件", "unsafe_archive")
        names.add(name.casefold())
        entries[name] = info
        size += info.file_size
        if size > MAX_ARCHIVE_BYTES:
            raise DomainError(413, "项目包解压大小超过限制", "archive_too_large")
    manifest_info = entries.get("manifest.json")
    if manifest_info is None or manifest_info.file_size > MAX_MANIFEST_BYTES:
        raise DomainError(400, "项目包缺少有效清单", "invalid_archive")
    return entries


def _manifest(archive: zipfile.ZipFile, entries: dict) -> dict:
    try:
        manifest = json.loads(archive.read("manifest.json"))
        if manifest["format"] != ARCHIVE_FORMAT:
            raise ValueError("unsupported format")
        project = manifest["project"]
        canvas = manifest["canvas"]
        assets = manifest["assets"]
        versions = manifest["versions"]
        members = manifest["project_assets"]
        if not isinstance(project, dict) or not isinstance(canvas, dict):
            raise ValueError("invalid project")
        if not all(isinstance(value, list) for value in (assets, versions, members)):
            raise ValueError("invalid collections")
        if project.get("aspect_ratio", "free") not in {"free", "16:9", "9:16"}:
            raise ValueError("invalid aspect ratio")
        if not isinstance(project.get("name"), str) or not project["name"].strip():
            raise ValueError("invalid project name")
        if not isinstance(canvas.get("nodes"), list) or not isinstance(canvas.get("edges"), list):
            raise ValueError("invalid canvas")
        if not isinstance(canvas.get("viewport"), dict):
            raise ValueError("invalid viewport")
        if "screenplay" in manifest:
            manifest["screenplay"] = json.loads(encode_screenplay(manifest["screenplay"]))
        asset_ids = {asset["id"] for asset in assets}
        version_ids = {version["id"] for version in versions}
        if any(not isinstance(identifier, str) or not identifier for identifier in asset_ids | version_ids):
            raise ValueError("invalid identifiers")
        if len(asset_ids) != len(assets) or len(version_ids) != len(versions):
            raise ValueError("duplicate identifiers")
        if set(members) != asset_ids or len(members) != len(set(members)):
            raise ValueError("unknown project asset")
        if not _canvas_version_ids(canvas).issubset(version_ids):
            raise ValueError("unknown canvas version")
        if project.get("cover_version_id") and project["cover_version_id"] not in version_ids:
            raise ValueError("unknown cover version")
        version_assets = {version["id"]: version["asset_id"] for version in versions}
        for asset in assets:
            if asset.get("type") not in {"image", "video", "audio"}:
                raise ValueError("invalid media type")
            if not isinstance(asset.get("name"), str) or not asset["name"].strip():
                raise ValueError("invalid asset name")
            current = asset.get("current_version_id")
            if not current or version_assets.get(current) != asset["id"]:
                raise ValueError("invalid current version")
            tags = json.loads(asset.get("tags", "[]")) if isinstance(asset.get("tags"), str) else asset.get("tags", [])
            if not isinstance(tags, list) or len(tags) > 50 or not all(isinstance(tag, str) and tag.strip() and len(tag) <= 80 for tag in tags):
                raise ValueError("invalid tags")
            asset["tags"] = json.dumps(tags, ensure_ascii=False)
        required_blobs = set()
        for version in versions:
            blob_hash = version["blob_hash"]
            if not isinstance(blob_hash, str) or not HASH_PATTERN.fullmatch(blob_hash):
                raise ValueError("invalid content hash")
            if version["asset_id"] not in asset_ids or not isinstance(version["filename"], str) or not version["filename"] or any(char in version["filename"] for char in ("\x00", "\r", "\n")):
                raise ValueError("invalid version")
            if not isinstance(version["size"], int) or version["size"] < 1:
                raise ValueError("invalid media size")
            entry = entries.get(f"blobs/{blob_hash}")
            if entry is None or entry.file_size != version["size"]:
                raise ValueError("missing or incorrect media")
            if not isinstance(version.get("mime"), str) or not version["mime"].startswith(("image/", "audio/", "video/")):
                raise ValueError("invalid MIME type")
            required_blobs.add(f"blobs/{blob_hash}")
        if set(entries) != required_blobs | {"manifest.json"}:
            raise ValueError("unreferenced media")
        return manifest
    except (ValueError, KeyError, TypeError, AttributeError) as error:
        raise DomainError(400, f"项目包清单无效：{error}", "invalid_archive") from error


def import_project(store, zip_path: Path) -> dict:
    with store.media_lock:
        return _import_project_locked(store, zip_path)


def _import_project_locked(store, zip_path: Path) -> dict:
    """Verify all bytes before publishing a new project in one transaction."""
    if store.maintenance:
        raise DomainError(409, "资产库正在迁移", "storage_migrating")
    staging_parent = store.root / "temp"
    staging_parent.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(zip_path) as archive, tempfile.TemporaryDirectory(prefix="import-", dir=staging_parent) as temporary:
            entries = _archive_entries(archive)
            manifest = _manifest(archive, entries)
            store.validate_canvas(manifest["canvas"])
            store.validate_name(manifest["project"]["name"])
            for asset in manifest["assets"]:
                store.validate_name(asset["name"])
            required_size = sum(info.file_size for name, info in entries.items() if name != "manifest.json")
            if shutil.disk_usage(store.root).free < required_size + 16 * 1024**2:
                raise DomainError(507, "磁盘空间不足，无法导入项目", "insufficient_storage")
            staging = Path(temporary)
            for name, info in entries.items():
                if name == "manifest.json":
                    continue
                blob_hash = name.split("/")[1]
                digest = hashlib.sha256()
                written = 0
                with archive.open(info) as source, (staging / blob_hash).open("wb") as destination:
                    for chunk in iter(lambda: source.read(1024 * 1024), b""):
                        written += len(chunk)
                        if written > info.file_size:
                            raise DomainError(400, "项目包文件大小异常", "invalid_archive")
                        digest.update(chunk)
                        destination.write(chunk)
                if written != info.file_size or digest.hexdigest() != blob_hash:
                    raise DomainError(400, "项目包原件校验失败", "archive_hash_mismatch")
            from .media import probe_media

            asset_types = {asset["id"]: asset["type"] for asset in manifest["assets"]}
            inspected = {}
            for version in manifest["versions"]:
                blob_hash = version["blob_hash"]
                if blob_hash not in inspected:
                    inspected[blob_hash] = probe_media(staging / blob_hash, version["filename"])
                metadata = inspected[blob_hash]
                if metadata["type"] != asset_types[version["asset_id"]]:
                    raise DomainError(400, "项目包资产类型与原件内容不符", "archive_media_mismatch")
                for field in ("mime", "size", "width", "height", "duration"):
                    version[field] = metadata.get(field)
            versions_by_id = {version["id"]: version for version in manifest["versions"]}
            for node in manifest["canvas"]["nodes"]:
                if node.get("type") != "subject":
                    continue
                subject = store.normalize_subject(node["data"]["subject"], allow_empty=True, allow_library=True)
                required = [(value, "image") for value in subject["image_version_ids"]]
                if subject["voice_version_id"]:
                    required.append((subject["voice_version_id"], "audio"))
                for identifier, kind in required:
                    if not versions_by_id[identifier]["mime"].startswith(kind + "/"):
                        raise DomainError(400, "项目包主体中的图片或音色引用类型错误。", "archive_subject_media_mismatch")
            return _commit_import(store, manifest, staging)
    except (zipfile.BadZipFile, zipfile.LargeZipFile, EOFError) as error:
        raise DomainError(400, "无法读取项目包 ZIP 文件", "invalid_archive") from error


def _commit_import(store, manifest: dict, staging: Path) -> dict:
    installed = []
    with store.lock:
        try:
            return _commit_import_records(store, manifest, staging, installed)
        except Exception:
            for digest, path in installed:
                if not store.conn.execute("SELECT 1 FROM blobs WHERE hash = ?", (digest,)).fetchone():
                    path.unlink(missing_ok=True)
            raise


def _commit_import_records(store, manifest: dict, staging: Path, installed: list) -> dict:
    created_at = now()
    project_id = new_id()
    asset_map = {asset["id"]: new_id() for asset in manifest["assets"]}
    version_map = {version["id"]: new_id() for version in manifest["versions"]}
    project = manifest["project"]
    canvas = _portable_canvas(manifest["canvas"])
    import_warnings = []
    has_workflows = store.conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='workflows'").fetchone()
    for node in canvas["nodes"]:
        data = node.get("data", {})
        for key in ("asset_version_id", "previous_image_version_id"):
            if data.get(key):
                data[key] = version_map[data[key]]
        composite = data.get("composite")
        if isinstance(composite, dict):
            composite["input_versions"] = [version_map[value] for value in composite.get("input_versions", [])]
        timeline = data.get("timeline")
        if isinstance(timeline, dict):
            for clip in timeline.get("clips", []):
                if clip.get("asset_version_id"):
                    clip["asset_version_id"] = version_map[clip["asset_version_id"]]
        shot = data.get("shot")
        if isinstance(shot, dict):
            for key in ("video_version_id", "audio_version_id"):
                if shot.get(key):
                    shot[key] = version_map[shot[key]]
        settings = data.get("production_settings")
        if isinstance(settings, dict) and settings.get("background_audio_version_id"):
            settings["background_audio_version_id"] = version_map[settings["background_audio_version_id"]]
        subject = data.get("subject")
        if isinstance(subject, dict):
            subject["image_version_ids"] = [version_map[value] for value in subject["image_version_ids"]]
            if subject.get("voice_version_id"):
                subject["voice_version_id"] = version_map[subject["voice_version_id"]]
            subject.pop("library_id", None)
        for entry in data.get("image_history", []):
            entry["version_id"] = version_map[entry["version_id"]]
        draft = data.get("generation")
        if not isinstance(draft, dict):
            continue
        for reference in draft.get("references", []):
            reference["version_id"] = version_map[reference["version_id"]]
        for guide in draft.get("h3_guides", []):
            guide["version_id"] = version_map[guide["version_id"]]
        if draft.get("edit_base_version_id"):
            draft["edit_base_version_id"] = version_map[draft["edit_base_version_id"]]
        if draft.get("mask_version_id"):
            draft["mask_version_id"] = version_map[draft["mask_version_id"]]
        if "reference_order" in draft:
            draft["reference_order"] = [version_map[value] for value in draft["reference_order"] if value in version_map]
        workflow_id = draft.get("workflow_id")
        draft.pop("workflow_import_warning", None)
        if workflow_id and workflow_id not in ("builtin-indextts25-local", "builtin-h3-local", "builtin-openai-text_to_image", "builtin-openai-reference", "builtin-openai-edit") and not (has_workflows and store.conn.execute("SELECT 1 FROM workflows WHERE id=?", (workflow_id,)).fetchone()):
            message = "原工作流未随项目包导入，请导入原工作流或明确选择其他工作流。"
            draft["workflow_import_warning"] = message
            import_warnings.append({"code": "workflow_not_imported", "node_id": node["id"], "workflow_id": workflow_id, "message": message})
    with store.tx():
        for version in manifest["versions"]:
            blob_hash = version["blob_hash"]
            destination = store.blob_path(blob_hash)
            destination.parent.mkdir(parents=True, exist_ok=True)
            source = staging / blob_hash
            if source.exists():
                if destination.exists() and _hash_file(destination) != blob_hash:
                    raise DomainError(409, "资产库内有校验失败的原件，请先修复", "library_hash_mismatch")
                if not destination.exists():
                    source.replace(destination)
                    installed.append((blob_hash, destination))
            store.conn.execute(
                "INSERT OR IGNORE INTO blobs(hash,path,size,created_at) VALUES(?,?,?,?)",
                (blob_hash, destination.relative_to(store.root).as_posix(), version["size"], created_at),
            )
        for asset in manifest["assets"]:
            store.conn.execute(
                "INSERT INTO assets(id,name,type,tags,source,created_at,current_version_id) VALUES(?,?,?,?,?,?,?)",
                (asset_map[asset["id"]], asset["name"], asset["type"], asset["tags"], "import", created_at,
                 version_map.get(asset.get("current_version_id"))),
            )
        for version in manifest["versions"]:
            version_id = version_map[version["id"]]
            store.conn.execute(
                "INSERT INTO versions(id,asset_id,blob_hash,filename,size,width,height,duration,mime,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (version_id, asset_map[version["asset_id"]], version["blob_hash"], Path(version["filename"]).name,
                 version["size"], version.get("width"), version.get("height"), version.get("duration"), version["mime"], created_at),
            )
            store.conn.execute(
                "INSERT INTO tasks(id,kind,version_id,created_at,updated_at) VALUES(?,?,?,?,?)",
                (new_id(), "preview", version_id, created_at, created_at),
            )
        store.conn.execute(
            "INSERT INTO projects(id,name,aspect_ratio,created_at,updated_at,cover_version_id) VALUES(?,?,?,?,?,?)",
            (project_id, project["name"][:190] + " · 导入", project.get("aspect_ratio", "free"), created_at, created_at,
             version_map.get(project.get("cover_version_id"))),
        )
        store.conn.execute(
            "INSERT INTO canvases(project_id,nodes,edges,viewport) VALUES(?,?,?,?)",
            (project_id, json.dumps(canvas["nodes"], ensure_ascii=False), json.dumps(canvas["edges"], ensure_ascii=False),
             json.dumps(canvas["viewport"], ensure_ascii=False)),
        )
        if "screenplay" in manifest:
            store.conn.execute("INSERT INTO screenplays(project_id,document) VALUES(?,?)", (project_id, encode(manifest["screenplay"])))
        for asset_id in manifest["project_assets"]:
            store.conn.execute(
                "INSERT INTO project_assets(project_id,asset_id,added_at) VALUES(?,?,?)",
                (project_id, asset_map[asset_id], created_at),
            )
        store.emit("project.imported", {"project_id": project_id, "warnings": import_warnings})
    return {**store.project(project_id), "import_warnings": import_warnings}


def storage_status(store) -> dict:
    from .media import find_binary

    # Read the atomic journal independently of the long migration/database lock.
    root = store.root
    journal = _read_json(_journal_path(store))
    migration = None
    if journal:
        migration = {key: value for key, value in journal.items() if key != "files"}
        migration["status"] = journal.get("state", "pending")
        total_files = journal.get("total_files", 0)
        migration["progress"] = round(100 * journal.get("copied_files", 0) / total_files) if total_files else 0
        if migration["status"] == "completed":
            migration["progress"] = 100
    activity = getattr(store, "migration_activity", None)
    if activity and (not migration or migration.get("state") not in ACTIVE_MIGRATION_STATES or migration.get("target") != activity.get("target")):
        migration = activity
    cached = getattr(store, "storage_size_cache", None)
    if journal and journal.get("files"):
        total = sum(entry["size"] for entry in journal["files"])
    elif cached and cached[0] == root and time.monotonic() - cached[1] < 10:
        total = cached[2]
    else:
        total = 0
        for path in root.rglob("*"):
            try:
                if path.is_file():
                    total += path.stat().st_size
            except FileNotFoundError:
                continue
        store.storage_size_cache = (root, time.monotonic(), total)
    return {
        "root": str(root),
        "size_bytes": total,
        "free_bytes": shutil.disk_usage(root).free,
        "ffmpeg": find_binary("ffmpeg"),
        "ffprobe": find_binary("ffprobe"),
        "migration": migration,
    }


def migrate_storage(store, target: str) -> dict:
    with store.media_lock, store.lock:
        existing = _read_json(_journal_path(store))
        if existing and existing.get("state") in ACTIVE_MIGRATION_STATES:
            raise DomainError(409, "已有迁移任务，请继续或取消", "migration_pending")
        source = store.root.resolve()
        destination = Path(target).expanduser().resolve()
        if destination == source or source in destination.parents or destination in source.parents:
            raise DomainError(400, "目标目录必须与当前资产库互相独立", "invalid_migration_target")
        if destination.exists() and (not destination.is_dir() or any(destination.iterdir())):
            raise DomainError(409, "迁移目标必须为空目录", "migration_target_not_empty")
        destination.mkdir(parents=True, exist_ok=True)
        migration_id = new_id()
        journal = {
            "id": migration_id, "state": "copying", "source": str(source), "target": str(destination),
            "created_at": now(), "updated_at": now(), "copied_files": 0, "total_files": 0, "error": None,
        }
        _write_json(destination / ".manju-migration.json", {"id": migration_id})
        _write_json(_journal_path(store), journal)
        store.maintenance = True
    return resume_migration(store)


def _migration_files(store, source: Path) -> list[dict]:
    database_path = Path(store.conn.execute("PRAGMA database_list").fetchone()[2]).resolve()
    comfy_runtime = store.config_file.parent / (store.config_file.stem + ".comfy")
    snapshot = source / "temp" / "migration-database.sqlite"
    snapshot.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(snapshot)) as connection:
        store.conn.backup(connection)
    files = []
    for path in sorted(source.rglob("*")):
        if path.is_relative_to(comfy_runtime):
            continue
        if path.is_symlink():
            raise DomainError(409, "资产库包含符号链接，迁移前请移除链接", "migration_symlink")
        if not path.is_file():
            continue
        relative = path.relative_to(source)
        if relative.parts[0] in {"tmp", "temp"} or relative.as_posix() in {".manju-migration.json", ".manju.lock"} or path in {database_path, store.config_file, _journal_path(store)} or str(path).endswith(("-wal", "-shm")):
            continue
        files.append({"path": relative.as_posix(), "size": path.stat().st_size, "hash": _hash_file(path)})
    files.append({
        "path": database_path.relative_to(source).as_posix(), "source_path": snapshot.relative_to(source).as_posix(),
        "size": snapshot.stat().st_size, "hash": _hash_file(snapshot),
    })
    return files


def _copy_verified(source: Path, target: Path, entry: dict) -> None:
    destination = target / entry["path"]
    if destination.is_file() and destination.stat().st_size == entry["size"] and _hash_file(destination) == entry["hash"]:
        return
    original = source / entry.get("source_path", entry["path"])
    if not original.is_file() or _hash_file(original) != entry["hash"]:
        raise DomainError(409, "迁移期间源文件发生变化，请取消后重新迁移", "migration_source_changed")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".migration-part")
    shutil.copyfile(original, temporary)
    if _hash_file(temporary) != entry["hash"]:
        raise DomainError(500, "复制文件校验失败，可以继续迁移", "migration_copy_failed")
    temporary.replace(destination)


def resume_migration(store) -> dict:
    with store.media_lock, store.lock:
        journal = _read_json(_journal_path(store))
        if not journal or journal.get("state") not in ACTIVE_MIGRATION_STATES:
            raise DomainError(409, "没有可以继续的迁移任务", "migration_not_pending")
        source = Path(journal["source"]).resolve()
        destination = Path(journal["target"]).resolve()
        marker = _read_json(destination / ".manju-migration.json")
        if not marker or marker.get("id") != journal["id"]:
            raise DomainError(409, "迁移目标标记丢失，请检查目标目录", "migration_target_changed")
        store.maintenance = True
        previous_config = _read_json(store.config_file) or {}
        try:
            if store.root.resolve() != source:
                store.reopen(source)
            journal["state"] = "copying"
            journal["error"] = None
            if not journal.get("files"):
                journal["files"] = _migration_files(store, source)
                journal["total_files"] = len(journal["files"])
            required = sum(entry["size"] for entry in journal["files"] if not (destination / entry["path"]).exists())
            if shutil.disk_usage(destination).free < required + 16 * 1024**2:
                raise DomainError(507, "目标磁盘空间不足", "insufficient_storage")
            _write_json(_journal_path(store), journal)
            for index, entry in enumerate(journal["files"]):
                _copy_verified(source, destination, entry)
                journal["copied_files"] = index + 1
                journal["updated_at"] = now()
                _write_json(_journal_path(store), journal)
            journal["state"] = "switching"
            _write_json(_journal_path(store), journal)
            store.reopen(destination)
            if store.conn.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise DomainError(500, "迁移数据库校验失败", "migration_database_invalid")
            configuration = dict(previous_config)
            configuration["root"] = str(destination)
            _write_json(store.config_file, configuration)
            journal["state"] = "completed"
            journal["completed_at"] = now()
            journal["updated_at"] = now()
            journal.pop("files", None)
            _write_json(_journal_path(store), journal)
            store.maintenance = False
            with store.tx():
                store.emit("storage.migrated", {"source": str(source), "root": str(destination)})
            return storage_status(store)
        except Exception as error:
            store.reopen(source)
            store.maintenance = True
            previous_config["root"] = str(source)
            _write_json(store.config_file, previous_config)
            journal["state"] = "failed"
            journal["error"] = str(error)
            journal["updated_at"] = now()
            _write_json(_journal_path(store), journal)
            if isinstance(error, DomainError):
                raise
            raise DomainError(500, f"迁移失败，原资产库已恢复：{error}", "migration_failed") from error


def cancel_migration(store) -> dict:
    with store.media_lock, store.lock:
        journal = _read_json(_journal_path(store))
        if not journal or journal.get("state") not in ACTIVE_MIGRATION_STATES:
            raise DomainError(409, "没有可以取消的迁移任务", "migration_not_pending")
        source = Path(journal["source"]).resolve()
        if store.root.resolve() != source:
            store.reopen(source)
        configuration = _read_json(store.config_file) or {}
        configuration["root"] = str(source)
        _write_json(store.config_file, configuration)
        journal["state"] = "cancelled"
        journal["updated_at"] = now()
        journal.pop("files", None)
        _write_json(_journal_path(store), journal)
        store.maintenance = False
        return storage_status(store)
