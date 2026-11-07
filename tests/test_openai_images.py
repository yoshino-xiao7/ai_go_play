"""Provider protocol and recovery tests. All generated images use an isolated peer."""
import base64
from email.parser import BytesParser
from email.policy import default
from io import BytesIO
import json
import threading
import time
from types import SimpleNamespace

import httpx
from PIL import Image
import pytest

from conftest import project, upload
from manju.generation import GenerationService
from manju.openai_images import estimate_cost, load_api_key, MODEL_NAMES
from manju.store import DomainError


class OpenAIPeer:
    def __init__(self, image):
        self.image, self.calls, self.submissions = image, [], []
        self.models = list(MODEL_NAMES)
        self.failure = None
        self.wait = None
        self.entered = threading.Event()

    def __call__(self, request):
        assert request.url.host == "api.openai.com"
        self.calls.append((request.method, request.url.path))
        if request.url.path == "/v1/models":
            return httpx.Response(200, json={"data": [{"id": model} for model in self.models]})
        assert request.url.path in ("/v1/images/generations", "/v1/images/edits")
        self.submissions.append(request)
        self.entered.set()
        if self.wait:
            assert self.wait.wait(timeout=5)
        if self.failure == "timeout":
            raise httpx.ReadTimeout("response lost; credentials must not be persisted", request=request)
        if isinstance(self.failure, int):
            return httpx.Response(self.failure, json={"error": {"message": "sk-test-must-never-leak"}})
        return httpx.Response(200, headers={"x-request-id": "req-image-test"}, json={"data": [{"b64_json": base64.b64encode(self.image).decode()}],
            "usage": {"input_tokens": 120, "input_tokens_details": {"text_tokens": 20, "image_tokens": 100}, "output_tokens": 1756, "total_tokens": 1876}})


@pytest.fixture
def external(client, png_bytes):
    client.app.state.generations.close()
    peer = OpenAIPeer(png_bytes("green"))
    service = GenerationService(client.app.state.store, SimpleNamespace(port=19123), client.app.state.workflows,
        transport=httpx.MockTransport(lambda request: pytest.fail("Unexpected ComfyUI request")),
        openai_transport=httpx.MockTransport(peer), openai_key_loader=lambda: "sk-test-must-never-leak")
    client.app.state.generations = service
    return service, peer


def submit(client, project_id, **extra):
    response = client.post("/api/generations", json={"project_id": project_id, "workflow_id": "builtin-openai-text_to_image", "prompt": "雨夜的车站",
        "model": "gpt-image-2.6-flare", "quality": "high", "parameters": {"width": 1024, "height": 1024}, **extra})
    assert response.status_code == 202, response.text
    return response.json()


def finish(service, job_id):
    service.tick()
    for future in list(service.external_jobs.values()):
        future.result(timeout=5)
    return service.get(job_id)


@pytest.mark.parametrize("model,quality,width,height,tokens,cost", [
    ("gpt-image-2.6-flare", "low", 1024, 1024, 823, .02469),
    ("gpt-image-2.6-sunburst", "medium", 1024, 1024, 1449, .04347),
    ("gpt-image-2.6-flare", "high", 1024, 1024, 1756, .05268),
    ("gpt-image-2.6-flare", "max", 1024, 1024, 7024, .21072),
    ("gpt-image-2.5-flare", "low", 1024, 1024, 196, .00588),
    ("gpt-image-2.6-flare", "high", 1536, 1024, 1372, .04116),
    ("gpt-image-2", "high", 1024, 1024, 7024, .21072),
])
def test_published_output_calculator(model, quality, width, height, tokens, cost):
    value = estimate_cost({"model": model, "quality": quality, "parameters": {"width": width, "height": height}})
    assert value["output_tokens"] == tokens
    assert value["output_usd"] == cost
    assert value["scope"] == "image_output" and "另计" in value["note"]


