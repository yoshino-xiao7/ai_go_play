"""Media inspection and durable preview worker using local executables."""
from __future__ import annotations

import array
from functools import lru_cache
import json
import mimetypes
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading

from PIL import Image, ImageOps, UnidentifiedImageError

from .store import DomainError, Store, now


def run_process(arguments: list[str], timeout: int = 60) -> subprocess.CompletedProcess:
    result = subprocess.run(arguments, capture_output=True, timeout=timeout, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    if result.returncode:
        message = result.stderr.decode("utf-8", errors="replace")[-1800:]
        raise RuntimeError(message or f"媒体处理进程退出，代码 {result.returncode}")
    return result


@lru_cache(maxsize=2)
def find_binary(name: str) -> str | None:
    candidates = []
    configured = os.environ.get(f"MANJU_{name.upper()}")
    if configured:
        candidates.append(configured)
    sibling_config = os.environ.get("MANJU_FFMPEG" if name == "ffprobe" else "MANJU_FFPROBE")
    if sibling_config:
        candidates.append(str(Path(sibling_config).with_name(name + (".exe" if os.name == "nt" else ""))))
    located = shutil.which(name)
    if located:
        candidates.append(located)
    if os.name == "nt":
        package_root = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Packages"
        if package_root.is_dir():
            for package in package_root.glob("*FFmpeg*"):
                candidates.extend(str(path) for path in package.rglob(f"{name}.exe"))
        candidates.extend([f"C:/ffmpeg/bin/{name}.exe", f"D:/ffmpeg/bin/{name}.exe"])
    for candidate in dict.fromkeys(candidates):
        try:
            run_process([candidate, "-version"], timeout=8)
            return str(Path(candidate).resolve())
        except (OSError, RuntimeError, subprocess.TimeoutExpired):
            continue
    return None


def probe_media(path: Path, filename: str) -> dict:
    size = path.stat().st_size
    if size == 0:
        raise DomainError(422, "文件为空。", "empty_upload")
    try:
        with Image.open(path) as image:
            image.verify()
        with Image.open(path) as image:
            width, height = ImageOps.exif_transpose(image).size
            mime = Image.MIME.get(image.format, mimetypes.guess_type(filename)[0] or "image/png")
            duration = None
            if getattr(image, "is_animated", False):
                duration = sum(image.seek(index) or image.info.get("duration", 0) for index in range(min(image.n_frames, 10000))) / 1000
            return {"type": "image", "mime": mime, "size": size, "width": width, "height": height, "duration": duration}
    except Image.DecompressionBombError as error:
        raise DomainError(413, "图片像素数量超出可安全处理的范围。", "image_too_large") from error
    except (UnidentifiedImageError, OSError, ValueError):
        pass
    probe = find_binary("ffprobe")
    if not probe:
        raise DomainError(503, "视频和音频导入需要 FFprobe。请在存储设置检查本机 FFmpeg，或设置 MANJU_FFPROBE。", "ffprobe_missing")
    try:
        result = run_process([probe, "-v", "error", "-protocol_whitelist", "file,pipe", "-show_streams", "-show_format", "-of", "json", str(path)], timeout=60)
        data = json.loads(result.stdout)
    except (RuntimeError, subprocess.TimeoutExpired, json.JSONDecodeError) as error:
        raise DomainError(415, "文件无法识别为可读取的图片、视频或音频。", "unsupported_media") from error
    streams = data.get("streams", [])
    video = next((stream for stream in streams if stream.get("codec_type") == "video" and not stream.get("disposition", {}).get("attached_pic")), None)
    audio = next((stream for stream in streams if stream.get("codec_type") == "audio"), None)
    if not video and not audio:
        raise DomainError(415, "文件没有有效的音视频流。", "unsupported_media")
    media_type = "video" if video else "audio"
    formats = set(data.get("format", {}).get("format_name", "").split(","))
    if "mov" in formats or "mp4" in formats:
        brand = data.get("format", {}).get("tags", {}).get("major_brand", "").strip()
        mime = "video/quicktime" if video and brand == "qt" else f"{media_type}/mp4"
    elif "matroska" in formats or "webm" in formats:
        with path.open("rb") as source:
            header = source.read(4096)
        mime = f"{media_type}/webm" if b"webm" in header else f"{media_type}/x-matroska"
    else:
        container_mimes = {"wav": "audio/wav", "mp3": "audio/mpeg", "flac": "audio/flac", "aac": "audio/aac", "aiff": "audio/aiff", "ogg": f"{media_type}/ogg", "avi": "video/x-msvideo", "mpegts": "video/mp2t", "mpeg": "video/mpeg"}
        mime = next((value for container, value in container_mimes.items() if container in formats), f"{media_type}/octet-stream")
    duration_value = data.get("format", {}).get("duration") or (video or audio).get("duration")
    duration = float(duration_value) if duration_value not in (None, "N/A") else None
    return {"type": media_type, "mime": mime, "size": size, "width": video.get("width") if video else None, "height": video.get("height") if video else None, "duration": duration}


def _save_image(image: Image.Image, output: Path, size: tuple[int, int]) -> None:
    image = ImageOps.exif_transpose(image)
    image.thumbnail(size, Image.Resampling.LANCZOS)
    temporary = output.with_name(output.stem + ".pending.webp")
    has_alpha = "A" in image.getbands() or "transparency" in image.info
    image.convert("RGBA" if has_alpha else "RGB").save(temporary, "WEBP", quality=88)
    os.replace(temporary, output)


def build_preview(store: Store, version: dict) -> None:
    source = Path(version["path"])
    if not source.is_file():
        raise RuntimeError("原文件缺失，请从资产详情修复后重试。")
    target = store.root / "cache" / version["id"]
    target.mkdir(parents=True, exist_ok=True)
    if version["mime"].startswith("image/"):
        with Image.open(source) as image:
            _save_image(image.copy(), target / "thumbnail.webp", (480, 480))
            _save_image(image.copy(), target / "preview.webp", (1920, 1920))
        return
    ffmpeg = find_binary("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("未找到可执行的 FFmpeg。安装后重试，或设置 MANJU_FFMPEG。")
    if version["mime"].startswith("video/"):
        run_process([ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-y", "-protocol_whitelist", "file,pipe", "-i", str(source), "-frames:v", "1", "-vf", "scale=480:480:force_original_aspect_ratio=decrease", str(target / "thumbnail.pending.webp")], timeout=120)
        os.replace(target / "thumbnail.pending.webp", target / "thumbnail.webp")
        run_process([ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-y", "-protocol_whitelist", "file,pipe", "-i", str(source), "-map", "0:v:0", "-map", "0:a?", "-vf", "scale=1280:1280:force_original_aspect_ratio=decrease:force_divisible_by=2", "-c:v", "libx264", "-preset", "veryfast", "-crf", "24", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", str(target / "preview.pending.mp4")], timeout=1800)
        os.replace(target / "preview.pending.mp4", target / "preview.mp4")
        return
    run_process([ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-y", "-protocol_whitelist", "file,pipe", "-i", str(source), "-vn", "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", str(target / "preview.pending.m4a")], timeout=1800)
    os.replace(target / "preview.pending.m4a", target / "preview.m4a")
    result = run_process([ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-protocol_whitelist", "file,pipe", "-i", str(source), "-vn", "-ac", "1", "-ar", "2000", "-f", "s16le", "-t", "7200", "pipe:1"], timeout=1800)
    samples = array.array("h", result.stdout)
    if sys.byteorder != "little":
        samples.byteswap()
    step = max(1, len(samples) // 360)
    levels = [max((abs(value) for value in samples[index:index + step]), default=0) / 32768 for index in range(0, len(samples), step)][:360]
    (target / "waveform.json").write_text(json.dumps({"duration": version["duration"], "peaks": levels}), encoding="utf-8")
    bars = []
    for index, level in enumerate(levels):
        height = max(2, level * 94)
        bars.append(f'<rect x="{index * 2}" y="{(100 - height) / 2:.2f}" width="1.4" height="{height:.2f}" rx="0.7"/>')
    waveform = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 720 100"><g fill="#7dd3fc">' + "".join(bars) + "</g></svg>"
    (target / "waveform.svg").write_text(waveform, encoding="utf-8")


class PreviewWorker:
    def __init__(self, store: Store):
        self.store = store
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self.run, name="manju-previews", daemon=True)

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        self.thread.join(timeout=5)

    def run(self) -> None:
        while not self.stop_event.is_set():
            task = None
            try:
                with self.store.media_lock:
                    with self.store.tx():
                        row = self.store.conn.execute("SELECT * FROM tasks WHERE status='pending' AND kind='preview' ORDER BY created_at LIMIT 1").fetchone()
                        if row:
                            task = dict(row)
                            self.store.conn.execute("UPDATE tasks SET status='running',attempts=attempts+1,updated_at=? WHERE id=?", (now(), task["id"]))
                            self.store.emit("task.updated", {"task_id": task["id"], "status": "running"})
                    if task:
                        self.execute(task)
            except DomainError:
                pass
            except (OSError, RuntimeError):
                pass
            if task is None:
                self.stop_event.wait(0.4)

    def execute(self, task: dict) -> None:
        try:
            version = self.store.version(task["version_id"])
            build_preview(self.store, version)
            status, error = "ready", None
        except Exception as failure:
            status, error = "failed", str(failure)[-2000:]
        with self.store.tx():
            self.store.conn.execute("UPDATE tasks SET status=?,error=?,updated_at=? WHERE id=?", (status, error, now(), task["id"]))
            self.store.conn.execute("UPDATE versions SET preview_status=?,preview_error=? WHERE id=?", (status, error, task["version_id"]))
            self.store.emit("task.updated", {"task_id": task["id"], "version_id": task["version_id"], "status": status, "error": error})
            self.store.emit("asset.updated", {"version_id": task["version_id"]})
