from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

import httpx

from conftest import pin, project, upload
from manju.share import ShareService

SLUG = "AbCdEfGhIjKlMnOpQrStUv"
SHARE_URL = f"https://yk.test/s/{SLUG}"


def test_public_share_round_trips_through_portable_project(client, png_bytes, monkeypatch):
    content = png_bytes()
    digest = hashlib.sha256(content).hexdigest()
    media_url = f"https://test-bucket.oss-cn-shanghai.aliyuncs.com/canvas/media/preview/{digest}?signature=test"
    project_id = project(client)["id"]
    _canvas_with_prompt(client, project_id, upload(client, content, project_id=project_id)["current_version_id"])
    canvas = client.get(f"/api/projects/{project_id}/canvas").json()
    canvas["nodes"][0]["data"].update(
        asset_version_id="public-image",
        image_history=[{"version_id": "video-poster-only"}],
    )
    snapshot = {
        "slug": SLUG, "visibility": "PUBLIC", "project": {"name": "公开作品", "aspectRatio": "16:9"},
        "canvas": canvas, "media": {
            "public-image": {"kind": "image", "urls": {"view": media_url}},
            "video-poster-only": {"kind": "video", "urls": {"thumb": media_url}},
        },
    }
    seen = []
    served = content

    def upstream(request):
        seen.append(request)
        assert "Authorization" not in request.headers
        if request.url.host == "api.yk.test":
            assert request.url.path == f"/canvas/public/{SLUG}"
            return httpx.Response(200, json=snapshot)
        assert str(request.url) == media_url
        return httpx.Response(200, content=served)

    monkeypatch.setenv("MANJU_SETU_WEB_BASE", "https://yk.test")
    monkeypatch.setenv("MANJU_SETU_API_BASE", "https://api.yk.test")
    client.app.state.share._transport = httpx.MockTransport(upstream)

    exported = client.get("/api/share/export", params={"link": SHARE_URL})
    assert exported.status_code == 200, exported.text
    assert ".manju" in exported.headers["Content-Disposition"]
    uploaded = client.post("/api/projects/import", files={"file": ("square.manju", exported.content)})
    direct = client.post("/api/share/import", json={"link": SHARE_URL})
    assert uploaded.status_code == direct.status_code == 201, direct.text
    assert direct.json()["omitted_history"] == 1
    assert uploaded.json()["id"] != direct.json()["id"]
    for response in (uploaded, direct):
        loaded = client.get(f"/api/projects/{response.json()['id']}/canvas").json()
        node = loaded["nodes"][0]
        assert node["data"]["generation"]["prompt"] == "雨夜的站台"
        assert node["data"]["asset_version_id"] != "public-image"
        assert node["data"]["image_history"] == []
        assert loaded["edges"] == canvas["edges"]

    before = len(client.get("/api/projects").json())
    bad_link = client.post("/api/share/import", json={"link": SHARE_URL.replace("yk.test", "external.invalid")})
    assert bad_link.status_code == 400
    assert len(seen) == 4
    snapshot["media"]["public-image"]["urls"]["view"] = "http://127.0.0.1:1234/image"
    rejected = client.post("/api/share/import", json={"link": SHARE_URL})
    assert rejected.status_code == 422
    assert len(seen) == 5
    snapshot["media"]["public-image"]["urls"]["view"] = media_url
    served = b"truncated upstream response"
    corrupt = client.post("/api/share/import", json={"link": SHARE_URL})
    assert corrupt.status_code == 400
    assert corrupt.json()["detail"]["code"] == "share_import_hash_mismatch"
    assert not list((client.app.state.store.root / "temp").glob("export-*.manju"))
    snapshot["visibility"] = "LINK"
    assert client.post("/api/share/import", json={"link": SHARE_URL}).status_code == 403
    assert len(client.get("/api/projects").json()) == before


