from email.parser import BytesParser
from email.policy import default
from io import BytesIO
import json
from types import SimpleNamespace

import httpx
from PIL import Image
import pytest

from manju.generation import GenerationService
from manju.store import DomainError, Store
from manju.workflows import WorkflowService
from conftest import project, upload
from test_workflows import catalog


class ComfyFixture:
    """An isolated protocol peer: no call in these tests reaches a GPU service."""

    def __init__(self, image):
        self.image = image
        self.pending, self.running, self.history = [], [], {}
        self.uploads, self.submissions, self.calls = [], [], []
        self.images = {}
        self.timeout_after_accept = False
        self.targeted_cancel = True
        self.run_during_delete = False

    def complete(self, prompt_id, *, error=False):
        entry = next(item for item in self.pending + self.running if item[1] == prompt_id)
        self.pending = [item for item in self.pending if item[1] != prompt_id]
        self.running = [item for item in self.running if item[1] != prompt_id]
        self.history[prompt_id] = {"prompt": entry, "status": {"completed": True, "status_str": "error" if error else "success", "messages": [["execution_error", {"node_id": "9", "exception_message": "fixture failure"}]] if error else []}, "outputs": {} if error else {"11": {"images": [{"filename": "结果.png", "subfolder": "Manju", "type": "output"}]}}}

    def __call__(self, request):
        path = request.url.path
        self.calls.append((request.method, path))
        if path == "/upload/image":
            message = BytesParser(policy=default).parsebytes(b"Content-Type: " + request.headers["content-type"].encode() + b"\r\n\r\n" + request.read())
            fields = {part.get_param("name", header="content-disposition"): part for part in message.iter_parts()}
            image = fields["image"]
            self.uploads.append({"filename": image.get_filename(), "content": image.get_payload(decode=True)})
            return httpx.Response(200, json={"name": image.get_filename(), "subfolder": fields["subfolder"].get_payload(decode=True).decode()})
        if path == "/prompt":
            payload = json.loads(request.content)
            self.submissions.append(payload)
            entry = [len(self.submissions), payload["prompt_id"], payload["prompt"], {**payload["extra_data"], "client_id": payload["client_id"]}, ["11"]]
            self.pending.append(entry)
            if self.timeout_after_accept:
                raise httpx.ReadTimeout("accepted, reply lost", request=request)
            return httpx.Response(200, json={"prompt_id": payload["prompt_id"]})
        if path == "/queue" and request.method == "GET":
            return httpx.Response(200, json={"queue_running": self.running, "queue_pending": self.pending})
        if path == "/queue" and request.method == "POST":
            deleted = json.loads(request.content)["delete"]
            if self.run_during_delete:
                self.running += [item for item in self.pending if item[1] in deleted]
            self.pending = [item for item in self.pending if item[1] not in deleted]
            return httpx.Response(200)
        if path == "/history":
            return httpx.Response(200, json=self.history)
        if path.startswith("/history/"):
            prompt_id = path.rsplit("/", 1)[-1]
            return httpx.Response(200, json={prompt_id: self.history[prompt_id]} if prompt_id in self.history else {})
        if path == "/view":
            return httpx.Response(200, content=self.images.get(request.url.params.get("filename"), self.image))
        if path.startswith("/api/jobs/") and path.endswith("/cancel"):
            if not self.targeted_cancel:
                return httpx.Response(404, json={})
            prompt_id = path.split("/")[3]
            self.running = [item for item in self.running if item[1] != prompt_id]
            return httpx.Response(200, json={"cancelled": True})
        raise AssertionError(f"Unexpected request {request.method} {request.url}")


@pytest.fixture
def generation(client, png_bytes, monkeypatch):
    previous = client.app.state.generations
    previous.close()
    peer = ComfyFixture(png_bytes("green"))
    workflows = client.app.state.workflows
    comfy = SimpleNamespace(port=19123)
    workflows.comfy = comfy
    monkeypatch.setattr(workflows, "object_info", catalog)
    service = GenerationService(client.app.state.store, comfy, workflows, transport=httpx.MockTransport(peer))
    client.app.state.generations = service
    return service, peer


def submit(client, project_id, **values):
    payload = {"project_id": project_id, "workflow_id": "builtin-qwen21-text_to_image", "prompt": "雨夜车站中的二次元女孩", "parameters": {"width": 512, "height": 512, "steps": 4}, **values}
    response = client.post("/api/generations", json=payload)
    assert response.status_code == 202, response.text
    return response.json()


