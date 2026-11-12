from copy import deepcopy
from types import SimpleNamespace

import pytest

from manju.store import DomainError, Store
from manju.reference_contract import compile_prompt
from manju.workflows import WorkflowService, builtin_workflows


def catalog():
    def node(inputs, outputs, optional=None, **extra):
        return {"input": {"required": inputs, "optional": optional or {}}, "output": outputs, **extra}
    return {
        "UNETLoader": node({"unet_name": [["qwen_image_2.1_turbo_int8_convrot.safetensors", "minimax_h3_image_pruned_int8_convrot.safetensors"]], "weight_dtype": [["default"]]}, ["MODEL"]),
        "CLIPLoader": node({"clip_name": [["qwen3vl_8b_int8_convrot.safetensors", "qwen3vl_32b_minimax_h3_int8_convrot.safetensors", "qwen3.5_9b_w4a8_gptq.safetensors"]], "type": [["qwen_image", "minimax"]]}, ["CLIP"], {"device": [["default", "cpu"]]}),
        "VAELoader": node({"vae_name": [["qwen_image_2.1_vae_bf16.safetensors", "minimax_h3_image_vae_fp16.safetensors"]]}, ["VAE"]),
        "TextEncodeQwenImage21GH": node({"clip": ["CLIP"], "prompt": ["STRING"], "negative_prompt": ["STRING"], "latent_width": ["INT", {"min": 32, "max": 4096, "step": 32}], "latent_height": ["INT", {"min": 32, "max": 4096, "step": 32}], "mode": [["填充", "裁剪"]], "ref_image_size": [["自动"]]}, ["CONDITIONING", "CONDITIONING", "LATENT", "INFO"], {"vae": ["VAE"], "mask": ["MASK"], **{f"image_{n:02d}": ["IMAGE"] for n in range(1, 4)}}),
        "MiniMaxH3ImageConditioning": node(
            {"clip": ["CLIP"], "prompt": ["STRING"], "width": ["INT", {"min": 0, "step": 32}], "height": ["INT", {"min": 0, "step": 32}]},
            ["CONDITIONING", "LATENT"], {"vae": ["VAE"], "images": ["COMFY_AUTOGROW_V3", {}]},
        ),
        "ConditioningZeroOut": node({"conditioning": ["CONDITIONING"]}, ["CONDITIONING"]),
        "PrimitiveStringMultiline": node({"value": ["STRING"]}, ["STRING"]),
        "PrimitiveBoolean": node({"value": ["BOOLEAN"]}, ["BOOLEAN"]),
        "StringReplace": node({"string": ["STRING"], "find": ["STRING"], "replace": ["STRING"]}, ["STRING"]),
        "JsonExtractString": node({"json_string": ["STRING"], "key": ["STRING"]}, ["STRING"]),
        "ComfySwitchNode": node({"switch": ["BOOLEAN"]}, ["COMFY_MATCHTYPE_V3"], {
            "on_false": ["COMFY_MATCHTYPE_V3"], "on_true": ["COMFY_MATCHTYPE_V3"],
        }),
        "PreviewAny": node({"source": ["*"]}, ["STRING"]),
        "TextGenerateV2": node({
            "clip": ["CLIP"], "prompt": ["STRING"], "max_length": ["INT"],
            "sampling_mode": ["COMFY_DYNAMICCOMBO_V3", {"options": [
                {"key": "on", "inputs": {"required": {
                    key: [kind] for key, kind in {
                        "temperature": "FLOAT", "top_k": "INT", "top_p": "FLOAT",
                        "min_p": "FLOAT", "repetition_penalty": "FLOAT", "presence_penalty": "FLOAT", "seed": "INT",
                    }.items()
                }}},
            ]}],
        }, ["STRING", "STRING"], {
            "images": ["COMFY_AUTOGROW_V3", {}], "thinking": ["BOOLEAN"], "use_default_template": ["BOOLEAN"],
            "mtp": [["auto"]], "system_prompt": ["STRING"],
        }),
        "ResizeImageMaskNode": node({
            "input": ["COMFY_MATCHTYPE_V3"], "scale_method": [["area"]],
            "resize_type": ["COMFY_DYNAMICCOMBO_V3", {"options": [
                {"key": "scale to multiple", "inputs": {"required": {"multiple": ["INT"]}}},
                {"key": "scale total pixels", "inputs": {"required": {"megapixels": ["FLOAT"]}}},
            ]}],
        }, ["COMFY_MATCHTYPE_V3"]),
        "KSampler": node({"model": ["MODEL"], "seed": ["INT", {"min": 0, "max": 2**64-1}], "steps": ["INT", {"min": 1, "max": 10000}], "cfg": ["FLOAT", {"min": 0, "max": 100}], "sampler_name": [["euler"]], "scheduler": [["simple"]], "positive": ["CONDITIONING"], "negative": ["CONDITIONING"], "latent_image": ["LATENT"], "denoise": ["FLOAT", {"min": 0, "max": 1}]}, ["LATENT"]),
        "VAEDecode": node({"samples": ["LATENT"], "vae": ["VAE"]}, ["IMAGE"]),
        "VAEEncode": node({"pixels": ["IMAGE"], "vae": ["VAE"]}, ["LATENT"]),
        "SaveImage": node({"images": ["IMAGE"], "filename_prefix": ["STRING"]}, ["IMAGE"]),
        "LoadImage": node({"image": [["some_other_uploaded_image.png"]]}, ["IMAGE", "MASK"]),
    }


