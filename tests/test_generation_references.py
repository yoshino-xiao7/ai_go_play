from copy import deepcopy

import pytest

from conftest import project, upload
from test_generation_archives import save_draft


@pytest.mark.parametrize("input_kind", ["reference", "mask", "pending"])
def test_saved_draft_inputs_are_project_references_until_explicit_unlink(client, png_bytes, input_kind):
    first = project(client, "第一项目")
    second = project(client, "第二项目")
    asset = upload(client, png_bytes())
    old_version = asset["current_version_id"]
    upload(client, png_bytes("blue"), asset_id=asset["id"])
    draft = {"mode": "edit", "prompt": "保留固定版本", "references": [], "parameters": {}}
    if input_kind == "reference":
        draft["references"] = [{"version_id": old_version, "title": "旧图", "source": "mention"}]
    elif input_kind == "mask":
        draft["mask_version_id"] = old_version
    else:
        draft["pending_submission"] = {"references": [{"version_id": old_version}], "mask_version_id": old_version}
    for item in (first, second):
        save_draft(client, item["id"], deepcopy(draft))
        members = client.get("/api/assets", params={"project_id": item["id"]}).json()
        assert members["total"] == 1
        assert members["items"][0]["id"] == asset["id"]
    references = client.get(f"/api/assets/{asset['id']}").json()["references"]
    assert len(references) == 2
    assert all(reference["node_ids"] == ["prompt-card"] and reference["node_count"] == 1 for reference in references)
    assert client.delete(f"/api/assets/{asset['id']}").json()["detail"]["code"] == "asset_referenced"
    assert client.delete(f"/api/projects/{first['id']}").status_code == 200
    # A project in the recycle bin continues protecting its recoverable draft.
    assert client.delete(f"/api/assets/{asset['id']}").status_code == 409
    assert client.post(f"/api/projects/{first['id']}/restore").status_code == 200
    for item in (first, second):
        path = f"/api/projects/{item['id']}/assets/{asset['id']}"
        blocked = client.delete(path)
        assert blocked.status_code == 409
        assert blocked.json()["detail"]["code"] == "asset_in_canvas"
        assert blocked.json()["detail"]["node_ids"] == ["prompt-card"]
        removed = client.delete(path, params={"remove_nodes": True})
        assert removed.status_code == 200
        assert removed.json()["canvas"]["nodes"] == []
    assert client.delete(f"/api/assets/{asset['id']}").status_code == 200
    assert client.delete(f"/api/assets/{asset['id']}/permanent").status_code == 200


def test_reopen_backfills_legacy_draft_membership_and_prevents_purge(client, png_bytes):
    item = project(client)
    asset = upload(client, png_bytes())
    draft = {"mode": "reference", "prompt": "旧版草稿", "references": [{"version_id": asset["current_version_id"]}], "parameters": {}}
    original = save_draft(client, item["id"], draft)
    store = client.app.state.store
    # Simulate an older build that did not track draft references and allowed
    # this still-referenced asset to enter the recycle bin.
    with store.tx():
        store.conn.execute("DELETE FROM project_assets WHERE project_id=?", (item["id"],))
        store.conn.execute("UPDATE assets SET deleted_at='2026-01-01' WHERE id=?", (asset["id"],))
    store.reopen(store.root)
    references = client.get(f"/api/assets/{asset['id']}").json()["references"]
    assert references[0]["id"] == item["id"]
    assert references[0]["node_ids"] == ["prompt-card"]
    assert client.delete(f"/api/assets/{asset['id']}/permanent").json()["detail"]["code"] == "asset_referenced"
    assert client.post(f"/api/assets/{asset['id']}/restore").status_code == 200
    assert client.get(f"/api/projects/{item['id']}/canvas").json() == original


def test_duplicate_project_keeps_draft_but_never_original_submission(client, png_bytes):
    item = project(client)
    asset = upload(client, png_bytes())
    version_id = asset["current_version_id"]
    draft = {"mode": "edit", "prompt": "保留完整提示词", "workflow_id": "builtin-qwen21-edit", "parameters": {"seed": 42}, "references": [{"version_id": version_id, "node_id": "base-card"}], "mask_version_id": version_id, "reference_order": [version_id], "last_job_id": "original-job", "pending_request_id": "original-request", "pending_submission": {"project_id": item["id"], "source_node_id": "prompt-card", "references": [{"version_id": version_id}], "request_id": "original-request"}}
    original = save_draft(client, item["id"], draft, version_id)
    duplicated = client.post(f"/api/projects/{item['id']}/duplicate")
    assert duplicated.status_code == 201
    copied_id = duplicated.json()["id"]
    copied = client.get(f"/api/projects/{copied_id}/canvas").json()
    restored = copied["nodes"][1]["data"]["generation"]
    assert restored == {key: value for key, value in draft.items() if key not in {"last_job_id", "pending_request_id", "pending_submission"}}
    assert "generation_id" not in copied["nodes"][0]["data"]
    assert copied["edges"] == original["edges"]
    assert client.get(f"/api/projects/{item['id']}/canvas").json() == original
    assert client.get("/api/generations", params={"project_id": copied_id}).json()["items"] == []
    assert client.get("/api/assets", params={"project_id": copied_id}).json()["total"] == 1


@pytest.mark.parametrize("bad_draft,status", [
    ({"references": [{"version_id": "missing"}]}, 404),
    ({"mask_version_id": "missing"}, 404),
    ({"references": [{"version_id": ["invalid"]}]}, 422),
    ({"references": "invalid"}, 422),
    ({"pending_submission": {"references": [None]}}, 422),
])
def test_canvas_rejects_bad_draft_references_atomically(client, png_bytes, bad_draft, status):
    item = project(client)
    asset = upload(client, png_bytes())
    path = f"/api/projects/{item['id']}/canvas"
    original = client.get(path).json()
    changed = deepcopy(original)
    changed["nodes"] = [{"id": "valid", "type": "media", "position": {"x": 0, "y": 0}, "data": {"asset_version_id": asset["current_version_id"]}}, {"id": "invalid", "type": "media", "position": {"x": 100, "y": 0}, "data": {"generation": bad_draft}}]
    response = client.put(path, json=changed)
    assert response.status_code == status, response.text
    assert client.get(path).json() == original
    assert client.get("/api/assets", params={"project_id": item["id"]}).json()["total"] == 0
