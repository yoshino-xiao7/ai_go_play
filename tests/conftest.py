from __future__ import annotations

from io import BytesIO
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image
import pytest

from manju.app import create_app


@pytest.fixture
def png_bytes():
    def make(color="red"):
        buffer = BytesIO()
        Image.new("RGB", (32, 24), color).save(buffer, format="PNG")
        return buffer.getvalue()
    return make


@pytest.fixture
def client(tmp_path):
    app = create_app(data_dir=tmp_path / "素材库", config_file=tmp_path / "配置.json")
    with TestClient(app, base_url="http://127.0.0.1") as session:
        # Deterministic state lets tests explicitly execute and fail preview jobs.
        app.state.worker.stop()
        yield session


def upload(client, content: bytes, name="角色.png", **fields):
    response = client.post("/api/assets/upload", files={"file": (name, content)}, data=fields)
    assert response.status_code == 201, response.text
    return response.json()


def project(client, name="末班车"):
    response = client.post("/api/projects", json={"name": name, "aspect_ratio": "9:16"})
    assert response.status_code == 201, response.text
    return response.json()


def pin(client, project_id, version_id, request_id="canvas-1"):
    path = f"/api/projects/{project_id}/canvas"
    canvas = client.get(path).json()
    canvas["nodes"].append({"id": "card-1", "type": "media", "position": {"x": 12, "y": 34}, "data": {"asset_version_id": version_id}})
    canvas["request_id"] = request_id
    response = client.put(path, json=canvas)
    assert response.status_code == 200, response.text
    return response.json()
