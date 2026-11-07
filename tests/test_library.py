from __future__ import annotations

from io import BytesIO
import json
from pathlib import Path
import time
import wave
import zipfile

from fastapi.testclient import TestClient
import pytest

from manju.app import create_app
from manju import media, transfers
from manju.store import DomainError, Store
from conftest import pin, project, upload


def wait_migration(client, expected):
    deadline = time.monotonic() + 10
    result = None
    while time.monotonic() < deadline:
        result = client.get("/api/settings/storage").json()
        migration = result.get("migration") or {}
        if migration.get("status") == expected and not client.app.state.migration_guard.locked():
            return result
        time.sleep(0.02)
    pytest.fail(f"Migration did not become {expected}: {result}")


def test_content_deduplication_and_same_filename(client, png_bytes):
    first = upload(client, png_bytes(), "相同名字.png")
    duplicate = upload(client, png_bytes(), "另一个名字.png")
    different = upload(client, png_bytes("blue"), "相同名字.png")
    assert duplicate["id"] == first["id"]
    assert duplicate["version_count"] == 1
    assert different["id"] != first["id"]
    assert different["name"] == first["name"]
    assert client.get("/api/assets").json()["total"] == 2
    assert len(list((client.app.state.store.root / "blobs").rglob("[0-9a-f]" * 64))) == 2


def test_upload_idempotency_conflict(client, png_bytes):
    headers = {"X-Request-ID": "upload-one"}
    first = client.post("/api/assets/upload", files={"file": ("a.png", png_bytes())}, headers=headers)
    again = client.post("/api/assets/upload", files={"file": ("a.png", png_bytes())}, headers=headers)
    assert first.status_code == again.status_code == 201
    assert first.json() == again.json()
    conflict = client.post("/api/assets/upload", files={"file": ("a.png", png_bytes("blue"))}, headers=headers)
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["code"] == "idempotency_conflict"


def test_reimport_old_content_preserves_current_version(client, png_bytes):
    first = upload(client, png_bytes())
    old_version = first["current_version_id"]
    updated = upload(client, png_bytes("blue"), asset_id=first["id"])
    repeated = upload(client, png_bytes(), "另一文件名.png")
    assert repeated["id"] == first["id"]
    assert repeated["version_count"] == 2
    assert repeated["imported_version_id"] == old_version
    assert repeated["current_version_id"] == updated["current_version_id"]
    assert client.get("/api/assets").json()["total"] == 1


def test_pinned_old_version_and_project_copy(client, png_bytes):
    original = project(client)
    first = upload(client, png_bytes(), project_id=original["id"])
    old_version = first["current_version_id"]
    pin(client, original["id"], old_version)
    second = upload(client, png_bytes("blue"), asset_id=first["id"])
    assert second["version_count"] == 2
    assert second["current_version_id"] != old_version
    copied = client.post(f"/api/projects/{original['id']}/duplicate").json()
    for item in (original, copied):
        canvas = client.get(f"/api/projects/{item['id']}/canvas").json()
        assert canvas["nodes"][0]["data"]["asset_version_id"] == old_version
    assert client.get(f"/api/media/{old_version}").content == png_bytes()
    assert len(client.get(f"/api/assets/{first['id']}").json()["references"]) == 2


def test_multi_project_reference_protection_and_recycle(client, png_bytes):
    first, second = project(client, "第一集"), project(client, "第二集")
    asset = upload(client, png_bytes(), project_id=first["id"])
    client.post(f"/api/projects/{second['id']}/assets", json={"asset_id": asset["id"]})
    path = f"/api/assets/{asset['id']}"
    assert client.delete(path).status_code == 409
    client.delete(f"/api/projects/{first['id']}")
    assert client.delete(path).status_code == 409
    assert client.post(f"/api/projects/{first['id']}/restore").json()["deleted_at"] is None
    for item in (first, second):
        client.delete(f"/api/projects/{item['id']}")
        assert client.delete(f"/api/projects/{item['id']}/permanent").status_code == 200
    assert client.delete(path + "/permanent").status_code == 409
    assert client.delete(path).json()["deleted_at"]
    assert client.get("/api/assets").json()["total"] == 0
    assert client.get("/api/assets", params={"trash": True}).json()["total"] == 1
    assert client.post(path + "/restore").json()["deleted_at"] is None
    client.delete(path)
    assert client.delete(path + "/permanent").status_code == 200
    assert client.get(path).status_code == 404
    assert not Path(asset["version"]["path"]).exists()