def test_generation_roundtrip_preserves_canvas_and_audits_exact_inputs(client, generation, png_bytes):
    service, peer = generation
    item = project(client)
    asset = upload(client, png_bytes("red"))
    version = asset["current_version_id"]
    updated = upload(client, png_bytes("blue"), asset_id=asset["id"])
    canvas = service.store.canvas(item["id"])
    canvas["nodes"] = [{"id": "prompt", "type": "media", "position": {"x": 20, "y": 40}, "data": {"kind": "image", "generation": {"prompt": "保留草稿"}}}]
    service.store.save_canvas(item["id"], canvas)
    job = submit(client, item["id"], workflow_id="builtin-qwen21-reference", source_node_id="prompt", references=[{"version_id": version}], request_id="same-generation")
    assert client.get("/api/assets", params={"project_id": item["id"]}).json()["total"] == 1
    service.tick()
    queued = service.get(job["id"])
    assert queued["status"] == "queued", queued
    assert peer.uploads[0]["content"] == png_bytes("red")
    assert queued["request"]["references"][0]["snapshot"]["id"] == version
    assert queued["request"]["resolved_parameters"]["seed"] == job["request"]["parameters"]["seed"]
    assert queued["mapped_graph"]["30"]["inputs"]["image"].endswith(version + ".png")
    assert queued["mapped_graph"]["8"]["inputs"]["prompt"] == job["prompt"]
    canvas = service.store.canvas(item["id"])
    canvas["nodes"][0]["position"]["x"] = 100
    canvas["nodes"].append({"id": "other", "type": "text", "position": {"x": 10, "y": 10}, "data": {"text": "生成期间的编辑"}})
    service.store.save_canvas(item["id"], canvas)
    peer.complete(queued["prompt_id"])
    service.tick()
    result = service.get(job["id"])
    assert result["status"] == "succeeded", result
    assert len(result["outputs"]) == 1
    output = result["outputs"][0]
    assert service.store.asset(output["asset_id"])["source"] == "comfyui"
    assert service.store.asset(asset["id"])["current_version_id"] == updated["current_version_id"]
    canvas = service.store.canvas(item["id"])
    assert len(canvas["nodes"]) == 2
    assert canvas["nodes"][0]["data"]["generation"]["prompt"] == "保留草稿"
    assert canvas["nodes"][0]["position"] == {"x": 100, "y": 40}
    assert canvas["nodes"][0]["data"]["generation_id"] == job["id"]
    assert canvas["nodes"][0]["data"]["image_history"][0]["version_id"] == output["version_id"]
    assert output["node_id"] == "prompt"
    assert canvas["edges"] == []
    assert any(event["type"] == "canvas.updated" and event["data"].get("reason") == "generation_result" for event in service.store.events(0))
    revision = canvas["revision"]
    service._collect(result, peer.history[queued["prompt_id"]])
    assert service.store.canvas(item["id"])["revision"] == revision
    assert service.store.assets()["total"] == 2


def test_request_id_seed_and_payload_conflict(client, generation):
    service, _ = generation
    item = project(client)
    first = submit(client, item["id"], request_id="one", parameters={"seed": -1})
    second = submit(client, item["id"], request_id="one", parameters={"seed": -1})
    assert first["id"] == second["id"]
    assert first["request"]["parameters"]["seed"] == second["request"]["parameters"]["seed"] >= 0
    assert first["request"]["parameters"]["seed"] < 2**31
    response = client.post("/api/generations", json={"project_id": item["id"], "workflow_id": first["workflow_id"], "prompt": "different", "request_id": "one"})
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "idempotency_conflict"
    assert client.get("/api/generations", params={"project_id": item["id"]}).json()["items"][0]["id"] == first["id"]
    unsafe = client.post("/api/generations", json={"project_id": item["id"], "workflow_id": first["workflow_id"], "prompt": "unsafe seed", "parameters": {"seed": 2**53}})
    assert unsafe.status_code == 422


