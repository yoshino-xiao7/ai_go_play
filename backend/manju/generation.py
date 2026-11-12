"""Durable image/video jobs and immutable ComfyUI provenance."""
from __future__ import annotations

import copy
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import logging
import math
from pathlib import Path
import secrets
import threading
import uuid

import httpx
from PIL import Image, ImageOps

from .media import probe_media, find_binary, run_process
from .video import H3Adapter, normalize_video
from .video_inputs import frame_count, guide_file_key, validate_guide
from .camera_motion import linked_camera_motion
from .speech import SpeechAdapter, normalize_speech
from .voice_design import VoiceDesignAdapter, normalize_voice_design, PROFILE_ID as VOICE_DESIGN_PROFILE
from .lipsync import LipSyncAdapter, normalize_lipsync, PROFILE_ID as LIPSYNC_PROFILE
from .video_enhance import PROFILES as ENHANCEMENT_PROFILES, VideoEnhanceAdapter, normalize_enhancement
from .store import DomainError, encode, fingerprint, new_id, now
from .reference_contract import normalize_references, compile_prompt
from .generation_progress import GenerationProgress
from .openai_images import OpenAIImages, PREFIX as OPENAI_PREFIX, estimate_cost, usage_cost


ACTIVE_STATUSES = ("pending", "submitting", "queued", "running", "collecting", "unknown")
TERMINAL_STATUSES = ("succeeded", "failed", "cancelled")
MAX_OUTPUT_BYTES = 256 * 1024 * 1024
SCHEMA = """
CREATE TABLE IF NOT EXISTS generation_jobs (
 id TEXT PRIMARY KEY, project_id TEXT NOT NULL, source_node_id TEXT,
 status TEXT NOT NULL, request_id TEXT NOT NULL UNIQUE, request_hash TEXT NOT NULL,
 request_json TEXT NOT NULL, workflow_json TEXT NOT NULL, mapped_graph_json TEXT,
 prompt_id TEXT, backend_url TEXT NOT NULL, outputs_json TEXT NOT NULL DEFAULT '[]',
 error_json TEXT, logs_json TEXT NOT NULL DEFAULT '[]', progress REAL NOT NULL DEFAULT 0,
 message TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
 parent_job_id TEXT, submission_started_at TEXT, cancel_requested INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS generation_inputs (
 job_id TEXT NOT NULL REFERENCES generation_jobs(id) ON DELETE CASCADE,
 version_id TEXT NOT NULL, PRIMARY KEY(job_id, version_id)
);
CREATE INDEX IF NOT EXISTS idx_generations_project ON generation_jobs(project_id, created_at);
CREATE INDEX IF NOT EXISTS idx_generations_status ON generation_jobs(status);
CREATE INDEX IF NOT EXISTS idx_generation_inputs_version ON generation_inputs(version_id);
"""