@pytest.fixture
def workflows(tmp_path, monkeypatch):
    store = Store(tmp_path / "素材", tmp_path / "配置.json")
    service = WorkflowService(store, SimpleNamespace(port=19999))
    monkeypatch.setattr(service, "object_info", catalog)
    yield service
    store.close()


def test_builtin_catalog_models_and_modes(workflows):
    assert {w["mode"] for w in workflows.list()} == {"text_to_image", "reference", "edit"}
    revisions = {workflow["id"]: workflow.get("revision", 1) for workflow in builtin_workflows()}
    for value in workflows.list():
        assert value["read_only"] and value["revision"] == revisions[value["id"]]
        assert workflows.validate(value["id"])["valid"]
        assert workflows.get(value["id"])["ready"] is True
    with pytest.raises(DomainError, match="只读"):
        workflows.update("builtin-qwen21-edit", {"revision": 1, "name": "edit"})


def test_crud_revision_snapshot_and_persistence(workflows):
    copy = workflows.duplicate("builtin-qwen21-text_to_image")
    assert copy["builtin"] is False
    saved = workflows.update(copy["id"], {"revision": 1, "name": "中文镜头"})
    assert saved["name"] == "中文镜头" and saved["revision"] == 2
    with pytest.raises(DomainError) as conflict:
        workflows.update(copy["id"], {"revision": 1, "name": "旧修改"})
    assert conflict.value.status == 409
    workflows.delete(copy["id"])
    with pytest.raises(DomainError) as deleted:
        workflows.get(copy["id"])
    assert deleted.value.status == 404
    prepared = workflows.prepare(copy, "不受随后修改影响", parameters={"seed": 123})
    assert prepared["workflow"]["revision"] == 1
    assert prepared["api_graph"]["8"]["inputs"]["prompt"] == "不受随后修改影响"
    assert len(WorkflowService(workflows.store, workflows.comfy).list()) == len(builtin_workflows())


def test_h3_image_reference_slots_and_prompt_mapping(workflows):
    workflow = workflows.get("builtin-minimax-h3-image-reference")
    prompt = compile_prompt({
        "references": [
            {"id": "scene", "version_id": "v1"},
            {"id": "actor", "version_id": "v2", "description": "短发", "use_description": True},
        ],
        "prompt_parts": [{"type": "reference", "reference_id": "actor"}, {"type": "text", "text": "站在门口"}],
    }, workflow)
    assert prompt == "<Picture 2>站在门口\n<Picture 2>的主体设定：短发"
    graph = workflows.prepare(workflow, prompt, reference_images=["scene.png", "actor.png"])["api_graph"]
    conditioning = graph["32"]["inputs"]
    enhancer = graph["34"]["inputs"]
    assert conditioning["images.image_1"] == enhancer["images.image1"] == ["48", 0]
    assert conditioning["images.image_2"] == enhancer["images.image2"] == ["102", 0]
    assert "images.image_3" not in conditioning
    assert "images.image3" not in enhancer
    assert conditioning["vae"] == ["31", 0]
    assert graph["45"]["inputs"]["image"] == "scene.png"
    assert graph["102"]["inputs"]["image"] == "actor.png"
    assert graph["43"]["inputs"]["value"] == prompt
    assert graph["61"]["inputs"]["value"] is True
    assert graph["38"]["inputs"]["steps"] == 6
    assert graph["38"]["inputs"]["cfg"] == 1.0


