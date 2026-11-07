from copy import deepcopy
from io import BytesIO
import json
import zipfile

import httpx
import pytest

from manju.generation import GenerationService
from conftest import project, upload
from test_generation import generation, submit
from test_generation_archives import rewrite_manifest


def image_card(client, project_id, version_id=None):
    store = client.app.state.store
    canvas = store.canvas(project_id)
    node = {"id": "current-card", "type": "media", "position": {"x": 120, "y": 80}, "style": {"width": 480, "height": 360}, "data": {"title": "保留卡片名称", "kind": "image", "generation": {"mode": "text_to_image", "prompt": "保留草稿", "references": [], "parameters": {}}}}
    if version_id:
        node["data"]["asset_version_id"] = version_id
    canvas["nodes"] = [node]
    store.save_canvas(project_id, canvas)
    return node


def finish(service, peer, job, png_bytes, colors):
    service.tick()
    prompt_id = service.get(job["id"])["prompt_id"]
    peer.complete(prompt_id)
    descriptors = []
    for index, color in enumerate(colors):
        filename = f"{job['id']}-{index}.png"
        peer.images[filename] = png_bytes(color)
        descriptors.append({"filename": filename, "type": "output", "subfolder": ""})
    peer.history[prompt_id]["outputs"]["11"]["images"] = descriptors
    service.tick()
    result = service.get(job["id"])
    assert result["status"] == "succeeded", result
    return result


def test_batches_and_repeated_generations_use_one_card_without_edges(client, generation, png_bytes):
    service, peer = generation
    item = project(client)
    original = upload(client, png_bytes("red"))
    original_version = original["current_version_id"]
    card = image_card(client, item["id"], original_version)
    first = submit(client, item["id"], source_node_id=card["id"], placement={"x": 999, "y": 999})
    result = finish(service, peer, first, png_bytes, ["green", "blue", "green"])
    canvas = service.store.canvas(item["id"])
    assert len(canvas["nodes"]) == 1 and canvas["edges"] == []
    current = canvas["nodes"][0]
    assert current["position"] == card["position"]
    assert current["style"] == card["style"]
    assert current["data"]["title"] == card["data"]["title"]
    assert current["data"]["generation"] == card["data"]["generation"]
    assert {output["node_id"] for output in result["outputs"]} == {card["id"]}
    assert current["data"]["asset_version_id"] == result["outputs"][0]["version_id"]
    assert [entry["version_id"] for entry in current["data"]["image_history"]] == [original_version, result["outputs"][0]["version_id"], result["outputs"][1]["version_id"]]
    second = submit(client, item["id"], source_node_id=card["id"])
    again = finish(service, peer, second, png_bytes, ["yellow"])
    canvas = service.store.canvas(item["id"])
    assert len(canvas["nodes"]) == 1 and canvas["edges"] == []
    assert len(canvas["nodes"][0]["data"]["image_history"]) == 4
    assert canvas["nodes"][0]["data"]["generation_id"] == again["id"]
    event = [event for event in service.store.events(0) if event["type"] == "canvas.updated"][-1]
    assert event["data"]["reason"] == "generation_result"
    assert event["data"]["updated_node_ids"] == [card["id"]]


def test_delivery_receipt_survives_restart_and_never_resets_history_choice(client, generation, png_bytes, monkeypatch):
    service, peer = generation
    item = project(client)
    original = upload(client, png_bytes("red"))
    original_version = original["current_version_id"]
    card = image_card(client, item["id"], original_version)
    job = submit(client, item["id"], source_node_id=card["id"])
    service.tick()
    prompt_id = service.get(job["id"])["prompt_id"]
    peer.complete(prompt_id)
    real_update = service._update
    def fail_after_canvas(job_id, **changes):
        if changes.get("status") == "succeeded":
            raise RuntimeError("simulated crash after atomic canvas delivery")
        return real_update(job_id, **changes)
    monkeypatch.setattr(service, "_update", fail_after_canvas)
    service.tick()
    assert service.get(job["id"])["status"] == "failed"
    canvas = service.store.canvas(item["id"])
    assert len(canvas["nodes"][0]["data"]["image_history"]) == 2
    canvas["nodes"][0]["data"]["asset_version_id"] = original_version
    canvas["nodes"][0]["data"].pop("generation_id")
    canvas["nodes"][0]["data"]["title"] = "用户已选回原图并改标题"
    expected = service.store.save_canvas(item["id"], canvas)
    real_update(job["id"], status="collecting")
    service.close()
    service.store.reopen(service.store.root)
    restarted = GenerationService(service.store, service.comfy, service.workflows, transport=httpx.MockTransport(peer))
    client.app.state.generations = restarted
    restarted.tick()
    assert restarted.get(job["id"])["status"] == "succeeded"
    assert service.store.canvas(item["id"]) == expected
    assert restarted.get(job["id"])["outputs"][0]["node_id"] == card["id"]
    assert len(peer.submissions) == 1


