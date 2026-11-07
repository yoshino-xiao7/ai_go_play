"""OpenAI image workflows, server-side credentials, and published output estimates."""
from __future__ import annotations

import base64
import hashlib
from io import BytesIO
import math
import os
from pathlib import Path
import re
import threading
import time

import httpx
from PIL import Image, ImageOps

from .store import DomainError, now


API_ROOT = "https://api.openai.com/v1"
PREFIX = "builtin-openai-"
PRICING_DATE = "2026-11-06"
PRICING_URL = "https://developers.openai.com/api/docs/guides/image-generation#calculating-costs"
QUALITY_NAMES = {"low": "低", "medium": "中", "high": "高", "xhigh": "超高", "max": "最高"}
MODE_NAMES = {"text_to_image": "文生图", "reference": "参考生图", "edit": "图像编辑"}
MODEL_NAMES = {
    "gpt-image-2.6-sunburst": "GPT Image 2.6 Sunburst · 精细创作",
    "gpt-image-2.6-flare": "GPT Image 2.6 Flare · 快速迭代",
    "gpt-image-2.5-sunburst": "GPT Image 2.5 Sunburst",
    "gpt-image-2.5-flare": "GPT Image 2.5 Flare",
    "gpt-image-2": "GPT Image 2",
}
SIZES = [
    {"label": "1:1 · 1024 × 1024", "width": 1024, "height": 1024},
    {"label": "3:2 · 1536 × 1024", "width": 1536, "height": 1024},
    {"label": "2:3 · 1024 × 1536", "width": 1024, "height": 1536},
    {"label": "16:9 · 1536 × 864", "width": 1536, "height": 864},
    {"label": "9:16 · 864 × 1536", "width": 864, "height": 1536},
    {"label": "1:1 · 2048 × 2048", "width": 2048, "height": 2048},
    {"label": "16:9 · 2048 × 1152", "width": 2048, "height": 1152},
    {"label": "9:16 · 1152 × 2048", "width": 1152, "height": 2048},
    {"label": "16:9 · 3840 × 2160", "width": 3840, "height": 2160},
    {"label": "9:16 · 2160 × 3840", "width": 2160, "height": 3840},
]


def qualities(model):
    return list(QUALITY_NAMES)[:3] if model == "gpt-image-2" else list(QUALITY_NAMES)


def validate_options(payload):
    model, quality = payload.get("model", "gpt-image-2.6-flare"), payload.get("quality", "high")
    if not isinstance(model, str) or model not in MODEL_NAMES:
        raise DomainError(422, "请选择已接入的 OpenAI 图片模型。", "openai_model_invalid")
    if not isinstance(quality, str) or quality not in qualities(model):
        raise DomainError(422, "当前模型不支持所选画质。", "openai_quality_invalid")
    parameters = payload.get("parameters", {})
    if not isinstance(parameters, dict) or set(parameters) - {"width", "height"}:
        raise DomainError(422, "OpenAI 图片工作流只接受宽度和高度参数。", "openai_parameters_invalid")
    width, height = parameters.get("width", 1024), parameters.get("height", 1024)
    if any(isinstance(v, bool) or not isinstance(v, int) or v <= 0 or v % 16 for v in (width, height)) or max(width, height) > 3840 or max(width, height) / min(width, height) > 3 or not 655360 <= width * height <= 8294400:
        raise DomainError(422, "尺寸须为 16 的倍数，长边不超过 3840，宽高比不超过 3:1，总像素为 655360–8294400。", "openai_size_invalid")
    return {"model": model, "quality": quality, "parameters": {"width": width, "height": height}}


def estimate_cost(payload):
    """Port of the official calculator; excludes input tokens, explicitly."""
    options = validate_options(payload)
    model, quality = options["model"], options["quality"]
    width, height = options["parameters"].values()
    grids = {"low": 16, "medium": 48, "high": 96} if model == "gpt-image-2" else {"low": 16, "medium": 24, "high": 48, "xhigh": 64, "max": 96}
    long_grid = grids[quality]
    short_grid = round(long_grid * min(width, height) / max(width, height))
    tokens = math.ceil(long_grid * short_grid * (2000000 + width * height) / 4000000)
    if model.startswith("gpt-image-2.6-"):
        tokens = math.floor(tokens * {"low": 4.2, "medium": 3.3}.get(quality, 1) + 0.5)
    return {**options, "currency": "USD", "output_tokens": tokens,
            "output_usd": round(tokens * 30 / 1000000, 8), "scope": "image_output",
            "text_input_per_million": 5, "image_input_per_million": 8,
            "pricing_date": PRICING_DATE, "pricing_url": PRICING_URL,
            "note": "单张图片输出估算；提示词与参考图输入另计，最终以实际用量为准。"}