def test_import_api_format_and_inferred_bindings(workflows):
    source = builtin_workflows()[0]
    imported = workflows.import_graph({"name": "新工作流", "api_graph": source["api_graph"]})
    assert imported["bindings"]["prompt"] == [{"node_id": "8", "input_name": "prompt"}]
    assert imported["defaults"]["width"] == 1024
    assert workflows.validate(imported)["valid"]
    with pytest.raises(DomainError) as invalid:
        workflows.import_graph({"api_graph": {"nodes": [], "links": []}})
    assert invalid.value.detail["code"] == "workflow_api_format_required"


def test_prepare_ordered_references_removes_unused_inputs(workflows):
    result = workflows.prepare("builtin-qwen21-reference", "保持图1人物，采用图2构图", reference_images=["manju/人物.png", "manju/构图.png"], parameters={"seed": 42, "width": 512, "height": 768}, output_prefix="Manju/job_42")
    graph = result["api_graph"]
    assert graph["30"]["inputs"]["image"] == "manju/人物.png"
    assert graph["31"]["inputs"]["image"] == "manju/构图.png"
    assert "32" not in graph and "image_03" not in graph["8"]["inputs"]
    assert graph["8"]["inputs"]["latent_width"] == 512
    assert graph["11"]["inputs"]["filename_prefix"] == "Manju/job_42"
    assert "32" in result["workflow"]["api_graph"]
    with pytest.raises(DomainError) as count:
        workflows.prepare("builtin-qwen21-reference", "角色", reference_images=[])
    assert count.value.detail["code"] == "workflow_image_count_invalid"


def test_edit_optional_mask_and_safe_filenames(workflows):
    without = workflows.prepare("builtin-qwen21-edit", "把背景改成夜晚", reference_images=["base.png"])
    assert "40" not in without["api_graph"]
    assert "mask" not in without["api_graph"]["8"]["inputs"]
    masked = workflows.prepare("builtin-qwen21-edit", "修改衣服", reference_images=["base.png"], mask_image="mask.png")
    assert masked["api_graph"]["40"]["inputs"]["image"] == "mask.png"
    assert masked["api_graph"]["8"]["inputs"]["mask"] == ["40", 1]
    for filename in ("../secret.png", "C:/secret.png", "sub\\secret.png"):
        with pytest.raises(DomainError) as unsafe:
            workflows.prepare("builtin-qwen21-edit", "修改", reference_images=[filename])
        assert unsafe.value.detail["code"] == "workflow_image_filename_invalid"


def test_models_node_types_and_numeric_constraints(workflows, monkeypatch):
    value = workflows.get("builtin-qwen21-text_to_image")
    value["api_graph"]["1"]["inputs"]["unet_name"] = "not-installed.safetensors"
    report = workflows.validate(value)
    assert any(e["code"] == "workflow_choice_unavailable" and e["node_id"] == "1" for e in report["errors"])
    value["api_graph"]["9"]["inputs"]["positive"] = ["7", 0]
    assert any(e["code"] == "workflow_link_type_invalid" for e in workflows.validate(value)["errors"])
    for params in ({"width": 513}, {"seed": -2}, {"cfg": float("inf")}, {"steps": True}, {"unexpected": 12}):
        with pytest.raises(DomainError):
            workflows.prepare("builtin-qwen21-text_to_image", "中文", parameters=params)
    altered = catalog()
    del altered["TextEncodeQwenImage21GH"]
    monkeypatch.setattr(workflows, "object_info", lambda: altered)
    assert any(e["code"] == "workflow_node_unavailable" for e in workflows.validate("builtin-qwen21-text_to_image")["errors"])


def test_bindings_must_reach_output_and_img2img_cannot_claim_reference(workflows):
    value = workflows.get("builtin-qwen21-reference")
    value["api_graph"]["8"]["inputs"].pop("image_01")
    assert any(e["code"] == "workflow_binding_unused" for e in workflows.validate(value)["errors"])
    value = workflows.get("builtin-qwen21-reference")
    for name in ("image_01", "image_02", "image_03"):
        value["api_graph"]["8"]["inputs"].pop(name)
    value["api_graph"].pop("31")
    value["api_graph"].pop("32")
    value["api_graph"]["50"] = {"class_type": "VAEEncode", "inputs": {"pixels": ["30", 0], "vae": ["7", 0]}}
    value["api_graph"]["9"]["inputs"]["latent_image"] = ["50", 0]
    value["bindings"]["images"] = value["bindings"]["images"][:1]
    value["capabilities"]["max_images"] = 1
    assert any(e["code"] == "workflow_reference_unused" for e in workflows.validate(value)["errors"])