def test_canvas_and_delivery_receipt_rollback_together(client, generation, png_bytes, monkeypatch):
    service, peer = generation
    item = project(client)
    original = upload(client, png_bytes("red"))
    image_card(client, item["id"], original["current_version_id"])
    expected = service.store.canvas(item["id"])
    job = submit(client, item["id"], source_node_id="current-card")
    service.tick()
    peer.complete(service.get(job["id"])["prompt_id"])
    remember = service.store.remember_request
    def fail_receipt(key, route, payload, result):
        if route == "generation-delivery":
            raise RuntimeError("receipt commit failed")
        return remember(key, route, payload, result)
    monkeypatch.setattr(service.store, "remember_request", fail_receipt)
    service.tick()
    assert service.get(job["id"])["status"] == "failed"
    assert service.store.canvas(item["id"]) == expected
    assert not service.store.conn.execute("SELECT 1 FROM requests WHERE key=? AND route='generation-delivery'", (job["id"],)).fetchone()
    monkeypatch.setattr(service.store, "remember_request", remember)
    service._update(job["id"], status="collecting")
    service.tick()
    assert service.get(job["id"])["status"] == "succeeded"
    assert len(service.store.canvas(item["id"])["nodes"][0]["data"]["image_history"]) == 2
    assert len(peer.submissions) == 1


def test_identical_output_new_job_displays_once_then_respects_history_choice(client, generation, png_bytes):
    service, peer = generation
    item = project(client)
    original = upload(client, png_bytes("red"))
    card = image_card(client, item["id"], original["current_version_id"])
    first = finish(service, peer, submit(client, item["id"], source_node_id=card["id"]), png_bytes, ["green"])
    second = finish(service, peer, submit(client, item["id"], source_node_id=card["id"]), png_bytes, ["green"])
    assert first["outputs"][0]["version_id"] == second["outputs"][0]["version_id"]
    canvas = service.store.canvas(item["id"])
    assert len(canvas["nodes"][0]["data"]["image_history"]) == 2
    assert canvas["nodes"][0]["data"]["generation_id"] == second["id"]
    canvas["nodes"][0]["data"]["asset_version_id"] = original["current_version_id"]
    canvas["nodes"][0]["data"].pop("generation_id")
    expected = service.store.save_canvas(item["id"], canvas)
    service._collect(first, peer.history[first["prompt_id"]])
    service._collect(second, peer.history[second["prompt_id"]])
    assert service.store.canvas(item["id"]) == expected


@pytest.mark.parametrize("deleted_source", [False, True])
def test_missing_source_collects_batch_in_one_fallback_card(client, generation, png_bytes, deleted_source):
    service, peer = generation
    item = project(client)
    if deleted_source:
        card = image_card(client, item["id"])
    job = submit(client, item["id"], source_node_id=card["id"] if deleted_source else None, placement={"x": 45, "y": 67})
    if deleted_source:
        canvas = service.store.canvas(item["id"])
        canvas["nodes"] = []
        service.store.save_canvas(item["id"], canvas)
    result = finish(service, peer, job, png_bytes, ["green", "blue"])
    canvas = service.store.canvas(item["id"])
    assert len(canvas["nodes"]) == 1 and canvas["edges"] == []
    node = canvas["nodes"][0]
    assert node["position"] == {"x": 45, "y": 67}
    assert len(node["data"]["image_history"]) == 2
    assert {output["node_id"] for output in result["outputs"]} == {node["id"]}


