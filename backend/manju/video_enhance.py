"""Video-only postproduction adapters for the durable ComfyUI queue."""

from .media import find_binary
from .store import DomainError


PROFILES = {
    "builtin-video-interpolate-local": ("interpolate", "RIFE · 视频插帧"),
    "builtin-video-upscale-local": ("upscale", "Anime6B · 视频超分"),
}
NODE = "ManjuVideoEnhance"
DEFAULTS = {"fps": 60, "width": 3840, "height": 2160, "cuts": []}
METHODS = {
    "interpolate": {
        "rife": ("RIFE 4.26 · 运动插帧", "FrameInterpolationModelLoader", "DRBA-RIFE/train_log_rife_426_heavy/flownet.pkl"),
        "hold": ("保留原画格 · 重复帧", None, None),
    },
    "upscale": {
        "anime6b": ("Anime6B · 动画线稿", "UpscaleModelLoader", "RealESRGAN_x4plus_anime_6B.pth"),
        "remacri": ("Remacri · 通用超分", "UpscaleModelLoader", "4x_foolhardy_Remacri.pth"),
    },
}


def available_models(catalog, loader):
    spec = catalog.get(loader, {}).get("input", {}).get("required", {}).get("model_name", [])
    if spec and isinstance(spec[0], list):
        entries = spec[0]
    elif len(spec) > 1 and isinstance(spec[1], dict):
        entries = spec[1].get("options", [])
    else:
        entries = []
    return {name.replace("\\", "/").casefold() for name in entries if isinstance(name, str)}


def normalize_enhancement(payload, base):
    workflow_id = payload["workflow_id"]
    clean = {**payload, "prompt": payload.get("prompt") or PROFILES[workflow_id][1]}
    clean.pop("kind", None)
    request = base(clean)
    if request.get("mask_version_id") or payload.get("provider", "comfyui") != "comfyui" or request["parameters"]:
        raise DomainError(422, "视频后期只接受本地视频和后期参数。", "video_enhance_parameters")
    options = payload.get("enhance_options", {})
    methods = METHODS[PROFILES[workflow_id][0]]
    defaults = {**DEFAULTS, "method": next(iter(methods))}
    if not isinstance(options, dict) or set(options) - defaults.keys():
        raise DomainError(422, "视频后期参数格式无效。", "video_enhance_parameters")
    options = {**defaults, **options}
    method = options["method"]
    if not isinstance(method, str) or method not in methods:
        raise DomainError(422, "所选模式与当前视频后期操作不匹配。", "video_enhance_method")
    fps, width, height, cuts = (options[key] for key in ("fps", "width", "height", "cuts"))
    if type(fps) is not int or not 1 <= fps <= 120:
        raise DomainError(422, "目标帧率须为 1 至 120 的整数。", "video_enhance_fps")
    if any(type(v) is not int or not 64 <= v <= 4096 or v % 2 for v in (width, height)):
        raise DomainError(422, "输出宽高须为 64 至 4096 的偶数。", "video_enhance_dimensions")
    if (not isinstance(cuts, list) or len(cuts) > 4096
            or any(type(frame) is not int or not 0 < frame < 2**31 for frame in cuts)
            or cuts != sorted(set(cuts))):
        raise DomainError(422, "切点须为递增且不重复的正整数帧号。", "video_enhance_cuts")
    if len(request["references"]) != 1 or payload["references"][0].get("media_type", "video") != "video":
        raise DomainError(422, "此节点需要且只接受一个视频输入。", "video_enhance_input")
    ref = request["references"][0]
    ref.update(id=ref.get("id") or "video", role="reference", media_type="video")
    request.update(kind="video", enhance_options=options, result_policy=payload.get("result_policy", "replace"))
    return request


class VideoEnhanceAdapter:
    def __init__(self, store, workflows, profile_id):
        self.store, self.workflows = store, workflows
        self.id = profile_id
        self.operation, self.name = PROFILES[profile_id]

    def status(self):
        try:
            catalog = self.workflows.object_info()
        except DomainError:
            catalog = {}
        errors = []
        if NODE not in catalog:
            errors.append("本机 ComfyUI 未加载 Manju 视频后期节点。")
        elif "method" not in catalog[NODE].get("input", {}).get("optional", {}):
            errors.append("请更新本机 Manju 视频后期节点后重启 ComfyUI。")
        if not find_binary("ffmpeg") or not find_binary("ffprobe"):
            errors.append("本机缺少 FFmpeg 或 FFprobe。")
        configured = METHODS[self.operation]
        methods = [{"id": key, "name": name, "ready": not errors and (
            loader is None or model.casefold() in available_models(catalog, loader))}
            for key, (name, loader, model) in configured.items()]
        if not errors and not any(item["ready"] for item in methods):
            errors.append("本机未找到此操作所需的模型。")
        return {"id": self.id, "name": self.name, "kind": "video", "mode": "video", "builtin": True,
                "read_only": True, "ready": not errors, "errors": errors, "methods": methods,
                "defaults": {**DEFAULTS, "method": next(iter(configured))}}

    def snapshot(self, options=None):
        status = self.status()
        if not status["ready"]:
            raise DomainError(422, "本机视频后期工作流尚未就绪。", "video_enhance_not_ready", errors=status["errors"])
        return {**status, "revision": 2, "bindings": {}, "capabilities": {"min_images": 1, "max_images": 1},
                "output_nodes": ["enhance"]}

    def compile_prompt(self, request):
        method = request["enhance_options"]["method"]
        if not any(item["id"] == method and item["ready"] for item in self.status()["methods"]):
            raise DomainError(422, "本机尚未就绪，无法执行所选视频后期模式。", "video_enhance_method_not_ready")
        version = self.store.version(request["references"][0]["version_id"])
        if version["missing"] or not version["mime"].startswith("video/"):
            raise DomainError(422, "视频后期需要可读取的视频原件。", "video_enhance_input")
        if self.store.asset(version["asset_id"], details=False)["deleted_at"]:
            raise DomainError(409, "请先恢复回收站中的视频。", "asset_trashed")
        return request["prompt"]

    def prepare(self, job, files):
        request = job["request"]
        options = request["enhance_options"]
        ffmpeg = find_binary("ffmpeg")
        if not ffmpeg:
            raise DomainError(503, "本机缺少 FFmpeg。", "ffmpeg_missing")
        inputs = {**options, "video": files[request["references"][0]["id"]], "operation": self.operation,
                  "cuts": ",".join(map(str, options["cuts"])), "ffmpeg": ffmpeg,
                  "filename_prefix": "Manju/" + job["id"]}
        return {"api_graph": {"enhance": {"class_type": NODE, "inputs": inputs}}, "parameters": options}
