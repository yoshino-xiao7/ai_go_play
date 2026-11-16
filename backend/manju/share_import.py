"""Turn a public Setu canvas snapshot into an ordinary portable project."""
from __future__ import annotations

import hashlib
import json
import mimetypes
import re
import tempfile
import zipfile
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from .media import probe_media
from .share import ShareClient, _valid_viewport
from .store import DomainError, new_id, now
from .transfers import ARCHIVE_FORMAT, MAX_MANIFEST_BYTES, _canvas_version_ids, _portable_canvas

SHARE_PATH = re.compile(r"/s/([A-Za-z0-9_-]{16,32})/?")
OSS_HOST = re.compile(r"[a-z0-9-]+\.oss-[a-z0-9-]+\.aliyuncs\.com")
OSS_OBJECT = re.compile(r"/canvas/media/(?:original|preview|thumb)/([0-9a-f]{64})")
MAX_MEDIA_BYTES = 200 * 1024**2
MAX_TOTAL_BYTES = 4 * 1024**3


def _slug(link: str, web_base: str) -> str:
    try:
        url, base = urlsplit(link.strip()), urlsplit(web_base)
        match = SHARE_PATH.fullmatch(url.path)
        if url.scheme == base.scheme and url.netloc.lower() == base.netloc.lower() and match:
            return match[1]
    except ValueError:
        pass
    raise DomainError(400, "请粘贴亦可画布作品页的完整链接。", "invalid_share_link")


def _snapshot(client: ShareClient, slug: str) -> dict:
    try:
        with client.client.stream(
            "GET", f"{client.api_base}/canvas/public/{slug}", headers=client._headers(),
            timeout=httpx.Timeout(30, connect=10),
        ) as response:
            if response.status_code == 401:
                raise DomainError(403, "这张画布需要登录查看。请使用广场上的公开画布。", "share_import_private")
            if response.is_error:
                if response.status_code == 404:
                    raise DomainError(404, "画布不存在、已撤下或链接有误。", "share_not_found")
                raise DomainError(502, f"亦可未能读取画布（HTTP {response.status_code}）。", "share_import_unavailable")
            data = bytearray()
            for chunk in response.iter_bytes():
                if len(data) + len(chunk) > MAX_MANIFEST_BYTES:
                    raise DomainError(413, "亦可画布清单超过导入大小限制。", "share_import_too_large")
                data.extend(chunk)
        try:
            snapshot = json.loads(data)
        except ValueError as error:
            raise DomainError(502, "亦可返回的画布清单无法解析。", "share_bad_response") from error
    except httpx.HTTPError as error:
        raise DomainError(502, "无法连接亦可，请检查网络后重试。", "share_network_error") from error
    if not isinstance(snapshot, dict) or snapshot.get("slug") != slug:
        raise DomainError(502, "亦可返回的画布标识与链接不符。", "share_bad_response")
    if snapshot.get("visibility") != "PUBLIC":
        raise DomainError(403, "当前支持导入亦可广场的公开画布。", "share_import_private")
    return snapshot


def _media_source(entry: dict) -> tuple[str, str]:
    urls = entry.get("urls") or {}
    url = urls.get("view") or (urls.get("thumb") if entry.get("kind") == "image" else None)
    try:
        if not isinstance(url, str):
            raise ValueError("missing media URL")
        parsed = urlsplit(url)
        match = OSS_OBJECT.fullmatch(parsed.path)
        if parsed.scheme != "https" or not OSS_HOST.fullmatch(parsed.netloc) or not match:
            raise ValueError("invalid OSS object URL")
    except ValueError as error:
        raise DomainError(422, "亦可没有提供可下载的画布素材。", "share_import_media_missing") from error
    return url, match[1]


def _omit_unavailable_history(canvas: dict, media: dict) -> int:
    # The Setu publisher may upload only a thumbnail for historical videos.
    nodes_without_history = [
        {**node, "data": {key: value for key, value in node.get("data", {}).items() if key != "image_history"}}
        for node in canvas["nodes"]
    ]
    required = _canvas_version_ids({"nodes": nodes_without_history})
    omitted = set()
    for node in canvas["nodes"]:
        data = node.get("data", {})
        if "image_history" not in data:
            continue
        history = []
        for row in data["image_history"]:
            identifier = row["version_id"]
            item = media.get(identifier)
            urls = item.get("urls") or {} if isinstance(item, dict) else {}
            if identifier in required or urls.get("view") or (
                isinstance(item, dict) and item.get("kind") == "image" and urls.get("thumb")
            ):
                history.append(row)
            else:
                omitted.add(identifier)
        data["image_history"] = history
    return len(omitted)


