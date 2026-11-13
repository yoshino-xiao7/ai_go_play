"""Render a canvas watermark onto a fixed video version with local FFmpeg."""
from __future__ import annotations

from fractions import Fraction
from io import BytesIO
import json
import os
from pathlib import Path
import re
import subprocess

from PIL import Image, ImageDraw, ImageFont, ImageOps

from .media import find_binary, run_process
from .store import DomainError

PROFILE_ID = "builtin-video-watermark-local"
TITLE = "视频水印"
DEFAULTS = {"mode": "text", "text": "", "position": "bottom-right", "size": 4, "opacity": 65, "color": "#ffffff"}
POSITIONS = ("top-left", "top-right", "bottom-left", "bottom-right", "center")
COPY_AUDIO = {"aac", "mp3", "alac", "ac3", "eac3", "opus", "flac"}


def watermark_options(value):
    if not isinstance(value, dict) or value.keys() - DEFAULTS.keys():
        raise DomainError(422, "水印参数格式无效。", "watermark_options")
    options = {**DEFAULTS, **value}
    if options["mode"] not in ("text", "image") or options["position"] not in POSITIONS:
        raise DomainError(422, "请选择有效的水印类型和位置。", "watermark_options")
    text = options["text"]
    if not isinstance(text, str) or len(text) > 100 or any(ord(char) < 32 or 0xD800 <= ord(char) <= 0xDFFF for char in text):
        raise DomainError(422, "水印文字最多 100 个字符，须为单行。", "watermark_options")
    options["text"] = text.strip()
    if options["mode"] == "text" and not options["text"]:
        raise DomainError(422, "请输入水印文字。", "watermark_options")
    for key, minimum, maximum in (("size", 1, 40), ("opacity", 1, 100)):
        if type(options[key]) is not int or not minimum <= options[key] <= maximum:
            raise DomainError(422, "水印大小或不透明度超出范围。", "watermark_options")
    if not isinstance(options["color"], str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", options["color"]):
        raise DomainError(422, "水印颜色格式无效。", "watermark_options")
    return options


def normalize_watermark(payload, base):
    clean = {**payload, "prompt": TITLE}
    clean.pop("kind", None)
    request = base(clean)
    if request["mask_version_id"] or request["parameters"] or payload.get("provider") is not None:
        raise DomainError(422, "水印只接受视频素材和水印参数。", "watermark_options")
    options = watermark_options(payload.get("watermark_options", {}))
    types = [ref.get("media_type") for ref in payload.get("references", [])]
    if types.count("video") != 1 or types.count("image") != (options["mode"] == "image") or len(types) != (2 if options["mode"] == "image" else 1):
        raise DomainError(422, "请连接一段视频。图片水印还需要连接一张 Logo 图片。", "watermark_input")
    for ref, kind in zip(request["references"], types):
        ref.update(media_type=kind, role="reference")
    request.update(kind="video", watermark_options=options, result_policy=payload.get("result_policy", "replace"))
    return request


def watermark_font(size):
    windows = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
    candidates = (
        windows / "msyh.ttc", windows / "simhei.ttf",
        Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
        Path("/System/Library/Fonts/PingFang.ttc"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    )
    return next((ImageFont.truetype(str(path), size) for path in candidates if path.is_file()), None) or ImageFont.load_default(size=size)


def render_layer(width, height, options, logo=None):
    short = min(width, height)
    margin = min(max(1, round(short * 0.03)), (short - 1) // 2)
    bounds = (width - 2 * margin, height - 2 * margin)
    size = max(1, round(short * options["size"] / 100))
    if logo is not None:
        with Image.open(logo) as source:
            mark = ImageOps.exif_transpose(source).convert("RGBA")
        scale = min(size / max(mark.size), *(limit / dim for limit, dim in zip(bounds, mark.size)))
        mark = mark.resize(tuple(max(1, round(dim * scale)) for dim in mark.size), Image.Resampling.LANCZOS)
    else:
        text = options["text"]
        font = watermark_font(size)
        stroke = max(1, round(size * 0.045))
        left, top, right, bottom = font.getbbox(text, stroke_width=stroke)
        mark = Image.new("RGBA", (max(1, right - left), max(1, bottom - top)))
        ImageDraw.Draw(mark).text((-left, -top), text, font=font, fill=options["color"], stroke_width=stroke, stroke_fill="#101010")
        mark.thumbnail(bounds, Image.Resampling.LANCZOS)
    opacity = options["opacity"]
    if opacity < 100:
        mark.putalpha(mark.getchannel("A").point([round(level * opacity / 100) for level in range(256)]))
    position = options["position"]
    x = (width - mark.width) // 2 if position == "center" else width - mark.width - margin if position.endswith("right") else margin
    y = (height - mark.height) // 2 if position == "center" else height - mark.height - margin if position.startswith("bottom") else margin
    # The video overlay uses 4:2:0 chroma, which aligns coordinates to even pixels.
    return mark, x - x % 2, y - y % 2


class WatermarkAdapter:
    def __init__(self, store):
        self.store = store

    def status(self):
        ready = bool(find_binary("ffmpeg") and find_binary("ffprobe"))
        return {"id": PROFILE_ID, "name": TITLE, "kind": "video", "mode": "video", "builtin": True,
                "read_only": True, "ready": ready, "errors": [] if ready else ["本机缺少 FFmpeg 或 FFprobe。"],
                "defaults": DEFAULTS, "output_nodes": ["watermark"]}

    def snapshot(self, _options=None):
        status = self.status()
        if not status["ready"]:
            raise DomainError(503, status["errors"][0], "ffmpeg_missing")
        return {**status, "revision": 1, "bindings": {}, "capabilities": {"min_images": 1, "max_images": 2}}

    def input_version(self, version_id, kind=None):
        version = self.store.version(version_id)
        actual = version["mime"].split("/", 1)[0]
        if version["missing"] or actual not in ("video", "image") or kind and actual != kind:
            raise DomainError(422, "水印素材缺失或类型不符。", "watermark_input", version_id=version_id)
        if self.store.asset(version["asset_id"], details=False)["deleted_at"]:
            raise DomainError(409, "请先恢复回收站中的水印素材。", "asset_trashed")
        return version

    def compile_prompt(self, request):
        for ref in request["references"]:
            self.input_version(ref["version_id"], ref["media_type"])
        return TITLE

    def source_info(self, source):
        ffprobe = find_binary("ffprobe")
        if not ffprobe:
            raise DomainError(503, "本机缺少 FFprobe。", "ffmpeg_missing")
        result = run_process([ffprobe, "-v", "error", "-protocol_whitelist", "file,pipe", "-show_streams", "-of", "json", source["path"]])
        streams = json.loads(result.stdout)["streams"]
        stream = next((s for s in streams if s["codec_type"] == "video" and not s.get("disposition", {}).get("attached_pic")), None)
        if not stream or not stream.get("width") or not stream.get("height"):
            raise DomainError(422, "水印需要可读取的视频画面。", "watermark_input")
        width, height = stream["width"], stream["height"]
        rotation = next((item["rotation"] for item in stream.get("side_data_list", []) if "rotation" in item), 0)
        if abs(rotation) % 180 == 90:
            width, height = height, width
        return stream, width, height, [s.get("codec_name") for s in streams if s["codec_type"] == "audio"]

    def preview(self, video_id, options, logo_id=None):
        options = watermark_options(options)
        source = self.input_version(video_id, "video")
        logo = self.input_version(logo_id, "image")["path"] if options["mode"] == "image" and logo_id else None
        if options["mode"] == "image" and not logo:
            raise DomainError(422, "请连接 Logo 图片。", "watermark_input")
        _, width, height, _ = self.source_info(source)
        mark, x, y = render_layer(width, height, options, logo)
        scale = min(1, 640 / max(width, height))
        layer = Image.new("RGBA", (max(1, round(width * scale)), max(1, round(height * scale))))
        layer.paste(mark.resize((max(1, round(mark.width * scale)), max(1, round(mark.height * scale))), Image.Resampling.LANCZOS),
                    (round(x * scale), round(y * scale)))
        data = BytesIO()
        layer.save(data, format="PNG")
        return data.getvalue()

    def burn(self, request, output, report):
        ffmpeg = find_binary("ffmpeg")
        if not ffmpeg:
            raise DomainError(503, "本机缺少 FFmpeg。", "ffmpeg_missing")
        refs = {ref["media_type"]: self.input_version(ref["version_id"], ref["media_type"]) for ref in request["references"]}
        source = refs["video"]
        stream, width, height, audio = self.source_info(source)
        mark, x, y = render_layer(width, height, request["watermark_options"], refs.get("image", {}).get("path"))
        overlay = output.with_suffix(".png")
        log = output.with_suffix(".log")
        mark.save(overlay)
        pix_fmt = "yuv444p" if width % 2 or height % 2 else "yuv420p"
        video_filter = f"[0:{stream['index']}][1:v]overlay=x={x}:y={y}:format={'yuv444' if pix_fmt == 'yuv444p' else 'yuv420'}[marked]"
        time_base = Fraction(stream["time_base"])
        args = [ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-y", "-copyts", "-start_at_zero",
                "-protocol_whitelist", "file,pipe", "-i", source["path"], "-i", str(overlay),
                "-filter_complex_threads", "2", "-filter_complex", video_filter, "-map", "[marked]", "-map", "0:a?",
                "-fps_mode", "passthrough", "-enc_time_base", str(time_base), "-c:v", "libx264",
                "-preset", "fast", "-crf", "16", "-threads:v", "4", "-pix_fmt", pix_fmt, "-c:a", "copy"]
        for index, codec in enumerate(audio):
            if codec not in COPY_AUDIO:
                args.extend([f"-c:a:{index}", "aac"])
        args.extend(["-movflags", "+faststart", "-progress", "pipe:1", str(output)])
        try:
            with log.open("wb") as errors, subprocess.Popen(
                args, stdout=subprocess.PIPE, stderr=errors, text=True, encoding="utf-8",
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            ) as process:
                try:
                    for line in process.stdout:
                        key, _, value = line.strip().partition("=")
                        if key == "out_time_us" and value not in ("N/A", ""):
                            report(max(0, int(value)) / 1_000_000, source.get("duration"))
                except BaseException:
                    process.kill()
                    raise
                if process.wait():
                    raise RuntimeError("FFmpeg 水印编码失败。" + log.read_text(encoding="utf-8", errors="replace")[-1200:])
        finally:
            overlay.unlink(missing_ok=True)
            log.unlink(missing_ok=True)
