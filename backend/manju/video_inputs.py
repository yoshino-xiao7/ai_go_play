"""Validated, reproducible H3 inputs. Originals always remain untouched."""
import json
import math
import re
from pathlib import Path
from PIL import Image, ImageOps
from .media import find_binary, run_process
from .store import DomainError

VIDEO_OPTIONS = {"engine": "native", "sampler": "res_multistep", "scheduler": "simple", "ref_image_size": "1024"}
TURBO_OPTIONS = {"engine": "turbo", "sampler": "euler", "scheduler": "beta", "ref_image_size": "match"}
OPTION_VALUES = {"engine": ("native", "director", "turbo"), "sampler": ("res_multistep", "euler"),
                 "scheduler": ("simple", "beta", "normal"), "ref_image_size": ("match", "1024", "1280", "1536", "max")}
FPS = 24
FIRST_FRAME_COUNT = 5
FRAME_COUNT_STEP = 17
MAX_FRAME_COUNT = 362
MAX_GUIDES = 12


def frame_count(request):
    explicit = request.get("frame_count")
    return explicit if explicit is not None else FIRST_FRAME_COUNT + FRAME_COUNT_STEP * math.ceil(
        (request["duration"] * FPS - FIRST_FRAME_COUNT) / FRAME_COUNT_STEP
    )


def guide_file_key(index):
    # Keep timed guides in a separate namespace from editable reference IDs.
    return ("h3_guide", index)


def normalize_guides(payload, request):
    count = payload.get("frame_count")
    if count is not None:
        if (type(count) is not int or not FIRST_FRAME_COUNT <= count <= MAX_FRAME_COUNT
                or (count - FIRST_FRAME_COUNT) % FRAME_COUNT_STEP):
            raise DomainError(422, "H3 精确帧数须为 5 + 17n，范围为 5–362 帧。", "video_frame_count_invalid")
        request["frame_count"] = count

    guides = payload.get("h3_guides", [])
    if not isinstance(guides, list) or len(guides) > MAX_GUIDES:
        raise DomainError(422, f"H3 定帧引导最多 {MAX_GUIDES} 项。", "video_guide_count")
    if request["video_options"]["engine"] == "director" and (guides or count is not None):
        raise DomainError(422, "精确帧数和定帧引导支持原生及 Turbo 流程。", "video_guide_engine")
    if not guides:
        return

    result = []
    for guide in guides:
        if not isinstance(guide, dict):
            raise DomainError(422, "定帧引导格式无效。", "video_guide_invalid")
        version_id = guide.get("version_id")
        kind = guide.get("media_type")
        index = guide.get("frame_idx")
        use_audio = guide.get("use_audio", False)
        start, end = guide.get("clip_start", 0), guide.get("clip_end")
        if (not isinstance(version_id, str) or not version_id
                or kind not in ("image", "video", "audio")
                or type(use_audio) is not bool or (use_audio and kind != "video")):
            raise DomainError(422, "请选择固定版本的图片、视频或音频作为定帧引导。", "video_guide_invalid")
        if type(index) is not int or not 0 <= index < frame_count(request):
            raise DomainError(422, "引导起始帧超出生成范围。", "video_guide_out_of_range")
        if (type(start) not in (int, float) or not math.isfinite(start) or start < 0
                or (end is not None and (type(end) not in (int, float) or not math.isfinite(end) or end <= start))
                or (kind == "image" and (start != 0 or end is not None))):
            raise DomainError(422, "定帧引导的片段范围无效。", "video_guide_clip")
        item = {"version_id": version_id, "media_type": kind, "frame_idx": index,
                "role": "guide", "use_audio": use_audio, "clip_start": start, "clip_end": end}
        for key in ("id", "title", "node_id"):
            value = guide.get(key)
            if value is not None:
                if not isinstance(value, str):
                    raise DomainError(422, "定帧引导标识或标题无效。", "video_guide_invalid")
                item[key] = value
        result.append(item)
    request["h3_guides"] = result


def validate_guide(guide, version, length):
    kind = guide["media_type"]
    if version["mime"].split("/", 1)[0] != kind:
        raise DomainError(422, "定帧引导类型与固定素材版本不符。", "video_guide_type")
    if kind == "image":
        return
    duration = version.get("duration")
    start, end = guide["clip_start"], guide["clip_end"]
    if duration is None or (end is not None and end > duration + .05):
        raise DomainError(422, "请选择原素材范围内的引导片段。", "video_guide_clip")
    end = duration if end is None else min(end, duration)
    if end <= start:
        raise DomainError(422, "请选择原素材范围内的引导片段。", "video_guide_clip")
    guide["clip_end"] = end
    if kind == "video":
        selected_frames = math.floor((end - start) * FPS + .5)
        if selected_frames < FIRST_FRAME_COUNT:
            raise DomainError(422, "视频引导至少需要 5 帧。", "video_guide_clip")
        clip_frames = selected_frames - (selected_frames - FIRST_FRAME_COUNT) % FRAME_COUNT_STEP
        if guide["frame_idx"] + clip_frames > length:
            raise DomainError(422, "视频引导超出生成范围，请缩短引导片段或提前起始帧。", "video_guide_out_of_range")
        guide["clip_frames"] = clip_frames
        if guide["use_audio"] and not has_audio(Path(version["path"])):
            raise DomainError(422, "该视频引导没有声音轨道，请关闭参考原声。", "video_guide_audio_missing")


def normalize_options(value):
    if not isinstance(value, dict) or set(value) - VIDEO_OPTIONS.keys() or any(v not in OPTION_VALUES[k] for k, v in value.items()):
        raise DomainError(422, "视频流程选项无效。", "video_options_invalid")
    return dict(TURBO_OPTIONS) if value.get("engine") == "turbo" else {**VIDEO_OPTIONS, **value}


def normalize_inputs(request, raw_references):
    canonical, aliases, original = {}, {}, request["references"]
    for ref, raw in zip(original, raw_references):
        ref["fit"] = raw.get("fit", "contain")
        ref["purpose"] = raw.get("purpose", "general")
        ref["use_audio"] = raw.get("use_audio", False)
        if ref["fit"] not in ("contain", "cover") or ref["purpose"] not in ("general", "identity", "composition", "motion", "camera", "voice") or type(ref["use_audio"]) is not bool:
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
        clip_frames = ref.get("clip_frames")
        if clip_frames is not None:
            args += ["-t", str(clip_frames / FPS)]
        elif ref.get("clip_end") is not None:
            args += ["-t", str(ref["clip_end"]-ref.get("clip_start", 0))]
        if kind == "video":
            args += ["-map", "0:v:0", "-vf", "fps=24", "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p"]
            args += ["-map", "0:a:0", "-c:a", "aac"] if ref.get("use_audio") else ["-an"]
            args += ["-movflags", "+faststart"]
        else: args += ["-vn", "-c:a", "pcm_s16le"]
        run_process([*args, str(destination)], timeout=180)
        if clip_frames is not None:
            probe = find_binary("ffprobe")
            if not probe:
                raise DomainError(503, "检查视频引导帧数需要 FFprobe。", "ffprobe_missing")
            result = run_process([probe, "-v", "error", "-select_streams", "v:0", "-show_entries",
                                  "stream=nb_frames", "-of", "json", str(destination)])
            streams = json.loads(result.stdout).get("streams", [])
            if not streams or streams[0].get("nb_frames") != str(clip_frames):
                raise DomainError(422, "引导视频转换后的帧数与选段不符，请调整选段。", "video_guide_clip")
    return destination
