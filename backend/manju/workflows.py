"""Versioned, local ComfyUI API workflows and explicit generation input bindings.

Workflows are snapshots: preparing a queued definition never consults a newer
registry revision. Validation is repeated against the selected local backend.
"""
from __future__ import annotations

from copy import deepcopy
import json
import math
from pathlib import PurePosixPath
import re
import secrets
from typing import Any

import httpx

from .store import DomainError, Store, encode, new_id, now


MODES = {"text_to_image", "reference", "edit"}
SCALARS = ("prompt", "negative_prompt", "seed", "width", "height", "steps", "cfg", "denoise")
NUMERIC = {"seed", "width", "height", "steps", "cfg", "denoise"}
INTEGER = {"seed", "width", "height", "steps"}
LIMITS = {"seed": (0, 2**53 - 1), "width": (32, 16384), "height": (32, 16384), "steps": (1, 1000), "cfg": (0, 100), "denoise": (0, 1)}


def _binding(node_id: str, input_name: str) -> dict:
    return {"node_id": node_id, "input_name": input_name}


def builtin_workflows() -> list[dict]:
    """Model names are ComfyUI catalog identifiers, never personal disk paths."""
    result = []
    for mode, title in (("text_to_image", "Qwen Image 2.1 · 中文文生图"), ("reference", "Qwen Image 2.1 · 多图参考"), ("edit", "Qwen Image 2.1 · 指令编辑")):
        graph = {
            "1": {"class_type": "UNETLoader", "inputs": {"unet_name": "qwen_image_2.1_turbo_int8_convrot.safetensors", "weight_dtype": "default"}},
            "6": {"class_type": "CLIPLoader", "inputs": {"clip_name": "qwen3vl_8b_int8_convrot.safetensors", "type": "qwen_image", "device": "default"}},
            "7": {"class_type": "VAELoader", "inputs": {"vae_name": "qwen_image_2.1_vae_bf16.safetensors"}},
            "8": {"class_type": "TextEncodeQwenImage21GH", "inputs": {"clip": ["6", 0], "vae": ["7", 0], "prompt": "二次元动画分镜，干净线稿，电影感光影", "negative_prompt": "", "latent_width": 1024, "latent_height": 1024, "mode": "填充", "ref_image_size": "自动"}},
            "9": {"class_type": "KSampler", "inputs": {"model": ["1", 0], "seed": 0, "steps": 8, "cfg": 1.0, "sampler_name": "euler", "scheduler": "simple", "positive": ["8", 0], "negative": ["8", 1], "latent_image": ["8", 2], "denoise": 1.0}},
            "10": {"class_type": "VAEDecode", "inputs": {"samples": ["9", 0], "vae": ["7", 0]}},
            "11": {"class_type": "SaveImage", "inputs": {"images": ["10", 0], "filename_prefix": "Manju/image"}},
        }
        bindings = {key: [] for key in SCALARS}
        bindings.update({"prompt": [_binding("8", "prompt")], "negative_prompt": [_binding("8", "negative_prompt")], "width": [_binding("8", "latent_width")], "height": [_binding("8", "latent_height")], "images": [], "mask": None})
        for key in ("seed", "steps", "cfg", "denoise"):
            bindings[key] = [_binding("9", key)]
        if mode != "text_to_image":
            for index in range(3):
                node_id = str(30 + index)
                graph[node_id] = {"class_type": "LoadImage", "inputs": {"image": f"manju_reference_{index + 1}.png"}}
                graph["8"]["inputs"][f"image_{index + 1:02d}"] = [node_id, 0]
                bindings["images"].append(_binding(node_id, "image"))
        if mode == "edit":
            graph["40"] = {"class_type": "LoadImage", "inputs": {"image": "manju_mask.png"}}
            graph["8"]["inputs"]["mask"] = ["40", 1]
            bindings["mask"] = _binding("40", "image")
        result.append({
            "id": f"builtin-qwen21-{mode}", "name": title, "mode": mode,
            "description": "本地 Qwen Image 2.1 Turbo，中文提示词，8 步 / CFG 1；需要 Goohaitools 的 TextEncodeQwenImage21GH。" + ("按图片顺序描述图1、图2、图3；参考条件不保证人物完全一致。" if mode == "reference" else "第一张图为编辑底图，可再提供两张参考图；可选白改黑保蒙版（边缘会羽化），目标尺寸须为32的倍数。" if mode == "edit" else "目标尺寸须为32的倍数。"),
            "api_graph": graph, "bindings": bindings,
            "capabilities": {"min_images": int(mode != "text_to_image"), "max_images": 0 if mode == "text_to_image" else 3, "requires_mask": False, "supports_mask": mode == "edit", "reference_kind": "none" if mode == "text_to_image" else "image_conditioning"},
            "defaults": {"seed": 0, "width": 1024, "height": 1024, "steps": 8, "cfg": 1.0, "denoise": 1.0, "negative_prompt": ""}, "output_nodes": ["11"],
        })
    return result