def test_negative_prompt_default_is_frozen_and_explicit_empty_clears(client, generation):
    service, peer = generation
    workflow = service.workflows.duplicate("builtin-qwen21-text_to_image")
    service.workflows.update(workflow["id"], {"revision": workflow["revision"], "defaults": {**workflow["defaults"], "negative_prompt": "低清晰度，水印"}})
    item = project(client)
    defaulted = submit(client, item["id"], workflow_id=workflow["id"], request_id="negative-default")
    empty = submit(client, item["id"], workflow_id=workflow["id"], negative_prompt="")
    assert defaulted["request"]["negative_prompt"] == "低清晰度，水印"
    assert empty["request"]["negative_prompt"] == ""
    changed = service.workflows.get(workflow["id"])
    service.workflows.update(workflow["id"], {"revision": changed["revision"], "defaults": {**changed["defaults"], "negative_prompt": "另一默认值"}})
    assert submit(client, item["id"], workflow_id=workflow["id"], request_id="negative-default")["request"]["negative_prompt"] == "低清晰度，水印"
    service.tick()
    assert [payload["prompt"]["8"]["inputs"]["negative_prompt"] for payload in peer.submissions] == ["", ""]  # GH encoder ignores negative conditioning.
    peer.complete(service.get(defaulted["id"])["prompt_id"], error=True)
    service.tick()
    assert service.retry(defaulted["id"])["request"]["negative_prompt"] == "低清晰度，水印"


def test_omitted_seed_uses_frozen_workflow_default_and_explicit_seed_wins(client, generation):
    service, _ = generation
    workflow = service.workflows.duplicate("builtin-qwen21-text_to_image")
    service.workflows.update(workflow["id"], {"revision": workflow["revision"], "defaults": {**workflow["defaults"], "seed": 12345}})
    item = project(client)
    defaulted = submit(client, item["id"], workflow_id=workflow["id"], request_id="seed-default")
    assert defaulted["request"]["parameters"]["seed"] == 12345
    explicit = submit(client, item["id"], workflow_id=workflow["id"], parameters={"seed": 42})
    assert explicit["request"]["parameters"]["seed"] == 42
    random = submit(client, item["id"], workflow_id=workflow["id"], parameters={"seed": -1})
    assert 0 <= random["request"]["parameters"]["seed"] < 2**31
    changed = service.workflows.get(workflow["id"])
    service.workflows.update(workflow["id"], {"revision": changed["revision"], "defaults": {**changed["defaults"], "seed": 56789}})
    assert submit(client, item["id"], workflow_id=workflow["id"], request_id="seed-default")["request"]["parameters"]["seed"] == 12345


def test_unbound_seed_is_not_injected_into_custom_workflow(client, generation):
    service, peer = generation
    workflow = service.workflows.duplicate("builtin-qwen21-text_to_image")
    bindings, defaults = workflow["bindings"], workflow["defaults"]
    bindings["seed"] = []
    defaults.pop("seed")
    service.workflows.update(workflow["id"], {"revision": workflow["revision"], "bindings": bindings, "defaults": defaults})
    job = submit(client, project(client)["id"], workflow_id=workflow["id"])
    assert "seed" not in job["request"]["parameters"]
    service.tick()
    assert service.get(job["id"])["status"] == "queued"
    assert peer.submissions[0]["prompt"]["9"]["inputs"]["seed"] == 0


def test_default_random_seed_resolves_once_at_creation(client, generation, monkeypatch):
    service, peer = generation
    workflow = service.workflows.duplicate("builtin-qwen21-text_to_image")
    service.workflows.update(workflow["id"], {"revision": workflow["revision"], "defaults": {**workflow["defaults"], "seed": -1}})
    calls = []
    def random_seed(bits):
        calls.append(bits)
        return 54321
    monkeypatch.setattr("manju.generation.secrets.randbits", random_seed)
    item = project(client)
    first = submit(client, item["id"], workflow_id=workflow["id"], request_id="default-random")
    again = submit(client, item["id"], workflow_id=workflow["id"], request_id="default-random")
    assert first["id"] == again["id"]
    assert first["workflow_snapshot"]["defaults"]["seed"] == -1
    assert first["request"]["parameters"]["seed"] == 54321
    service.tick()
    assert service.get(first["id"])["status"] == "queued"
    assert peer.submissions[0]["prompt"]["9"]["inputs"]["seed"] == 54321
    assert calls == [31]


def test_lost_submission_response_recovers_without_resubmit(client, generation):
    service, peer = generation
    peer.timeout_after_accept = True
    job = submit(client, project(client)["id"])
    service.tick()
    assert service.get(job["id"])["status"] == "unknown"
    service.close()
    restarted = GenerationService(service.store, service.comfy, service.workflows, transport=httpx.MockTransport(peer))
    client.app.state.generations = restarted
    restarted.tick()
    recovered = restarted.get(job["id"])
    assert recovered["status"] == "queued"
    peer.complete(recovered["prompt_id"])
    restarted.tick()
    assert restarted.get(job["id"])["status"] == "succeeded"
    assert len(peer.submissions) == 1


