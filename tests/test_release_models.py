import importlib.util
import hashlib
import json
from pathlib import Path

import pytest


spec = importlib.util.spec_from_file_location("release_audit", Path(__file__).parents[1] / "scripts/audit_release_models.py")
audit_tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit_tool)


@pytest.fixture
def inventory(tmp_path):
    (tmp_path / "model.bin").write_bytes(b"model")
    catalog = {"packs": [{"id": "image"}, {"id": "video"}], "files": [
        {"path": "model.bin", "packs": ["image", "video"]},
        {"path": "absent.bin", "packs": ["video"]},
    ]}
    return tmp_path, catalog


def test_unknown_cloud_never_becomes_an_upload_plan(inventory):
    root, catalog = inventory
    report = audit_tool.audit(root, catalog)
    assert report["summary"]["remote_status"] == {"unknown": 2}
    assert report["summary"]["local_bytes"] == 5
    assert audit_tool.upload_plan(report, root)["files"] == []


def test_missing_cloud_file_is_planned_once_for_shared_model(inventory):
    root, catalog = inventory
    report = audit_tool.audit(root, catalog, remote={})
    plan = audit_tool.upload_plan(report, root)["files"]
    assert len(plan) == 1
    assert plan[0]["destination"] == "image/models/model.bin"
    assert plan[0]["packs"] == ["image", "video"]


def test_same_size_does_not_imply_same_contents(inventory):
    root, catalog = inventory
    remote = {"model.bin": {"size": 5, "sha256": "0" * 64}}
    assert audit_tool.audit(root, catalog, remote)["files"][0]["remote_status"] == "same_size_unverified"
    report = audit_tool.audit(root, catalog, remote, hash_files=True)
    assert report["files"][0]["remote_status"] == "hash_mismatch"
    remote["model.bin"]["sha256"] = report["files"][0]["sha256"]
    assert audit_tool.audit(root, catalog, remote, hash_files=True)["files"][0]["remote_status"] == "verified_sha256"


@pytest.mark.parametrize("name", ["../secret", "/absolute", "C:\\secret", "folder/../../secret", ""])
def test_rejects_paths_outside_model_root(name):
    with pytest.raises(ValueError):
        audit_tool.relative_path(name)


def test_remote_inventory_rejects_ambiguous_duplicate_paths(tmp_path):
    path = tmp_path / "remote.json"
    path.write_text(json.dumps({"files": [{"path": "a/b", "size": 1}, {"path": "a\\b", "size": 1}]}))
    with pytest.raises(ValueError, match="Duplicate"):
        audit_tool.read_remote(path)


def test_release_source_evidence_covers_exact_published_files_and_digests():
    release = Path(__file__).parents[1] / 'release'
    catalog = json.loads((release / 'models.json').read_text(encoding='utf-8'))
    sources = json.loads((release / 'model-sources.json').read_text(encoding='utf-8'))['files']
    checks = dict(line.split('  ', 1)[::-1] for line in (release / 'model-checksums.sha256').read_text().splitlines() if line.strip())
    assert len({row['path'] for row in sources}) == len(sources)
    assert {row['path'] for row in sources} == set(checks) == {row['path'] for row in catalog['files']}
    for row in sources:
        assert row['sha256'] == checks[row['path']]
        if row['proof']['method'] in ('upstream-lfs-sha256', 'downloaded-upstream-sha256', 'downloaded-release-sha256'):
            assert row['proof']['value'] == row['sha256']
        if row['source_status'] == 'verified':
            assert len(row['source']['revision']) == 40
            assert row['source']['url'].startswith('https://')
    unet = next(row for row in sources if row['path'].endswith('latentsync_unet.pt'))
    assert unet['license_status'] == 'version-scope-unresolved'
    assert 'OpenRAIL++' in unet['license']


def test_original_license_attachments_match_recorded_bytes():
    root = Path(__file__).parents[1]
    records = json.loads((root / 'release/licenses/index.json').read_text())['documents']
    for record in records:
        path = (root / record['path']).resolve()
        assert path.is_relative_to(root / 'release/licenses')
        assert hashlib.sha256(path.read_bytes()).hexdigest() == record['sha256']


def test_model_license_page_available_before_onboarding(client):
    response = client.get('/api/setup/model-licenses')
    assert response.status_code == 200
    assert 'text/plain' in response.headers['content-type']
    assert 'OpenRAIL++' in response.text and 'CC-BY-NC-SA-4.0' in response.text
