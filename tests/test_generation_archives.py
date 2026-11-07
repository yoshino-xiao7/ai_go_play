from copy import deepcopy
from io import BytesIO
import json
import zipfile

from fastapi.testclient import TestClient
import pytest

from manju.app import create_app
from conftest import project, upload


def rewrite_manifest(content, edit):
    output = BytesIO()
    with zipfile.ZipFile(BytesIO(content)) as source, zipfile.ZipFile(output, "w") as target:
        manifest = json.loads(source.read("manifest.json"))
        edit(manifest)
        target.writestr("manifest.json", json.dumps(manifest))
        for name in source.namelist():
            if name != "manifest.json":
                target.writestr(name, source.read(name))
    return output.getvalue()


def save_draft(client, project_id, draft, base_version=None):
    path = f"/api/projects/{project_id}/canvas"
    canvas = client.get(path).json()
    canvas["nodes"] = [{"id": "prompt-card", "type": "media", "position": {"x": 20, "y": 40}, "data": {"kind": "image", "generation": draft}}]
    if base_version:
        canvas["nodes"].insert(0, {"id": "base-card", "type": "media", "position": {"x": -300, "y": 40}, "data": {"asset_version_id": base_version, "generation_id": "old-output-job"}})
        canvas["edges"] = [{"id": "reference-edge", "source": "base-card", "target": "prompt-card"}]
    response = client.put(path, json=canvas)
    assert response.status_code == 200, response.text
    return response.json()


def test_generation_archive_cross_library_pins_draft_inputs_and_clears_job_state(client, png_bytes, tmp_path):
    item = project(client)
    base = upload(client, png_bytes("red"))
    reference = upload(client, png_bytes("blue"))
    pinned = reference["current_version_id"]
    newer = upload(client, png_bytes("yellow"), asset_id=reference["id"])
    mask = upload(client, png_bytes("white"))
    custom = client.post("/api/workflows/builtin-qwen21-edit/duplicate").json()
    draft = {"mode": "edit", "prompt": "按图2的配色修改图1", "workflow_id": custom["id"], "parameters": {"seed": 42, "steps": 4}, "references": [{"version_id": pinned, "title": "旧版配色", "source": "mention"}, {"version_id": base["current_version_id"], "node_id": "base-card", "title": "底图", "source": "connection", "edge_id": "reference-edge"}], "reference_order": [pinned, base["current_version_id"], "obsolete-sort-entry"], "excluded_edge_ids": [], "mask_version_id": mask["current_version_id"], "last_job_id": "old-job", "pending_request_id": "old-request", "pending_submission": {"project_id": item["id"], "request_id": "old-request", "references": [{"version_id": pinned}]}}
    original = save_draft(client, item["id"], draft, base["current_version_id"])
    # Simulate a legacy draft saved before @ images gained project membership.
    store = client.app.state.store
    with store.tx():
        store.conn.execute("DELETE FROM project_assets WHERE project_id=? AND asset_id IN (?,?)", (item["id"], reference["id"], mask["id"]))
    assert client.get("/api/assets", params={"project_id": item["id"]}).json()["total"] == 1
    response = client.get(f"/api/projects/{item['id']}/export")
    assert response.status_code == 200, response.text
    with zipfile.ZipFile(BytesIO(response.content)) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        assert {version["id"] for version in manifest["versions"]} == {base["current_version_id"], pinned, mask["current_version_id"]}
        assert newer["current_version_id"] not in {version["id"] for version in manifest["versions"]}
        packed = manifest["canvas"]["nodes"][1]["data"]["generation"]
        assert not {"last_job_id", "pending_request_id", "pending_submission"} & packed.keys()
        assert "generation_id" not in manifest["canvas"]["nodes"][0]["data"]
    assert client.get(f"/api/projects/{item['id']}/canvas").json() == original

    # Simulate a previous exporter that included transient runtime fields.
    def inject_old_runtime(manifest):
        manifest["canvas"]["nodes"][0]["data"]["generation_id"] = "old-output-job"
        manifest["canvas"]["nodes"][1]["data"]["generation"].update(last_job_id="old-job", pending_request_id="old-request", pending_submission={"project_id": item["id"], "request_id": "old-request"})
    archived = rewrite_manifest(response.content, inject_old_runtime)
    target_app = create_app(data_dir=tmp_path / "目标资料库", config_file=tmp_path / "目标配置.json")
    with TestClient(target_app, base_url="http://127.0.0.1") as destination:
        target_app.state.worker.stop()
        imported = destination.post("/api/projects/import", files={"file": ("跨库.manju", archived)})
        assert imported.status_code == 201, imported.text
        project_id = imported.json()["id"]
        warning = imported.json()["import_warnings"][0]
        assert warning["code"] == "workflow_not_imported"
        assert warning["workflow_id"] == custom["id"]
        canvas = destination.get(f"/api/projects/{project_id}/canvas").json()
        base_data = canvas["nodes"][0]["data"]
        restored = canvas["nodes"][1]["data"]["generation"]
        assert restored["workflow_id"] == custom["id"]
        assert "未随项目包导入" in restored["workflow_import_warning"]
        assert restored["parameters"] == draft["parameters"]
        assert not {"last_job_id", "pending_request_id", "pending_submission"} & restored.keys()
        assert "generation_id" not in base_data
        versions = [reference["version_id"] for reference in restored["references"]]
        assert restored["reference_order"] == versions
        assert versions[1] == base_data["asset_version_id"]
        assert restored["references"][1]["node_id"] == "base-card"
        assert restored["references"][1]["edge_id"] == canvas["edges"][0]["id"]
        assert all(old != new for old, new in zip([pinned, base["current_version_id"]], versions))
        assert destination.get(f"/api/media/{versions[0]}").content == png_bytes("blue")
        assert destination.get(f"/api/media/{restored['mask_version_id']}").content == png_bytes("white")
        assert destination.get("/api/assets", params={"project_id": project_id}).json()["total"] == 3
        assert destination.get("/api/generations", params={"project_id": project_id}).json()["items"] == []