def usage_cost(usage):
    if not isinstance(usage, dict):
        return None
    details = usage.get("input_tokens_details") or {}
    values = [details.get("text_tokens"), details.get("image_tokens"), usage.get("output_tokens")]
    if any(isinstance(v, bool) or not isinstance(v, int) or v < 0 for v in values):
        return None
    return {"currency": "USD", "total_usd": round((values[0] * 5 + values[1] * 8 + values[2] * 30) / 1000000, 8),
            "source": "api_usage", "pricing_date": PRICING_DATE}


def load_api_key():
    value = os.environ.get("OPENAI_API_KEY", "").strip()
    if not value:
        target = Path(__file__).resolve().parents[2] / ".env.local"
        try:
            if target.is_symlink():
                return ""
            for line in target.read_text(encoding="utf-8-sig").splitlines():
                match = re.fullmatch(r"\s*(?:export\s+)?OPENAI_API_KEY\s*=\s*(.*?)\s*", line)
                if match:
                    value = match[1]
                    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                        value = value[1:-1]
        except OSError:
            return ""
    return value if re.fullmatch(r"sk-[A-Za-z0-9_-]+", value) else ""


class OpenAIImages:
    def __init__(self, store, *, transport=None, key_loader=load_api_key):
        self.store, self.key_loader = store, key_loader
        self.client = httpx.Client(timeout=httpx.Timeout(600, connect=10), transport=transport)
        self.catalog_lock = threading.Lock()
        self.catalog_checked = 0.0
        self.catalog_checked_at = None
        self.available = None
        self.catalog_error = ""

    def close(self):
        self.client.close()

    def _headers(self):
        key = self.key_loader()
        if not key:
            raise DomainError(503, "未配置 OpenAI 密钥，请在本机配置 OPENAI_API_KEY 后重新检查。", "openai_key_missing")
        return {"Authorization": f"Bearer {key}"}

    @staticmethod
    def _reject(response):
        # Provider error bodies can echo input. Never persist or expose them.
        messages = {401: "OpenAI 密钥无效或已失效。", 403: "当前账户或项目没有所选能力的权限，图片模型可能需要组织验证。",
                    429: "OpenAI 额度不足或请求过于频繁，请检查余额和速率限制。", 400: "OpenAI 拒绝了图片请求，请检查描述、参考图及模型参数。"}
        raise DomainError(502, messages.get(response.status_code, f"OpenAI 服务返回 HTTP {response.status_code}。"), "openai_request_rejected", upstream_status=response.status_code)

    def catalog(self, *, refresh=False):
        configured = bool(self.key_loader())
        if configured:
            with self.catalog_lock:
                if refresh or self.available is None or time.monotonic() - self.catalog_checked > 300:
                    try:
                        response = self.client.get(API_ROOT + "/models", headers=self._headers(), timeout=15)
                        if response.is_error:
                            self._reject(response)
                        data = response.json()["data"]
                        if not isinstance(data, list):
                            raise ValueError("invalid model catalog")
                        self.available = {item["id"] for item in data if isinstance(item, dict) and isinstance(item.get("id"), str)}
                        self.catalog_error = ""
                    except DomainError as error:
                        self.available, self.catalog_error = set(), error.detail["message"]
                    except (httpx.HTTPError, ValueError, KeyError, TypeError):
                        self.available, self.catalog_error = set(), "无法查询 OpenAI 模型，请检查网络后重新检查。"
                    self.catalog_checked = time.monotonic()
                    self.catalog_checked_at = now()
        models = [{"id": model, "name": name, "qualities": qualities(model), "available": configured and model in (self.available or set())} for model, name in MODEL_NAMES.items()]
        return {"provider": "openai", "configured": configured,
                "ready": configured and not self.catalog_error and any(m["available"] for m in models),
                "models": models, "sizes": SIZES, "quality_names": QUALITY_NAMES,
                "checked_at": self.catalog_checked_at if configured else None,
                "error": self.catalog_error if configured else "未配置 OPENAI_API_KEY。",
                "pricing_date": PRICING_DATE, "pricing_url": PRICING_URL}

    def snapshot(self, mode):
        if mode not in MODE_NAMES:
            raise DomainError(422, "未知的 OpenAI 图片工作流。", "openai_workflow_invalid")
        bindings = {key: [] for key in ("prompt", "negative_prompt", "seed", "width", "height", "steps", "cfg", "denoise", "images")}
        bindings.update(width=[{"node_id": "openai", "input_name": "width"}], height=[{"node_id": "openai", "input_name": "height"}], mask=None)
        return {"id": PREFIX + mode, "provider": "openai", "name": "OpenAI · " + MODE_NAMES[mode],
                "mode": mode, "description": "云端 GPT Image 图片生成与编辑；可选模型、画质和尺寸，提交前预估费用。参考图会发送到 OpenAI。",
                "api_graph": {}, "bindings": bindings,
                "capabilities": {"min_images": int(mode != "text_to_image"), "max_images": 0 if mode == "text_to_image" else 16,
                                 "requires_mask": False, "supports_mask": mode == "edit", "reference_kind": "none" if mode == "text_to_image" else "img2img", "reference_mapping": "numbered"},
                "defaults": {"width": 1024, "height": 1024}, "output_nodes": ["openai"],
                "revision": 1, "builtin": True, "read_only": True, "validation": None,
                "ready": bool(self.key_loader()), "created_at": PRICING_DATE, "updated_at": PRICING_DATE}

    def workflows(self, mode=None):
        return [self.snapshot(key) for key in MODE_NAMES if mode is None or key == mode]

    def validate_request(self, request):
        result = validate_options(request)
        report = self.catalog()
        if not report["ready"]:
            raise DomainError(503, report["error"] or "当前项目没有可用的已接入图片模型。", "openai_unavailable")
        if not any(m["id"] == result["model"] and m["available"] for m in report["models"]):
            raise DomainError(422, "当前项目的模型列表中没有所选模型，请重新检查或选择其他模型。", "openai_model_unavailable")
        return result

    def input_png(self, version, *, mask=False):
        path = Path(version["path"])
        if version["size"] > 50 * 1024**2:
            raise DomainError(413, "OpenAI 每张参考图须小于 50 MiB。", "openai_input_too_large")
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != version["hash"]:
            raise DomainError(409, "参考图原件校验失败，请修复该版本。", "generation_input_corrupt")
        try:
            with Image.open(BytesIO(raw)) as original:
                image = ImageOps.exif_transpose(original)
                if mask:
                    gray = image.convert("L")
                    if not gray.getbbox():
                        raise DomainError(422, "请在蒙版中涂出要修改的白色区域。", "generation_mask_empty")
                    image = Image.new("RGBA", image.size, "white")
                    image.putalpha(ImageOps.invert(gray))
                else:
                    image = image.convert("RGBA" if "A" in image.getbands() else "RGB")
                buffer = BytesIO()
                image.save(buffer, "PNG")
                data = buffer.getvalue()
                if len(data) >= 50 * 1024**2:
                    raise DomainError(413, "转换后的参考图超过 OpenAI 的 50 MiB 限制。", "openai_input_too_large")
                return data
        except (OSError, ValueError) as error:
            raise DomainError(422, "无法读取参考图或蒙版。", "generation_input_missing") from error

    def prepare(self, job, input_version):
        request = job["request"]
        fields = {"model": request["model"], "quality": request["quality"],
                  "size": f"{request['parameters']['width']}x{request['parameters']['height']}",
                  "prompt": request.get("compiled_prompt", request["prompt"]), "n": 1, "output_format": "png"}
        if len(fields["prompt"]) > 32000:
            raise DomainError(422, "加入主体设定后的提示词超过 32000 字符。", "openai_prompt_too_long")
        files = []
        for version_id in dict.fromkeys(ref["version_id"] for ref in request["references"]):
            data = self.input_png(input_version(version_id))
            files.append(("image[]", ("reference.png", data, "image/png")))
        if request.get("mask_version_id"):
            files.append(("mask", ("mask.png", self.input_png(input_version(request["mask_version_id"]), mask=True), "image/png")))
        return fields, files

    def generate(self, fields, files):
        headers = self._headers()
        if files:
            response = self.client.post(API_ROOT + "/images/edits", headers=headers, data={key: str(value) for key, value in fields.items()}, files=files)
        else:
            response = self.client.post(API_ROOT + "/images/generations", headers=headers, json=fields)
        if response.is_error:
            if response.status_code >= 500:
                raise httpx.ReadError("OpenAI submission outcome unknown")
            self._reject(response)
        try:
            result = response.json()
            data = result.get("data")
            if not isinstance(data, list) or len(data) != 1 or not isinstance(data[0].get("b64_json"), str):
                raise ValueError("missing image")
            if len(data[0]["b64_json"]) > 256 * 1024**2:
                raise ValueError("output too large")
            # Persist only image data and metering, never arbitrary provider text.
            return {"data": [{"b64_json": data[0]["b64_json"]}], "usage": result.get("usage"), "request_id": response.headers.get("x-request-id")}
        except (ValueError, KeyError, TypeError, AttributeError) as error:
            raise httpx.ReadError("OpenAI returned no recoverable image") from error

    @staticmethod
    def decode_image(result):
        try:
            return base64.b64decode(result["data"][0]["b64_json"], validate=True)
        except (ValueError, KeyError, TypeError, IndexError) as error:
            raise DomainError(502, "OpenAI 图片响应格式无效。", "openai_output_invalid") from error