def test_unlink_requires_explicit_canvas_removal(client, png_bytes):
    item = project(client)
    asset = upload(client, png_bytes())
    pin(client, item["id"], asset["current_version_id"])
    path = f"/api/projects/{item['id']}/assets/{asset['id']}"
    assert client.delete(path).status_code == 409
    result = client.delete(path, params={"remove_nodes": True})
    assert result.status_code == 200
    assert result.json()["canvas"]["nodes"] == []
    assert client.delete(f"/api/assets/{asset['id']}").status_code == 200


def test_canvas_revision_idempotency_and_atomic_validation(client):
    item = project(client)
    path = f"/api/projects/{item['id']}/canvas"
    canvas = client.get(path).json()
    canvas.update({"request_id": "same-operation", "nodes": [{"id": "note", "type": "text", "position": {"x": 2, "y": 4}, "data": {"text": "开场"}}]})
    first = client.put(path, json=canvas)
    assert first.status_code == 200
    assert first.json()["revision"] == 1
    assert client.put(path, json=canvas).json() == first.json()
    canvas["request_id"] = "different-operation"
    assert client.put(path, json=canvas).status_code == 409
    canvas.update({"revision": 1, "nodes": [{"id": "note", "type": "text", "parentId": "note", "position": {"x": 0, "y": 0}, "data": {}}]})
    assert client.put(path, json=canvas).status_code == 422
    assert client.get(path).json() == first.json()


def test_project_archive_roundtrip_and_shared_blob_purge(client, png_bytes):
    item = project(client)
    asset = upload(client, png_bytes(), project_id=item["id"])
    old_version = asset["current_version_id"]
    pin(client, item["id"], old_version)
    upload(client, png_bytes("blue"), asset_id=asset["id"])
    exported = client.get(f"/api/projects/{item['id']}/export")
    assert exported.status_code == 200
    with zipfile.ZipFile(BytesIO(exported.content)) as package:
        manifest = json.loads(package.read("manifest.json"))
        assert len(manifest["versions"]) == 2
        assert len(package.namelist()) == 3
    imported = client.post("/api/projects/import", files={"file": ("test.manju", exported.content)})
    assert imported.status_code == 201, imported.text
    new_id = imported.json()["id"]
    assert new_id != item["id"]
    canvas = client.get(f"/api/projects/{new_id}/canvas").json()
    new_version = canvas["nodes"][0]["data"]["asset_version_id"]
    assert new_version != old_version
    assert client.get(f"/api/media/{new_version}").content == png_bytes()
    client.delete(f"/api/projects/{item['id']}")
    client.delete(f"/api/projects/{item['id']}/permanent")
    client.delete(f"/api/assets/{asset['id']}")
    assert client.delete(f"/api/assets/{asset['id']}/permanent").status_code == 200
    assert client.get(f"/api/media/{new_version}").content == png_bytes()


@pytest.mark.parametrize("entry", ["../escape", "C:/escape", "blobs/../../escape", "\\escape"])
def test_malicious_zip_paths_rejected_atomically(client, entry):
    content = BytesIO()
    with zipfile.ZipFile(content, "w") as package:
        package.writestr("manifest.json", "{}")
        package.writestr(entry, "bad")
    response = client.post("/api/projects/import", files={"file": ("bad.manju", content.getvalue())})
    assert response.status_code == 400
    assert client.get("/api/projects").json() == []
    assert client.get("/api/assets").json()["total"] == 0


def test_tampered_archive_hash_rejected(client, png_bytes):
    item = project(client)
    upload(client, png_bytes(), project_id=item["id"])
    data = client.get(f"/api/projects/{item['id']}/export").content
    buffer = BytesIO()
    with zipfile.ZipFile(BytesIO(data)) as source, zipfile.ZipFile(buffer, "w") as target:
        for name in source.namelist():
            content = source.read(name)
            if name.startswith("blobs/"):
                content = b"x" + content[1:]
            target.writestr(name, content)
    response = client.post("/api/projects/import", files={"file": ("tampered.manju", buffer.getvalue())})
    assert response.status_code == 400, response.text
    assert len(client.get("/api/projects").json()) == 1


def test_missing_media_repair_requires_identical_content(client, png_bytes):
    asset = upload(client, png_bytes())
    path = Path(asset["version"]["path"])
    path.unlink()
    assert client.get(f"/api/assets/{asset['id']}").json()["version"]["missing"]
    assert client.get(f"/api/media/{asset['current_version_id']}").status_code == 404
    endpoint = f"/api/assets/{asset['id']}/repair"
    assert client.post(endpoint, files={"file": ("wrong.png", png_bytes("blue"))}).status_code == 409
    response = client.post(endpoint, files={"file": ("right.png", png_bytes())})
    assert response.status_code == 200
    assert path.read_bytes() == png_bytes()