class GenerationService:
    def __init__(self, store, comfy, workflows, *, transport=None, openai_transport=None, openai_key_loader=None):
        self.store, self.comfy, self.workflows = store, comfy, workflows
        self.video = H3Adapter(store, workflows)
        self.speech = SpeechAdapter(store, workflows)
        self.voice_design = VoiceDesignAdapter(self.video)
        self.lipsync = LipSyncAdapter(store, workflows)
        self.video_enhancement = {key: VideoEnhanceAdapter(store, workflows, key) for key in ENHANCEMENT_PROFILES}
        self.openai = OpenAIImages(store, transport=openai_transport, **({"key_loader": openai_key_loader} if openai_key_loader else {}))
        self.external_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="manju-openai")
        self.external_jobs = {}
        self.telemetry = GenerationProgress(enabled=transport is None)
        self.client = httpx.Client(timeout=httpx.Timeout(15, connect=3), trust_env=False, transport=transport)
        self.operation_lock = threading.RLock()
        self.stop_event = threading.Event()
        self.poll_cursor = 0
        self.thread = threading.Thread(target=self.run, name="manju-generations", daemon=True)
        with store.lock:
            store.conn.executescript(SCHEMA)
            store.conn.commit()

    def start(self):
        self.thread.start()

    def close(self):
        self.stop_event.set()
        if self.thread.is_alive():
            self.thread.join(timeout=20)
        if not self.thread.is_alive():
            self.client.close()
        self.external_executor.shutdown(wait=True, cancel_futures=True)
        self.openai.close()
        self.telemetry.close()

    @staticmethod
    def _decode(row):
        job = dict(row)
        for column, key in (("request_json", "request"), ("workflow_json", "workflow_snapshot"), ("mapped_graph_json", "mapped_graph"), ("outputs_json", "outputs"), ("error_json", "error"), ("logs_json", "logs")):
            value = job.pop(column)
            job[key] = json.loads(value) if value is not None else None
        job["prompt"] = job["request"]["prompt"]
        job["workflow_id"] = job["request"]["workflow_id"]
        job["cancel_requested"] = bool(job["cancel_requested"])
        job["can_retry"] = job["status"] in ("failed", "cancelled")
        job["can_cancel"] = job["status"] in ACTIVE_STATUSES and job["status"] != "collecting"
        if job["request"].get("provider") == "openai":
            job["can_cancel"] = job["status"] == "unknown" or (job["status"] == "pending" and not job["submission_started_at"])
        return job

    def get(self, job_id):
        with self.store.lock:
            row = self.store.conn.execute("SELECT * FROM generation_jobs WHERE id=?", (job_id,)).fetchone()
            if row is None:
                raise DomainError(404, "生成任务不存在。", "generation_not_found")
            return self._with_progress(self._decode(row))

    def _with_progress(self, job):
        job["execution_progress"] = self.telemetry.snapshot(job["id"]) if job["status"] in ACTIVE_STATUSES else None
        # A node's sampling fraction is not the fraction of the whole workflow.
        if job["status"] in ACTIVE_STATUSES:
            job["progress"] = None
        return job

    def list(self, project_id=None, limit=100):
        with self.store.lock:
            if project_id:
                rows = self.store.conn.execute("SELECT * FROM generation_jobs WHERE project_id=? ORDER BY created_at DESC LIMIT ?", (project_id, limit)).fetchall()
            else:
                rows = self.store.conn.execute("SELECT * FROM generation_jobs ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
            jobs = [self._with_progress(self._decode(row)) for row in rows]
        for job in jobs:
            for key in ("mapped_graph", "workflow_snapshot", "logs"):
                job.pop(key, None)
        return jobs

    def audio_adapter(self, request):
        return self.voice_design if request.get("workflow_id") == VOICE_DESIGN_PROFILE else self.speech

    def video_adapter(self, request):
        workflow_id = request.get("workflow_id")
        if workflow_id == LIPSYNC_PROFILE:
            return self.lipsync
        return self.video_enhancement.get(workflow_id, self.video)

    def create(self, payload, request_id=None, *, workflow_snapshot=None, parent_job_id=None, recover_local_response=False):
        request = self._validate_request(payload)
        video = request.get("kind") == "video"
        video_adapter = self.video_adapter(request)
        speech = request.get("kind") == "audio"
        audio_adapter = self.audio_adapter(request)
        external = request.get("provider") == "openai"
        key = request_id or payload.get("request_id") or new_id()
        if not isinstance(key, str) or not key.strip() or len(key) > 200:
            raise DomainError(422, "request_id 须为 1 至 200 个字符。", "invalid_request_id")
        if request_id and payload.get("request_id") and request_id != payload["request_id"]:
            raise DomainError(422, "请求头与请求体的 request_id 不一致。", "invalid_request_id")
        request_hash = fingerprint(request)
        with self.store.tx():
            existing = self.store.conn.execute("SELECT * FROM generation_jobs WHERE request_id=?", (key,)).fetchone()
            if existing:
                if existing["request_hash"] != request_hash:
                    raise DomainError(409, "相同请求标识已用于其他生成参数。", "idempotency_conflict")
                return self._decode(existing)
            self.store.project(request["project_id"], include_deleted=False)
            canvas = self.store.canvas(request["project_id"])
            nodes = {node["id"]: node for node in canvas["nodes"]}
            source = request.get("source_node_id")
            if source and source not in nodes:
                raise DomainError(422, "生成源卡片已移除，请先保存当前画布。", "generation_source_missing")
            if source and not self._is_media_card(nodes[source], request.get("kind", "image")):
                raise DomainError(422, "生成结果须写入对应类型的媒体卡片。", "generation_source_type")
            if source:
                active = self.store.conn.execute("SELECT id,status FROM generation_jobs WHERE project_id=? AND source_node_id=? AND status IN ('pending','submitting','queued','running','collecting','unknown') LIMIT 1", (request['project_id'], source)).fetchone()
                if active:
                    raise DomainError(409, "此卡片已有未结束任务，请等待完成或核对后结束跟踪。", "generation_source_busy", job_id=active['id'], job_status=active['status'])
            if speech:
                audio_adapter.bind_subject(request, nodes)
            if external:
                if not recover_local_response:
                    request.update(self.openai.validate_request(request))
                request["cost_estimate"] = estimate_cost(request)
            workflow = copy.deepcopy(workflow_snapshot or (self.openai.snapshot(request["workflow_id"].removeprefix(OPENAI_PREFIX)) if external else video_adapter.snapshot(request.get("video_options")) if video else audio_adapter.snapshot() if speech else self.workflows.get(request["workflow_id"])))
            if video and video_adapter is self.video:
                defaults=workflow.get("defaults",{})
                # Apply saved defaults after the idempotency check. A retry keeps
                # its resolved request and snapshot, even if global settings change.
                request=self._validate_request({**payload,
                    "duration":payload.get("duration",defaults.get("duration",4)),
                    "audio":payload.get("audio",defaults.get("audio",True)),
                    "parameters":{**{k:v for k,v in defaults.items() if k not in ("duration","audio")},**payload.get("parameters",{})}})
                if source and parent_job_id is None and "camera_motion" not in request:
                    motion = linked_camera_motion(nodes, canvas["edges"], source)
                    if motion is not None:
                        request["camera_motion"] = motion
            report = {"valid":True} if video or speech or external else self.workflows.validate(workflow, online=False)
            if speech:
                audio_adapter.configure(request, payload, workflow)
            if not report["valid"]:
                raise DomainError(422, "工作流配置尚未通过验证。", "workflow_invalid", validation=report)
            request.setdefault("negative_prompt", workflow.get("defaults", {}).get("negative_prompt", ""))
            references = request["references"]
            capabilities = workflow.get("capabilities", {})
            minimum, maximum = capabilities.get("min_images", 0), capabilities.get("max_images", 0)
            if not minimum <= len(references) <= maximum:
                raise DomainError(422, f"此工作流需要 {minimum} 至 {maximum} 份输入素材。", "generation_reference_count")
            request["compiled_prompt"] = video_adapter.compile_prompt(request) if video else request["compiled_prompt"] if speech else compile_prompt(request, workflow)
            mask_id = request.get("mask_version_id")
            if capabilities.get("requires_mask") and not mask_id:
                raise DomainError(422, "此工作流需要蒙版图片。", "generation_mask_required")
            if mask_id and not capabilities.get("supports_mask"):
                raise DomainError(422, "此工作流未绑定蒙版输入。", "generation_mask_unsupported")
            versions = {}
            for reference in references:
                version = self.video.input_version(reference["version_id"]) if video else audio_adapter.input_version(reference["version_id"]) if speech else self._input_version(reference["version_id"])
                node_id = reference.get("node_id")
                # A node is provenance, not ownership of an immutable image version.
                versions[version["id"]] = version
                reference["snapshot"] = self._version_snapshot(version)
            guides = request.get("h3_guides", [])
            if guides and not workflow.get("h3_guides_ready"):
                raise DomainError(422, "ComfyUI 缺少 H3 定帧引导节点。", "video_guide_unavailable")
            for guide in guides:
                version = self.video.input_version(guide["version_id"])
                validate_guide(guide, version, frame_count(request))
                versions[version["id"]] = version
                guide["snapshot"] = self._version_snapshot(version)
            if mask_id:
                mask = self._input_version(mask_id)
                if not references:
                    raise DomainError(422, "蒙版需要对应的底图。", "generation_mask_without_image")
                base = versions[references[0]["version_id"]]
                if (mask["width"], mask["height"]) != (base["width"], base["height"]):
                    raise DomainError(422, "蒙版尺寸须与第一张输入图一致。", "generation_mask_dimensions")
                versions[mask_id] = mask
                request["mask_snapshot"] = self._version_snapshot(mask)
            if workflow.get("bindings", {}).get("seed"):
                request["parameters"].setdefault("seed", workflow.get("defaults", {}).get("seed", -1))
            if request["parameters"].get("seed") == -1:
                request["parameters"]["seed"] = secrets.randbits(31)
            timestamp, job_id = now(), new_id()
            self.store.conn.execute("INSERT INTO generation_jobs(id,project_id,source_node_id,status,request_id,request_hash,request_json,workflow_json,backend_url,created_at,updated_at,parent_job_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", (job_id, request["project_id"], source, "pending", key, request_hash, encode(request), encode(workflow), "https://api.openai.com/v1" if external else f"http://127.0.0.1:{self.comfy.port}", timestamp, timestamp, parent_job_id))
            for version in versions.values():
                self.store.conn.execute("INSERT INTO generation_inputs VALUES(?,?)", (job_id, version["id"]))
                self.store._link_asset(request["project_id"], version["asset_id"])
            self.store.emit("generation.updated", {"job_id": job_id, "project_id": request["project_id"], "status": "pending", "progress": 0})
            self.store.emit("project.assets_updated", {"project_id": request["project_id"]})
        return self.get(job_id)

    @staticmethod
    def _validate_request(payload):
        if not isinstance(payload, dict):
            raise DomainError(422, "生成请求格式无效。", "invalid_generation")
        if payload.get("kind") == "video":
            if payload.get("workflow_id") == LIPSYNC_PROFILE:
                return normalize_lipsync(payload, GenerationService._validate_request)
            if isinstance(payload.get("workflow_id"), str) and payload["workflow_id"] in ENHANCEMENT_PROFILES:
                return normalize_enhancement(payload, GenerationService._validate_request)
            return normalize_video(payload, GenerationService._validate_request)
        if payload.get("kind") == "audio":
            if payload.get("workflow_id") == VOICE_DESIGN_PROFILE:
                return normalize_voice_design(payload, GenerationService._validate_request)
            return normalize_speech(payload, GenerationService._validate_request)
        provider = payload.get("provider", "openai" if str(payload.get("workflow_id", "")).startswith(OPENAI_PREFIX) else "comfyui")
        if provider not in ("openai", "comfyui"):
            raise DomainError(422, "未知的生成服务。", "generation_provider_invalid")
        request = {key: copy.deepcopy(payload.get(key)) for key in ("project_id", "workflow_id", "prompt")}
        if any(not isinstance(value, str) or not value.strip() for value in request.values()):
            raise DomainError(422, "请选择项目和工作流，并填写提示词。", "invalid_generation")
        if len(request["prompt"]) > 32000:
            raise DomainError(422, "提示词长度超过限制。", "invalid_generation")
        if "negative_prompt" in payload:
            request["negative_prompt"] = payload["negative_prompt"]
            if not isinstance(request["negative_prompt"], str) or len(request["negative_prompt"]) > 32000:
                raise DomainError(422, "负面提示词格式无效。", "invalid_generation")
        for key in ("source_node_id", "mask_version_id"):
            value = payload.get(key)
            if value is not None and (not isinstance(value, str) or not value):
                raise DomainError(422, "节点或版本标识无效。", "invalid_generation")
            request[key] = value
        references = payload.get("references", [])
        if not isinstance(references, list) or len(references) > 16:
            raise DomainError(422, "参考图列表无效。", "invalid_generation")
        request["references"] = []
        for reference in references:
            if not isinstance(reference, dict) or not isinstance(reference.get("version_id"), str) or not reference["version_id"]:
                raise DomainError(422, "参考图缺少具体版本。", "invalid_generation")
            node_id = reference.get("node_id")
            if node_id is not None and (not isinstance(node_id, str) or not node_id):
                raise DomainError(422, "参考图节点标识无效。", "invalid_generation")
            request["references"].append({"version_id": reference["version_id"], "node_id": node_id})
        normalize_references(payload, request)
        parameters = payload.get("parameters", {})
        if not isinstance(parameters, dict) or set(parameters) - {"seed", "width", "height", "steps", "cfg", "denoise"}:
            raise DomainError(422, "生成参数包含未支持的字段。", "invalid_generation_parameters")
        for key, value in parameters.items():
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise DomainError(422, "生成参数需要有限数值。", "invalid_generation_parameters")
            if key in ("seed", "width", "height", "steps") and not isinstance(value, int):
                raise DomainError(422, "种子、尺寸和步数需要整数。", "invalid_generation_parameters")
        if "seed" in parameters and not -1 <= parameters["seed"] <= 2**53 - 1:
            raise DomainError(422, "种子须为 -1（随机）或 0 至 9007199254740991 的整数。", "invalid_generation_parameters")
        request["parameters"] = copy.deepcopy(parameters)
        if provider == "openai":
            if request["workflow_id"] not in {OPENAI_PREFIX + mode for mode in ("text_to_image", "reference", "edit")}:
                raise DomainError(422, "请选择 OpenAI 图片工作流。", "openai_workflow_invalid")
            from .openai_images import validate_options
            request.update(validate_options(payload), provider="openai")
        elif request["workflow_id"].startswith(OPENAI_PREFIX):
            raise DomainError(422, "工作流和生成服务不一致。", "generation_provider_invalid")
        placement = payload.get("placement")
        if placement is not None:
            if not isinstance(placement, dict) or any(isinstance(placement.get(key), bool) or not isinstance(placement.get(key), (int, float)) or not math.isfinite(placement[key]) for key in ("x", "y")):
                raise DomainError(422, "结果位置需要有效坐标。", "invalid_generation_placement")
            request["placement"] = {"x": placement["x"], "y": placement["y"]}
        return request

    def _input_version(self, version_id):
        version = self.store.version(version_id)
        if not version["mime"].startswith("image/") or version["missing"]:
            raise DomainError(422, "参考图或蒙版必须是可读取的图片原件。", "generation_input_missing", version_id=version_id)
        if self.store.asset(version["asset_id"], details=False)["deleted_at"]:
            raise DomainError(409, "请先恢复回收站中的输入图片。", "asset_trashed")
        return version

    def _is_image_card(self, node):
        return self._is_media_card(node, "image")

    def _is_media_card(self, node, kind):
        data = node.get("data", {})
        if node.get("type", "media") != "media" or data.get("kind") not in (None, kind):
            return False
        version_id = data.get("asset_version_id")
        return not version_id or self.store.version(version_id)["mime"].startswith(kind+"/")

    @staticmethod
    def _version_snapshot(version):
        return {key: version.get(key) for key in ("id", "asset_id", "hash", "filename", "mime", "width", "height", "size", "duration")}

    def _update(self, job_id, *, status=None, message=None, progress=None, error=None, **fields):
        with self.store.tx():
            job = self.get(job_id)
            updates = dict(fields)
            if status is not None:
                updates["status"] = status
            if progress is not None:
                updates["progress"] = progress
            if message is not None:
                updates["message"] = message
            if error is not None:
                updates["error_json"] = encode(error)
            log_changed = (status is not None and status != job["status"]) or (message is not None and message != job["message"])
            if log_changed:
                logs = job["logs"] + [{"at": now(), "status": status or job["status"], "message": message or job["message"]}]
                updates["logs_json"] = encode(logs[-200:])
            updates["updated_at"] = now()
            assignments = ",".join(f"{key}=?" for key in updates)
            self.store.conn.execute(f"UPDATE generation_jobs SET {assignments} WHERE id=?", [*updates.values(), job_id])
            if log_changed:
                self.store.emit("generation.updated", {"job_id": job_id, "project_id": job["project_id"], "status": status or job["status"], "progress": progress if progress is not None else job["progress"]})

    def run(self):
        try:
            while not self.stop_event.is_set():
                try:
                    self.tick()
                except Exception:
                    logging.getLogger(__name__).exception("Generation worker tick failed")
                self.stop_event.wait(0.7)
        finally:
            self.client.close()

    def tick(self):
        if self.store.maintenance:
            return
        with self.operation_lock, self.store.media_lock:
            if self.store.maintenance:
                return
            with self.store.lock:
                pending = self.store.conn.execute("SELECT id FROM generation_jobs WHERE status='pending' ORDER BY created_at,id LIMIT 5").fetchall()
                polling = self.store.conn.execute("SELECT id FROM generation_jobs WHERE status IN ('submitting','queued','running','collecting','unknown') ORDER BY created_at,id").fetchall()
            # Reserve submission slots and rotate reconciliation slots: unresolved
            # upstream receipts must never starve new jobs or later running jobs.
            offset = self.poll_cursor % len(polling) if polling else 0
            rotating = polling[offset:] + polling[:offset]
            rows = list(pending) + list(rotating[:15])
            self.poll_cursor = (offset + min(15, len(polling))) % len(polling) if polling else 0
            self.telemetry.retain({row["id"] for row in list(pending) + list(polling)})
            for row in rows:
                if self.stop_event.is_set() or self.store.maintenance:
                    return
                job = self.get(row["id"])
                try:
                    if job["request"].get("provider") == "openai":
                        self._tick_openai(job)
                        continue
                    if job["status"] == "pending" or (job["status"] == "submitting" and not job["submission_started_at"]):
                        self._submit(job)
                    elif job["prompt_id"]:
                        self._poll(job)
                    else:
                        self._reconcile(job)
                except DomainError as error:
                    if error.detail["code"] == "storage_busy":
                        return
                    self._fail(job["id"], error.detail)
                except httpx.HTTPError as error:
                    current = self.get(job["id"])
                    if current["prompt_id"] or current["submission_started_at"]:
                        self._update(job["id"], message="ComfyUI 连接中断，等待恢复后核对原任务。")
                    else:
                        self._fail(job["id"], {"code": "comfy_connection_error", "message": str(error)})
                except Exception as error:
                    self._fail(job["id"], {"code": "generation_error", "message": str(error)})

    def _openai_receipt(self, job_id):
        return self.store.root / "temp" / f"openai-{job_id}.json"

    def _tick_openai(self, job):
        for key, future in list(self.external_jobs.items()):
            if future.done():
                future.result()
                del self.external_jobs[key]
        if job["id"] in self.external_jobs:
            return
        receipt = self._openai_receipt(job["id"])
        if receipt.exists():
            self.external_jobs[job["id"]] = self.external_executor.submit(self._run_openai, job, True)
        elif job["submission_started_at"]:
            if job["status"] != "unknown":
                self._update(job["id"], status="unknown", message="OpenAI 原提交结果尚未确认，不会自动重复发送。请核对平台用量后结束跟踪。", error={"code": "openai_submission_unknown", "message": "服务重启前已发送请求，未找到本地结果。"})
        elif len(self.external_jobs) < 2 and not self.stop_event.is_set():
            self._update(job["id"], status="submitting", message="正在准备 OpenAI 图片输入。")
            self.external_jobs[job["id"]] = self.external_executor.submit(self._run_openai, job, False)

    def _run_openai(self, job, recover):
        submitted = False
        receipt = self._openai_receipt(job["id"])
        try:
            if not recover:
                fields, files = self.openai.prepare(job, self._input_version)
                if self.stop_event.is_set():
                    self._update(job["id"], status="pending", message="服务关闭前尚未提交，启动后继续。")
                    return
                self._update(job["id"], status="running", submission_started_at=now(), message="OpenAI 正在生成图片；已提交的云端请求不能中途撤回。")
                submitted = True
                result = self.openai.generate(fields, files)
                temporary = receipt.with_suffix(".tmp")
                temporary.write_text(encode(result), encoding="utf-8")
                temporary.replace(receipt)
            else:
                result = json.loads(receipt.read_text(encoding="utf-8"))
            self._update(job["id"], status="collecting", message="正在保存 OpenAI 结果。")
            request = copy.deepcopy(job["request"])
            request.update(usage=result.get("usage"), actual_cost=usage_cost(result.get("usage")), upstream_request_id=result.get("request_id"))
            self._update(job["id"], request_json=encode(request))
            path = self.store.root / "temp" / f"openai-{job['id']}.png"
            try:
                data = self.openai.decode_image(result)
                path.write_bytes(data)
                metadata = probe_media(path, "OpenAI.png")
                if metadata["type"] != "image":
                    raise DomainError(502, "OpenAI 返回的结果不是图片。", "openai_output_invalid")
                with self.store.media_lock:
                    if self.store.maintenance:
                        raise DomainError(409, "资料库正在迁移，稍后继续保存原结果。", "storage_busy")
                    asset = self.store.ingest(path, f"OpenAI-{job['id'][:8]}.png", metadata, hashlib.sha256(data).hexdigest(), project_id=job["project_id"], request_id=f"generation:{job['id']}:0", source="openai")
                    outputs = [{"asset_id": asset["id"], "version_id": asset["imported_version_id"], "node_id": job["source_node_id"] or f"generation-{job['id']}-0"}]
                    self._update(job["id"], outputs_json=encode(outputs))
                    self._append_results(job, outputs)
                    self._update(job["id"], status="succeeded", message="OpenAI 结果已保存，可在原卡片查看。", progress=1, outputs_json=encode(outputs), error_json=None)
                receipt.unlink(missing_ok=True)
            finally:
                path.unlink(missing_ok=True)
        except DomainError as error:
            if error.detail["code"] == "storage_busy":
                return
            self._fail(job["id"], error.detail)
        except httpx.HTTPError:
            if submitted:
                self._update(job["id"], status="unknown", message="OpenAI 响应中断，原请求可能已经计费；不会自动重复提交。请核对平台用量。", error={"code": "openai_submission_unknown", "message": "未能收到完整的生成结果。"})
            else:
                self._fail(job["id"], {"code": "openai_connection_error", "message": "无法连接 OpenAI，请检查网络。"})
        except Exception:
            # Never persist exception strings that might contain request credentials.
            if submitted and not receipt.exists():
                self._update(job["id"], status="unknown", message="OpenAI 原提交结果待确认，不会自动重复提交。", error={"code": "openai_submission_unknown", "message": "未能保存完整的生成结果。"})
            else:
                self._fail(job["id"], {"code": "openai_collection_error", "message": "OpenAI 结果保存失败，重试将优先回收本地原结果。"})

    def _fail(self, job_id, detail):
        job = self.get(job_id)
        self._update(job_id, status="failed", message=detail.get("message", "生成失败。"), error={**detail, "phase": "collect" if job["status"] == "collecting" else "execute"})

    def _json(self, method, url, **kwargs):
        response = self.client.request(method, url, **kwargs)
        response.raise_for_status()
        return response.json()

    def _upload_image(self, job, version_id, *, mask=False, reference=None):
        version = self.video.input_version(version_id) if job["request"].get("kind") == "video" else self.audio_adapter(job["request"]).input_version(version_id) if job["request"].get("kind") == "audio" else self._input_version(version_id)
        path = Path(version["path"])
        digest = hashlib.sha256()
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
        if digest.hexdigest() != version["hash"]:
            raise DomainError(409, "输入原件内容校验失败，请先修复该版本。", "generation_input_corrupt", version_id=version_id)
        temporary = None
        try:
            extension = Path(version["filename"]).suffix or ".png"
            workflow_id = job['request'].get('workflow_id')
            if reference is not None and (workflow_id == LIPSYNC_PROFILE or workflow_id in ENHANCEMENT_PROFILES):
                token=hashlib.sha256(encode(reference).encode()).hexdigest()[:16]
            elif reference is not None:
                from .video_inputs import prepare_reference
                token=hashlib.sha256(encode(reference).encode()).hexdigest()[:16]
                extension={"image":".png","video":".mp4","audio":".wav"}[reference["media_type"]]
                temporary=self.store.root / "temp" / f"video-ref-{job['id']}-{token}{extension}"
                path=prepare_reference(path,temporary,reference,job["request"]["parameters"])
            elif version["mime"].startswith("video/"):
                ffmpeg = find_binary("ffmpeg")
                if not ffmpeg:
                    raise DomainError(503,"参考视频需要 FFmpeg 转换到 24fps。","ffmpeg_missing")
                temporary = self.store.root / "temp" / f"video-ref-{job['id']}-{version_id}.mp4"
                run_process([ffmpeg,"-hide_banner","-loglevel","error","-nostdin","-y","-i",str(path),"-map","0:v:0","-map","0:a?","-vf","fps=24","-c:v","libx264","-crf","18","-pix_fmt","yuv420p","-c:a","aac","-movflags","+faststart",str(temporary)],timeout=180)
                path, extension = temporary, ".mp4"
            if mask:
                temporary = self.store.root / "temp" / f"generation-mask-{job['id']}.png"
                with Image.open(path) as original:
                    gray = original.convert("L")
                    histogram = gray.histogram()
                    # Qwen GH clears values <=0.02, then interprets <=0.2%
                    # remaining area as no mask (whole-image editing).
                    if sum(histogram[6:]) <= gray.width * gray.height * 0.002:
                        raise DomainError(422, "蒙版白色区域过小，请明确涂出要修改的区域后重试。", "generation_mask_empty")
                    alpha = ImageOps.invert(gray)
                    normalized = Image.new("RGBA", original.size, "white")
                    normalized.putalpha(alpha)
                    normalized.save(temporary, "PNG")
                path, extension = temporary, ".png"
            with path.open("rb") as source:
                filename=f"input-{token}{extension}" if reference is not None else f"{'mask' if mask else 'input'}-{version_id}{extension}"
                mime={".png":"image/png",".mp4":"video/mp4",".wav":"audio/wav"}.get(extension,version["mime"])
                result = self._json("POST", job["backend_url"] + "/upload/image", files={"image": (filename, source, mime)}, data={"type": "input", "subfolder": "manju/" + job["id"], "overwrite": "true"})
            name, subfolder = result.get("name"), result.get("subfolder", "")
            if not isinstance(name, str) or not name or not isinstance(subfolder, str):
                raise DomainError(502, "ComfyUI 上传返回值无效。", "comfy_upload_invalid")
            return "/".join(part for part in (subfolder, name) if part)
        finally:
            if temporary:
                temporary.unlink(missing_ok=True)

    def _submit(self, job):
        if job["backend_url"] != f"http://127.0.0.1:{self.comfy.port}":
            raise DomainError(409, "ComfyUI 地址已改变，请确认安装后重试生成。", "comfy_backend_changed")
        self._update(job["id"], status="submitting", message="上传指定版本并校验工作流。", progress=0.05)
        request = job["request"]
        files = ({ref["id"]:self._upload_image(job,ref["version_id"],reference=ref) for ref in request["references"]} if request.get("kind")=="video"
                 else {version:self._upload_image(job,version) for version in dict.fromkeys(item["version_id"] for item in request["references"])})
        prepared_guides = {}
        for index, guide in enumerate(request.get("h3_guides", [])):
            media = {key: value for key, value in guide.items()
                     if key not in ("frame_idx", "id", "title", "node_id", "snapshot")}
            signature = fingerprint(media)
            if signature not in prepared_guides:
                prepared_guides[signature] = self._upload_image(job, guide["version_id"], reference=media)
            files[guide_file_key(index)] = prepared_guides[signature]
        mask = self._upload_image(job, request["mask_version_id"], mask=True) if request.get("mask_version_id") else None
        video_adapter = self.video_adapter(request)
        prepared = video_adapter.prepare(job,files) if request.get("kind") == "video" else self.audio_adapter(request).prepare(job,files) if request.get("kind") == "audio" else self.workflows.prepare(job["workflow_snapshot"], request.get("compiled_prompt", request["prompt"]), negative_prompt=request["negative_prompt"], reference_images=list(files.values()), mask_image=mask, parameters=request["parameters"], output_prefix="Manju/" + job["id"])
        if job["backend_url"] != f"http://127.0.0.1:{self.comfy.port}":
            raise DomainError(409, "准备图片期间 ComfyUI 地址发生变化，请确认安装后重试。", "comfy_backend_changed")
        graph = prepared["api_graph"]
        snapshot = dict(request)
        snapshot["resolved_parameters"] = prepared["parameters"]
        self._update(job["id"], mapped_graph_json=encode(graph), request_json=encode(snapshot), submission_started_at=now(), message="正在提交到 ComfyUI。", progress=0.15)
        payload = {"prompt": graph, "client_id": job["id"], "prompt_id": str(uuid.UUID(job["id"])), "extra_data": {"manju_job_id": job["id"]}}
        self.telemetry.ensure({**job, "prompt_id": payload["prompt_id"], "mapped_graph": graph})
        try:
            response = self.client.post(job["backend_url"] + "/prompt", json=payload)
        except httpx.HTTPError as error:
            self._update(job["id"], status="unknown", message="提交响应丢失，正在核对 ComfyUI 队列与历史。", error={"code": "submission_unknown", "message": str(error)})
            return
        if response.is_error:
            try:
                detail = response.json()
            except ValueError:
                detail = response.text[:4000]
            if response.status_code >= 500:
                self._update(job["id"], status="unknown", message="ComfyUI 提交状态不明确，等待核对。", error={"code": "submission_unknown", "message": str(detail)})
            else:
                self._fail(job["id"], {"code": "comfy_prompt_rejected", "message": "ComfyUI 拒绝了工作流。", "details": detail})
            return
        try:
            prompt_id = response.json()["prompt_id"]
            if not isinstance(prompt_id, str) or not prompt_id:
                raise ValueError("missing prompt id")
        except (ValueError, KeyError, TypeError):
            self._update(job["id"], status="unknown", message="ComfyUI 未返回任务标识，正在核对队列。")
            return
        self._update(job["id"], status="queued", prompt_id=prompt_id, message="已提交，等待 ComfyUI 执行。", progress=0.2, error_json=None)

    @staticmethod
    def _queue_ids(queue, key):
        return {item[1] for item in queue.get(key, []) if isinstance(item, list) and len(item) > 1}

    @staticmethod
    def _owns_entry(entry, job_id):
        return isinstance(entry, (list, tuple)) and len(entry) > 3 and isinstance(entry[3], dict) and (entry[3].get("manju_job_id") == job_id or entry[3].get("client_id") == job_id)

    def _reconcile(self, job):
        queue = self._json("GET", job["backend_url"] + "/queue")
        for key, status in (("queue_running", "running"), ("queue_pending", "queued")):
            for entry in queue.get(key, []):
                if self._owns_entry(entry, job["id"]):
                    self._update(job["id"], status=status, prompt_id=entry[1], message="已从 ComfyUI 队列恢复任务。", error_json=None)
                    return
        history = self._json("GET", job["backend_url"] + "/history", params={"max_items": 200})
        for prompt_id, result in history.items():
            if isinstance(result, dict) and self._owns_entry(result.get("prompt"), job["id"]):
                self._update(job["id"], status="queued", prompt_id=prompt_id, message="已从 ComfyUI 历史恢复任务。", error_json=None)
                self._poll(self.get(job["id"]))
                return
        self._update(job["id"], status="unknown", message="尚未找到原提交记录，保留输入并继续核对，请勿重复提交。")

    def _poll(self, job):
        self.telemetry.ensure(job)
        history = self._json("GET", job["backend_url"] + "/history/" + job["prompt_id"])
        result = history.get(job["prompt_id"])
        if result:
            state = result.get("status", {})
            messages = state.get("messages", [])
            interrupted = any(isinstance(item, list) and item and item[0] == "execution_interrupted" for item in messages)
            if state.get("status_str") == "error" or interrupted:
                if job["cancel_requested"] or interrupted:
                    self._update(job["id"], status="cancelled", message="生成已取消。", progress=0)
                else:
                    self._fail(job["id"], {"code": "comfy_execution_failed", "message": "ComfyUI 执行失败，请检查任务日志。", "details": messages})
                return
            if state.get("completed") or result.get("outputs"):
                self._collect(job, result)
                return
        queue = self._json("GET", job["backend_url"] + "/queue")
        if job["prompt_id"] in self._queue_ids(queue, "queue_running"):
            self._update(job["id"], status="running", message="ComfyUI 正在生成"+("人物口型" if job['request'].get('workflow_id') == LIPSYNC_PROFILE else "视频" if job["request"].get("kind")=="video" else "配音" if job["request"].get("kind")=="audio" else "图片")+"。" if not job["cancel_requested"] else "已请求取消，等待当前任务结束。", progress=0.4)
        elif job["prompt_id"] in self._queue_ids(queue, "queue_pending"):
            self._update(job["id"], status="queued", message="正在 ComfyUI 队列中等待。", progress=0.2)
        elif job["cancel_requested"]:
            self._update(job["id"], status="cancelled", message="生成已取消。", progress=0)
        else:
            self._update(job["id"], status="unknown", message="ComfyUI 暂未返回此任务，保留任务标识等待恢复。")

    def _collect(self, job, result):
        request = job["request"]
        video = request.get("kind") == "video"
        voice_audition = (
            request.get("workflow_id") == VOICE_DESIGN_PROFILE
            and bool(request.get("subject_node_id"))
            and not job["source_node_id"]
        )
        canvas_node_id = None if voice_audition else job["source_node_id"] or f"generation-{job['id']}-0"
        self._update(job["id"], status="collecting", message="正在校验并保存生成媒体。", progress=0.8)
        descriptors = []
        for node_id in job["workflow_snapshot"]["output_nodes"]:
            output = result.get("outputs", {}).get(str(node_id), {})
            for descriptor in (sum((output.get(key,[]) for key in ("videos","gifs","images")),[]) if video else output.get("audio" if job["request"].get("kind")=="audio" else "images", [])):
                if isinstance(descriptor, dict) and isinstance(descriptor.get("filename"), str):
                    descriptors.append({"node_id": str(node_id), "filename": descriptor["filename"], "subfolder": descriptor.get("subfolder", ""), "type": descriptor.get("type", "output")})
        descriptors = list({(d["node_id"], d["filename"], d["subfolder"], d["type"]): d for d in descriptors}.values())
        if not descriptors or len(descriptors) > 64:
            raise DomainError(502, "工作流没有返回可回收的媒体，或输出数量超过限制。", "generation_outputs_missing")
        outputs = []
        for index, descriptor in enumerate(descriptors):
            path = self.store.root / "temp" / f"generation-{job['id']}-{index}.download"
            digest, size = hashlib.sha256(), 0
            try:
                with self.client.stream("GET", job["backend_url"] + "/view", params={key: descriptor[key] for key in ("filename", "subfolder", "type")}) as response:
                    response.raise_for_status()
                    with path.open("wb") as target:
                        for chunk in response.iter_bytes(1024 * 1024):
                            size += len(chunk)
                            if size > (2*1024**3 if video else MAX_OUTPUT_BYTES):
                                raise DomainError(413, "生成视频超过 2 GiB。" if video else "生成媒体超过 256 MiB。", "generation_output_too_large")
                            target.write(chunk)
                            digest.update(chunk)
                filename = Path(descriptor["filename"].replace("\\", "/")).name
                metadata = probe_media(path, filename)
                if metadata["type"] != job["request"].get("kind", "image"):
                    raise DomainError(422, "输出媒体类型与任务不符。", "generation_output_invalid")
                asset = self.store.ingest(path, filename, metadata, digest.hexdigest(), project_id=job["project_id"], request_id=f"generation:{job['id']}:{index}", source="comfyui")
                outputs.append({"asset_id": asset["id"], "version_id": asset["imported_version_id"], "node_id": canvas_node_id, "comfy_output": descriptor})
                self._update(job["id"], outputs_json=encode(outputs))
            finally:
                path.unlink(missing_ok=True)
        if voice_audition:
            message = "音色候选已保存，可在角色的音色设计窗口试听并绑定。"
        else:
            self._append_results(job, outputs)
            message = "生成结果已保存，可在原卡片内查看候选。"
        self._update(job["id"], status="succeeded", message=message, progress=1, outputs_json=encode(outputs), error_json=None)

    def _append_results(self, job, outputs):
        kind = job["request"].get("kind", "image")
        with self.store.lock:
            version_ids = [output["version_id"] for output in outputs]
            receipt = self.store.request_result(job["id"], "generation-delivery", version_ids)
            if receipt:
                for output in outputs:
                    output["node_id"] = receipt["node_id"]
                return
            canvas = self.store.canvas(job["project_id"])
            nodes = {node["id"]: node for node in canvas["nodes"]}
            target = nodes.get(job["source_node_id"])
            if target is not None and not self._is_media_card(target, kind):
                target = None
            if target is None:
                target_id = f"generation-{job['id']}-0"
                target = nodes.get(target_id)
                if target is not None and not self._is_media_card(target, kind):
                    while target_id in nodes:
                        target_id += "-result"
                    target = None
                if target is None:
                    target = {"id": target_id, "type": "media", "position": dict(job["request"].get("placement") or {"x": 80, "y": 80}), "style": {"width": 264, "height": 214}, "data": {"kind": kind, "title": "生成视频" if kind=="video" else "生成配音" if kind=="audio" else "生成图片"}}
                    if job["request"].get("workflow_id") == VOICE_DESIGN_PROFILE:
                        target["data"]["title"] = "角色音色候选"
                    canvas["nodes"].append(target)
            data = target.setdefault("data", {})
            history, seen = [], set()
            for entry in data.get("image_history", []):
                if entry["version_id"] not in seen:
                    history.append(dict(entry))
                    seen.add(entry["version_id"])
            current = data.get("asset_version_id")
            if current and current not in seen:
                original = {"version_id": current}
                if data.get("generation_id"):
                    original["job_id"] = data["generation_id"]
                history.insert(0, original)
                seen.add(current)
            timestamp = now()
            for output in outputs:
                output["node_id"] = target["id"]
                if output["version_id"] not in seen:
                    history.append({"version_id": output["version_id"], "job_id": job["id"], "created_at": timestamp, "candidate": job["request"].get("result_policy") == "review" and (bool(current) or output["version_id"] != outputs[0]["version_id"])})
                    seen.add(output["version_id"])
            data.update(kind=kind, image_history=history)
            if not current or job["request"].get("result_policy") != "review":
                if kind == "image" and current and current != outputs[0]["version_id"]:
                    data["previous_image_version_id"] = current
                data.update(asset_version_id=outputs[0]["version_id"], generation_id=job["id"])
            canvas["request_id"] = f"generation-result:{job['id']}:{canvas['revision']}"
            self.store.save_canvas(job["project_id"], canvas, event_details={"reason": "generation_result", "job_id": job["id"], "updated_node_ids": [target["id"]]}, generation_delivery={"job_id": job["id"], "version_ids": version_ids, "node_id": target["id"]})

    def cancel(self, job_id, interrupt_running=False):
        with self.operation_lock, self.store.media_lock:
            job = self.get(job_id)
            if job["status"] in TERMINAL_STATUSES:
                return job
            if job["request"].get("provider") == "openai":
                if job["status"] == "pending" and job["id"] not in self.external_jobs:
                    self._update(job_id, status="cancelled", message="已取消尚未提交的 OpenAI 任务。")
                elif job["status"] == "unknown":
                    if not interrupt_running:
                        raise DomainError(409, "结束跟踪不会撤回上游请求，原请求可能已计费；确认核对后结束跟踪？", "generation_interrupt_confirmation")
                    self._update(job_id, status="cancelled", message="已结束本地跟踪；上游原请求可能已计费。")
                else:
                    raise DomainError(409, "OpenAI 已提交的图片任务不能撤回，请等待结果。", "openai_cancel_unavailable")
                return self.get(job_id)
            if job["status"] == "collecting":
                raise DomainError(409, "媒体正在保存，请等待结果完成。", "generation_collecting")
            if job["status"] == "unknown":
                if not interrupt_running:
                    raise DomainError(409, "结束跟踪不会中断或撤回 ComfyUI 原任务，原任务可能仍在运行。核对后结束本地跟踪？", "generation_interrupt_confirmation")
                self._update(job_id, status="cancelled", message="已结束本地跟踪；ComfyUI 原任务可能仍在运行，不会自动重复提交。", error_json=encode({"code": "tracking_ended", "message": "用户明确结束了状态不明任务的本地跟踪。"}))
                return self.get(job_id)
            if not job["prompt_id"] and not job["submission_started_at"]:
                self._update(job_id, status="cancelled", message="已取消尚未提交的任务。")
                return self.get(job_id)
            if not job["prompt_id"]:
                self._reconcile(job)
                job = self.get(job_id)
                if not job["prompt_id"]:
                    raise DomainError(409, "提交结果尚未确认，正在核对原任务。", "generation_submission_unknown")
            queue = self._json("GET", job["backend_url"] + "/queue")
            if job["prompt_id"] in self._queue_ids(queue, "queue_pending"):
                response = self.client.post(job["backend_url"] + "/queue", json={"delete": [job["prompt_id"]]})
                response.raise_for_status()
                self._update(job_id, message="已请求移除排队任务，正在确认执行状态。", cancel_requested=1)
                # A pending item can begin between GET /queue and deletion. Never
                # report it cancelled until queue/history confirms disappearance.
                self._poll(self.get(job_id))
                job = self.get(job_id)
                if job["status"] != "running":
                    return job
                queue = {"queue_running": [[0, job["prompt_id"]]]}
            if job["prompt_id"] in self._queue_ids(queue, "queue_running"):
                if not interrupt_running:
                    raise DomainError(409, "任务正在运行，取消需要明确确认中断该任务。", "generation_interrupt_confirmation")
                response = self.client.post(job["backend_url"] + f"/api/jobs/{job['prompt_id']}/cancel", json={})
                if response.status_code == 404:
                    raise DomainError(409, "此 ComfyUI 版本未提供按任务取消接口，请在 ComfyUI 中处理。", "targeted_cancel_unavailable")
                response.raise_for_status()
                self._update(job_id, message="已请求定向取消，等待此任务结束。", cancel_requested=1)
            else:
                self._poll(job)
            return self.get(job_id)

    def retry(self, job_id, request_id=None):
        # Publish a retry that only collects old outputs atomically with respect
        # to the worker, so it can never be mistaken for a fresh submission.
        with self.operation_lock, self.store.media_lock:
            return self._retry_locked(job_id, request_id)

    def _retry_locked(self, job_id, request_id=None):
        original = self.get(job_id)
        if original["status"] not in ("failed", "cancelled"):
            raise DomainError(409, "仅已失败或已取消的任务可重试，状态不明的提交会继续核对。", "generation_retry_unavailable")
        request = copy.deepcopy(original["request"])
        request.pop("request_id", None)
        recover_local = request.get("provider") == "openai" and self._openai_receipt(job_id).exists()
        job = self.create(request, request_id, workflow_snapshot=original["workflow_snapshot"], parent_job_id=job_id, recover_local_response=recover_local)
        if request.get("provider") == "openai" and self._openai_receipt(job_id).exists() and job["status"] == "pending":
            # A collection retry reuses the saved response and never purchases another image.
            self._openai_receipt(job["id"]).write_bytes(self._openai_receipt(job_id).read_bytes())
        if job["status"] == "pending" and original["prompt_id"] and (original["error"] or {}).get("phase") == "collect":
            self._update(job["id"], status="queued", prompt_id=original["prompt_id"], backend_url=original["backend_url"], mapped_graph_json=encode(original["mapped_graph"]), submission_started_at=original["submission_started_at"], message="重试回收已生成的原任务结果。")
        return self.get(job["id"])
