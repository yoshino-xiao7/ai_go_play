"""Subject snapshots keep every image and voice on immutable media versions."""
from copy import deepcopy
from io import BytesIO
import json
from pathlib import Path
import sqlite3
import wave
import zipfile

from fastapi.testclient import TestClient
import pytest

from manju.app import create_app
from conftest import project, upload
from test_generation import generation, submit
from test_library import wait_migration


def audio_bytes(value=0):
    output = BytesIO()
    with wave.open(output, "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(16000)
        stream.writeframes(value.to_bytes(2, "little", signed=True) * 160)
    return output.getvalue()


def media(client, png_bytes):
    images = [upload(client, png_bytes(color), f"{color}.png") for color in ("red", "blue")]
    voice = upload(client, audio_bytes(), "人物音色.wav")
    return images, voice


def snapshot(images=(), voice=None, **changes):
    return {"kind": "character", "name": "女主", "description": "灰发少女，短外套", "image_version_ids": [item["current_version_id"] for item in images], "voice_version_id": voice["current_version_id"] if voice else None, "voice_name": "清亮女声" if voice else "", "voice_transcript": "末班车即将到站。" if voice else "", **changes}


def subject_node(subject, node_id="subject"):
    data = {"kind": "image", "title": "画布内别名", "subject": deepcopy(subject)}
    if subject["image_version_ids"]:
        data["asset_version_id"] = subject["image_version_ids"][0]
    return {"id": node_id, "type": "subject", "position": {"x": 20, "y": 30}, "data": data}


def save_node(client, project_id, node):
    path = f"/api/projects/{project_id}/canvas"
    canvas = client.get(path).json()
    canvas["nodes"] = [node]
    return client.put(path, json=canvas)


def create_subject(client, payload, request_id="subject-multi"):
    response = client.post("/api/subjects", json=payload, headers={"X-Request-ID": request_id})
    assert response.status_code == 201, response.text
    return response.json()


def test_multi_image_voice_crud_fixed_versions_and_release(client, png_bytes):
    images, voice = media(client, png_bytes)
    payload = snapshot(images, voice)
    before = client.app.state.store.conn.execute("SELECT COUNT(*) FROM blobs").fetchone()[0]
    subject = create_subject(client, payload)
    assert create_subject(client, payload) == subject
    assert client.app.state.store.conn.execute("SELECT COUNT(*) FROM blobs").fetchone()[0] == before
    assert subject["image_version_ids"] == [item["id"] for item in subject["images"]]
    assert subject["version_id"] == subject["version"]["id"] == subject["image_version_ids"][0]
    assert subject["voice_version_id"] == subject["voice"]["id"] == voice["current_version_id"]
    assert subject["voice"]["mime"].startswith("audio/")
    upload(client, png_bytes("green"), asset_id=images[1]["id"])
    upload(client, audio_bytes(15), "新音色.wav", asset_id=voice["id"])
    assert client.get(f"/api/subjects/{subject['id']}").json()["image_version_ids"] == payload["image_version_ids"]
    assert client.get(f"/api/subjects/{subject['id']}").json()["voice_version_id"] == payload["voice_version_id"]
    for asset in [*images, voice]:
        reference = client.get(f"/api/assets/{asset['id']}").json()["subject_references"][0]
        assert reference["id"] == subject["id"]
        assert asset["current_version_id"] in reference["referenced_version_ids"]
        assert client.delete(f"/api/assets/{asset['id']}").json()["detail"]["code"] == "subject_referenced"
        with pytest.raises(sqlite3.IntegrityError), client.app.state.store.tx():
            client.app.state.store.conn.execute("DELETE FROM versions WHERE id=?", (asset["current_version_id"],))
    with client.app.state.store.tx():
        client.app.state.store.conn.execute("UPDATE assets SET deleted_at='2026-01-01' WHERE id=?", (voice["id"],))
    purge = client.delete(f"/api/assets/{voice['id']}/permanent")
    assert purge.status_code == 409 and purge.json()["detail"]["code"] == "subject_referenced"
    assert client.post(f"/api/assets/{voice['id']}/restore").status_code == 200
    reordered = client.patch(f"/api/subjects/{subject['id']}", json={"image_version_ids": payload["image_version_ids"][::-1]}).json()
    assert reordered["version_id"] == images[1]["current_version_id"]
    assert reordered["asset_id"] == images[1]["id"]
    assert client.patch(f"/api/subjects/{subject['id']}", json={"version_id": images[0]["current_version_id"]}).status_code == 422
    update = {"kind": "scene", "image_version_ids": [images[0]["current_version_id"]], "voice_version_id": None, "voice_name": "", "voice_transcript": ""}
    changed = client.patch(f"/api/subjects/{subject['id']}", json=update)
    assert changed.status_code == 200, changed.text
    assert changed.json()["voice"] is None
    assert client.get("/api/subjects?kind=scene").json()["total"] == 1
    assert client.get("/api/subjects?kind=character").json()["total"] == 0
    assert client.get("/api/subjects?kind=bogus").status_code == 422
    assert client.delete(f"/api/assets/{images[1]['id']}").status_code == 200
    assert client.delete(f"/api/assets/{voice['id']}").status_code == 200
    assert client.delete(f"/api/subjects/{subject['id']}").status_code == 200
    assert client.get(f"/api/media/{images[0]['current_version_id']}").status_code == 200


@pytest.mark.parametrize("changes", [
    {"kind": "image"}, {"image_version_ids": []}, {"image_version_ids": "oops"},
    {"image_version_ids": ["v"] * 2}, {"image_version_ids": [str(i) for i in range(13)]},
    {"image_version_ids": [None]}, {"voice_version_id": ""}, {"voice_version_id": 3},
    {"voice_name": None}, {"voice_name": "x" * 251}, {"voice_transcript": "x" * 6001},
    {"kind": "scene", "voice_name": "残留音色"}, {"kind": "prop", "voice_transcript": "残留文本"},
])
def test_subject_invalid_new_fields_are_atomic(client, png_bytes, changes):
    image = upload(client, png_bytes())
    response = client.post("/api/subjects", json={**snapshot([image]), **changes})
    assert response.status_code == 422, response.text
    assert client.get("/api/subjects").json()["total"] == 0


def test_subject_media_types_missing_files_and_update_rollback(client, png_bytes):
    images, voice = media(client, png_bytes)
    subject = create_subject(client, snapshot(images, voice))
    for changes, code in [
        ({"image_version_ids": [voice["current_version_id"]]}, "subject_image_required"),
        ({"voice_version_id": images[0]["current_version_id"]}, "subject_audio_required"),
        ({"kind": "prop"}, "subject_voice_character_only"),
    ]:
        response = client.patch(f"/api/subjects/{subject['id']}", json=changes)
        assert response.status_code == 422
        assert response.json()["detail"]["code"] == code
        assert client.get(f"/api/subjects/{subject['id']}").json() == subject
    Path(voice["version"]["path"]).unlink()
    missing = client.post("/api/subjects", json=snapshot(images, voice))
    assert missing.status_code == 409
    assert missing.json()["detail"]["code"] == "subject_audio_missing"
    # A malformed legacy/new combination must return 422, never a server error.
    mixed = client.post("/api/subjects", json={"name": "坏输入", "version_id": images[0]["current_version_id"], "image_version_ids": {"x": 1}})
    assert mixed.status_code == 422


def test_canvas_subject_empty_then_snapshot_protects_all_media_and_duplicates(client, png_bytes):
    item = project(client)
    empty = subject_node(snapshot())
    assert save_node(client, item["id"], empty).status_code == 200
    assert client.get(f"/api/projects/{item['id']}").json()["cover_version_id"] is None
    images, voice = media(client, png_bytes)
    global_subject = create_subject(client, snapshot(images, voice))
    node = subject_node(snapshot(images, voice, library_id=global_subject["id"]))
    response = save_node(client, item["id"], node)
    assert response.status_code == 200, response.text
    assert client.get(f"/api/projects/{item['id']}").json()["cover_version_id"] == images[0]["current_version_id"]
    assert client.get("/api/assets", params={"project_id": item["id"]}).json()["total"] == 3
    assert client.patch(f"/api/subjects/{global_subject['id']}", json={"name": "全局改名", "image_version_ids": [images[1]["current_version_id"]]}).status_code == 200
    assert client.get(f"/api/projects/{item['id']}/canvas").json()["nodes"][0] == node
    assert client.delete(f"/api/subjects/{global_subject['id']}").status_code == 200
    for asset in [*images, voice]:
        details = client.get(f"/api/assets/{asset['id']}").json()
        assert details["references"][0]["node_ids"] == ["subject"]
        assert client.delete(f"/api/assets/{asset['id']}").json()["detail"]["code"] == "asset_referenced"
        unlink = client.delete(f"/api/projects/{item['id']}/assets/{asset['id']}")
        assert unlink.status_code == 409, unlink.text
    duplicate = client.post(f"/api/projects/{item['id']}/duplicate").json()
    assert client.get(f"/api/projects/{duplicate['id']}/canvas").json()["nodes"][0] == node
    changed = deepcopy(node)
    changed["data"]["subject"]["description"] = "副本单独修改"
    assert save_node(client, duplicate["id"], changed).status_code == 200
    assert client.get(f"/api/projects/{item['id']}/canvas").json()["nodes"][0] == node
    for project_id in (item["id"], duplicate["id"]):
        assert client.delete(f"/api/projects/{project_id}").status_code == 200
        assert client.delete(f"/api/projects/{project_id}/permanent").status_code == 200
    for asset in [*images, voice]:
        assert client.delete(f"/api/assets/{asset['id']}").status_code == 200
        assert client.delete(f"/api/assets/{asset['id']}/permanent").status_code == 200


@pytest.mark.parametrize("mutation", ["cover", "kind", "wrong_image", "wrong_voice", "hidden_subject", "wrong_subject_kind", "too_many"])
def test_canvas_subject_rejects_invalid_snapshot_atomically(client, png_bytes, mutation):
    images, voice = media(client, png_bytes)
    item = project(client)
    node = subject_node(snapshot(images, voice))
    if mutation == "cover":
        node["data"]["asset_version_id"] = images[1]["current_version_id"]
    elif mutation == "kind":
        node["data"]["kind"] = "audio"
    elif mutation == "wrong_image":
        node["data"]["subject"]["image_version_ids"].append(voice["current_version_id"])
    elif mutation == "wrong_voice":
        node["data"]["subject"]["voice_version_id"] = images[1]["current_version_id"]
    elif mutation == "hidden_subject":
        node["type"] = "media"
    elif mutation == "wrong_subject_kind":
        node["data"]["subject"]["kind"] = "scene"
    else:
        node["data"]["subject"]["image_version_ids"] = [str(i) for i in range(13)]
    response = save_node(client, item["id"], node)
    assert response.status_code == 422, response.text
    assert client.get(f"/api/projects/{item['id']}/canvas").json()["revision"] == 0
    assert client.get("/api/assets", params={"project_id": item["id"]}).json()["items"] == []


def rewrite_archive(content, mutate):
    output = BytesIO()
    with zipfile.ZipFile(BytesIO(content)) as original, zipfile.ZipFile(output, "w") as target:
        manifest = json.loads(original.read("manifest.json"))
        mutate(manifest)
        target.writestr("manifest.json", json.dumps(manifest))
        for name in original.namelist():
            if name != "manifest.json":
                target.writestr(name, original.read(name))
    return output.getvalue()


def test_subject_project_archive_remaps_every_image_voice_and_clears_library_origin(client, png_bytes):
    images, voice = media(client, png_bytes)
    item = project(client)
    subject = create_subject(client, snapshot(images, voice))
    assert save_node(client, item["id"], subject_node(snapshot(images, voice, library_id=subject["id"]))).status_code == 200
    archive = client.get(f"/api/projects/{item['id']}/export").content
    with zipfile.ZipFile(BytesIO(archive)) as package:
        manifest = json.loads(package.read("manifest.json"))
        assert len(manifest["versions"]) == 3
        assert "subjects" not in manifest
    imported = client.post("/api/projects/import", files={"file": ("人物.manju", archive)})
    assert imported.status_code == 201, imported.text
    data = client.get(f"/api/projects/{imported.json()['id']}/canvas").json()["nodes"][0]["data"]
    copied = data["subject"]
    assert "library_id" not in copied
    assert copied["image_version_ids"] != subject["image_version_ids"]
    assert copied["voice_version_id"] != subject["voice_version_id"]
    assert copied["name"] == subject["name"] and copied["voice_transcript"] == subject["voice_transcript"]
    assert data["asset_version_id"] == copied["image_version_ids"][0]
    for old, new in zip([*subject["image_version_ids"], subject["voice_version_id"]], [*copied["image_version_ids"], copied["voice_version_id"]]):
        assert client.get(f"/api/media/{old}").content == client.get(f"/api/media/{new}").content
    assert client.get("/api/subjects").json()["total"] == 1
    before = len(client.get("/api/projects").json())
    for mutate in (
        lambda value: value["canvas"]["nodes"][0]["data"]["subject"]["image_version_ids"].append(voice["current_version_id"]),
        lambda value: value["canvas"]["nodes"][0]["data"]["subject"].update(voice_version_id=images[0]["current_version_id"]),
    ):
        invalid = client.post("/api/projects/import", files={"file": ("坏类型.manju", rewrite_archive(archive, mutate))})
        assert invalid.status_code == 400, invalid.text
        assert invalid.json()["detail"]["code"] == "archive_subject_media_mismatch"
    assert len(client.get("/api/projects").json()) == before


def test_legacy_subject_schema_upgrades_and_reindexes_all_versions(client, png_bytes):
    asset = upload(client, png_bytes())
    store = client.app.state.store
    with store.tx():
        store.conn.execute("DROP TABLE subject_media")
        store.conn.execute("DROP TABLE subjects")
        store.conn.execute("CREATE TABLE subjects(id TEXT PRIMARY KEY,name TEXT NOT NULL,description TEXT NOT NULL DEFAULT '',version_id TEXT NOT NULL REFERENCES versions(id) ON DELETE RESTRICT,created_at TEXT NOT NULL,updated_at TEXT NOT NULL)")
        store.conn.execute("INSERT INTO subjects VALUES(?,?,?,?,?,?)", ("legacy", "旧角色", "原始备注", asset["current_version_id"], "2026-01-01", "2026-01-01"))
    store.reopen(store.root)
    for attempt in range(2):
        subject = client.get("/api/subjects/legacy").json()
        assert subject["kind"] == "character"
        assert subject["image_version_ids"] == [asset["current_version_id"]]
        assert subject["voice"] is None and subject["voice_name"] == ""
        assert subject["created_at"] == "2026-01-01"
        assert client.delete(f"/api/assets/{asset['id']}").json()["detail"]["code"] == "subject_referenced"
        store.reopen(store.root)


def test_multi_subject_migration_and_restart_keep_snapshot_and_audio(tmp_path, png_bytes):
    source, target, config = tmp_path / "旧资料", tmp_path / "新资料 中文", tmp_path / "配置.json"
    with TestClient(create_app(source, config), base_url="http://127.0.0.1") as client:
        images, voice = media(client, png_bytes)
        subject = create_subject(client, snapshot(images, voice))
        item = project(client)
        node = subject_node(snapshot(images, voice, library_id=subject["id"]))
        assert save_node(client, item["id"], node).status_code == 200
        assert client.post("/api/settings/storage/migrate", json={"target": str(target)}).status_code == 202
        wait_migration(client, "completed")
    with TestClient(create_app(source, config), base_url="http://127.0.0.1") as client:
        result = client.get(f"/api/subjects/{subject['id']}").json()
        assert result["image_version_ids"] == subject["image_version_ids"]
        assert result["voice_version_id"] == voice["current_version_id"]
        assert all(Path(version["path"]).is_relative_to(target) for version in [*result["images"], result["voice"]])
        assert client.get(f"/api/projects/{item['id']}/canvas").json()["nodes"][0] == node
        assert client.delete(f"/api/assets/{voice['id']}").json()["detail"]["code"] == "subject_referenced"


def test_generation_accepts_subject_secondary_image_but_never_outputs_to_subject(client, generation, png_bytes):
    service, peer = generation
    images, voice = media(client, png_bytes)
    item = project(client)
    node = subject_node(snapshot(images, voice))
    assert save_node(client, item["id"], node).status_code == 200
    result = client.post("/api/generations", json={"project_id": item["id"], "source_node_id": "subject", "workflow_id": "builtin-qwen21-text_to_image", "prompt": "不应覆盖主体"})
    assert result.status_code == 422
    assert result.json()["detail"]["code"] == "generation_source_type"
    job = submit(client, item["id"], workflow_id="builtin-qwen21-reference", references=[{"version_id": images[1]["current_version_id"], "node_id": "subject"}])
    service.tick()
    assert service.get(job["id"])["status"] == "queued"
    assert peer.uploads[0]["content"] == png_bytes("blue")
    peer.complete(service.get(job["id"])["prompt_id"])
    service.tick()
    canvas = service.store.canvas(item["id"])
    assert canvas["nodes"][0] == node
    assert len(canvas["nodes"]) == 2 and canvas["nodes"][1]["type"] == "media"
    unrelated = upload(client, png_bytes("yellow"))
    mismatch = client.post("/api/generations", json={"project_id": item["id"], "workflow_id": "builtin-qwen21-reference", "prompt": "不属于主体", "references": [{"version_id": unrelated["current_version_id"], "node_id": "subject"}]})
    assert mismatch.status_code == 202
    assert mismatch.json()["request"]["references"][0]["version_id"] == unrelated["current_version_id"]


def test_running_generation_preserves_source_changed_to_subject(client, generation, png_bytes):
    service, peer = generation
    item = project(client)
    original = {"id": "source", "type": "media", "position": {"x": 50, "y": 50}, "data": {"kind": "image"}}
    assert save_node(client, item["id"], original).status_code == 200
    job = submit(client, item["id"], source_node_id="source")
    service.tick()
    node = subject_node(snapshot(), node_id="source")
    assert save_node(client, item["id"], node).status_code == 200
    peer.complete(service.get(job["id"])["prompt_id"])
    service.tick()
    result = service.get(job["id"])
    assert result["status"] == "succeeded", result
    canvas = service.store.canvas(item["id"])
    assert canvas["nodes"][0] == node
    assert len(canvas["nodes"]) == 2 and canvas["nodes"][1]["type"] == "media"
    assert result["outputs"][0]["node_id"] != "source"
