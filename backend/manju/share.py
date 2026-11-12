"""Setu (亦可) canvas sharing: device connection, snapshot planning and publishing.

The local workbench never exposes itself to the internet. It talks to the Setu
API with a scoped device token, uploads media bytes straight to Aliyun OSS via
presigned URLs, and commits a read-only canvas manifest.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import threading
import time
import webbrowser
from pathlib import Path
from urllib.parse import urlencode

import httpx

from .store import DomainError, Store, now
from .transfers import project_snapshot

DEFAULT_API_BASE = "https://api.yukiryou.icu"
DEFAULT_WEB_BASE = "https://yk.yukiryou.icu"
CLIENT_NAME = "Manju"
CLIENT_VERSION = "0.1.0"

CONNECT_TIMEOUT_SECONDS = 600.0
CONNECT_POLL_SECONDS = 3.5
PREVIEW_WAIT_SECONDS = 20.0
UPLOAD_ATTEMPTS = 3

MAX_SHARE_BYTES = 512 * 1024**2
MAX_ORIGINAL_IMAGE_BYTES = 12 * 1024**2
MAX_ORIGINAL_VIDEO_BYTES = 200 * 1024**2
MAX_ORIGINAL_AUDIO_BYTES = 50 * 1024**2

MEDIA_ROLES = ("VIEW", "THUMB", "WAVEFORM")


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _valid_viewport(value) -> dict | None:
    if not isinstance(value, dict):
        return None
    try:
        x, y, zoom = float(value.get("x")), float(value.get("y")), float(value.get("zoom"))
    except (TypeError, ValueError):
        return None
    if not all(v == v and abs(v) != float("inf") for v in (x, y, zoom)) or zoom <= 0:
        return None
    return {"x": x, "y": y, "zoom": zoom}


class ShareConfig:
    """Connection state stored next to the workbench config with owner-only access."""

    def __init__(self, store: Store):
        self.store = store
        self.lock = threading.RLock()

    @property
    def path(self) -> Path:
        return self.store.config_file.with_suffix(".share.json")

    def load(self) -> dict:
        with self.lock:
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                return {}
            return data if isinstance(data, dict) else {}

    def save(self, data: dict) -> None:
        with self.lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_name(self.path.name + ".tmp")
            with temporary.open("w", encoding="utf-8") as stream:
                json.dump(data, stream, ensure_ascii=False, indent=2)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.chmod(temporary, 0o600)
            except OSError:
                pass
            temporary.replace(self.path)

    def clear(self) -> None:
        with self.lock:
            try:
                self.path.unlink(missing_ok=True)
            except OSError:
                pass

    def api_base(self) -> str:
        value = os.environ.get("MANJU_SETU_API_BASE", "").strip()
        if value:
            return value.rstrip("/")
        saved = str(self.load().get("api_base") or "").strip()
        return (saved or DEFAULT_API_BASE).rstrip("/")

    def web_base(self) -> str:
        value = os.environ.get("MANJU_SETU_WEB_BASE", "").strip()
        if value:
            return value.rstrip("/")
        saved = str(self.load().get("web_base") or "").strip()
        return (saved or DEFAULT_WEB_BASE).rstrip("/")

    def token(self) -> str:
        return str(self.load().get("token") or "")

    def user(self) -> dict | None:
        user = self.load().get("user")
        return user if isinstance(user, dict) else None


class ShareClient:
    """Minimal Setu API client for the share device token."""

    def __init__(self, api_base: str, token: str | None = None, transport=None):
        self.api_base = api_base.rstrip("/")
        self.token = token
        self.client = httpx.Client(
            timeout=httpx.Timeout(600, connect=15),
            transport=transport,
            trust_env=False,
            headers={"User-Agent": f"Manju/{CLIENT_VERSION} (canvas-share)"},
        )

    def close(self) -> None:
        self.client.close()

    def _headers(self) -> dict:
        headers = {"X-Setu-Client": f"manju:{CLIENT_VERSION}"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def _request(self, method: str, path: str, body: dict | None = None, timeout=None):
        try:
            response = self.client.request(
                method, self.api_base + path, json=body, headers=self._headers(), timeout=timeout
            )
        except httpx.HTTPError as error:
            raise DomainError(502, "无法连接亦可服务，请检查网络后重试。", "share_network_error",
                              reason=str(error)) from error
        if response.status_code >= 400:
            self._reject(response)
        if response.status_code == 204:
            return None
        try:
            return response.json()
        except ValueError as error:
            raise DomainError(502, "亦可服务返回了无法解析的数据。", "share_bad_response") from error

    @staticmethod
    def _reject(response) -> None:
        detail = {}
        try:
            parsed = response.json()
            if isinstance(parsed, dict):
                detail = parsed
        except ValueError:
            pass
        code = str(detail.get("code") or detail.get("error") or "share_request_failed")
        message = detail.get("message") or detail.get("msg")
        status = response.status_code
        if status == 401:
            raise DomainError(401, message or "亦可连接已失效，请在 Manju 重新登录。",
                              "share_unauthorized", upstream_status=status, upstream_code=code)
        if status == 404:
            raise DomainError(404, message or "分享不存在或已删除。",
                              "share_not_found", upstream_status=status, upstream_code=code)
        if status == 429:
            raise DomainError(429, message or "操作过于频繁，请稍后重试。",
                              "share_rate_limited", upstream_status=status, upstream_code=code)
        if status == 503:
            raise DomainError(503, message or "亦可的画布分享服务暂不可用。",
                              "share_unavailable", upstream_status=status, upstream_code=code)
        if status >= 500:
            raise DomainError(502, "亦可服务异常，请稍后重试。",
                              "share_upstream_error", upstream_status=status, upstream_code=code)
        raise DomainError(400, message or f"亦可拒绝了请求（HTTP {status}）。",
                          "share_rejected", upstream_status=status, upstream_code=code)

    def exchange_token(self, request_id: str, verifier: str) -> dict:
        return self._request("POST", "/canvas/connect/token", {
            "requestId": request_id,
            "verifier": verifier,
            "clientName": CLIENT_NAME,
            "clientVersion": CLIENT_VERSION,
        })

    def prepare(self, body: dict) -> dict:
        return self._request("POST", "/canvas/device/shares/prepare", body)

    def commit(self, share_id, manifest: dict) -> dict:
        return self._request("POST", f"/canvas/device/shares/{share_id}/commit", {"manifest": manifest})

    def delete_share(self, share_id) -> None:
        self._request("DELETE", f"/canvas/device/shares/{share_id}")

    def list_shares(self) -> list:
        result = self._request("GET", "/canvas/device/shares")
        return result if isinstance(result, list) else []


class ShareService:
    def __init__(self, store: Store, *, transport=None):
        self.store = store
        self.config = ShareConfig(store)
        self._transport = transport
        self._connects: dict[str, dict] = {}
        self._jobs: dict[str, dict] = {}
        self._lock = threading.RLock()
        self._hash_cache: dict[tuple, str] = {}
        self._closed = threading.Event()
        self._ensure_schema()

    # ------------------------------------------------------------- connection

    def status(self) -> dict:
        token = self.config.token()
        return {
            "connected": bool(token),
            "user": self.config.user(),
            "siteBase": self.config.web_base(),
            "apiBase": self.config.api_base(),
            "tokenPrefix": token[:12] if token else None,
        }

    def start_connect(self) -> dict:
        request_id = secrets.token_hex(16)
        verifier = _b64url(secrets.token_bytes(32))
        challenge = _b64url(hashlib.sha256(verifier.encode("ascii")).digest())
        state = {"state": "pending", "user": None, "error": None, "started_at": time.time()}
        with self._lock:
            self._connects[request_id] = state
        threading.Thread(
            target=self._poll_connect, args=(request_id, verifier), name="manju-share-connect", daemon=True
        ).start()
        authorize_url = f"{self.config.web_base()}/connect?" + urlencode({
            "request": request_id,
            "challenge": challenge,
            "name": CLIENT_NAME,
            "version": CLIENT_VERSION,
        })
        if self._transport is None:
            try:
                webbrowser.open(authorize_url)
            except Exception:
                pass
        return {"request_id": request_id, "authorize_url": authorize_url, "expires_in": 600}

    def connect_state(self, request_id: str) -> dict:
        with self._lock:
            state = self._connects.get(request_id)
            if state is None:
                raise DomainError(404, "连接请求不存在或已过期。", "share_connect_missing")
            result = dict(state)
            result["request_id"] = request_id
            result["seconds_left"] = max(0, int(CONNECT_TIMEOUT_SECONDS - (time.time() - state["started_at"])))
            return result

    def _poll_connect(self, request_id: str, verifier: str) -> None:
        api_base = self.config.api_base()
        client = ShareClient(api_base, None, self._transport)
        deadline = time.time() + CONNECT_TIMEOUT_SECONDS
        try:
            while time.time() < deadline and not self._closed.is_set():
                with self._lock:
                    state = self._connects.get(request_id)
                    if state is None or state["state"] != "pending":
                        return
                try:
                    data = client.exchange_token(request_id, verifier)
                except DomainError as error:
                    code = str(error.detail.get("code") or "")
                    upstream = str(error.detail.get("upstream_code") or "")
                    if code in {"share_not_found", "share_rate_limited"} or upstream in {
                        "CANVAS_CONNECT_REQUEST_INVALID", "CANVAS_CONNECT_RATE_LIMITED"
                    }:
                        time.sleep(CONNECT_POLL_SECONDS)
                        continue
                    self._finish_connect(request_id, "failed", error.detail.get("message"))
                    return
                except Exception:
                    time.sleep(CONNECT_POLL_SECONDS)
                    continue
                user = data.get("user") if isinstance(data.get("user"), dict) else {}
                self.config.save({
                    "api_base": api_base,
                    "web_base": self.config.web_base(),
                    "token": data.get("token"),
                    "user": user,
                    "connected_at": now(),
                })
                self._finish_connect(request_id, "approved", None, user)
                with self.store.tx():
                    self.store.emit("share.connected", {"user": user})
                return
            self._finish_connect(request_id, "expired", "授权已超时，请重新发起连接。")
        finally:
            client.close()

    def _finish_connect(self, request_id: str, state: str, error, user: dict | None = None) -> None:
        with self._lock:
            current = self._connects.get(request_id)
            if current is None:
                return
            current["state"] = state
            current["error"] = error
            current["user"] = user or current.get("user")

    def disconnect(self) -> dict:
        self.config.clear()
        return {"connected": False}

    # -------------------------------------------------------------- publishing

    def project_share(self, project_id: str) -> dict:
        self.store.project(project_id)
        row = self.store.conn.execute(
            "SELECT * FROM shares WHERE project_id = ?", (project_id,)
        ).fetchone()
        with self._lock:
            job = dict(self._jobs[project_id]) if project_id in self._jobs else None
        return {"share": dict(row) if row else None, "job": job}

    def list_all(self) -> list[dict]:
        rows = self.store.conn.execute(
            """SELECT s.*, p.name AS project_name
               FROM shares s JOIN projects p ON p.id = s.project_id
               ORDER BY s.updated_at DESC
               LIMIT 200"""
        ).fetchall()
        return [dict(row) for row in rows]

    def start_publish(self, project_id: str, payload: dict) -> dict:
        project = self.store.project(project_id)
        if not self.config.token():
            raise DomainError(409, "请先在浏览器登录亦可账号。", "share_not_connected")
        revision = payload.get("canvas_revision")
        if revision is not None and int(revision) != int(project["revision"]):
            raise DomainError(409, "画布有未保存的修改，请保存后再分享。", "share_outdated")
        with self._lock:
            existing = self._jobs.get(project_id)
            if existing and existing["state"] == "running":
                raise DomainError(409, "该画布正在分享中，请稍候。", "share_busy")
            job = {
                "job_id": secrets.token_hex(8),
                "state": "running",
                "phase": "snapshot",
                "uploaded": 0,
                "total": 0,
                "error": None,
                "url": None,
                "started_at": now(),
            }
            self._jobs[project_id] = job
        threading.Thread(
            target=self._run_publish,
            args=(project_id, dict(payload), job),
            name="manju-share-publish",
            daemon=True,
        ).start()
        return {"job_id": job["job_id"], "state": job["state"]}

    def _run_publish(self, project_id: str, payload: dict, job: dict) -> None:
        client = None
        try:
            plan = self._build_plan(project_id, payload)
            job["phase"] = "prepare"
            job["total"] = len(plan["files"])
            self._notify(project_id, job)
            client = ShareClient(self.config.api_base(), self.config.token(), self._transport)
            body = {
                "shareId": plan["share_id"],
                "projectName": plan["project"]["name"],
                "aspectRatio": plan["project"]["aspectRatio"],
                "title": plan["title"],
                "visibility": plan["visibility"],
                "quality": plan["quality"],
                "canvasRevision": plan["canvas_revision"],
                "nodeCount": plan["stats"]["nodes"],
                "edgeCount": plan["stats"]["edges"],
                "files": plan["files"],
            }
            prepared = client.prepare(body)
            if not prepared.get("shareId"):
                raise DomainError(502, "亦可没有返回分享标识，请稍后重试。", "share_bad_response")
            paths = plan["paths"]
            job["phase"] = "upload"
            uploaded = 0
            for target in prepared.get("uploads") or []:
                if target.get("skip"):
                    uploaded += 1
                    job["uploaded"] = uploaded
                    self._notify(project_id, job)
                    continue
                path = paths.get(target.get("contentHash"))
                if path is None:
                    raise DomainError(409, "本地媒体文件已变化，请重新分享。", "share_media_changed")
                self._upload(target, path)
                uploaded += 1
                job["uploaded"] = uploaded
                self._notify(project_id, job)
            job["phase"] = "commit"
            result = client.commit(prepared.get("shareId"), plan["manifest"])
            self._save_share(project_id, prepared, result, plan, payload)
            job["state"] = "done"
            job["phase"] = "done"
            job["url"] = result.get("url")
            with self.store.tx():
                self.store.emit("share.updated", {"project_id": project_id, "url": job["url"]})
        except DomainError as error:
            job["state"] = "failed"
            job["error"] = error.detail.get("message") or "分享失败"
            if error.detail.get("code") == "share_unauthorized":
                self.config.clear()
            with self.store.tx():
                self.store.emit("share.updated", {"project_id": project_id, "error": job["error"]})
        except Exception as error:  # pragma: no cover - defensive
            job["state"] = "failed"
            job["error"] = f"分享失败：{error}"
            with self.store.tx():
                self.store.emit("share.updated", {"project_id": project_id, "error": job["error"]})
        finally:
            if client is not None:
                client.close()
            self._notify(project_id, job)

    def _notify(self, project_id: str, job: dict) -> None:
        with self._lock:
            snapshot = dict(job)
        with self.store.tx():
            self.store.emit("share.progress", {"project_id": project_id, **snapshot})

    def _upload(self, target: dict, path: Path) -> None:
        headers = target.get("headers") if isinstance(target.get("headers"), dict) else {}
        last_error = ""
        client = httpx.Client(transport=self._transport, trust_env=False)
        try:
            for attempt in range(UPLOAD_ATTEMPTS):
                try:
                    with path.open("rb") as stream:
                        response = client.put(
                            target["url"], content=stream, headers=headers,
                            timeout=httpx.Timeout(1800, connect=20),
                        )
                    if response.status_code in (200, 201, 204):
                        return
                    if response.status_code in (401, 403):
                        raise DomainError(502, "对象存储拒绝了上传，请稍后重试。", "share_upload_rejected")
                    last_error = f"HTTP {response.status_code}"
                except httpx.HTTPError as error:
                    last_error = str(error)
                time.sleep(1.5 * (attempt + 1))
        finally:
            client.close()
        raise DomainError(502, f"媒体上传失败（{last_error}），请检查网络后重试。", "share_upload_failed")

    def _save_share(self, project_id: str, prepared: dict, result: dict, plan: dict, payload: dict) -> None:
        with self.store.tx():
            self.store.conn.execute(
                """INSERT INTO shares(project_id, share_id, slug, title, visibility, quality, revision,
                       node_count, edge_count, media_count, size_bytes, url, status, updated_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(project_id) DO UPDATE SET
                     share_id=excluded.share_id, slug=excluded.slug, title=excluded.title,
                     visibility=excluded.visibility, quality=excluded.quality, revision=excluded.revision,
                     node_count=excluded.node_count, edge_count=excluded.edge_count,
                     media_count=excluded.media_count, size_bytes=excluded.size_bytes,
                     url=excluded.url, status=excluded.status, updated_at=excluded.updated_at""",
                (
                    project_id,
                    prepared.get("shareId"),
                    result.get("slug"),
                    plan["title"],
                    plan["visibility"],
                    plan["quality"],
                    plan["canvas_revision"],
                    plan["stats"]["nodes"],
                    plan["stats"]["edges"],
                    plan["stats"]["media"],
                    prepared.get("totalBytes") or plan["total_bytes"],
                    result.get("url"),
                    "ACTIVE",
                    now(),
                ),
            )

    def delete_share(self, project_id: str) -> dict:
        self.store.project(project_id)
        row = self.store.conn.execute(
            "SELECT * FROM shares WHERE project_id = ?", (project_id,)
        ).fetchone()
        if row is None:
            return {"deleted": False}
        if self.config.token() and row["share_id"] is not None:
            client = ShareClient(self.config.api_base(), self.config.token(), self._transport)
            try:
                client.delete_share(row["share_id"])
            except DomainError as error:
                if error.status != 404:
                    raise
            finally:
                client.close()
        with self.store.tx():
            self.store.conn.execute("DELETE FROM shares WHERE project_id = ?", (project_id,))
        return {"deleted": True}

    # ------------------------------------------------------------------ plans

    def _ensure_schema(self) -> None:
        with self.store.tx():
            self.store.conn.execute(
                """CREATE TABLE IF NOT EXISTS shares (
                    project_id TEXT PRIMARY KEY,
                    share_id INTEGER,
                    slug TEXT,
                    title TEXT,
                    visibility TEXT,
                    quality TEXT,
                    revision INTEGER NOT NULL DEFAULT 0,
                    node_count INTEGER NOT NULL DEFAULT 0,
                    edge_count INTEGER NOT NULL DEFAULT 0,
                    media_count INTEGER NOT NULL DEFAULT 0,
                    size_bytes INTEGER NOT NULL DEFAULT 0,
                    url TEXT,
                    status TEXT NOT NULL DEFAULT 'ACTIVE',
                    updated_at TEXT NOT NULL
                )"""
            )

    def _build_plan(self, project_id: str, payload: dict) -> dict:
        snapshot = project_snapshot(self.store, project_id)
        canvas = json.loads(json.dumps(snapshot["canvas"]))
        viewport = _valid_viewport(payload.get("viewport"))
        if viewport is not None:
            canvas["viewport"] = viewport
        project = snapshot["project"]
        quality = "full" if str(payload.get("quality") or "").lower() == "full" else "preview"
        visibility = "LOGIN" if str(payload.get("visibility") or "").lower() == "login" else "LINK"
        title = str(payload.get("title") or "").strip()[:60] or (project["name"] or "未命名画布")[:60]

        history_only = self._history_only_version_ids(canvas)
        media: dict[str, dict] = {}
        files: list[dict] = []
        paths: dict[str, Path] = {}
        unique_hashes: set[str] = set()
        total_bytes = 0

        for version in snapshot["versions"]:
            version_id = version["id"]
            kind = str(version.get("mime") or "").split("/")[0]
            if kind not in {"image", "video", "audio"}:
                continue
            primary = version_id not in history_only
            variants = self._select_variants(version, kind, quality, primary)
            if not variants:
                continue
            entry = {
                "kind": kind,
                "quality": quality,
                "width": version.get("width"),
                "height": version.get("height"),
                "durationMs": int(version["duration"] * 1000) if version.get("duration") else None,
                "degraded": "THUMB" not in variants,
                "variants": {},
            }
            for role, spec in variants.items():
                entry["variants"][role.lower()] = {"hash": spec["hash"]}
                paths[spec["hash"]] = spec["path"]
                if spec["hash"] not in unique_hashes:
                    unique_hashes.add(spec["hash"])
                    total_bytes += spec["size"]
                files.append({
                    "key": version_id,
                    "role": role,
                    "contentHash": spec["hash"],
                    "variant": spec["variant"],
                    "mime": spec["mime"],
                    "size": spec["size"],
                    "width": version.get("width") if role == "VIEW" else None,
                    "height": version.get("height") if role == "VIEW" else None,
                    "durationMs": entry["durationMs"] if role == "VIEW" else None,
                    "fileName": spec["path"].name,
                })
            media[version_id] = entry

        if total_bytes > MAX_SHARE_BYTES:
            raise DomainError(
                413,
                f"分享体积约 {total_bytes / 1024**2:.0f} MB，超过 {MAX_SHARE_BYTES // 1024**2} MB 上限。请改用预览画质或拆分画布。",
                "share_too_large",
            )

        share_id = None
        row = self.store.conn.execute(
            "SELECT share_id FROM shares WHERE project_id = ?", (project_id,)
        ).fetchone()
        if row is not None:
            share_id = row["share_id"]

        stats = {"nodes": len(canvas.get("nodes") or []), "edges": len(canvas.get("edges") or []),
                 "media": len(media), "bytes": total_bytes}
        manifest = {
            "format": "manju-canvas-share",
            "version": 1,
            "project": {"name": project["name"], "aspectRatio": project.get("aspect_ratio") or "free"},
            "canvas": canvas,
            "media": media,
            "stats": {"nodes": stats["nodes"], "edges": stats["edges"], "media": stats["media"]},
        }
        return {
            "share_id": share_id,
            "project": manifest["project"],
            "title": title,
            "visibility": visibility,
            "quality": quality,
            "canvas_revision": int(project["revision"]),
            "files": files,
            "paths": paths,
            "manifest": manifest,
            "stats": stats,
            "total_bytes": total_bytes,
        }

    def _select_variants(self, version: dict, kind: str, quality: str, primary: bool) -> dict[str, dict]:
        version_id = version["id"]
        if primary:
            self._wait_for_preview(version_id)
        cache = self.store.root / "cache" / version_id
        original = self.store.blob_path(version["blob_hash"])

        def artifact(name: str) -> Path | None:
            path = cache / name
            return path if path.is_file() else None

        thumb = artifact("thumbnail.webp")
        variants: dict[str, dict] = {}
        if kind == "image":
            if primary:
                view = None
                if quality == "full" and original.is_file() and version["size"] <= MAX_ORIGINAL_IMAGE_BYTES:
                    view = self._spec("ORIGINAL", original, version["mime"])
                if view is None:
                    preview = artifact("preview.webp")
                    if preview is not None:
                        view = self._spec("PREVIEW", preview, "image/webp")
                if view is None and original.is_file():
                    view = self._spec("ORIGINAL", original, version["mime"])
                if view is None:
                    raise DomainError(409, "图片原件缺失，请先在本地修复资产。", "share_media_missing")
                variants["VIEW"] = view
                if thumb is not None:
                    variants["THUMB"] = self._spec("THUMB", thumb, "image/webp")
            elif thumb is not None:
                variants["THUMB"] = self._spec("THUMB", thumb, "image/webp")
            return variants

        if kind == "video":
            if primary:
                preview = artifact("preview.mp4")
                if preview is not None:
                    view = self._spec("PREVIEW", preview, "video/mp4")
                elif original.is_file() and version["size"] <= MAX_ORIGINAL_VIDEO_BYTES:
                    view = self._spec("ORIGINAL", original, version["mime"])
                else:
                    raise DomainError(409, "视频预览尚未生成完成，请稍后再分享。", "share_media_pending")
                variants["VIEW"] = view
                if thumb is not None:
                    variants["THUMB"] = self._spec("THUMB", thumb, "image/webp")
            elif thumb is not None:
                variants["THUMB"] = self._spec("THUMB", thumb, "image/webp")
            return variants

        preview = artifact("preview.m4a")
        if primary:
            if preview is not None:
                variants["VIEW"] = self._spec("PREVIEW", preview, "audio/mp4")
            elif original.is_file() and version["size"] <= MAX_ORIGINAL_AUDIO_BYTES:
                variants["VIEW"] = self._spec("ORIGINAL", original, version["mime"])
            else:
                raise DomainError(409, "音频预览尚未生成完成，请稍后再分享。", "share_media_pending")
        waveform = artifact("waveform.svg")
        if waveform is not None:
            variants["WAVEFORM"] = self._spec("WAVEFORM", waveform, "image/svg+xml")
        return variants

    def _spec(self, variant: str, path: Path, mime: str) -> dict:
        stat = path.stat()
        key = (str(path), stat.st_size, stat.st_mtime_ns)
        with self._lock:
            digest = self._hash_cache.get(key)
        if digest is None:
            digest = _sha256_file(path)
            with self._lock:
                self._hash_cache[key] = digest
                if len(self._hash_cache) > 4096:
                    self._hash_cache.clear()
        return {"variant": variant, "path": path, "mime": mime, "size": stat.st_size, "hash": digest}

    def _wait_for_preview(self, version_id: str) -> str:
        deadline = time.monotonic() + PREVIEW_WAIT_SECONDS
        status = "pending"
        while True:
            row = self.store.conn.execute(
                "SELECT preview_status FROM versions WHERE id = ?", (version_id,)
            ).fetchone()
            status = row[0] if row else "failed"
            if status in {"ready", "failed"} or time.monotonic() >= deadline:
                return status
            time.sleep(0.5)

    @staticmethod
    def _history_only_version_ids(canvas: dict) -> set[str]:
        primary: set[str] = set()
        history: set[str] = set()
        for node in canvas.get("nodes") or []:
            if not isinstance(node, dict):
                continue
            data = node.get("data")
            if not isinstance(data, dict):
                continue
            for key in ("asset_version_id", "previous_image_version_id"):
                value = data.get(key)
                if isinstance(value, str) and value:
                    primary.add(value)
            for entry in data.get("image_history") or []:
                if isinstance(entry, dict) and isinstance(entry.get("version_id"), str):
                    history.add(entry["version_id"])
            if any(key in data for key in ("subject", "shot", "timeline", "production_settings", "composite")):
                try:
                    primary.update(Store.node_version_ids(node, strict=False))
                except Exception:
                    pass
            draft = data.get("generation")
            if isinstance(draft, dict):
                for key in ("references", "h3_guides"):
                    for item in draft.get(key) or []:
                        if isinstance(item, dict) and isinstance(item.get("version_id"), str):
                            primary.add(item["version_id"])
                for key in ("edit_base_version_id", "mask_version_id"):
                    value = draft.get(key)
                    if isinstance(value, str) and value:
                        primary.add(value)
        return history - primary

    def close(self) -> None:
        self._closed.set()
        with self._lock:
            self._connects.clear()
            self._hash_cache.clear()