def test_unknown_submission_never_retries_blindly(client, generation):
    service, peer = generation
    peer.timeout_after_accept = True
    job = submit(client, project(client)["id"])
    service.tick()
    peer.pending.clear()
    service.tick()
    service.tick()
    assert len(peer.submissions) == 1
    assert service.get(job["id"])["status"] == "unknown"
    assert client.post(f"/api/generations/{job['id']}/retry").status_code == 409
    assert client.post(f"/api/generations/{job['id']}/cancel").status_code == 409


def test_active_reference_guards_and_terminal_release(client, generation, png_bytes):
    service, _ = generation
    item = project(client)
    asset = upload(client, png_bytes())
    job = submit(client, item["id"], workflow_id="builtin-qwen21-reference", references=[{"version_id": asset["current_version_id"]}])
    for path in (f"/api/projects/{item['id']}", f"/api/assets/{asset['id']}"):
        response = client.delete(path)
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "generation_in_progress"
    unlink = client.delete(f"/api/projects/{item['id']}/assets/{asset['id']}", params={"remove_nodes": True})
    assert unlink.status_code == 409
    assert unlink.json()["detail"]["code"] == "generation_in_progress"
    assert client.post(f"/api/generations/{job['id']}/cancel").json()["status"] == "cancelled"
    assert client.delete(f"/api/projects/{item['id']}").status_code == 200


def test_cancel_only_owned_queue_item_and_confirm_running(client, generation):
    service, peer = generation
    item = project(client)
    first, second = submit(client, item["id"]), submit(client, item["id"])
    service.tick()
    first, second = service.get(first["id"]), service.get(second["id"])
    assert service.cancel(first["id"])["status"] == "cancelled"
    assert [entry[1] for entry in peer.pending] == [second["prompt_id"]]
    peer.running, peer.pending = peer.pending, []
    with pytest.raises(DomainError) as confirmation:
        service.cancel(second["id"])
    assert confirmation.value.detail["code"] == "generation_interrupt_confirmation"
    peer.targeted_cancel = False
    with pytest.raises(DomainError) as unsupported:
        service.cancel(second["id"], True)
    assert unsupported.value.detail["code"] == "targeted_cancel_unavailable"
    peer.targeted_cancel = True
    assert service.cancel(second["id"], True)["cancel_requested"]
    service.tick()
    assert service.get(second["id"])["status"] == "cancelled"
    assert all(path != "/interrupt" for _, path in peer.calls)


def test_cancel_queue_to_running_race_is_not_reported_cancelled(client, generation):
    service, peer = generation
    job = submit(client, project(client)["id"])
    service.tick()
    peer.run_during_delete = True
    with pytest.raises(DomainError) as confirmation:
        service.cancel(job["id"])
    assert confirmation.value.detail["code"] == "generation_interrupt_confirmation"
    assert service.get(job["id"])["status"] == "running"
    assert len(peer.running) == 1


def test_failed_node_and_retry_preserve_snapshot(client, generation):
    service, peer = generation
    job = submit(client, project(client)["id"])
    service.tick()
    peer.complete(service.get(job["id"])["prompt_id"], error=True)
    service.tick()
    failed = service.get(job["id"])
    assert failed["status"] == "failed"
    assert failed["error"]["details"][0][1]["node_id"] == "9"
    retry = client.post(f"/api/generations/{job['id']}/retry", json={"request_id": "retry-one"}).json()
    assert retry["parent_job_id"] == job["id"]
    assert retry["workflow_snapshot"] == failed["workflow_snapshot"]
    assert retry["request"]["parameters"] == failed["request"]["parameters"]
    assert service.retry(job["id"], "retry-one")["id"] == retry["id"]


def test_mask_upload_white_means_regenerate_and_empty_is_rejected(client, generation, png_bytes):
    service, peer = generation
    item = project(client)
    base = upload(client, png_bytes())
    mask = Image.new("L", (32, 24), 0)
    mask.paste(255, (0, 0, 16, 24))
    stream = BytesIO()
    mask.save(stream, "PNG")
    mask_asset = upload(client, stream.getvalue())
    job = submit(client, item["id"], workflow_id="builtin-qwen21-edit", references=[{"version_id": base["current_version_id"]}], mask_version_id=mask_asset["current_version_id"])
    service.tick()
    assert service.get(job["id"])["status"] == "queued"
    with Image.open(BytesIO(peer.uploads[1]["content"])) as normalized:
        assert normalized.mode == "RGBA"
        assert normalized.getpixel((2, 2))[3] == 0
        assert normalized.getpixel((20, 2))[3] == 255
    empty = upload(client, png_bytes("black"))
    empty_job = submit(client, item["id"], workflow_id="builtin-qwen21-edit", references=[{"version_id": base["current_version_id"]}], mask_version_id=empty["current_version_id"])
    service.tick()
    assert service.get(empty_job["id"])["error"]["code"] == "generation_mask_empty"
    assert len(peer.submissions) == 1