def test_preview_failure_retry_and_recovery(client, png_bytes, monkeypatch):
    asset = upload(client, png_bytes())
    task = client.get("/api/tasks").json()[0]
    original = media.build_preview
    def fail_preview(store, version):
        raise RuntimeError("模拟媒体处理失败")
    monkeypatch.setattr(media, "build_preview", fail_preview)
    client.app.state.worker.execute(task)
    failed = client.get("/api/tasks").json()[0]
    assert failed["status"] == "failed"
    assert "模拟" in failed["error"]
    monkeypatch.setattr(media, "build_preview", original)
    retried = client.post(f"/api/tasks/{task['id']}/retry")
    assert retried.status_code == 200
    assert retried.json()["status"] == "pending"
    client.app.state.worker.execute(retried.json())
    assert client.get("/api/tasks").json()[0]["status"] == "ready"
    assert client.get(f"/api/media/{asset['current_version_id']}?variant=thumbnail").status_code == 200


def test_corrupt_media_and_empty_upload_rejected(client, monkeypatch):
    # Avoid depending on an installed binary for this malformed-file branch.
    monkeypatch.setattr(media, "find_binary", lambda name: "ffprobe")
    def invalid_probe(*args, **kwargs):
        raise RuntimeError("Invalid data found")
    monkeypatch.setattr(media, "run_process", invalid_probe)
    assert client.post("/api/assets/upload", files={"file": ("broken.png", b"corrupt")}).status_code == 415
    assert client.post("/api/assets/upload", files={"file": ("empty.png", b"")}).status_code == 422
    assert client.get("/api/assets").json()["total"] == 0
    assert list((client.app.state.store.root / "temp").iterdir()) == []


def test_media_range_and_head(client, png_bytes):
    content = png_bytes()
    asset = upload(client, content)
    path = f"/api/media/{asset['current_version_id']}"
    partial = client.get(path, headers={"Range": "bytes=3-12"})
    assert partial.status_code == 206
    assert partial.content == content[3:13]
    assert partial.headers["content-range"] == f"bytes 3-12/{len(content)}"
    assert client.get(path, headers={"Range": "bytes=-8"}).content == content[-8:]
    head = client.head(path, headers={"Range": "bytes=3-12"})
    assert head.status_code == 206 and head.content == b""
    assert int(head.headers["content-length"]) == 10
    assert client.get(path, headers={"Range": "bytes=99999-"}).status_code == 416
    assert client.get(path, headers={"Range": "bytes=0-1,4-5"}).status_code == 416