@pytest.mark.parametrize("parameters", [{"width": True}, {"width": 0}, {"width": 1023}, {"width": 512, "height": 512}, {"width": 4096}, {"width": 3840, "height": 3840}, {"width": 3840, "height": 512}, {"steps": 20}])
def test_invalid_dimensions_rejected_before_submission(client, external, parameters):
    response = client.post("/api/openai/images/estimate", json={"parameters": parameters})
    assert response.status_code == 422
    assert not external[1].submissions


def test_unified_workflow_catalog_and_secret_boundary(client, external):
    items = client.get("/api/workflows").json()["items"]
    cloud = [item for item in items if item.get("provider") == "openai"]
    assert len(cloud) == 3
    assert {item["mode"] for item in cloud} == {"text_to_image", "reference", "edit"}
    assert all(item["read_only"] for item in cloud)
    catalog = client.get("/api/openai/images").json()
    assert catalog["ready"] and len(catalog["models"]) == 5
    assert "sk-test" not in json.dumps(catalog)
    report = client.post("/api/workflows/builtin-openai-edit/validate").json()
    assert report["valid"] and report["online"]
    snapshot = client.get("/api/workflows/builtin-openai-edit").json()
    assert snapshot["capabilities"]["supports_mask"]


def test_missing_key_and_model_visibility(client, external):
    service, peer = external
    service.openai.key_loader = lambda: ""
    report = client.get("/api/openai/images").json()
    assert not report["ready"] and not report["configured"]
    assert client.post("/api/generations", json={"project_id": project(client)["id"], "workflow_id": "builtin-openai-text_to_image", "prompt": "test"}).status_code == 503
    service.openai.key_loader = lambda: "sk-test-must-never-leak"
    peer.models = ["gpt-image-2.5-flare"]
    report = client.get("/api/openai/images?refresh=true").json()
    assert [m["id"] for m in report["models"] if m["available"]] == peer.models
    response = client.post("/api/generations", json={"project_id": project(client)["id"], "workflow_id": "builtin-openai-text_to_image", "prompt": "test"})
    assert response.status_code == 422
    assert not peer.submissions


def test_generation_roundtrip_idempotency_and_metering(client, external):
    service, peer = external
    item = project(client)
    job = submit(client, item["id"], request_id="one-purchase")
    assert submit(client, item["id"], request_id="one-purchase")["id"] == job["id"]
    result = finish(service, job["id"])
    assert result["status"] == "succeeded", result
    assert len(peer.submissions) == 1
    payload = json.loads(peer.submissions[0].content)
    assert payload["model"] == "gpt-image-2.6-flare" and payload["quality"] == "high"
    assert payload["size"] == "1024x1024" and payload["n"] == 1
    assert result["request"]["actual_cost"]["total_usd"] == .05358
    assert result["request"]["upstream_request_id"] == "req-image-test"
    assert "sk-test" not in json.dumps(result)
    asset = service.store.asset(result["outputs"][0]["asset_id"])
    assert asset["source"] == "openai"
    assert service.store.canvas(item["id"])["nodes"][0]["data"]["asset_version_id"] == result["outputs"][0]["version_id"]
    assert submit(client, item["id"], request_id="one-purchase")["id"] == job["id"]
    service.tick()
    assert len(peer.submissions) == 1