def _link(value: Any) -> bool:
    return isinstance(value, list) and len(value) == 2 and isinstance(value[0], str) and isinstance(value[1], int) and not isinstance(value[1], bool)


def _ancestors(graph: dict, outputs: list[str]) -> set[str]:
    found, pending = set(), list(outputs)
    while pending:
        node_id = pending.pop()
        if node_id in found or node_id not in graph:
            continue
        found.add(node_id)
        node = graph[node_id]
        if isinstance(node, dict) and isinstance(node.get("inputs"), dict):
            pending.extend(value[0] for value in node["inputs"].values() if _link(value))
    return found


def infer_bindings(graph: dict, mode: str = "text_to_image") -> dict:
    result = {key: [] for key in SCALARS}
    result.update(images=[], mask=None)
    negative_nodes = set()
    for node in graph.values():
        inputs = node.get("inputs", {}) if isinstance(node, dict) else {}
        if _link(inputs.get("negative")):
            negative_nodes.update(_ancestors(graph, [inputs["negative"][0]]))
    for node_id, node in graph.items():
        if not isinstance(node, dict) or not isinstance(node.get("inputs"), dict):
            continue
        kind, inputs = node.get("class_type", ""), node["inputs"]
        for key in SCALARS:
            names = {"width": ("width", "latent_width"), "height": ("height", "latent_height"), "seed": ("seed", "noise_seed")}.get(key, (key,))
            for name in names:
                if name in inputs and not _link(inputs[name]):
                    result[key].append(_binding(node_id, name))
        if kind == "CLIPTextEncode" and "text" in inputs:
            result["negative_prompt" if node_id in negative_nodes else "prompt"].append(_binding(node_id, "text"))
        if kind in {"LoadImage", "LoadImageMask"} and "image" in inputs:
            used_as_mask = any(_link(v) and v[0] == node_id and ("mask" in name.lower() or kind == "LoadImageMask") for consumer in graph.values() if isinstance(consumer, dict) for name, v in consumer.get("inputs", {}).items())
            if used_as_mask and result["mask"] is None:
                result["mask"] = _binding(node_id, "image")
            else:
                result["images"].append(_binding(node_id, "image"))
    return result