def test_audio_import_and_real_preview(client):
    if not media.find_binary("ffmpeg") or not media.find_binary("ffprobe"):
        pytest.skip("FFmpeg/FFprobe unavailable on this test host")
    buffer = BytesIO()
    with wave.open(buffer, "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(8000)
        output.writeframes(b"\x00\x00" * 1600)
    asset = upload(client, buffer.getvalue(), "对白.wav")
    assert asset["type"] == "audio"
    assert asset["version"]["duration"] == pytest.approx(0.2, abs=0.02)
    client.app.state.worker.execute(client.get("/api/tasks").json()[0])
    assert client.get("/api/tasks").json()[0]["status"] == "ready"
    assert client.get(f"/api/media/{asset['current_version_id']}?variant=waveform").status_code == 200


def test_chinese_storage_migration_survives_restart(png_bytes, tmp_path, monkeypatch):
    destination = tmp_path / "新素材库 中文 空格"
    initial = create_app(data_dir=tmp_path / "素材库", config_file=tmp_path / "配置.json")
    with TestClient(initial, base_url="http://127.0.0.1") as client:
        item = project(client)
        asset = upload(client, png_bytes(), project_id=item["id"])
        result = client.post("/api/settings/storage/migrate", json={"target": str(destination)})
        assert result.status_code == 202, result.text
        completed = wait_migration(client, "completed")
        assert Path(completed["root"]) == destination
    monkeypatch.delenv("MANJU_DATA_DIR", raising=False)
    app = create_app(data_dir=tmp_path / "素材库", config_file=tmp_path / "配置.json")
    with TestClient(app, base_url="http://127.0.0.1") as restarted:
        assert Path(restarted.get("/api/health").json()["root"]) == destination
        assert restarted.get(f"/api/projects/{item['id']}").status_code == 200
        assert restarted.get(f"/api/media/{asset['current_version_id']}").content == png_bytes()


def test_migration_keeps_changing_comfy_runtime_with_bootstrap(png_bytes, tmp_path, monkeypatch):
    source = tmp_path / "原资料库"
    config = source / "config.json"
    destination = tmp_path / "迁移目标"
    app = create_app(data_dir=source, config_file=config)
    with TestClient(app, base_url="http://127.0.0.1") as client:
        app.state.worker.stop()
        item = project(client)
        asset = upload(client, png_bytes(), project_id=item["id"])
        runtime = source / "config.comfy"
        logs = runtime / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        (runtime / "settings.json").write_text('{"port":8188}', encoding="utf-8")
        (runtime / "process.json.tmp").write_text("{}", encoding="utf-8")
        log = logs / "running.log"
        log.write_text("ComfyUI starting\n", encoding="utf-8")
        original_copy = transfers._copy_verified

        def copy_while_logging(*args):
            with log.open("a", encoding="utf-8") as output:
                output.write("ComfyUI is still running\n")
            return original_copy(*args)

        monkeypatch.setattr(transfers, "_copy_verified", copy_while_logging)
        response = client.post("/api/settings/storage/migrate", json={"target": str(destination)})
        assert response.status_code == 202, response.text
        assert Path(wait_migration(client, "completed")["root"]) == destination
        assert not (destination / "config.comfy").exists()
        assert (runtime / "settings.json").is_file()
        assert "still running" in log.read_text(encoding="utf-8")
        assert client.get(f"/api/projects/{item['id']}").status_code == 200
        assert client.get(f"/api/media/{asset['current_version_id']}?variant=original").content == png_bytes()


def test_migration_failure_resume_and_cancel(client, png_bytes, tmp_path, monkeypatch):
    asset = upload(client, png_bytes())
    original_copy = transfers._copy_verified
    def fail_copy(*args):
        raise OSError("模拟磁盘故障")
    monkeypatch.setattr(transfers, "_copy_verified", fail_copy)
    response = client.post("/api/settings/storage/migrate", json={"target": str(tmp_path / "第一次")})
    assert response.status_code == 202
    wait_migration(client, "failed")
    assert client.get("/api/health").json()["maintenance"] is True
    assert client.get(f"/api/media/{asset['current_version_id']}").content == png_bytes()
    assert client.post("/api/projects", json={"name": "迁移中"}).status_code in (409, 423)
    monkeypatch.setattr(transfers, "_copy_verified", original_copy)
    resumed = client.post("/api/settings/storage/migration/resume")
    assert resumed.status_code == 202, resumed.text
    wait_migration(client, "completed")
    monkeypatch.setattr(transfers, "_copy_verified", fail_copy)
    assert client.post("/api/settings/storage/migrate", json={"target": str(tmp_path / "第二次")}).status_code == 202
    wait_migration(client, "failed")
    cancelled = client.post("/api/settings/storage/migration/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["migration"]["status"] == "cancelled"
    assert client.get("/api/health").json()["maintenance"] is False
    assert client.post("/api/projects", json={"name": "恢复写入"}).status_code == 201


def test_cross_site_requests_are_rejected(client):
    assert client.get("/api/assets", headers={"Origin": "https://example.com"}).status_code == 403
    assert client.get("/api/assets", headers={"Host": "example.com"}).status_code == 403
    assert client.get("/api/assets", headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403


def test_library_lock_blocks_second_instance(client):
    store = client.app.state.store
    with pytest.raises(DomainError) as error:
        Store(store.root, store.config_file)
    assert error.value.detail["code"] == "library_in_use"
    assert client.get("/api/health").json()["ok"] is True


def test_failed_import_reports_file_required(client, monkeypatch):
    monkeypatch.setattr(media, "find_binary", lambda name: None)
    response = client.post("/api/assets/upload", files={"file": ("broken.wav", b"bad-data")})
    assert response.status_code >= 400
    tasks = client.get("/api/tasks").json()
    failed = next(task for task in tasks if task["kind"] == "import")
    assert failed["status"] == "failed"
    assert failed["requires_file"] is True
    assert failed["can_retry"] is False
    retry = client.post(f"/api/tasks/{failed['id']}/retry")
    assert retry.status_code == 409
    assert retry.json()["detail"]["code"] == "file_required"