def test_edit_uses_immutable_inputs_and_white_edit_mask(client, external, png_bytes):
    service, peer = external
    item = project(client)
    asset = upload(client, png_bytes("red"))
    base = asset["current_version_id"]
    upload(client, png_bytes("blue"), asset_id=asset["id"])
    canvas = service.store.canvas(item["id"])
    canvas["nodes"] = [{"id": "source", "type": "media", "position": {"x": 1, "y": 2}, "data": {"kind": "image", "asset_version_id": base}}]
    service.store.save_canvas(item["id"], canvas)
    mask = Image.new("L", (32, 24), 0)
    mask.paste(255, (0, 0, 16, 24))
    buffer = BytesIO()
    mask.save(buffer, "PNG")
    mask_id = upload(client, buffer.getvalue())["current_version_id"]
    job = submit(client, item["id"], workflow_id="builtin-openai-edit", source_node_id="source", references=[{"id": "base", "version_id": base, "title": "人物"}],
                 prompt_parts=[{"type": "reference", "reference_id": "base"}, {"type": "text", "text": "换背景"}], mask_version_id=mask_id, result_policy="review")
    result = finish(service, job["id"])
    assert result["status"] == "succeeded", result
    request = peer.submissions[0]
    assert request.url.path == "/v1/images/edits"
    message = BytesParser(policy=default).parsebytes(b"Content-Type: " + request.headers["content-type"].encode() + b"\r\n\r\n" + request.read())
    fields = {part.get_param("name", header="content-disposition"): part for part in message.iter_parts()}
    image = Image.open(BytesIO(fields["image[]"].get_payload(decode=True)))
    assert image.getpixel((0, 0)) == (255, 0, 0)
    normalized = Image.open(BytesIO(fields["mask"].get_payload(decode=True)))
    assert normalized.getpixel((0, 0))[3] == 0 and normalized.getpixel((20, 0))[3] == 255
    assert "参考图1" in fields["prompt"].get_payload(decode=True).decode()
    data = service.store.canvas(item["id"])["nodes"][0]["data"]
    assert data["asset_version_id"] == base
    assert data["image_history"][-1]["candidate"]


def test_response_loss_never_resubmits_and_restart_is_safe(client, external):
    service, peer = external
    peer.failure = "timeout"
    job = submit(client, project(client)["id"])
    assert finish(service, job["id"])["status"] == "unknown"
    service.tick()
    assert len(peer.submissions) == 1
    assert client.post(f"/api/generations/{job['id']}/retry", json={}).status_code == 409
    assert client.post(f"/api/generations/{job['id']}/cancel", json={}).status_code == 409
    response = client.post(f"/api/generations/{job['id']}/cancel", json={"interrupt_running": True})
    assert response.json()["status"] == "cancelled"
    assert len(peer.submissions) == 1


def test_collection_retry_reuses_receipt(client, external, monkeypatch):
    service, peer = external
    job = submit(client, project(client)["id"])
    original = service._append_results
    monkeypatch.setattr(service, "_append_results", lambda *args: (_ for _ in ()).throw(RuntimeError("disk failure")))
    result = finish(service, job["id"])
    assert result["status"] == "failed" and service._openai_receipt(job["id"]).exists()
    monkeypatch.setattr(service, "_append_results", original)
    service.openai.key_loader = lambda: ""  # Paid local outputs remain recoverable offline.
    retry = client.post(f"/api/generations/{job['id']}/retry", json={"request_id": "recover-original-image"}).json()
    result = finish(service, retry["id"])
    assert result["status"] == "succeeded", result
    assert len(peer.submissions) == 1
    assert service.store.assets()["total"] == 1


def test_cloud_request_does_not_block_local_state(client, external):
    service, peer = external
    peer.wait = threading.Event()
    job = submit(client, project(client)["id"])
    service.tick()
    assert peer.entered.wait(timeout=2)
    try:
        assert service.get(job["id"])["status"] == "running"
        assert client.get("/api/generations").status_code == 200
        assert not service.get(job["id"])["can_cancel"]
        assert client.post("/api/projects", json={"name": "云端等待期间继续工作"}).status_code == 201
    finally:
        peer.wait.set()
    assert finish(service, job["id"])["status"] == "succeeded"


@pytest.mark.parametrize("status", [400, 401, 403, 429, 500])
def test_provider_errors_are_safe(client, external, status):
    service, peer = external
    peer.failure = status
    job = submit(client, project(client)["id"])
    result = finish(service, job["id"])
    assert result["status"] == ("unknown" if status == 500 else "failed")
    assert "sk-test" not in json.dumps(result)


def test_env_key_loader_uses_environment_without_exposure(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-example")
    assert load_api_key() == "sk-test-example"
    monkeypatch.setenv("OPENAI_API_KEY", "invalid key with newline\n")
    assert load_api_key() == ""
