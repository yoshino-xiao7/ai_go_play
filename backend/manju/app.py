"""Local-only HTTP interface shared by the browser and command-line client."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import subprocess
import threading
from urllib.parse import quote, urlsplit

import httpx
from fastapi import Body, FastAPI, File, Form, Header, Query, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.background import BackgroundTask

from .media import PreviewWorker, find_binary, probe_media
from .comfy import ComfyManager, scan_installations
from .generation import GenerationService
from .production import ProductionService
from .timeline import TimelineService
from .orchestration import OrchestrationService
from .production_batch import generate_shots
from .frames import render_frame
from .openai_images import PREFIX as OPENAI_PREFIX, estimate_cost
from .screenplay import get_screenplay, save_screenplay
from .workflows import WorkflowService
from .store import DomainError, Store, new_id
from .transfers import cancel_migration, export_project, import_project, migrate_storage, recover_migration_state, resume_migration, storage_status


MAX_UPLOAD_BYTES = 20 * 1024**3


def record_upload_failure(store: Store, filename: str, error: BaseException) -> None:
    if isinstance(error, DomainError):
        message = error.detail["message"]
    elif isinstance(error, asyncio.CancelledError) or error.__class__.__name__ == "ClientDisconnect":
        message = "上传连接已中断，请重新选择文件。"
    else:
        message = str(error) or "导入被中断，请重新选择文件。"
    try:
        store.record_import_failure(filename, message)
    except Exception:
        logging.getLogger(__name__).warning("Failed to persist upload failure for %s", filename, exc_info=True)


def resolve_configuration(data_dir: str | Path | None, config_file: str | Path | None) -> tuple[Path, Path]:
    explicit_root = data_dir or os.environ.get("MANJU_DATA_DIR")
    configured_file = config_file or os.environ.get("MANJU_CONFIG_FILE")
    if configured_file:
        config_path = Path(configured_file).expanduser().resolve()
    elif explicit_root:
        config_path = Path(explicit_root).expanduser().resolve() / "config.json"
    else:
        config_path = Path(os.environ.get("APPDATA", str(Path.home() / ".config"))) / "Manju" / "config.json"
    settings = {}
    if config_path.is_file():
        try:
            settings = json.loads(config_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise RuntimeError(f"无法读取存储配置 {config_path}。请修复配置后启动。") from error
    root = Path(settings.get("root") or explicit_root or ("D:/ManjuData" if os.name == "nt" else str(Path.home() / "ManjuData"))).expanduser().resolve()
    return root, config_path


async def stage_upload(store: Store, upload: UploadFile) -> tuple[Path, str, str]:
    if store.maintenance:
        raise DomainError(423, "资产库正在迁移，请等待完成。", "storage_busy")
    path = store.root / "temp" / f"{new_id()}.upload"
    filename = (upload.filename or "未命名文件").replace("\\", "/").rsplit("/", 1)[-1].strip()[:250] or "未命名文件"
    digest, size = hashlib.sha256(), 0
    try:
        with path.open("wb") as output:
            while chunk := await upload.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    raise DomainError(413, "单个文件最大支持 20 GiB。", "upload_too_large")
                digest.update(chunk)
                output.write(chunk)
            output.flush()
            os.fsync(output.fileno())
        return path, filename, digest.hexdigest()
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    finally:
        await upload.close()


def create_app(data_dir: str | Path | None = None, config_file: str | Path | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(application: FastAPI):
        root, config_path = resolve_configuration(data_dir, config_file)
        store = Store(root, config_path)
        recover_migration_state(store)
        application.state.store = store
        application.state.comfy = ComfyManager(config_path)
        application.state.comfy.start_monitor()
        application.state.workflows = WorkflowService(store, application.state.comfy)
        application.state.generations = GenerationService(store, application.state.comfy, application.state.workflows)
        application.state.production = ProductionService(store)
        application.state.timeline = TimelineService(store, application.state.production)
        application.state.orchestration = OrchestrationService(store, application.state.generations)
        application.state.migration_guard = threading.Lock()
        application.state.migration_thread = None
        worker = PreviewWorker(store)
        application.state.worker = worker
        worker.start()
        application.state.generations.start()
        application.state.production.start()
        application.state.orchestration.start()
        try:
            yield
        finally:
            application.state.orchestration.close()
            application.state.production.close()
            application.state.generations.close()
            application.state.comfy.close()
            worker.stop()
            migration_thread = application.state.migration_thread
            if not worker.thread.is_alive() and not application.state.generations.thread.is_alive() and not application.state.production.thread.is_alive() and not application.state.orchestration.thread.is_alive() and not (migration_thread and migration_thread.is_alive()):
                store.close()

    application = FastAPI(title="Manju · 本地创作工作台", version="0.1.0", lifespan=lifespan)

    @application.exception_handler(DomainError)
    async def domain_error_handler(request: Request, error: DomainError):
        return JSONResponse(status_code=error.status, content={"detail": error.detail})

    @application.exception_handler(OSError)
    async def storage_error_handler(request: Request, error: OSError):
        return JSONResponse(status_code=507 if error.errno == 28 else 500, content={"detail": {"code": "storage_error", "message": f"本地文件操作失败，请检查路径、权限和剩余空间。{error}"}})

    @application.middleware("http")
    async def local_origin_only(request: Request, call_next):
        allowed_hosts = {"127.0.0.1", "localhost", "::1"}
        if data_dir is not None:
            allowed_hosts.add("testserver")
        if request.url.hostname not in allowed_hosts:
            return JSONResponse(status_code=403, content={"detail": {"code": "host_forbidden", "message": "仅允许通过本机地址访问。"}})
        origin = request.headers.get("origin")
        if origin:
            parsed = urlsplit(origin)
            if parsed.scheme not in ("http", "https") or parsed.netloc.lower() != request.url.netloc.lower():
                return JSONResponse(status_code=403, content={"detail": {"code": "origin_forbidden", "message": "此请求的网页来源不被允许。"}})
        if request.headers.get("sec-fetch-site") == "cross-site":
            return JSONResponse(status_code=403, content={"detail": {"code": "origin_forbidden", "message": "禁止跨站访问本地资产。"}})
        uploading = request.method == "POST" and request.url.path in ("/api/assets/upload", "/api/projects/import")
        if uploading:
            try:
                size = int(request.headers.get("content-length", "0"))
            except ValueError:
                size = 0
            if size > MAX_UPLOAD_BYTES + 1024 * 1024:
                error = DomainError(413, "单个文件最大支持 20 GiB。", "upload_too_large")
                record_upload_failure(request.app.state.store, "超出限制的上传", error)
                return JSONResponse(status_code=413, content={"detail": error.detail})
        try:
            response = await call_next(request)
        except BaseException as error:
            if uploading and not getattr(request.state, "import_failure_recorded", False):
                record_upload_failure(request.app.state.store, "中断的上传", error)
            raise
        if uploading and response.status_code >= 400 and not getattr(request.state, "import_failure_recorded", False):
            record_upload_failure(request.app.state.store, "未完成的上传", RuntimeError(f"上传请求未完成（HTTP {response.status_code}），请重新选择文件。"))
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Cross-Origin-Resource-Policy"] = "same-origin"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    def get_store(request: Request) -> Store:
        return request.app.state.store

    @application.get("/api/health")
    def health(request: Request):
        store = get_store(request)
        return {"ok": True, "version": "0.1.0", "root": str(store.root), "maintenance": store.maintenance}

    @application.get("/api/comfy")
    def comfy_status(request: Request):
        return request.app.state.comfy.status()

    @application.post("/api/comfy/scan")
    def comfy_scan(body: dict = Body(default={})):
        path = body.get("path")
        if path is not None and not isinstance(path, str):
            raise DomainError(422, "扫描路径须为本机目录。", "comfy_scan_path_invalid")
        return scan_installations(path)

    @application.put("/api/comfy/settings")
    def comfy_settings(request: Request, body: dict = Body(...)):
        return request.app.state.comfy.configure(body.get("installation_path"), body.get("port", 8188))

    @application.post("/api/comfy/start", status_code=202)
    def comfy_start(request: Request):
        return request.app.state.comfy.start()

    @application.post("/api/comfy/stop", status_code=202)
    def comfy_stop(request: Request, body: dict = Body(default={})):
        force = body.get("force", False)
        if not isinstance(force, bool):
            raise DomainError(422, "force 参数须为布尔值。", "invalid_request")
        return request.app.state.comfy.stop(force)

    @application.get("/api/comfy/logs")
    def comfy_logs(request: Request, limit: int = Query(200, ge=1, le=1000)):
        return request.app.state.comfy.logs(limit)

    @application.get("/api/workflows")
    def workflows(request: Request, mode: str | None = None, include_video: bool = False, include_audio: bool = False):
        items=[] if mode in ("video","audio") else request.app.state.workflows.list(mode)
        items.extend(request.app.state.generations.openai.workflows(mode))
        if include_video and mode in (None,"video"):
            items.append(request.app.state.generations.video.library_entry())
            items.extend(adapter.status() for adapter in request.app.state.generations.video_enhancement.values())
        if include_audio and mode in (None,"audio"):
            items.append(request.app.state.generations.speech.status())
        return {"items":items}

    @application.post("/api/workflows", status_code=201)
    def create_workflow(request: Request, body: dict = Body(...)):
        return request.app.state.workflows.create(body)

    @application.post("/api/workflows/import", status_code=201)
    def import_workflow(request: Request, body: dict = Body(...)):
        return request.app.state.workflows.import_graph(body)

    @application.get("/api/workflows/{workflow_id}")
    def workflow(request: Request, workflow_id: str):
        enhancement = request.app.state.generations.video_enhancement.get(workflow_id)
        if enhancement:
            return enhancement.status()
        if workflow_id == "builtin-indextts25-local":
            speech = request.app.state.generations.speech
            return {**speech.status(), **speech.template(), "read_only": True}
        if workflow_id.startswith(OPENAI_PREFIX):
            return request.app.state.generations.openai.snapshot(workflow_id.removeprefix(OPENAI_PREFIX))
        return request.app.state.workflows.get(workflow_id)

    @application.put("/api/workflows/{workflow_id}")
    def update_workflow(request: Request, workflow_id: str, body: dict = Body(...)):
        if workflow_id == "builtin-indextts25-local":
            return request.app.state.generations.speech.update(body)
        return request.app.state.workflows.update(workflow_id, body)

    @application.delete("/api/workflows/{workflow_id}")
    def delete_workflow(request: Request, workflow_id: str):
        return request.app.state.workflows.delete(workflow_id)

    @application.post("/api/workflows/{workflow_id}/duplicate", status_code=201)
    def duplicate_workflow(request: Request, workflow_id: str):
        return request.app.state.workflows.duplicate(workflow_id)

    @application.post("/api/workflows/{workflow_id}/validate")
    def validate_workflow(request: Request, workflow_id: str):
        enhancement = request.app.state.generations.video_enhancement.get(workflow_id)
        if enhancement:
            status = enhancement.status()
            return {"valid": status["ready"], "online": status["ready"],
                    "errors": [{"code": "video_enhance_not_ready", "message": error} for error in status["errors"]],
                    "warnings": [], "output_nodes": ["enhance"]}
        if workflow_id == "builtin-indextts25-local":
            status = request.app.state.generations.speech.status()
            return {"valid": status["ready"], "online": status["ready"], "errors": [{"code":"speech_unavailable","message":e} for e in status["errors"]], "warnings": [], "output_nodes": ["save"]}
        if workflow_id.startswith(OPENAI_PREFIX):
            report = request.app.state.generations.openai.catalog(refresh=True)
            return {"valid": report["ready"], "online": report["ready"], "checked_at": report["checked_at"],
                    "errors": [] if report["ready"] else [{"code": "openai_unavailable", "message": report["error"] or "当前项目没有已接入的图片模型。"}],
                    "warnings": [], "output_nodes": ["openai"]}
        return request.app.state.workflows.validate(workflow_id, online=True)

    @application.get("/api/openai/images")
    def openai_image_catalog(request: Request, refresh: bool = False):
        return request.app.state.generations.openai.catalog(refresh=refresh)

    @application.post("/api/openai/images/estimate")
    def openai_image_estimate(body: dict = Body(...)):
        return estimate_cost(body)

    @application.get("/api/video/settings")
    def video_settings():
        return application.state.generations.video.status()

    @application.put("/api/video/settings")
    def update_video_settings(payload: dict = Body(...)):
        return application.state.generations.video.update(payload)

    @application.get("/api/video/workflow")
    def video_workflow(mode: str = "text", engine: str = "native"):
        return application.state.generations.video.template(mode,engine)

    @application.get("/api/voice-design/settings")
    def voice_design_settings():
        return application.state.generations.voice_design.status()

    @application.get("/api/audio/settings")
    def audio_settings():
        return application.state.generations.speech.status()

    @application.get("/api/audio/workflow")
    def audio_workflow():
        return application.state.generations.speech.template()

    @application.put("/api/audio/settings")
    def update_audio_settings(payload: dict = Body(...)):
        return application.state.generations.speech.update(payload)

    @application.post("/api/generations", status_code=202)
    def create_generation(request: Request, body: dict = Body(...), x_request_id: str | None = Header(None)):
        return request.app.state.generations.create(body, x_request_id)

    @application.get("/api/generations")
    def generations(request: Request, project_id: str | None = None, limit: int = Query(100, ge=1, le=500)):
        return {"items": request.app.state.generations.list(project_id, limit)}

    @application.get("/api/generations/{job_id}")
    def generation(request: Request, job_id: str):
        return request.app.state.generations.get(job_id)

    @application.post("/api/generations/{job_id}/cancel")
    def cancel_generation(request: Request, job_id: str, body: dict = Body(default={})):
        interrupt = body.get("interrupt_running", False)
        if not isinstance(interrupt, bool):
            raise DomainError(422, "interrupt_running 参数须为布尔值。", "invalid_request")
        try:
            return request.app.state.generations.cancel(job_id, interrupt)
        except httpx.HTTPError as error:
            raise DomainError(503, "ComfyUI 暂时无法连接，请恢复连接后再取消。", "comfy_connection_error") from error

    @application.post("/api/generations/{job_id}/retry", status_code=202)
    def retry_generation(request: Request, job_id: str, body: dict = Body(default={}), x_request_id: str | None = Header(None)):
        if x_request_id and body.get("request_id") and x_request_id != body["request_id"]:
            raise DomainError(422, "请求头与请求体的 request_id 不一致。", "invalid_request_id")
        return request.app.state.generations.retry(job_id, x_request_id or body.get("request_id"))

    @application.get("/api/projects")
    def projects(request: Request, trash: bool = False, search: str = ""):
        return get_store(request).projects(trash, search)

    @application.get('/api/projects/{project_id}/production')
    def production_document(request: Request, project_id: str):
        return request.app.state.production.get(project_id)

    @application.get('/api/lipsync/settings')
    def lipsync_settings(request: Request):
        return request.app.state.generations.lipsync.status()

    @application.get('/api/projects/{project_id}/timeline')
    def timeline_document(request: Request, project_id: str):
        return request.app.state.timeline.get(project_id)

    @application.put('/api/projects/{project_id}/timeline')
    def save_timeline(request: Request, project_id: str, body: dict = Body(...)):
        return request.app.state.timeline.save(project_id, body)

    @application.post('/api/projects/{project_id}/timeline/import-production')
    def import_production_timeline(request: Request, project_id: str, body: dict = Body(...)):
        return request.app.state.timeline.import_production(project_id, body)

    @application.post('/api/projects/{project_id}/timeline/render', status_code=202)
    def render_timeline(request: Request, project_id: str, body: dict = Body(default={})):
        return request.app.state.timeline.render(project_id, body)

    @application.post('/api/projects/{project_id}/canvas-runs/plan')
    def plan_canvas_run(request: Request, project_id: str, body: dict = Body(default={})):
        return request.app.state.orchestration.plan(project_id, body)

    @application.post('/api/projects/{project_id}/canvas-runs', status_code=202)
    def create_canvas_run(request: Request, project_id: str, body: dict = Body(default={})):
        return request.app.state.orchestration.create(project_id, body)

    @application.get('/api/projects/{project_id}/canvas-runs')
    def list_canvas_runs(request: Request, project_id: str):
        return {'items': request.app.state.orchestration.list(project_id)}

    @application.get('/api/canvas-runs/{run_id}')
    def canvas_run(request: Request, run_id: str):
        return request.app.state.orchestration.get(run_id)

    @application.post('/api/canvas-runs/{run_id}/retry', status_code=202)
    def retry_canvas_run(request: Request, run_id: str):
        return request.app.state.orchestration.retry(run_id)

    @application.post('/api/canvas-runs/{run_id}/cancel', status_code=202)
    def cancel_canvas_run(request: Request, run_id: str):
        return request.app.state.orchestration.cancel(run_id)

    @application.post('/api/projects/{project_id}/frames/{frame_id}/render-image', status_code=201)
    def render_canvas_frame(request: Request, project_id: str, frame_id: str, body: dict = Body(default={})):
        return render_frame(get_store(request), project_id, frame_id, body)

    @application.put('/api/projects/{project_id}/production')
    def save_production(request: Request, project_id: str, body: dict = Body(...)):
        return request.app.state.production.save(project_id, body)

    @application.post('/api/projects/{project_id}/production/render', status_code=202)
    def render_production(request: Request, project_id: str, body: dict = Body(default={})):
        return request.app.state.production.render(project_id, body)

    @application.post('/api/projects/{project_id}/production/generate', status_code=202)
    def generate_production(request: Request, project_id: str, body: dict = Body(default={})):
        return generate_shots(get_store(request), request.app.state.generations, request.app.state.production, project_id, body)

    @application.get('/api/production/renders/{job_id}')
    def production_render(request: Request, job_id: str):
        return request.app.state.production.get_render(job_id)

    @application.post('/api/production/renders/{job_id}/retry', status_code=202)
    def retry_production_render(request: Request, job_id: str):
        return request.app.state.production.retry_render(job_id)

    @application.get('/api/projects/{project_id}/production/subtitles')
    def production_subtitles(request: Request, project_id: str):
        content = request.app.state.production.subtitle(project_id)
        return Response(content, media_type='application/x-subrip; charset=utf-8', headers={'Content-Disposition': f'attachment; filename="{project_id}.srt"'})

    @application.get('/api/projects/{project_id}/production/handoff')
    def production_handoff(request: Request, project_id: str):
        path = request.app.state.production.handoff(project_id)
        return FileResponse(path, filename=f'{project_id}-editing.zip', media_type='application/zip', background=BackgroundTask(path.unlink, missing_ok=True))

    @application.post("/api/projects", status_code=201)
    def create_project(request: Request, body: dict = Body(...)):
        return get_store(request).create_project(body.get("name", "未命名项目"), body.get("aspect_ratio", "free"))

    @application.post("/api/projects/import", status_code=201)
    async def import_archive(request: Request, file: UploadFile = File(...)):
        store = get_store(request)
        path = None
        try:
            path, _, _ = await stage_upload(store, file)
            return await run_in_threadpool(import_project, store, path)
        except BaseException as error:
            request.state.import_failure_recorded = True
            record_upload_failure(store, file.filename or "项目包", error)
            raise
        finally:
            if path:
                path.unlink(missing_ok=True)

    @application.get("/api/projects/{project_id}")
    def project(request: Request, project_id: str):
        return get_store(request).project(project_id)

    @application.patch("/api/projects/{project_id}")
    def update_project(request: Request, project_id: str, body: dict = Body(...)):
        return get_store(request).update_project(project_id, body)

    @application.delete("/api/projects/{project_id}")
    def trash_project(request: Request, project_id: str):
        return get_store(request).trash_project(project_id)

    @application.post("/api/projects/{project_id}/restore")
    def restore_project(request: Request, project_id: str):
        return get_store(request).trash_project(project_id, restore=True)

    @application.delete("/api/projects/{project_id}/permanent")
    def purge_project(request: Request, project_id: str):
        return get_store(request).purge_project(project_id)

    @application.post("/api/projects/{project_id}/duplicate", status_code=201)
    def duplicate_project(request: Request, project_id: str):
        return get_store(request).duplicate_project(project_id)

    @application.get("/api/projects/{project_id}/canvas")
    def canvas(request: Request, project_id: str):
        return get_store(request).canvas(project_id)

    @application.put("/api/projects/{project_id}/canvas")
    def update_canvas(request: Request, project_id: str, body: dict = Body(...)):
        return get_store(request).save_canvas(project_id, body)

    @application.get("/api/projects/{project_id}/screenplay")
    def screenplay(request: Request, project_id: str):
        return get_screenplay(get_store(request), project_id)

    @application.put("/api/projects/{project_id}/screenplay")
    def update_screenplay(request: Request, project_id: str, body: dict = Body(...)):
        return save_screenplay(get_store(request), project_id, body)

    @application.post("/api/projects/{project_id}/assets")
    def link_asset(request: Request, project_id: str, body: dict = Body(...)):
        return get_store(request).link_asset(project_id, body.get("asset_id", ""))

    @application.delete("/api/projects/{project_id}/assets/{asset_id}")
    def unlink_asset(request: Request, project_id: str, asset_id: str, remove_nodes: bool = False):
        return get_store(request).unlink_asset(project_id, asset_id, remove_nodes)

    @application.get("/api/projects/{project_id}/export")
    def export_archive(request: Request, project_id: str):
        store = get_store(request)
        path = export_project(store, project_id)
        name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", store.project(project_id)["name"])
        return FileResponse(path, media_type="application/zip", filename=name + ".manju", background=BackgroundTask(path.unlink, missing_ok=True))

    @application.get("/api/subjects")
    def subjects(request: Request, search: str = "", offset: int = Query(0, ge=0), limit: int = Query(60, ge=1, le=500), kind: str | None = None):
        return get_store(request).subjects(search, offset, limit, kind)

    @application.post("/api/subjects", status_code=201)
    def create_subject(request: Request, body: dict = Body(...), x_request_id: str | None = Header(None)):
        return get_store(request).create_subject(body, x_request_id)

    @application.get("/api/subjects/{subject_id}")
    def subject(request: Request, subject_id: str):
        return get_store(request).subject(subject_id)

    @application.patch("/api/subjects/{subject_id}")
    def update_subject(request: Request, subject_id: str, body: dict = Body(...)):
        return get_store(request).update_subject(subject_id, body)

    @application.delete("/api/subjects/{subject_id}")
    def delete_subject(request: Request, subject_id: str):
        return get_store(request).delete_subject(subject_id)

    @application.get("/api/assets")
    def assets(request: Request, search: str = "", type: str = "", tag: str = "", source: str = "", project_id: str | None = None, trash: bool = False, offset: int = Query(0, ge=0), limit: int = Query(60, ge=1, le=500)):
        return get_store(request).assets(search, type, tag, source, project_id, trash, offset, limit)

    @application.post("/api/assets/upload", status_code=201)
    async def upload_asset(request: Request, file: UploadFile = File(...), project_id: str | None = Form(None), asset_id: str | None = Form(None), x_request_id: str | None = Header(None)):
        store = get_store(request)
        path = None
        try:
            path, filename, digest = await stage_upload(store, file)
            metadata = await run_in_threadpool(probe_media, path, filename)
            return await run_in_threadpool(store.ingest, path, filename, metadata, digest, project_id, asset_id, x_request_id)
        except BaseException as error:
            request.state.import_failure_recorded = True
            record_upload_failure(store, file.filename or "未命名文件", error)
            raise
        finally:
            if path:
                path.unlink(missing_ok=True)

    @application.get("/api/assets/{asset_id}")
    def asset(request: Request, asset_id: str):
        return get_store(request).asset(asset_id)

    @application.patch("/api/assets/{asset_id}")
    def update_asset(request: Request, asset_id: str, body: dict = Body(...)):
        return get_store(request).update_asset(asset_id, body)

    @application.delete("/api/assets/{asset_id}")
    def trash_asset(request: Request, asset_id: str):
        return get_store(request).trash_asset(asset_id)

    @application.post("/api/assets/{asset_id}/restore")
    def restore_asset(request: Request, asset_id: str):
        return get_store(request).trash_asset(asset_id, restore=True)

    @application.delete("/api/assets/{asset_id}/permanent")
    def purge_asset(request: Request, asset_id: str):
        store = get_store(request)
        with store.media_lock:
            return store.purge_asset(asset_id)

    @application.post("/api/assets/{asset_id}/repair")
    async def repair_asset(request: Request, asset_id: str, file: UploadFile = File(...), version_id: str | None = Form(None)):
        store = get_store(request)
        path, _, digest = await stage_upload(store, file)
        try:
            version_id = version_id or store.asset(asset_id, details=False)["current_version_id"]
            return await run_in_threadpool(store.repair, asset_id, version_id, path, digest)
        finally:
            path.unlink(missing_ok=True)

    @application.post("/api/assets/{asset_id}/reveal")
    def reveal_asset(request: Request, asset_id: str, body: dict = Body(default={})):
        store = get_store(request)
        asset = store.asset(asset_id, details=False)
        version = store.version(body.get("version_id") or asset["current_version_id"])
        if version["asset_id"] != asset_id:
            raise DomainError(422, "版本属于其他资产。", "version_mismatch")
        path = Path(version["path"])
        if os.name == "nt":
            subprocess.Popen(["explorer.exe", "/select,", str(path)], creationflags=subprocess.CREATE_NO_WINDOW)
        return {"path": str(path), "exists": path.is_file()}

    @application.get("/api/versions/{version_id}")
    def version_details(request: Request, version_id: str):
        store = get_store(request)
        version = store.version(version_id)
        return {"version": version, "asset": store.asset(version["asset_id"])}

    @application.api_route("/api/media/{version_id}", methods=["GET", "HEAD"])
    def media(request: Request, version_id: str, variant: str = "original", download: bool = False):
        store = get_store(request)
        version = store.version(version_id)
        path, mime, filename = Path(version["path"]), version["mime"], version["filename"]
        cache = store.root / "cache" / version_id
        if variant == "thumbnail":
            if mime.startswith("audio/"):
                path, mime = cache / "waveform.svg", "image/svg+xml"
            else:
                path, mime = cache / "thumbnail.webp", "image/webp"
                if not path.is_file() and version["mime"].startswith("image/"):
                    path, mime = Path(version["path"]), version["mime"]
        elif variant == "preview":
            extension, mime = ("webp", "image/webp") if mime.startswith("image/") else (("mp4", "video/mp4") if mime.startswith("video/") else ("m4a", "audio/mp4"))
            path = cache / f"preview.{extension}"
            filename = Path(filename).stem + "." + extension
            if not path.is_file():
                path, mime, filename = Path(version["path"]), version["mime"], version["filename"]
        elif variant == "waveform":
            path, mime = cache / "waveform.svg", "image/svg+xml"
        elif variant != "original":
            raise DomainError(422, "未知媒体变体。", "invalid_media_variant")
        if not path.is_file():
            raise DomainError(404, "媒体文件缺失或预览尚未完成。", "media_unavailable", preview_status=version["preview_status"])
        size = path.stat().st_size
        headers = {"Accept-Ranges": "bytes", "Cache-Control": "private, max-age=60", "ETag": f'"{version["hash"]}-{variant}-{path.stat().st_mtime_ns}"'}
        if download:
            headers["Content-Disposition"] = "attachment; filename*=UTF-8''" + quote(filename)
        range_header = request.headers.get("range")
        if request.headers.get("if-range") and request.headers["if-range"] != headers["ETag"]:
            range_header = None
        if not range_header:
            return FileResponse(path, media_type=mime, headers=headers, filename=filename if download else None)
        match = re.fullmatch(r"bytes=(\d*)-(\d*)", range_header.strip())
        if not match or (not match.group(1) and not match.group(2)):
            return Response(status_code=416, headers={"Content-Range": f"bytes */{size}"})
        start_text, end_text = match.groups()
        if start_text:
            start = int(start_text)
            end = min(int(end_text), size - 1) if end_text else size - 1
        else:
            suffix = int(end_text)
            start, end = max(0, size - suffix), size - 1
        if start >= size or end < start:
            return Response(status_code=416, headers={"Content-Range": f"bytes */{size}"})
        headers.update({"Content-Range": f"bytes {start}-{end}/{size}", "Content-Length": str(end - start + 1)})
        if request.method == "HEAD":
            return Response(status_code=206, headers=headers, media_type=mime)

        def chunks():
            with path.open("rb") as stream:
                stream.seek(start)
                remaining = end - start + 1
                while remaining:
                    chunk = stream.read(min(1024 * 1024, remaining))
                    if not chunk:
                        break
                    remaining -= len(chunk)
                    yield chunk
        return StreamingResponse(chunks(), status_code=206, headers=headers, media_type=mime)

    @application.get("/api/tasks")
    def tasks(request: Request):
        return get_store(request).tasks()

    @application.post("/api/tasks/{task_id}/retry")
    def retry_task(request: Request, task_id: str):
        find_binary.cache_clear()
        return get_store(request).retry_task(task_id)

    @application.get("/api/events")
    async def events(request: Request, after: int | None = Query(None, ge=0)):
        try:
            last_event_id = request.headers.get("last-event-id")
            previous_cursor = int(last_event_id) if last_event_id is not None else None
        except ValueError:
            previous_cursor = None
        cursors = [value for value in (after, previous_cursor) if value is not None and value >= 0]
        cursor = max(cursors) if cursors else await run_in_threadpool(get_store(request).event_cursor)

        async def stream():
            nonlocal cursor
            heartbeat = 0
            while not await request.is_disconnected():
                records = await run_in_threadpool(get_store(request).events, cursor)
                for event in records:
                    cursor = event["id"]
                    yield f"id: {cursor}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
                heartbeat += 1
                if heartbeat >= 15:
                    yield ": keepalive\n\n"
                    heartbeat = 0
                await asyncio.sleep(1)
        return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @application.get("/api/settings/storage")
    def storage(request: Request):
        return storage_status(get_store(request))

    def start_migration(request: Request, operation, target: str) -> dict:
        guard = request.app.state.migration_guard
        if not guard.acquire(blocking=False):
            raise DomainError(409, "迁移正在执行，请等待完成。", "migration_running")
        store = get_store(request)
        store.migration_activity = {"status": "pending", "target": target, "progress": 0}

        def execute():
            try:
                operation()
                store.migration_activity = None
            except Exception as error:
                store.migration_activity = {"status": "failed", "target": target, "progress": 0, "error": str(error)}
            finally:
                guard.release()
        thread = threading.Thread(target=execute, name="manju-migration", daemon=True)
        request.app.state.migration_thread = thread
        thread.start()
        return {"root": str(store.root), "migration": {"status": "pending", "target": target, "progress": 0}}

    @application.post("/api/settings/storage/migrate", status_code=202)
    def migrate(request: Request, body: dict = Body(...)):
        target = body.get("target")
        if not isinstance(target, str) or not target.strip():
            raise DomainError(422, "请选择新的本地存储目录。", "invalid_target")
        store = get_store(request)
        destination = Path(target).expanduser().resolve()
        source = store.root.resolve()
        if destination == source or destination.is_relative_to(source) or source.is_relative_to(destination):
            raise DomainError(422, "新目录须与当前资产库互相独立。", "invalid_migration_target")
        if destination.exists() and (not destination.is_dir() or any(destination.iterdir())):
            raise DomainError(409, "请选择空目录进行迁移。", "migration_target_not_empty")
        if store.maintenance:
            raise DomainError(409, "已有迁移任务，请继续或取消。", "migration_pending")
        return start_migration(request, lambda: migrate_storage(store, target), target)

    @application.post("/api/settings/storage/migration/resume", status_code=202)
    def resume(request: Request):
        store = get_store(request)
        status = storage_status(store)
        migration = status.get("migration") or {}
        if migration.get("state") not in ("copying", "failed", "switching"):
            raise DomainError(409, "没有可以继续的迁移任务。", "migration_not_pending")
        return start_migration(request, lambda: resume_migration(store), migration["target"])

    @application.post("/api/settings/storage/migration/cancel")
    def cancel(request: Request):
        if request.app.state.migration_guard.locked():
            raise DomainError(409, "迁移正在执行，完成或失败后可以操作。", "migration_running")
        store = get_store(request)
        cancel_migration(store)
        store.migration_activity = None
        return storage_status(store)

    distribution = Path(__file__).resolve().parents[2] / "frontend" / "dist"
    if distribution.is_dir():
        application.mount("/", StaticFiles(directory=distribution, html=True), name="frontend")
    else:
        @application.get("/", response_class=HTMLResponse)
        def development_page():
            return '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>Manju</title><body><h1>Manju 本地服务已启动</h1><p>网页资源尚未构建，请运行 npm --prefix frontend run build，然后重启服务。</p></body></html>'
    return application


app = create_app()