class WorkflowService:
    def __init__(self, store: Store, comfy):
        self.store, self.comfy = store, comfy
        with store.tx():
            store.conn.execute("""CREATE TABLE IF NOT EXISTS workflows(
                id TEXT PRIMARY KEY, name TEXT NOT NULL, mode TEXT NOT NULL,
                definition TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 1,
                builtin INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL, deleted_at TEXT, validation TEXT)""")
            for value in builtin_workflows():
                timestamp = now()
                store.conn.execute("INSERT OR IGNORE INTO workflows(id,name,mode,definition,builtin,created_at,updated_at) VALUES(?,?,?,?,1,?,?)", (value["id"], value["name"], value["mode"], encode(value), timestamp, timestamp))

    @staticmethod
    def _row(row) -> dict:
        result = json.loads(row["definition"])
        result.update({key: row[key] for key in ("id", "name", "mode", "revision", "created_at", "updated_at")})
        result.update(builtin=bool(row["builtin"]), read_only=bool(row["builtin"]), validation=json.loads(row["validation"]) if row["validation"] else None)
        result["ready"] = result["validation"]["valid"] if result["validation"] is not None else None
        graph = result.get("api_graph", {})
        if any(node.get("class_type") == "TextEncodeQwenImage21GH" for node in graph.values()):
            result.setdefault("capabilities", {}).setdefault("reference_mapping", "numbered")
            result["bindings"]["negative_prompt"] = [binding for binding in result["bindings"].get("negative_prompt", []) if graph.get(binding.get("node_id"), {}).get("class_type") != "TextEncodeQwenImage21GH"]
        return result

    def list(self, mode: str | None = None) -> list[dict]:
        if mode is not None and mode not in MODES:
            raise DomainError(422, "工作流模式不正确。", "workflow_mode_invalid")
        with self.store.lock:
            rows = self.store.conn.execute("SELECT * FROM workflows WHERE deleted_at IS NULL ORDER BY builtin DESC,created_at,id").fetchall()
            return [self._row(row) for row in rows if mode is None or row["mode"] == mode]

    def get(self, workflow_id: str) -> dict:
        with self.store.lock:
            row = self.store.conn.execute("SELECT * FROM workflows WHERE id=? AND deleted_at IS NULL", (workflow_id,)).fetchone()
            if row is None:
                raise DomainError(404, "工作流不存在或已删除。", "workflow_not_found")
            return self._row(row)

    def _normalize(self, payload: dict) -> dict:
        if not isinstance(payload, dict):
            raise DomainError(422, "工作流须为 JSON 对象。", "workflow_invalid")
        value = deepcopy(payload)
        value["name"] = Store.validate_name(value.get("name", "导入的工作流"))
        value["description"] = str(value.get("description", ""))[:10000]
        value["mode"] = value.get("mode", "text_to_image")
        if value["mode"] not in MODES:
            raise DomainError(422, "工作流模式须为 text_to_image、reference 或 edit。", "workflow_mode_invalid")
        graph = value.get("api_graph", {})
        if not isinstance(graph, dict) or len(graph) > 1000 or "nodes" in graph or "links" in graph:
            raise DomainError(422, "请导入 ComfyUI 的 API 格式 JSON（节点 ID 对象），不是界面工作流格式。", "workflow_api_format_required")
        if any(not isinstance(node_id, str) or not isinstance(node, dict) or not isinstance(node.get("class_type"), str) or not isinstance(node.get("inputs"), dict) for node_id, node in graph.items()):
            raise DomainError(422, "每个 API 节点须包含 class_type 文本和 inputs 对象。", "workflow_node_invalid")
        if len(encode(graph).encode("utf-8")) > 8 * 1024 * 1024:
            raise DomainError(413, "工作流 JSON 超过 8 MB。", "workflow_too_large")
        value["api_graph"] = graph
        inferred = infer_bindings(graph, value["mode"])
        bindings = value.get("bindings", inferred)
        if not isinstance(bindings, dict):
            raise DomainError(422, "输入映射须为 JSON 对象。", "workflow_bindings_invalid")
        value["bindings"] = {key: bindings.get(key, [] if key != "mask" else None) for key in (*SCALARS, "images", "mask")}
        count = len(value["bindings"]["images"]) if isinstance(value["bindings"]["images"], list) else 0
        is_conditioning = any(isinstance(node, dict) and any(part in node.get("class_type", "") for part in ("QwenImage", "IPAdapter", "CLIPVision", "ReferenceLatent")) for node in graph.values())
        default_caps = {"min_images": int(value["mode"] != "text_to_image"), "max_images": count, "supports_mask": value["bindings"]["mask"] is not None, "requires_mask": False, "reference_kind": "image_conditioning" if is_conditioning and count else "img2img" if count else "none"}
        capabilities = value.get("capabilities", {})
        if not isinstance(capabilities, dict):
            raise DomainError(422, "工作流能力须为 JSON 对象。", "workflow_capabilities_invalid")
        value["capabilities"] = {**default_caps, **capabilities}
        if value["capabilities"].get("reference_mapping", "unsupported") not in ("numbered", "unsupported"):
            raise DomainError(422, "主体名称映射方式无效。", "workflow_capabilities_invalid")
        if any(node.get("class_type") == "TextEncodeQwenImage21GH" for node in graph.values()):
            value["capabilities"].setdefault("reference_mapping", "numbered")
            # This encoder explicitly ignores its negative_prompt input.
            value["bindings"]["negative_prompt"] = [binding for binding in value["bindings"].get("negative_prompt", []) if graph.get(binding.get("node_id"), {}).get("class_type") != "TextEncodeQwenImage21GH"]
        defaults = {}
        for key in (*NUMERIC, "negative_prompt"):
            mappings = value["bindings"][key]
            if isinstance(mappings, list) and mappings and isinstance(mappings[0], dict):
                binding = mappings[0]
                defaults[key] = graph.get(str(binding.get("node_id")), {}).get("inputs", {}).get(binding.get("input_name"))
        if not isinstance(value.get("defaults", {}), dict):
            raise DomainError(422, "默认参数须为 JSON 对象。", "workflow_defaults_invalid")
        value["defaults"] = {**defaults, **value.get("defaults", {})}
        value["output_nodes"] = value.get("output_nodes", [key for key, node in graph.items() if isinstance(node, dict) and node.get("class_type") == "SaveImage"])
        return {key: value[key] for key in ("name", "description", "mode", "api_graph", "bindings", "capabilities", "defaults", "output_nodes")}

    def create(self, payload: dict) -> dict:
        value, workflow_id, timestamp = self._normalize(payload), new_id(), now()
        with self.store.tx():
            self.store.conn.execute("INSERT INTO workflows(id,name,mode,definition,created_at,updated_at) VALUES(?,?,?,?,?,?)", (workflow_id, value["name"], value["mode"], encode(value), timestamp, timestamp))
            self.store.emit("workflow.created", {"workflow_id": workflow_id})
        return self.get(workflow_id)

    def import_graph(self, payload: dict) -> dict:
        return self.create(payload)

    def update(self, workflow_id: str, payload: dict) -> dict:
        with self.store.tx():
            previous = self.get(workflow_id)
            if previous["read_only"]:
                raise DomainError(409, "内置模板只读，请复制后编辑。", "workflow_read_only")
            if payload.get("revision") != previous["revision"]:
                raise DomainError(409, "工作流已在另一处更新，请重新加载。", "workflow_revision_conflict", revision=previous["revision"])
            value = self._normalize({**previous, **payload})
            self.store.conn.execute("UPDATE workflows SET name=?,mode=?,definition=?,revision=revision+1,updated_at=?,validation=NULL WHERE id=?", (value["name"], value["mode"], encode(value), now(), workflow_id))
            self.store.emit("workflow.updated", {"workflow_id": workflow_id})
        return self.get(workflow_id)

    def duplicate(self, workflow_id: str) -> dict:
        value = self.get(workflow_id)
        value["name"] = value["name"][:245] + " 副本"
        return self.create(value)

    def delete(self, workflow_id: str) -> dict:
        with self.store.tx():
            value = self.get(workflow_id)
            if value["read_only"]:
                raise DomainError(409, "内置模板不可删除，请管理其副本。", "workflow_read_only")
            self.store.conn.execute("UPDATE workflows SET deleted_at=?,updated_at=? WHERE id=?", (now(), now(), workflow_id))
            self.store.emit("workflow.deleted", {"workflow_id": workflow_id})
        return {"deleted": True, "id": workflow_id}

    def object_info(self) -> dict:
        try:
            response = httpx.get(f"http://127.0.0.1:{self.comfy.port}/object_info", timeout=20, trust_env=False)
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, dict) or not data:
                raise ValueError("empty node catalog")
            return data
        except (httpx.HTTPError, ValueError) as error:
            raise DomainError(503, "无法读取本地 ComfyUI 节点列表，请启动服务后重新校验。", "comfy_unavailable") from error

    def validate(self, workflow_or_id: str | dict, online: bool = True) -> dict:
        value = self.get(workflow_or_id) if isinstance(workflow_or_id, str) else deepcopy(workflow_or_id)
        catalog, connection_error = {}, None
        if online:
            try:
                catalog = self.object_info()
            except DomainError as error:
                connection_error = error.detail
        report = self._validate(value, catalog)
        report["online"] = bool(catalog)
        if connection_error:
            report["errors"].append({"code": connection_error["code"], "message": connection_error["message"]})
        if not online:
            report["warnings"].append({"code": "offline_validation", "message": "仅检查图结构，尚未核验本机节点和模型。"})
        report["valid"] = not report["errors"]
        if isinstance(workflow_or_id, str):
            with self.store.tx():
                self.store.conn.execute("UPDATE workflows SET validation=? WHERE id=? AND revision=?", (encode(report), value["id"], value["revision"]))
                self.store.emit("workflow.validated", {"workflow_id": value["id"], "valid": report["valid"]})
        return report

    @staticmethod
    def _validate(value: dict, catalog: dict) -> dict:
        errors, warnings = [], []
        def issue(code, message, node_id=None, input_name=None):
            item = {"code": code, "message": message}
            if node_id is not None:
                item["node_id"] = str(node_id)
            if input_name is not None:
                item["input_name"] = input_name
            errors.append(item)
        graph = value.get("api_graph", {})
        outputs = value.get("output_nodes", [])
        if not isinstance(outputs, list) or any(not isinstance(item, str) for item in outputs):
            outputs = []
            issue("workflow_output_invalid", "输出节点须为节点 ID 数组。")
        if not graph:
            issue("workflow_empty", "工作流没有节点。")
        for output in outputs:
            if not isinstance(graph.get(output), dict) or graph[output].get("class_type") != "SaveImage":
                issue("workflow_output_invalid", "输出必须指向 SaveImage 节点。", output)
        if not outputs:
            issue("workflow_output_missing", "需要至少一个 SaveImage 输出节点。")
        active = _ancestors(graph, outputs)
        for node_id, node in graph.items():
            if not isinstance(node, dict) or not isinstance(node.get("class_type"), str) or not isinstance(node.get("inputs"), dict):
                issue("workflow_node_invalid", "节点须包含 class_type 和 inputs。", node_id)
                continue
            for name, item in node["inputs"].items():
                if _link(item) and (item[0] not in graph or item[1] < 0):
                    issue("workflow_link_invalid", "连接指向不存在的节点或输出。", node_id, name)
                if name in {"seed", "noise_seed"} and isinstance(item, (int, float)) and item > 2**53 - 1:
                    issue("workflow_seed_precision", "种子不能超过 9007199254740991，以保证网页与任务记录精确一致。", node_id, name)
            if node_id not in active:
                warnings.append({"code": "workflow_unused_node", "message": "该节点未连接到输出。", "node_id": node_id})
        # DFS detects cycles even if a malformed graph is disconnected from output.
        colors = {}
        def visit(node_id):
            if colors.get(node_id) == 1:
                issue("workflow_cycle", "工作流包含循环连接。", node_id)
                return
            if colors.get(node_id) == 2:
                return
            colors[node_id] = 1
            node = graph.get(node_id)
            if isinstance(node, dict) and isinstance(node.get("inputs"), dict):
                for item in node["inputs"].values():
                    if _link(item) and item[0] in graph:
                        visit(item[0])
            colors[node_id] = 2
        try:
            for node_id in graph:
                visit(node_id)
        except RecursionError:
            issue("workflow_too_deep", "工作流连接层数过深。")
        bindings = value.get("bindings", {})
        file_targets, assigned = set(), set()
        for key in (*SCALARS, "images", "mask"):
            mapping = bindings.get(key)
            mappings = [] if mapping is None else [mapping] if key == "mask" else mapping
            if not isinstance(mappings, list):
                issue("workflow_binding_invalid", f"{key} 映射须为数组。")
                continue
            for binding in mappings:
                if not isinstance(binding, dict) or not isinstance(binding.get("node_id"), str) or not isinstance(binding.get("input_name"), str):
                    issue("workflow_binding_invalid", f"{key} 映射须包含 node_id 和 input_name。")
                    continue
                node_id, name = binding["node_id"], binding["input_name"]
                target = (node_id, name)
                if target in assigned:
                    issue("workflow_binding_duplicate", "同一个节点输入不能被多个参数覆盖。", node_id, name)
                assigned.add(target)
                node = graph.get(node_id, {})
                if not isinstance(node, dict):
                    node = {}
                if name not in node.get("inputs", {}):
                    issue("workflow_binding_missing", f"{key} 映射的输入不存在。", node_id, name)
                elif _link(node["inputs"][name]):
                    issue("workflow_binding_link", "映射须指向实际参数，不能覆盖图连接。", node_id, name)
                if node_id not in active:
                    issue("workflow_binding_unused", f"{key} 映射未连接到 SaveImage，输入不会生效。", node_id, name)
                if key in {"images", "mask"}:
                    file_targets.add(target)
                    if node.get("class_type") not in {"LoadImage", "LoadImageMask"} or name != "image":
                        issue("workflow_image_binding_invalid", "图片映射须指向 LoadImage / LoadImageMask 的 image 文件输入。", node_id, name)
        if not bindings.get("prompt"):
            issue("workflow_prompt_missing", "需要映射正向提示词输入。")
        for key, default in value.get("defaults", {}).items():
            if key not in NUMERIC and key != "negative_prompt":
                continue
            mappings = bindings.get(key, [])
            if not mappings:
                if key in NUMERIC:
                    issue("workflow_default_unbound", f"默认参数 {key} 没有对应输入映射。")
                continue
            if key == "negative_prompt":
                if not isinstance(default, str):
                    issue("workflow_default_invalid", "默认负面描述须为文本。")
                continue
            if key == "seed" and isinstance(default, int) and default == -1:
                # -1 is a workbench instruction; it is resolved before ComfyUI
                # sees the seed and must not be checked against its min=0.
                continue
            low, high = LIMITS[key]
            if not isinstance(default, (int, float)) or isinstance(default, bool) or not math.isfinite(default) or key in INTEGER and not isinstance(default, int) or not low <= default <= high:
                issue("workflow_default_invalid", f"默认参数 {key} 的类型或范围不正确。")
                continue
            for mapping in mappings if isinstance(mappings, list) else []:
                if not isinstance(mapping, dict):
                    continue
                node_id, name = mapping.get("node_id"), mapping.get("input_name")
                if not isinstance(node_id, str) or not isinstance(name, str):
                    continue
                node = graph.get(node_id, {})
                node_spec = catalog.get(node.get("class_type"), {}) if isinstance(node, dict) else {}
                sections = node_spec.get("input", {})
                field = sections.get("required", {}).get(name, sections.get("optional", {}).get(name, []))
                options = field[1] if len(field) > 1 and isinstance(field[1], dict) else {}
                if default < options.get("min", -math.inf) or default > options.get("max", math.inf) or key in {"width", "height"} and options.get("step") and default % options["step"]:
                    issue("workflow_default_invalid", f"默认参数 {key} 不符合节点范围或尺寸步长要求。", node_id, name)
        caps = value.get("capabilities", {})
        image_bindings = bindings.get("images", [])
        image_count = len(image_bindings) if isinstance(image_bindings, list) else 0
        low, high = caps.get("min_images", 0), caps.get("max_images", 0)
        if any(not isinstance(n, int) or isinstance(n, bool) for n in (low, high)) or not 0 <= low <= high <= image_count:
            issue("workflow_image_limits_invalid", "引用图片数量范围须与实际映射槽位一致。")
        if value.get("mode") in {"reference", "edit"} and (not isinstance(low, int) or low < 1):
            issue("workflow_image_required", "参考和编辑模式至少需要一张图片。")
        if caps.get("requires_mask") and not caps.get("supports_mask") or bool(caps.get("supports_mask")) != bool(bindings.get("mask")):
            issue("workflow_mask_invalid", "蒙版能力与实际蒙版映射不一致。")
        if value.get("mode") == "reference" and caps.get("reference_kind") != "image_conditioning":
            issue("workflow_not_reference", "参考模式需要图像条件工作流；普通 img2img 应使用编辑模式。")
        for node_id, node in graph.items():
            if not isinstance(node, dict) or not isinstance(node.get("inputs"), dict):
                continue
            kind, inputs = node.get("class_type"), node["inputs"]
            spec = catalog.get(kind)
            if catalog and not spec:
                issue("workflow_node_unavailable", f"本机缺少节点：{kind}", node_id)
                continue
            if not spec:
                continue
            if spec.get("api_node") or "comfy_api_nodes" in spec.get("python_module", "") or "/api" in spec.get("category", "").lower():
                issue("workflow_remote_node", "本地工作流不接受云 API 节点。", node_id)
            sections = spec.get("input", {})
            required, optional = sections.get("required", {}), sections.get("optional", {})
            for name in required:
                if name not in inputs:
                    issue("workflow_input_required", "节点缺少必填输入。", node_id, name)
            for name, item in inputs.items():
                field = required.get(name, optional.get(name))
                if field is None:
                    # Modern autogrow definitions are not expanded in object_info.
                    if not any(isinstance(v, list) and v and v[0] == "COMFY_AUTOGROW_V3" for v in [*required.values(), *optional.values()]):
                        issue("workflow_input_unknown", "节点不存在该输入。", node_id, name)
                    continue
                expected = field[0] if field else None
                options = field[1] if len(field) > 1 and isinstance(field[1], dict) else {}
                choices = expected if isinstance(expected, list) else options.get("options") if expected == "COMBO" else None
                if _link(item):
                    source = graph.get(item[0], {})
                    source_spec = catalog.get(source.get("class_type"), {}) if isinstance(source, dict) else {}
                    source_outputs = source_spec.get("output", [])
                    if source_spec and item[1] >= len(source_outputs):
                        issue("workflow_output_index_invalid", "连接输出序号超出节点输出数量。", node_id, name)
                    elif source_spec and isinstance(expected, str) and expected != "*" and source_outputs[item[1]] not in (expected, "*"):
                        issue("workflow_link_type_invalid", f"连接类型 {source_outputs[item[1]]} 与 {expected} 不匹配。", node_id, name)
                elif choices is not None and (node_id, name) not in file_targets and item not in choices:
                    issue("workflow_choice_unavailable", f"本机不存在所选模型或选项：{item}", node_id, name)
                elif isinstance(expected, str) and expected in ("INT", "FLOAT"):
                    numeric = isinstance(item, (int, float)) and not isinstance(item, bool) and math.isfinite(item)
                    if not numeric or expected == "INT" and not isinstance(item, int) or numeric and (item < options.get("min", -math.inf) or item > options.get("max", math.inf)):
                        issue("workflow_number_invalid", "数值类型或范围不符合节点要求。", node_id, name)
                    elif options.get("step") and expected == "INT" and name in {"width", "height", "latent_width", "latent_height"} and item % options["step"]:
                        issue("workflow_dimension_step", f"尺寸须为 {options['step']} 的倍数。", node_id, name)
                elif expected == "STRING" and not isinstance(item, str):
                    issue("workflow_string_invalid", "节点输入须为文本。", node_id, name)
                elif expected == "BOOLEAN" and not isinstance(item, bool):
                    issue("workflow_boolean_invalid", "节点输入须为布尔值。", node_id, name)
                elif isinstance(expected, str) and expected in {"MODEL", "CLIP", "VAE", "CONDITIONING", "LATENT", "IMAGE", "MASK", "CLIP_VISION", "CLIP_VISION_OUTPUT", "CONTROL_NET"}:
                    issue("workflow_connection_required", f"{expected} 输入必须连接到节点输出。", node_id, name)
            if kind == "SaveImage" and not _link(inputs.get("images")):
                issue("workflow_output_disconnected", "SaveImage 未连接图像输出。", node_id, "images")
        if catalog and value.get("mode") == "reference":
            # Follow actual connections: merely labelling an img2img graph as a
            # reference workflow must not bypass the conditioning requirement.
            for binding in image_bindings if isinstance(image_bindings, list) else []:
                if not isinstance(binding, dict):
                    continue
                source_id = binding.get("node_id")
                descendants, pending = set(), [source_id]
                while pending:
                    source = pending.pop()
                    for target, node in graph.items():
                        if target in descendants or not isinstance(node, dict):
                            continue
                        if any(_link(v) and v[0] == source for v in node.get("inputs", {}).values()):
                            descendants.add(target)
                            pending.append(target)
                conditioning = False
                for target in descendants & active:
                    output_types = catalog.get(graph[target].get("class_type"), {}).get("output", [])
                    for consumer_id in active:
                        for item in graph[consumer_id].get("inputs", {}).values():
                            if _link(item) and item[0] == target and 0 <= item[1] < len(output_types) and output_types[item[1]] in {"CONDITIONING", "MODEL"}:
                                conditioning = True
                if not conditioning:
                    issue("workflow_reference_unused", "图片未进入图像条件或模型参考分支，仅作为初始 latent 不属于参考生图。", source_id)
        return {"valid": not errors, "online": bool(catalog), "checked_at": now(), "errors": errors, "warnings": warnings, "output_nodes": outputs}

    def prepare(self, workflow_or_id: str | dict, prompt: str, negative_prompt: str = "", reference_images: list[str] | None = None, mask_image: str | None = None, parameters: dict | None = None, output_prefix: str | None = None) -> dict:
        backend_port = self.comfy.port
        value = self.get(workflow_or_id) if isinstance(workflow_or_id, str) else deepcopy(workflow_or_id)
        if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 50000:
            raise DomainError(422, "提示词须包含 1 至 50000 个字符。", "generation_prompt_invalid")
        if not isinstance(negative_prompt, str) or len(negative_prompt) > 50000:
            raise DomainError(422, "负向提示词须为不超过 50000 字符的文本。", "generation_prompt_invalid")
        report = self.validate(value, online=True)
        if not report["valid"]:
            raise DomainError(422 if report["online"] else 503, "工作流校验未通过，请检查节点、模型与输入映射。", "workflow_validation_failed", validation=report)
        references, parameters = reference_images or [], parameters or {}
        caps, bindings = value["capabilities"], value["bindings"]
        if not isinstance(references, list) or not caps["min_images"] <= len(references) <= caps["max_images"]:
            raise DomainError(422, f"该工作流需要 {caps['min_images']} 至 {caps['max_images']} 张图片。", "workflow_image_count_invalid")
        if caps["requires_mask"] and not mask_image or mask_image and not caps["supports_mask"]:
            raise DomainError(422, "蒙版输入与工作流能力不匹配。", "workflow_mask_required")
        for filename in [*references, *([mask_image] if mask_image else [])]:
            if not isinstance(filename, str) or not filename or "\\" in filename or PurePosixPath(filename).is_absolute() or ".." in PurePosixPath(filename).parts or ":" in filename:
                raise DomainError(422, "ComfyUI 图片须为已上传的相对文件名。", "workflow_image_filename_invalid")
        if not isinstance(parameters, dict) or set(parameters) - NUMERIC:
            raise DomainError(422, "包含不支持的生成参数。", "workflow_parameters_invalid")
        resolved = {key: val for key, val in value.get("defaults", {}).items() if key in NUMERIC and bindings.get(key)}
        resolved.update(parameters)
        if isinstance(resolved.get("seed"), int) and resolved["seed"] == -1:
            resolved["seed"] = secrets.randbits(31)
        for key, item in resolved.items():
            low, high = LIMITS[key]
            if not bindings.get(key):
                raise DomainError(422, f"该工作流没有映射参数 {key}。", "workflow_parameter_unbound")
            if not isinstance(item, (int, float)) or isinstance(item, bool) or not math.isfinite(item) or key in INTEGER and not isinstance(item, int) or not low <= item <= high:
                raise DomainError(422, f"参数 {key} 的类型或范围不正确。", "workflow_parameter_invalid")
        graph = deepcopy(value["api_graph"])
        for key, item in {"prompt": prompt, "negative_prompt": negative_prompt, **resolved}.items():
            for binding in bindings.get(key, []):
                graph[binding["node_id"]]["inputs"][binding["input_name"]] = item
        removed = set()
        for index, binding in enumerate(bindings.get("images", [])):
            if index < len(references):
                graph[binding["node_id"]]["inputs"][binding["input_name"]] = references[index]
            else:
                removed.add(binding["node_id"])
        if bindings.get("mask"):
            binding = bindings["mask"]
            if mask_image:
                graph[binding["node_id"]]["inputs"][binding["input_name"]] = mask_image
            else:
                removed.add(binding["node_id"])
        for node_id in removed:
            graph.pop(node_id, None)
        for node in graph.values():
            node["inputs"] = {name: item for name, item in node["inputs"].items() if not (_link(item) and item[0] in removed)}
        # Comfy executes every output node present in the submitted prompt.
        # Retain only the selected outputs and their dependencies.
        live_nodes = _ancestors(graph, value["output_nodes"])
        graph = {node_id: node for node_id, node in graph.items() if node_id in live_nodes}
        prefix = output_prefix or "Manju/" + new_id()
        if not isinstance(prefix, str) or not re.fullmatch(r"[A-Za-z0-9_/-]{1,180}", prefix) or prefix.startswith("/") or ".." in prefix:
            raise DomainError(422, "输出前缀须为安全的相对路径。", "workflow_output_prefix_invalid")
        for node_id in value["output_nodes"]:
            graph[node_id]["inputs"]["filename_prefix"] = prefix
        # A pruned optional image cannot silently remove a required graph input.
        compiled = deepcopy(value)
        compiled["api_graph"] = graph
        compiled["bindings"]["images"] = compiled["bindings"]["images"][:len(references)]
        if not mask_image:
            compiled["bindings"]["mask"] = None
        compiled["capabilities"].update(max_images=len(references), supports_mask=bool(mask_image))
        check = self._validate(compiled, self.object_info())
        if self.comfy.port != backend_port:
            raise DomainError(409, "准备工作流期间 ComfyUI 地址发生变化，请重新提交。", "comfy_backend_changed")
        if not check["valid"]:
            raise DomainError(422, "注入输入后的工作流无效，请检查可选图片连接与参数范围。", "workflow_validation_failed", validation=check)
        return {"api_graph": graph, "output_nodes": list(value["output_nodes"]), "workflow": value, "parameters": resolved}
