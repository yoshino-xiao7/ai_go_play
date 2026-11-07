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
from test_library import wait_migration


def save_subject(client, version_id, name="主角 · 正面", description="银发角色设定", request_id=None):
    response = client.post("/api/subjects", json={"name": name, "description": description, "version_id": version_id}, headers={"X-Request-ID": request_id} if request_id else {})
    assert response.status_code == 201, response.text
    return response.json()


def test_subject_crud_search_and_fixed_old_version_without_copying(client, png_bytes):
    asset = upload(client, png_bytes("red"))
    version = asset["current_version_id"]
    store = client.app.state.store
    before_blobs = store.conn.execute("SELECT COUNT(*) FROM blobs").fetchone()[0]
    subject = save_subject(client, version)
    assert subject["version_id"] == subject["version"]["id"] == version
    assert subject["asset_id"] == asset["id"]
    assert subject["version"]["mime"] == "image/png"
    assert store.conn.execute("SELECT COUNT(*) FROM blobs").fetchone()[0] == before_blobs
    assert client.get(f"/api/media/{version}?variant=thumbnail").status_code == 200
    assert client.get(f"/api/subjects/{subject['id']}").json() == subject
    updated_asset = upload(client, png_bytes("blue"), asset_id=asset["id"])
    assert updated_asset["current_version_id"] != version
    assert client.get(f"/api/subjects/{subject['id']}").json()["version_id"] == version
    assert client.get(f"/api/media/{version}").content == png_bytes("red")
    second = save_subject(client, updated_asset["current_version_id"], "主角 · 侧面", "蓝色衣服")
    assert client.get("/api/subjects", params={"search": "银发"}).json()["items"][0]["id"] == subject["id"]
    page = client.get("/api/subjects", params={"search": "主角", "limit": 1, "offset": 1}).json()
    assert page["total"] == 2 and len(page["items"]) == 1
    changed = client.patch(f"/api/subjects/{subject['id']}", json={"name": "女主正面", "description": " 第一集 · 冬装 "})
    assert changed.status_code == 200
    assert changed.json()["description"] == "第一集 · 冬装"
    assert changed.json()["version_id"] == version
    assert client.get("/api/subjects", params={"search": "女主"}).json()["total"] == 1
    immutable = client.patch(f"/api/subjects/{subject['id']}", json={"version_id": second["version_id"]})
    assert immutable.status_code == 422
    assert immutable.json()["detail"]["code"] == "subject_version_immutable"
    assert client.delete(f"/api/subjects/{subject['id']}").json() == {"id": subject["id"], "deleted": True}
    assert client.get(f"/api/subjects/{subject['id']}").status_code == 404
    assert client.get(f"/api/media/{version}").content == png_bytes("red")
    assert client.get(f"/api/assets/{asset['id']}").json()["version_count"] == 2


def test_subject_create_idempotency_and_conflict(client, png_bytes):
    asset = upload(client, png_bytes())
    first = save_subject(client, asset["current_version_id"], request_id="one-subject")
    again = save_subject(client, asset["current_version_id"], request_id="one-subject")
    assert again == first
    conflict = client.post("/api/subjects", json={"name": "其他名称", "version_id": asset["current_version_id"]}, headers={"X-Request-ID": "one-subject"})
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["code"] == "idempotency_conflict"
    assert client.get("/api/subjects").json()["total"] == 1
    events = client.app.state.store.events(0)
    assert sum(event["type"] == "subject.created" for event in events) == 1
    for request_id in ("", "x" * 201):
        invalid = client.post("/api/subjects", json={"name": "新主体", "version_id": asset["current_version_id"]}, headers={"X-Request-ID": request_id})
        assert invalid.status_code == 422


def test_subject_reference_protection_preserves_project_reference_dto(client, png_bytes):
    item = project(client)
    asset = upload(client, png_bytes(), project_id=item["id"])
    before = client.get(f"/api/assets/{asset['id']}").json()["references"]
    subject = save_subject(client, asset["current_version_id"])
    details = client.get(f"/api/assets/{asset['id']}").json()
    assert details["references"] == before
    assert details["subject_references"][0]["id"] == subject["id"]
    assert details["subject_references"][0]["version_id"] == asset["current_version_id"]
    blocked = client.delete(f"/api/assets/{asset['id']}")
    assert blocked.status_code == 409
    assert blocked.json()["detail"]["code"] == "subject_referenced"
    assert blocked.json()["detail"]["subjects"][0]["id"] == subject["id"]
    client.delete(f"/api/subjects/{subject['id']}")
    assert client.delete(f"/api/assets/{asset['id']}").json()["detail"]["code"] == "asset_referenced"
    assert client.get(f"/api/assets/{asset['id']}").json()["subject_references"] == []