def _ready(store, version_id: str) -> None:
    with store.tx():
        store.conn.execute("UPDATE versions SET preview_status='ready' WHERE id=?", (version_id,))


def _canvas_with_prompt(client, project_id: str, version_id: str) -> None:
    path = f"/api/projects/{project_id}/canvas"
    canvas = client.get(path).json()
    canvas["nodes"] = [
        {
            "id": "card-1",
            "type": "media",
            "position": {"x": 10, "y": 20},
            "style": {"width": 380, "height": 240},
            "data": {
                "title": "分镜 A",
                "kind": "image",
                "asset_version_id": version_id,
                "generation": {
                    "mode": "image",
                    "prompt": "雨夜的站台",
                    "parameters": {"steps": 28},
                    "references": [],
                },
            },
        },
        {
            "id": "note-1",
            "type": "text",
            "position": {"x": 420, "y": 20},
            "data": {"title": "备注", "text": "开场三秒"},
        },
    ]
    canvas["edges"] = [
        {"id": "edge-1", "source": "card-1", "target": "note-1", "data": {"role": "relation"}}
    ]
    canvas["request_id"] = "share-canvas"
    response = client.put(path, json=canvas)
    assert response.status_code == 200, response.text


def test_build_plan_carries_cards_prompts_edges_and_media(client, png_bytes):
    store = client.app.state.store
    item = project(client)
    asset = upload(client, png_bytes(), project_id=item["id"])
    version_id = asset["current_version_id"]
    _ready(store, version_id)
    _canvas_with_prompt(client, item["id"], version_id)

    plan = client.app.state.share._build_plan(
        item["id"],
        {"quality": "preview", "visibility": "link", "title": "雨夜", "viewport": {"x": 5, "y": 6, "zoom": 0.8}},
    )

    manifest = plan["manifest"]
    assert manifest["format"] == "manju-canvas-share"
    assert manifest["version"] == 1
    assert manifest["project"]["name"] == item["name"]
    assert manifest["canvas"]["nodes"][0]["data"]["generation"]["prompt"] == "雨夜的站台"
    assert manifest["canvas"]["edges"][0]["data"]["role"] == "relation"
    assert manifest["canvas"]["viewport"] == {"x": 5.0, "y": 6.0, "zoom": 0.8}
    assert manifest["stats"]["nodes"] == 2
    assert manifest["stats"]["edges"] == 1

    media = manifest["media"][version_id]
    assert media["kind"] == "image"
    expected_hash = hashlib.sha256(png_bytes()).hexdigest()
    assert media["variants"]["view"]["hash"] == expected_hash
    assert media["variants"]["view"]["variant"] == "ORIGINAL"
    assert media["degraded"] is True  # 缩略图尚未生成时降级但不缺失
    assert plan["visibility"] == "LINK"
    assert plan["quality"] == "preview"
    assert plan["files"][0]["contentHash"] == expected_hash
    assert plan["paths"][expected_hash].is_file()