def _download(client: httpx.Client, url: str, digest: str, path: Path, remaining: int) -> dict:
    checksum = hashlib.sha256()
    size = 0
    try:
        with client.stream("GET", url, timeout=httpx.Timeout(45, connect=12)) as response:
            if response.status_code != 200:
                raise DomainError(502, f"亦可素材下载失败（HTTP {response.status_code}），请重试。", "share_import_media_failed")
            with path.open("wb") as output:
                for chunk in response.iter_bytes(1024 * 1024):
                    size += len(chunk)
                    if size > min(MAX_MEDIA_BYTES, remaining):
                        raise DomainError(413, "亦可素材超过画布导入大小限制。", "share_import_too_large")
                    checksum.update(chunk)
                    output.write(chunk)
    except httpx.HTTPError as error:
        raise DomainError(502, "下载亦可画布素材时连接中断，请重试。", "share_import_media_failed") from error
    if not size or checksum.hexdigest() != digest:
        raise DomainError(400, "亦可画布素材校验失败，请重试。", "share_import_hash_mismatch")
    return probe_media(path, "media")


def export_public_canvas(service, link: str) -> tuple[Path, str, int]:
    """Fetch only the canonical public API and its verified content-addressed objects."""
    store = service.store
    slug = _slug(link, service.config.web_base())
    client = ShareClient(service.config.api_base(), transport=service._transport)
    try:
        snapshot = _snapshot(client, slug)
        try:
            shared = snapshot["canvas"]
            canvas = _portable_canvas({
                "nodes": shared["nodes"],
                "edges": shared["edges"],
                "viewport": _valid_viewport(shared.get("viewport")) or {"x": 0, "y": 0, "zoom": 1},
            })
            store.validate_canvas(canvas)
            identifiers = _canvas_version_ids(canvas)
            project = snapshot["project"]
            name = store.validate_name(project["name"])
            aspect = project.get("aspectRatio")
            media = snapshot["media"]
            if len(identifiers) > 2000 or not isinstance(media, dict):
                raise ValueError("invalid media")
            omitted = _omit_unavailable_history(canvas, media)
            identifiers = _canvas_version_ids(canvas)
            sources = {}
            for identifier in sorted(identifiers):
                item = media.get(identifier)
                if not isinstance(item, dict) or item.get("kind") not in {"image", "video", "audio"}:
                    raise DomainError(422, "公开快照缺少画布引用的素材，无法还原完整画布。", "share_import_media_missing")
                sources[identifier] = (_media_source(item), item["kind"])
        except (KeyError, TypeError, ValueError, AttributeError) as error:
            raise DomainError(422, "这张亦可画布的格式无法导入。", "invalid_share_canvas") from error

        manifest = {
            "format": ARCHIVE_FORMAT, "exported_at": now(), "canvas": canvas,
            "project": {"name": name, "aspect_ratio": aspect if aspect in ("16:9", "9:16") else "free"},
            "assets": [], "versions": [], "project_assets": [],
        }
        temp = store.root / "temp"
        temp.mkdir(parents=True, exist_ok=True)
        package = temp / f"export-{new_id()}.manju"
        try:
            with tempfile.TemporaryDirectory(dir=temp, prefix="share-") as staging, zipfile.ZipFile(
                package, "w", compression=zipfile.ZIP_STORED,
            ) as archive:
                file = Path(staging) / "media"
                verified = {}
                total = 0
                for index, (identifier, ((url, digest), kind)) in enumerate(sources.items(), start=1):
                    if digest not in verified:
                        metadata = _download(client.client, url, digest, file, MAX_TOTAL_BYTES - total)
                        verified[digest] = metadata
                        total += metadata["size"]
                        archive.write(file, f"blobs/{digest}")
                    metadata = verified[digest]
                    if metadata["type"] != kind:
                        raise DomainError(422, "亦可素材内容与画布标注的类型不一致。", "share_import_media_mismatch")
                    asset_id = new_id()
                    filename = f"亦可素材 {index}" + (mimetypes.guess_extension(metadata["mime"]) or "")
                    manifest["assets"].append({"id": asset_id, "name": filename, "type": kind,
                                               "current_version_id": identifier})
                    manifest["project_assets"].append(asset_id)
                    manifest["versions"].append({
                        **metadata, "id": identifier, "asset_id": asset_id, "blob_hash": digest, "filename": filename,
                    })
                encoded = json.dumps(manifest, ensure_ascii=False).encode("utf-8")
                if len(encoded) > MAX_MANIFEST_BYTES:
                    raise DomainError(413, "画布项目包清单超过大小限制。", "share_import_too_large")
                archive.writestr("manifest.json", encoded)
        except BaseException:
            package.unlink(missing_ok=True)
            raise
        return package, name, omitted
    finally:
        client.close()