def test_offline_remote_nodes_and_cycles(workflows, monkeypatch):
    def offline():
        raise DomainError(503, "未启动", "comfy_unavailable")
    monkeypatch.setattr(workflows, "object_info", offline)
    report = workflows.validate("builtin-qwen21-edit")
    assert not report["valid"] and not report["online"]
    assert report["errors"][0]["code"] == "comfy_unavailable"
    assert workflows.validate("builtin-qwen21-edit", online=False)["valid"]
    value = workflows.get("builtin-qwen21-text_to_image")
    value["api_graph"]["10"]["inputs"]["samples"] = ["11", 0]
    assert any(e["code"] == "workflow_cycle" for e in workflows.validate(value, online=False)["errors"])
    altered = catalog()
    altered["UNETLoader"]["api_node"] = True
    monkeypatch.setattr(workflows, "object_info", lambda: altered)
    assert any(e["code"] == "workflow_remote_node" for e in workflows.validate("builtin-qwen21-text_to_image")["errors"])


def test_invalid_draft_remains_editable(workflows):
    value = workflows.create({"name": "未完成草稿", "api_graph": {"1": {"class_type": "MissingPlugin", "inputs": {}}}})
    report = workflows.validate(value["id"])
    assert not report["valid"]
    assert workflows.get(value["id"])["ready"] is False
    valid = workflows.update(value["id"], {**builtin_workflows()[0], "revision": 1})
    assert valid["ready"] is None
    assert workflows.validate(valid)["valid"]


def test_unselected_output_pruned_and_backend_change_rejected(workflows, monkeypatch):
    value = workflows.get("builtin-qwen21-text_to_image")
    value["api_graph"]["unused_output"] = deepcopy(value["api_graph"]["11"])
    result = workflows.prepare(value, "只生成选定输出")
    assert "unused_output" not in result["api_graph"]
    calls = 0
    def changing_backend():
        nonlocal calls
        calls += 1
        if calls == 2:
            workflows.comfy.port = 19998
        return catalog()
    monkeypatch.setattr(workflows, "object_info", changing_backend)
    with pytest.raises(DomainError) as changed:
        workflows.prepare(value, "拒绝跨后端")
    assert changed.value.detail["code"] == "comfy_backend_changed"


@pytest.mark.parametrize("graph", [{"1": []}, {"1": {"class_type": "LoadImage", "inputs": "wrong"}}])
def test_malformed_api_node_rejected_without_internal_error(workflows, graph):
    with pytest.raises(DomainError) as malformed:
        workflows.create({"api_graph": graph})
    assert malformed.value.status == 422


@pytest.mark.parametrize("key,value", [("width", 513), ("cfg", ""), ("steps", 0), ("seed", -2), ("seed", 2**53)])
def test_invalid_defaults_reported_before_generation(workflows, key, value):
    draft = workflows.duplicate("builtin-qwen21-text_to_image")
    draft["defaults"][key] = value
    saved = workflows.update(draft["id"], draft)
    report = workflows.validate(saved["id"])
    assert not report["valid"]
    assert any(error["code"] == "workflow_default_invalid" for error in report["errors"])


def test_seed_json_safe_integer_boundary(workflows):
    value = workflows.get("builtin-qwen21-text_to_image")
    value["api_graph"]["9"]["inputs"]["seed"] = 2**53
    assert any(error["code"] == "workflow_seed_precision" for error in workflows.validate(value, online=False)["errors"])
    with pytest.raises(DomainError):
        workflows.prepare("builtin-qwen21-text_to_image", "中文", parameters={"seed": 2**53})
    result = workflows.prepare("builtin-qwen21-text_to_image", "中文", parameters={"seed": 2**53 - 1})
    assert result["api_graph"]["9"]["inputs"]["seed"] == 2**53 - 1


def test_default_random_seed_validates_and_resolves_before_comfy(workflows, monkeypatch):
    draft = workflows.duplicate("builtin-qwen21-text_to_image")
    draft["defaults"]["seed"] = -1
    saved = workflows.update(draft["id"], draft)
    assert workflows.validate(saved, online=False)["valid"]
    assert workflows.validate(saved)["valid"]
    monkeypatch.setattr("manju.workflows.secrets.randbits", lambda bits: 12345)
    result = workflows.prepare(saved, "默认随机种子")
    assert result["parameters"]["seed"] == 12345
    assert result["api_graph"]["9"]["inputs"]["seed"] == 12345
    assert result["workflow"]["defaults"]["seed"] == -1
    explicit = workflows.prepare(saved, "显式种子覆盖", parameters={"seed": 42})
    assert explicit["parameters"]["seed"] == 42