def test_invalid_output_retry_collects_original_without_recompute(client, generation, png_bytes):
    service, peer = generation
    item = project(client)
    job = submit(client, item["id"])
    service.tick()
    peer.complete(service.get(job["id"])["prompt_id"])
    peer.image = b"not an image"
    service.tick()
    assert service.get(job["id"])["status"] == "failed"
    assert service.get(job["id"])["error"]["phase"] == "collect"
    assert service.store.assets()["total"] == 0
    retry = service.retry(job["id"], "collect-again")
    peer.image = png_bytes("green")
    service.tick()
    assert service.get(retry["id"])["status"] == "succeeded"
    assert service.retry(job["id"], "collect-again")["status"] == "succeeded"
    assert len(peer.submissions) == 1


def test_maintenance_pauses_worker_and_resumes_pending(client, generation):
    service, peer = generation
    job = submit(client, project(client)["id"])
    service.store.maintenance = True
    try:
        service.tick()
        assert not peer.calls
        assert service.get(job["id"])["status"] == "pending"
    finally:
        service.store.maintenance = False
    service.tick()
    assert len(peer.submissions) == 1


def test_database_restart_recovers_submitted_prompt_without_duplicate(tmp_path, png_bytes):
    root, config = tmp_path / "持久资料", tmp_path / "配置.json"
    comfy, peer = SimpleNamespace(port=19123), ComfyFixture(png_bytes("green"))
    store = Store(root, config)
    workflows = WorkflowService(store, comfy)
    workflows.object_info = catalog
    service = GenerationService(store, comfy, workflows, transport=httpx.MockTransport(peer))
    item = store.create_project("可恢复项目")
    job = service.create({"project_id": item["id"], "workflow_id": "builtin-qwen21-text_to_image", "prompt": "二次元角色"})
    service.tick()
    prompt_id = service.get(job["id"])["prompt_id"]
    service.close()
    store.close()
    reopened = Store(root, config)
    recovered_workflows = WorkflowService(reopened, comfy)
    recovered_workflows.object_info = catalog
    restarted = GenerationService(reopened, comfy, recovered_workflows, transport=httpx.MockTransport(peer))
    try:
        peer.complete(prompt_id)
        restarted.tick()
        result = restarted.get(job["id"])
        assert result["status"] == "succeeded"
        assert result["prompt_id"] == prompt_id
        assert reopened.canvas(item["id"])["nodes"][0]["data"]["generation_id"] == job["id"]
        assert len(peer.submissions) == 1
    finally:
        restarted.close()
        reopened.close()


def test_corrupt_reference_and_invalid_parameters_never_submit(client, generation, png_bytes):
    service, peer = generation
    item = project(client)
    asset = upload(client, png_bytes())
    version = service.store.version(asset["current_version_id"])
    job = submit(client, item["id"], workflow_id="builtin-qwen21-reference", references=[{"version_id": version["id"]}])
    from pathlib import Path
    Path(version["path"]).write_bytes(b"corrupt")
    service.tick()
    assert service.get(job["id"])["error"]["code"] == "generation_input_corrupt"
    assert not peer.submissions
    response = client.post("/api/generations", json={"project_id": item["id"], "workflow_id": "builtin-qwen21-text_to_image", "prompt": "test", "parameters": {"seed": True}})
    assert response.status_code == 422


@pytest.mark.parametrize("gray,pixels,accepted", [(5, 768, False), (6, 768, True), (255, 1, False), (255, 2, True)])
def test_mask_threshold_matches_gh_without_whole_image_fallback(client, generation, png_bytes, gray, pixels, accepted):
    service, peer = generation
    base = upload(client, png_bytes())
    mask = Image.new("L", (32, 24), 0)
    mask.putdata([gray] * pixels + [0] * (768 - pixels))
    stream = BytesIO()
    mask.save(stream, "PNG")
    mask_asset = upload(client, stream.getvalue())
    job = submit(client, project(client)["id"], workflow_id="builtin-qwen21-edit", references=[{"version_id": base["current_version_id"]}], mask_version_id=mask_asset["current_version_id"])
    service.tick()
    assert service.get(job["id"])["status"] == ("queued" if accepted else "failed")
    assert len(peer.submissions) == int(accepted)
