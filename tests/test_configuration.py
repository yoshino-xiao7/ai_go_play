import json
import os
from pathlib import Path

import pytest

from manju.app import resolve_configuration


def test_new_install_uses_home_without_requiring_d_drive(tmp_path, monkeypatch):
    monkeypatch.delenv("MANJU_DATA_DIR", raising=False)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    original = Path.is_file
    monkeypatch.setattr(Path, "is_file", lambda p: False if p == Path("D:/ManjuData/library.sqlite") else original(p))
    root, _ = resolve_configuration(None, tmp_path / "config.json")
    assert root == tmp_path / "ManjuData"


@pytest.mark.skipif(os.name != "nt", reason="Windows legacy library")
def test_existing_legacy_library_is_preserved(tmp_path, monkeypatch):
    monkeypatch.delenv("MANJU_DATA_DIR", raising=False)
    original = Path.is_file
    monkeypatch.setattr(Path, "is_file", lambda p: True if p == Path("D:/ManjuData/library.sqlite") else original(p))
    root, _ = resolve_configuration(None, tmp_path / "config.json")
    assert root == Path("D:/ManjuData").resolve()


def test_saved_storage_still_takes_precedence(tmp_path):
    config = tmp_path / "config.json"
    saved = tmp_path / "existing"
    config.write_text(json.dumps({"root": str(saved)}), encoding="utf-8")
    root, _ = resolve_configuration(tmp_path / "other", config)
    assert root == saved