def test_publish_streams_uploads_and_commits_manifest(client, png_bytes):
    store = client.app.state.store
    item = project(client)
    asset = upload(client, png_bytes(), project_id=item["id"])
    version_id = asset["current_version_id"]
    _ready(store, version_id)
    _canvas_with_prompt(client, item["id"], version_id)

    seen = {"uploads": 0, "manifest": None}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if request.method == "POST" and path == "/canvas/device/shares/prepare":
            body = json.loads(request.content or b"{}")
            assert body["files"], body
            uploads = [
                {
                    "contentHash": item["contentHash"],
                    "variant": item["variant"],
                    "method": "PUT",
                    "url": f"https://oss.test/{item['contentHash']}",
                    "headers": {"Content-Type": item["mime"]},
                    "skip": False,
                }
                for item in body["files"]
            ]
            return httpx.Response(200, json={
                "shareId": 55, "slug": SLUG, "totalBytes": 1234, "uploads": uploads,
            })
        if request.method == "PUT" and request.url.host == "oss.test":
            seen["uploads"] += 1
            return httpx.Response(200)
        if request.method == "POST" and path == "/canvas/device/shares/55/commit":
            body = json.loads(request.content or b"{}")
            seen["manifest"] = body["manifest"]
            return httpx.Response(200, json={"slug": SLUG, "url": SHARE_URL, "warnings": []})
        return httpx.Response(404, json={"code": "NOT_FOUND", "message": "unexpected"})

    client.app.state.share.close()
    client.app.state.share = ShareService(store, transport=httpx.MockTransport(handler))
    client.app.state.share.config.save({
        "api_base": "https://api.test",
        "web_base": "https://yk.test",
        "token": "ykc_test",
        "user": {"id": 7, "nickname": "小明"},
    })

    revision = client.get(f"/api/projects/{item['id']}").json()["revision"]
    started = client.post(f"/api/projects/{item['id']}/share", json={
        "request_id": "share-1", "title": "雨夜", "visibility": "link", "quality": "preview",
        "canvas_revision": revision, "viewport": {"x": 0, "y": 0, "zoom": 1},
    })
    assert started.status_code == 202, started.text

    state = None
    for _ in range(100):
        state = client.get(f"/api/projects/{item['id']}/share").json()
        if state["job"] and state["job"]["state"] != "running":
            break
        time.sleep(0.05)
    assert state["job"]["state"] == "done", state
    assert seen["uploads"] >= 1
    assert seen["manifest"]["canvas"]["nodes"][0]["data"]["generation"]["prompt"] == "雨夜的站台"
    assert state["share"]["slug"] == SLUG
    assert state["share"]["url"] == SHARE_URL
    assert state["share"]["visibility"] == "LINK"

    registry = client.get("/api/shares").json()
    assert len(registry) == 1
    assert registry[0]["slug"] == SLUG
    assert registry[0]["project_name"] == item["name"]


def test_publish_rejects_stale_canvas_revision(client, png_bytes):
    store = client.app.state.store
    item = project(client)
    asset = upload(client, png_bytes(), project_id=item["id"])
    _canvas_with_prompt(client, item["id"], asset["current_version_id"])
    client.app.state.share.config.save({"token": "ykc_test", "api_base": "https://api.test", "web_base": "https://yk.test"})

    response = client.post(f"/api/projects/{item['id']}/share", json={
        "request_id": "share-2", "visibility": "link", "canvas_revision": 999,
    })
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "share_outdated"


def test_publish_requires_connected_account(client, png_bytes):
    item = project(client)
    response = client.post(f"/api/projects/{item['id']}/share", json={"request_id": "share-3"})
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "share_not_connected"


def test_share_status_and_connect_url(client):
    store = client.app.state.store
    client.app.state.share.close()
    client.app.state.share = ShareService(
        store,
        transport=httpx.MockTransport(
            lambda request: httpx.Response(404, json={"code": "CANVAS_CONNECT_REQUEST_INVALID"})
        ),
    )

    status = client.get("/api/share/status").json()
    assert status["connected"] is False

    started = client.post("/api/share/connect")
    assert started.status_code == 200, started.text
    payload = started.json()
    assert len(payload["request_id"]) == 32
    assert "/connect?" in payload["authorize_url"]
    assert "challenge=" in payload["authorize_url"]

    state = client.get(f"/api/share/connect/{payload['request_id']}").json()
    assert state["state"] == "pending"
    assert state["seconds_left"] > 0


def test_project_share_is_empty_before_first_publish(client):
    item = project(client)
    state = client.get(f"/api/projects/{item['id']}/share").json()
    assert state == {"share": None, "job": None}


def test_delete_share_without_remote_connection_is_local(client):
    item = project(client)
    response = client.delete(f"/api/projects/{item['id']}/share")
    assert response.status_code == 200
    assert response.json() == {"deleted": False}