def test_history_refs_protect_assets_and_project_roundtrip_remaps_all(client, png_bytes):
    item = project(client)
    first = upload(client, png_bytes("red"))
    old_version = first["current_version_id"]
    upload(client, png_bytes("blue"), asset_id=first["id"])
    displayed = upload(client, png_bytes("green"))
    card = image_card(client, item["id"], displayed["current_version_id"])
    store = client.app.state.store
    canvas = store.canvas(item["id"])
    canvas["nodes"][0]["data"]["image_history"] = [{"version_id": old_version, "job_id": "old-job", "created_at": "2026-01-01"}, {"version_id": displayed["current_version_id"], "job_id": "current-job"}]
    canvas["nodes"][0]["data"]["generation_id"] = "current-job"
    canvas["nodes"][0]["data"].pop("generation")
    store.save_canvas(item["id"], canvas)
    with store.tx():
        store.conn.execute("DELETE FROM project_assets WHERE project_id=? AND asset_id=?", (item["id"], first["id"]))
    store.reopen(store.root)
    reference = client.get(f"/api/assets/{first['id']}").json()["references"][0]
    assert reference["node_ids"] == [card["id"]]
    assert client.delete(f"/api/assets/{first['id']}").status_code == 409
    assert client.delete(f"/api/projects/{item['id']}/assets/{first['id']}").json()["detail"]["code"] == "asset_in_canvas"
    copied = client.post(f"/api/projects/{item['id']}/duplicate").json()
    copy_history = store.canvas(copied["id"])["nodes"][0]["data"]["image_history"]
    assert [entry["version_id"] for entry in copy_history] == [old_version, displayed["current_version_id"]]
    assert all("job_id" not in entry for entry in copy_history)
    archive = client.get(f"/api/projects/{item['id']}/export").content
    with zipfile.ZipFile(BytesIO(archive)) as packed:
        manifest = json.loads(packed.read("manifest.json"))
        assert old_version in {version["id"] for version in manifest["versions"]}
    imported = client.post("/api/projects/import", files={"file": ("history.manju", archive)})
    assert imported.status_code == 201, imported.text
    data = store.canvas(imported.json()["id"])["nodes"][0]["data"]
    assert all("job_id" not in entry for entry in data["image_history"])
    assert "generation_id" not in data
    versions = [entry["version_id"] for entry in data["image_history"]]
    assert versions[0] != old_version
    assert versions[1] == data["asset_version_id"]
    assert client.get(f"/api/media/{versions[0]}").content == png_bytes("red")
    assert client.get(f"/api/media/{versions[1]}").content == png_bytes("green")


@pytest.mark.parametrize("history", [[{"version_id": "absent"}], [None], {"version_id": "bad"}])
def test_invalid_history_in_archive_is_rejected(client, history):
    item = project(client)
    image_card(client, item["id"])
    archive = client.get(f"/api/projects/{item['id']}/export").content
    def edit(manifest):
        manifest["canvas"]["nodes"][0]["data"]["image_history"] = deepcopy(history)
    response = client.post("/api/projects/import", files={"file": ("bad-history.manju", rewrite_manifest(archive, edit))})
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "invalid_archive"


@pytest.mark.parametrize("node_type,kind", [("text", None), ("group", None), ("media", "video"), ("media", "audio")])
def test_generation_rejects_non_image_source_without_changing_card(client, generation, node_type, kind):
    service, _ = generation
    item = project(client)
    image_card(client, item["id"])
    canvas = service.store.canvas(item["id"])
    canvas["nodes"][0]["type"] = node_type
    canvas["nodes"][0]["data"]["kind"] = kind
    expected = service.store.save_canvas(item["id"], canvas)
    response = client.post("/api/generations", json={"project_id": item["id"], "source_node_id": "current-card", "workflow_id": "builtin-qwen21-text_to_image", "prompt": "不要覆盖其它卡"})
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "generation_source_type"
    assert service.store.canvas(item["id"]) == expected


def test_source_changed_to_text_during_generation_uses_fallback(client, generation, png_bytes):
    service, peer = generation
    item = project(client)
    image_card(client, item["id"])
    job = submit(client, item["id"], source_node_id="current-card")
    canvas = service.store.canvas(item["id"])
    canvas["nodes"][0]["type"] = "text"
    canvas["nodes"][0]["data"] = {"text": "用户改为文字卡"}
    expected = deepcopy(canvas["nodes"][0])
    service.store.save_canvas(item["id"], canvas)
    result = finish(service, peer, job, png_bytes, ["green"])
    canvas = service.store.canvas(item["id"])
    assert canvas["nodes"][0] == expected
    assert len(canvas["nodes"]) == 2 and not canvas["edges"]
    assert result["outputs"][0]["node_id"] == canvas["nodes"][1]["id"]