@pytest.mark.parametrize("malformed", [
    {"references": [{"version_id": "absent-version"}]},
    {"references": [{"version_id": ["invalid"]}]},
    {"references": "not-a-list"},
    {"references": [None]},
    {"mask_version_id": "absent-mask"},
    {"reference_order": [None]},
])
def test_missing_or_malformed_nested_archive_reference_rejected_atomically(client, malformed):
    item = project(client)
    save_draft(client, item["id"], {"mode": "reference", "prompt": "草稿", "references": [], "parameters": {}})
    archive = client.get(f"/api/projects/{item['id']}/export").content
    def edit(manifest):
        manifest["canvas"]["nodes"][0]["data"]["generation"].update(deepcopy(malformed))
    response = client.post("/api/projects/import", files={"file": ("无效引用.manju", rewrite_manifest(archive, edit))})
    assert response.status_code == 400, response.text
    assert response.json()["detail"]["code"] == "invalid_archive"
    assert len(client.get("/api/projects").json()) == 1
    assert client.get("/api/assets").json()["total"] == 0


def test_export_missing_draft_image_fails_explicitly(client):
    item = project(client)
    canvas = save_draft(client, item["id"], {"mode": "reference", "prompt": "保留缺失引用", "references": [], "parameters": {}})
    # Old builds allowed missing nested versions; export still fails explicitly.
    canvas["nodes"][0]["data"]["generation"]["references"] = [{"version_id": "missing-image", "source": "mention", "title": "图片"}]
    with client.app.state.store.tx():
        client.app.state.store.conn.execute("UPDATE canvases SET nodes=? WHERE project_id=?", (json.dumps(canvas["nodes"]), item["id"]))
    response = client.get(f"/api/projects/{item['id']}/export")
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "missing_version"
    assert response.json()["detail"]["version_id"] == "missing-image"


def test_known_builtin_workflow_remains_selected_without_warning(client):
    item = project(client)
    save_draft(client, item["id"], {"mode": "text_to_image", "prompt": "角色立绘", "workflow_id": "builtin-qwen21-text_to_image", "references": [], "parameters": {}, "workflow_import_warning": "旧提示"})
    archive = client.get(f"/api/projects/{item['id']}/export").content
    response = client.post("/api/projects/import", files={"file": ("builtin.manju", archive)})
    assert response.status_code == 201, response.text
    assert response.json()["import_warnings"] == []
    canvas = client.get(f"/api/projects/{response.json()['id']}/canvas").json()
    restored = canvas["nodes"][0]["data"]["generation"]
    assert restored["workflow_id"] == "builtin-qwen21-text_to_image"
    assert "workflow_import_warning" not in restored
