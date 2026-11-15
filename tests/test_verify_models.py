import hashlib
import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location("verify_models", Path(__file__).parents[1] / "release/verify_models.py")
verifier = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verifier)


def test_detects_same_size_corruption_and_missing_shared_dependency(tmp_path):
    (tmp_path / "weights.bin").write_bytes(b"bad")
    manifest = tmp_path / "checksums"
    digest = hashlib.sha256(b"yes").hexdigest()
    manifest.write_text(f"{digest}  weights.bin\n{digest}  shared.bin\n", encoding="utf-8")
    catalog = {"packs": [{"id": "video"}], "files": [
        {"path": "weights.bin", "packs": ["video"]},
        {"path": "shared.bin", "packs": ["video"]},
    ]}
    results = verifier.verify(tmp_path, manifest, catalog, "video")
    assert [r["status"] for r in results] == ["MISMATCH", "MISSING"]
    (tmp_path / "weights.bin").write_bytes(b"yes")
    (tmp_path / "shared.bin").write_bytes(b"yes")
    assert all(r["status"] == "OK" for r in verifier.verify(tmp_path, manifest, catalog))
    with pytest.raises(ValueError, match="Unknown"):
        verifier.verify(tmp_path, manifest, catalog, "typo")


def test_rejects_checksum_path_traversal(tmp_path):
    manifest = tmp_path / "checksums"
    manifest.write_text(f"{'0' * 64}  ../secret\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Invalid"):
        verifier.verify(tmp_path, manifest, {"packs": [], "files": []})
