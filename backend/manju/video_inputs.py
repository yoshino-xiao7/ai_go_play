"""Validated, reproducible H3 inputs. Originals always remain untouched."""
import json
import math
import re
from pathlib import Path
from PIL import Image, ImageOps
from .media import find_binary, run_process
from .store import DomainError

VIDEO_OPTIONS = {"engine": "native", "sampler": "res_multistep", "scheduler": "simple", "ref_image_size": "1024"}
OPTION_VALUES = {"engine": ("native", "director"), "sampler": ("res_multistep", "euler"),
                 "scheduler": ("simple", "beta", "normal"), "ref_image_size": ("match", "1024", "1280", "1536", "max")}


def normalize_options(value):
    if not isinstance(value, dict) or set(value) - VIDEO_OPTIONS.keys() or any(v not in OPTION_VALUES[k] for k, v in value.items()):
        raise DomainError(422, "视频流程选项无效。", "video_options_invalid")
    return {**VIDEO_OPTIONS, **value}


def normalize_inputs(request, raw_references):
    canonical, aliases, original = {}, {}, request["references"]
    for ref, raw in zip(original, raw_references):
        ref["fit"] = raw.get("fit", "contain")
        ref["purpose"] = raw.get("purpose", "general")
        ref["use_audio"] = raw.get("use_audio", False)
        if ref["fit"] not in ("contain", "cover") or ref["purpose"] not in ("general", "identity", "composition", "motion", "voice") or type(ref["use_audio"]) is not bool:
            raise DomainError(422, "参考素材处理方式无效。", "video_reference_options")
        crop = raw.get("crop", {"x": 0, "y": 0, "width": 1, "height": 1})
        if (not isinstance(crop, dict) or set(crop) != {"x", "y", "width", "height"}
            or any(type(v) not in (int, float) or not math.isfinite(v) for v in crop.values())
            or min(crop["x"], crop["y"]) < 0 or min(crop["width"], crop["height"]) <= 0
            or crop["x"] + crop["width"] > 1.000001 or crop["y"] + crop["height"] > 1.000001):
            raise DomainError(422, "裁切区域须在图片范围内。", "video_reference_crop")
        ref["crop"] = crop
        for key in ("clip_start", "clip_end"):
            value = raw.get(key, 0 if key == "clip_start" else None)
            if value is not None and (type(value) not in (int, float) or not math.isfinite(value) or value < 0):
                raise DomainError(422, "参考片段时间无效。", "video_reference_clip")
            ref[key] = value
        key = (ref["version_id"], ref["role"], ref["fit"], ref["purpose"], ref["use_audio"],
               tuple(crop[k] for k in ("x", "y", "width", "height")), ref["clip_start"], ref["clip_end"])
        kept = canonical.setdefault(key, ref)
        aliases[ref["id"]] = kept["id"]
    # Convert legacy plain-text aliases before removing duplicates (longest match first).
    if request.get("prompt_parts") is None:
        names = sorted((r for r in original if r.get("title")), key=lambda r: len(r["title"]), reverse=True)
        if names:
            pattern = re.compile("|".join(re.escape("@" + r["title"]) for r in names))
            lookup = {"@" + r["title"]: r["id"] for r in reversed(names)}
            parts, end = [], 0
            for match in pattern.finditer(request["prompt"]):
                parts.extend([{"type": "text", "text": request["prompt"][end:match.start()]}, {"type": "reference", "reference_id": lookup[match[0]]}])
                end = match.end()
            parts.append({"type": "text", "text": request["prompt"][end:]})
            request["prompt_parts"] = parts
    for part in request.get("prompt_parts", []):
        if part["type"] == "reference": part["reference_id"] = aliases[part["reference_id"]]
    request["references"] = list(canonical.values())


def has_audio(path):
    probe = find_binary("ffprobe")
    if not probe: raise DomainError(503, "检查参考声音需要 FFprobe。", "ffprobe_missing")
    result = run_process([probe, "-v", "error", "-select_streams", "a", "-show_entries", "stream=index", "-of", "json", str(path)])
    return bool(json.loads(result.stdout).get("streams"))


def prepare_reference(path, destination, ref, parameters):
    """Return a normalized copy, with selected crop / interval frozen in the job."""
    kind = ref["media_type"]
    if kind == "image":
        destination = destination.with_suffix(".png")
        with Image.open(path) as source:
            image = ImageOps.exif_transpose(source).convert("RGB")
            crop = ref.get("crop", {"x": 0, "y": 0, "width": 1, "height": 1})
            w, h = image.size
            left, top = min(w-1, round(crop["x"]*w)), min(h-1, round(crop["y"]*h))
            right, bottom = min(w, max(left+1, round((crop["x"]+crop["width"])*w))), min(h, max(top+1, round((crop["y"]+crop["height"])*h)))
            image = image.crop((left, top, right, bottom))
            if ref["role"] in ("first_frame", "last_frame"):
                size = (parameters["width"], parameters["height"])
                image = (ImageOps.fit(image, size, Image.Resampling.LANCZOS) if ref.get("fit") == "cover"
                         else ImageOps.pad(image, size, Image.Resampling.LANCZOS, color=(24, 24, 24)))
            image.save(destination)
    else:
        ffmpeg = find_binary("ffmpeg")
        if not ffmpeg: raise DomainError(503, "参考片段处理需要 FFmpeg。", "ffmpeg_missing")
        destination = destination.with_suffix(".mp4" if kind == "video" else ".wav")
        args = [ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-y", "-i", str(path), "-ss", str(ref.get("clip_start", 0))]
        if ref.get("clip_end") is not None: args += ["-t", str(ref["clip_end"]-ref.get("clip_start", 0))]
        if kind == "video":
            args += ["-map", "0:v:0", "-vf", "fps=24", "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p"]
            args += ["-map", "0:a:0", "-c:a", "aac"] if ref.get("use_audio") else ["-an"]
            args += ["-movflags", "+faststart"]
        else: args += ["-vn", "-c:a", "pcm_s16le"]
        run_process([*args, str(destination)], timeout=180)
    return destination