def test_subject_also_protects_purge_and_database_foreign_key(client, png_bytes):
    asset = upload(client, png_bytes())
    subject = save_subject(client, asset["current_version_id"])
    store = client.app.state.store
    with pytest.raises(sqlite3.IntegrityError):
        with store.tx():
            store.conn.execute("DELETE FROM assets WHERE id=?", (asset["id"],))
    # Exercise a legacy or externally edited database with a trashed asset.
    with store.tx():
        store.conn.execute("UPDATE assets SET deleted_at='2026-01-01' WHERE id=?", (asset["id"],))
    blocked = client.delete(f"/api/assets/{asset['id']}/permanent")
    assert blocked.status_code == 409
    assert blocked.json()["detail"]["code"] == "subject_referenced"
    assert client.delete(f"/api/subjects/{subject['id']}").status_code == 200
    assert client.delete(f"/api/assets/{asset['id']}/permanent").status_code == 200


@pytest.mark.parametrize("changes", [{"name": " "}, {"name": "x" * 251}, {"description": None}, {"description": "x" * 6001}, {"version_id": ""}, {"version_id": None}, {"unexpected": 1}])
def test_subject_rejects_invalid_payload_atomically(client, png_bytes, changes):
    asset = upload(client, png_bytes())
    payload = {"name": "角色", "version_id": asset["current_version_id"], **changes}
    response = client.post("/api/subjects", json=payload)
    assert response.status_code == 422, response.text
    assert client.get("/api/subjects").json() == {"items": [], "total": 0}


def test_subject_rejects_unknown_trashed_missing_and_nonimage_versions(client, png_bytes):
    assert client.post("/api/subjects", json={"name": "失效", "version_id": "unknown"}).status_code == 404
    trashed = upload(client, png_bytes("red"))
    client.delete(f"/api/assets/{trashed['id']}")
    response = client.post("/api/subjects", json={"name": "回收站", "version_id": trashed["current_version_id"]})
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "asset_trashed"
    missing = upload(client, png_bytes("blue"))
    Path(missing["version"]["path"]).unlink()
    response = client.post("/api/subjects", json={"name": "缺失", "version_id": missing["current_version_id"]})
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "subject_image_missing"
    content = BytesIO()
    with wave.open(content, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(b"\0\0" * 160)
    sound = upload(client, content.getvalue(), "声音.wav")
    response = client.post("/api/subjects", json={"name": "声音", "version_id": sound["current_version_id"]})
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "subject_image_required"
    assert client.get("/api/subjects").json()["total"] == 0


def test_subjects_survive_complete_library_migration_and_restart(tmp_path, png_bytes):
    source, target, config = tmp_path / "原始资料", tmp_path / "新资料 中文", tmp_path / "配置.json"
    with TestClient(create_app(source, config), base_url="http://127.0.0.1") as session:
        asset = upload(session, png_bytes())
        subject = save_subject(session, asset["current_version_id"])
        response = session.post("/api/settings/storage/migrate", json={"target": str(target)})
        assert response.status_code == 202
        assert Path(wait_migration(session, "completed")["root"]) == target
    with TestClient(create_app(source, config), base_url="http://127.0.0.1") as restarted:
        recovered = restarted.get(f"/api/subjects/{subject['id']}").json()
        assert recovered["version_id"] == subject["version_id"]
        assert recovered["name"] == subject["name"]
        assert Path(recovered["version"]["path"]).is_relative_to(target)
        assert restarted.get(f"/api/media/{subject['version_id']}").content == png_bytes()
        assert restarted.delete(f"/api/assets/{asset['id']}").json()["detail"]["code"] == "subject_referenced"


def test_project_archive_does_not_export_or_duplicate_global_subjects(client, png_bytes):
    item = project(client)
    project_asset = upload(client, png_bytes("red"), project_id=item["id"])
    unrelated = upload(client, png_bytes("blue"))
    subject = save_subject(client, unrelated["current_version_id"], "全局角色")
    save_subject(client, project_asset["current_version_id"], "项目角色")
    archive = client.get(f"/api/projects/{item['id']}/export").content
    with zipfile.ZipFile(BytesIO(archive)) as package:
        manifest = json.loads(package.read("manifest.json"))
        assert "subjects" not in manifest
        assert {version["id"] for version in manifest["versions"]} == {project_asset["current_version_id"]}
    imported = client.post("/api/projects/import", files={"file": ("单项目.manju", archive)})
    assert imported.status_code == 201
    assert client.get("/api/subjects").json()["total"] == 2
    assert client.get(f"/api/subjects/{subject['id']}").json()["version_id"] == unrelated["current_version_id"]
    imported_asset = client.get("/api/assets", params={"project_id": imported.json()["id"]}).json()["items"][0]
    assert client.get(f"/api/assets/{imported_asset['id']}").json()["subject_references"] == []


def test_existing_database_adds_subject_table_without_changing_media(client, png_bytes):
    asset = upload(client, png_bytes())
    store = client.app.state.store
    with store.tx():
        store.conn.execute("DROP TABLE subjects")
    store.reopen(store.root)
    assert client.get("/api/subjects").json() == {"items": [], "total": 0}
    subject = save_subject(client, asset["current_version_id"])
    assert subject["version_id"] == asset["current_version_id"]
    assert client.get(f"/api/media/{subject['version_id']}").content == png_bytes()


def test_subject_description_matches_web_limit(client, png_bytes):
    asset = upload(client, png_bytes())
    subject = save_subject(client, asset["current_version_id"], description="字" * 6000)
    assert len(subject["description"]) == 6000
