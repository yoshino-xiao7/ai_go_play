"""Free multitrack editing with immutable media and durable FFmpeg composition."""
from __future__ import annotations

import json
from pathlib import Path
import re

from PIL import Image, ImageColor, ImageDraw, ImageFont

from .media import find_binary, probe_media, run_process
from .production import identifier, normalize_settings, number, text
from .store import DomainError, encode, fingerprint, new_id, now


def color(value, label, *, transparent=True):
    if value == "transparent" and transparent:
        return value
    if not isinstance(value, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}(?:[0-9a-fA-F]{2})?", value):
        raise DomainError(422, f"{label}须为十六进制颜色。", "invalid_timeline")
    return value.lower()


def flag(value, label):
    if not isinstance(value, bool):
        raise DomainError(422, f"{label}须为布尔值。", "invalid_timeline")
    return value


def normalize_timeline(payload, aspect="16:9"):
    raw_settings = payload.get("settings", {})
    base = normalize_settings(raw_settings, aspect)
    settings = {key: base[key] for key in ("width", "height", "fps")}
    settings["background_color"] = color(raw_settings.get("background_color", "#000000"), "画布背景", transparent=False)
    settings["duration"] = None if raw_settings.get("duration") is None else number(raw_settings["duration"], "总时长", 1/base["fps"]-1e-6, 3600)
    raw_tracks, raw_clips = payload.get("tracks", []), payload.get("clips", [])
    if not isinstance(raw_tracks, list) or len(raw_tracks) > 64 or not isinstance(raw_clips, list) or len(raw_clips) > 500:
        raise DomainError(422, "时间线最多支持 64 个轨道、500 个片段。", "invalid_timeline")
    tracks = []
    for i, raw in enumerate(raw_tracks):
        if not isinstance(raw, dict) or raw.get("type") not in ("video", "audio", "text"):
            raise DomainError(422, "轨道类型须为 video、audio 或 text。", "invalid_timeline")
        tracks.append({"id": identifier(raw.get("id"), "轨道 ID") or new_id(), "type": raw["type"],
                       "name": text(raw.get("name", f"轨道 {i+1}"), "轨道名称", 150),
                       "order": int(number(raw.get("order", i), "轨道顺序", 0, 10000)),
                       "muted": flag(raw.get("muted", False), "轨道静音/隐藏"), "locked": flag(raw.get("locked", False), "轨道锁定")})
    if len({t["id"] for t in tracks}) != len(tracks):
        raise DomainError(422, "轨道 ID 重复。", "invalid_timeline")
    by_id = {t["id"]: t for t in tracks}
    clips = []
    fps = settings["fps"]
    for raw in raw_clips:
        if not isinstance(raw, dict) or raw.get("track_id") not in by_id:
            raise DomainError(422, "片段引用了不存在的轨道。", "invalid_timeline")
        track = by_id[raw["track_id"]]
        transform = raw.get("transform") or {}
        style = raw.get("text_style") or {}
        if not isinstance(transform, dict) or not isinstance(style, dict):
            raise DomainError(422, "片段变换或文字样式格式无效。", "invalid_timeline")
        trim = number(raw.get("trim_start", raw.get("in", 0)), "素材入点", 0, 86400)
        raw_duration = raw.get("duration")
        if raw_duration is None:
            raw_duration = number(raw.get("out", raw.get("trim_end", trim+5)), "素材出点", 0, 90000) - trim
        requested_duration = number(raw_duration, "片段时长", 1/fps-1e-6, 3600)
        duration = max(1, round(requested_duration*fps))/fps
        start = round(number(raw.get("start", 0), "片段开始时间", 0, 3600)*fps)/fps
        # trim_end is a derived response field. An explicit `out` can also set
        # duration, while editing duration on a GET document must remain valid.
        trim_end = raw.get("out")
        if trim_end is not None and abs(number(trim_end, "素材出点", 0, 90000) - (trim + duration)) > 1/fps + 1e-5:
            raise DomainError(422, "素材出点须等于入点加片段时长；调整片段时长即可裁剪出点。", "timeline_trim_mismatch")
        align = style.get("align", "center")
        if align not in ("left", "center", "right"):
            raise DomainError(422, "文字对齐方式无效。", "invalid_timeline")
        audio_preset = raw.get("audio_preset", "none")
        if audio_preset not in ("none", "dialogue", "phone", "narration"):
            raise DomainError(422, "声音处理预设无效。", "invalid_timeline")
        clip = {"id": identifier(raw.get("id"), "片段 ID") or new_id(), "track_id": raw["track_id"],
                "name": text(raw.get("name", ""), "片段名称", 250), "start": start, "duration": duration,
                "trim_start": trim, "trim_end": trim + duration,
                "asset_version_id": identifier(raw.get("asset_version_id"), "素材版本"),
                "source_node_id": identifier(raw.get("source_node_id"), "来源卡片"),
                "text": text(raw.get("text", ""), "文字内容", 5000),
                "transform": {"x": number(transform.get("x", 40 if track["type"] == "text" else 0), "横坐标", -15360, 15360),
                              "y": number(transform.get("y", settings["height"]-100 if track["type"] == "text" else 0), "纵坐标", -15360, 15360),
                              "scale": number(transform.get("scale", 1), "缩放", .02, 8),
                              "opacity": number(transform.get("opacity", 1), "透明度", 0, 1)},
                "volume": number(raw.get("volume", raw.get("gain", 1)), "片段音量", 0, 4),
                "audio_preset": audio_preset,
                "fade_in": min(duration, number(raw.get("fade_in", 0), "淡入时长", 0, max(duration, requested_duration)+1e-6)),
                "fade_out": min(duration, number(raw.get("fade_out", 0), "淡出时长", 0, max(duration, requested_duration)+1e-6)),
                "muted": flag(raw.get("muted", False), "片段静音/隐藏"), "locked": flag(raw.get("locked", False), "片段锁定"),
                "text_style": {"font_size": int(number(style.get("font_size", max(20, round(settings["height"]*.055))), "字号", 8, 300)),
                               "color": color(style.get("color", "#ffffff"), "文字颜色", transparent=False),
                               "background_color": color(style.get("background_color", "transparent"), "文字背景"), "align": align}}
        if track["type"] == "text":
            clip["asset_version_id"] = None
        clips.append(clip)
    if len({c["id"] for c in clips}) != len(clips):
        raise DomainError(422, "片段 ID 重复。", "invalid_timeline")
    end = max((c["start"] + c["duration"] for c in clips), default=0)
    if end > 3600:
        raise DomainError(422, "时间线最长为一小时。", "invalid_timeline")
    if settings["duration"] is not None:
        settings["duration"] = round(settings["duration"]*fps)/fps
        if settings["duration"] + 1e-6 < end:
            raise DomainError(422, "总时长不能短于现有片段，请先裁剪片段。", "timeline_clip_overflow")
    return {"schema_version": 1, "settings": settings, "tracks": sorted(tracks, key=lambda t: t["order"]), "clips": clips,
            "total_duration": round(settings["duration"] if settings["duration"] is not None else end, 6)}


class TimelineService:
    def __init__(self, store, production):
        self.store, self.production = store, production

    def get(self, project_id):
        with self.store.lock:
            project = self.store.project(project_id)
            canvas = self.store.canvas(project_id)
            raw = next((n["data"]["timeline"] for n in canvas["nodes"] if isinstance(n.get("data", {}).get("timeline"), dict)), {})
            doc = normalize_timeline(raw, project["aspect_ratio"])
            sources = {n["id"]: n for n in canvas["nodes"]}
            for clip in doc["clips"]:
                source = sources.get(clip["source_node_id"])
                latest = source.get("data", {}).get("asset_version_id") if source else None
                clip["latest_version_id"] = latest
                clip["stale"] = bool(latest and clip["asset_version_id"] != latest)
            doc["revision"] = canvas["revision"]
            doc["renders"] = [r for r in self.production.list_renders(project_id) if r.get("kind") == "timeline"]
            return doc

    def save(self, project_id, payload):
        if not isinstance(payload, dict):
            raise DomainError(422, "时间线格式不正确。", "invalid_timeline")
        key = identifier(payload.get("request_id"), "请求编号")
        with self.store.lock:
            previous = self.store.request_result(key, f"timeline:{project_id}", payload)
            if previous is not None:
                return previous
            project = self.store.project(project_id, include_deleted=False)
            canvas = self.store.canvas(project_id)
            if payload.get("revision") != canvas["revision"]:
                raise DomainError(409, "画布或时间线已更新，请先载入最新版本。", "revision_conflict", revision=canvas["revision"])
            doc = normalize_timeline(payload, project["aspect_ratio"])
            old = self.get(project_id)
            old_tracks, new_tracks = {t["id"]: t for t in old["tracks"]}, {t["id"]: t for t in doc["tracks"]}
            old_clips, new_clips = {c["id"]: c for c in normalize_timeline(old)["clips"]}, {c["id"]: c for c in doc["clips"]}
            for tid, track in old_tracks.items():
                if track["locked"] and (tid not in new_tracks or new_tracks[tid]["locked"]):
                    a = [c for c in old_clips.values() if c["track_id"] == tid]
                    b = [c for c in new_clips.values() if c["track_id"] == tid]
                    if track != new_tracks.get(tid) or a != b:
                        raise DomainError(409, "请先解锁轨道再修改其中的片段。", "timeline_locked")
            for cid, clip in old_clips.items():
                if clip["locked"] and (cid not in new_clips or new_clips[cid]["locked"]) and clip != new_clips.get(cid):
                    raise DomainError(409, "请先解锁片段。", "timeline_locked")
            kinds = {t["id"]: t["type"] for t in doc["tracks"]}
            for clip in doc["clips"]:
                if clip["asset_version_id"]:
                    self._media(clip, kinds[clip["track_id"]])
            node = next((n for n in canvas["nodes"] if "timeline" in n.get("data", {})), None)
            if node is None:
                node = {"id": "timeline-" + new_id(), "type": "frame", "position": {"x": -820, "y": -360}, "style": {"width": 340, "height": 200}, "data": {}}
                canvas["nodes"].append(node)
            node["hidden"] = True
            node["data"].update(title="多轨时间线", timeline=doc)
            self.store.save_canvas(project_id, canvas)
            result = self.get(project_id)
            with self.store.tx():
                self.store.remember_request(key, f"timeline:{project_id}", payload, result)
            return result

    def _media(self, clip, kind, *, render=False):
        version = self.store.version(clip["asset_version_id"])
        allowed = ("image/", "video/") if kind == "video" else ("audio/", "video/")
        if not version["mime"].startswith(allowed):
            raise DomainError(422, "轨道与素材类型不匹配。视频轨支持图片或视频，音频轨支持音频或视频原声。", "timeline_media_type")
        if version["missing"]:
            raise DomainError(409, "时间线素材原件缺失。", "missing_media", version_id=version["id"])
        if render and not version["mime"].startswith("image/"):
            if version["duration"] is None or clip["trim_end"] > version["duration"] + .05:
                raise DomainError(422, f"片段“{clip['name'] or clip['id']}”的入点加时长超出原件，请调整出点。", "timeline_media_too_short")
        return version

    def import_production(self, project_id, payload):
        if not isinstance(payload, dict):
            raise DomainError(422, "导入请求格式不正确。", "invalid_timeline")
        key = identifier(payload.get("request_id"), "请求编号") or new_id()
        route = f"timeline-import-production:{project_id}"
        with self.store.lock:
            previous = self.store.request_result(key, route, payload)
            if previous is not None:
                return previous
            doc = self.get(project_id)
            if payload.get("revision") != doc["revision"]:
                raise DomainError(409, "时间线已更新，请重新载入后导入。", "revision_conflict", revision=doc["revision"])
            production = self.production.get(project_id)
            if not production["shots"]:
                raise DomainError(422, "当前项目没有分镜。", "production_empty")
            if not doc["tracks"]:
                doc["settings"] = {**{k:production["settings"][k] for k in ("width", "height", "fps")}, "background_color":"#000000", "duration":None}
            offset = number(payload.get("start", 0), "导入开始时间", 0, 3600)
            prefix = "story-" + new_id()
            order = max((t["order"] for t in doc["tracks"]), default=-1) + 1
            for i, kind in enumerate(("video", "audio", "text")):
                doc["tracks"].append({"id":prefix+'-'+kind, "name":{"video":"分镜画面","audio":"分镜配音","text":"分镜字幕"}[kind], "type":kind,"order":order+i,"muted":False,"locked":False})
            cursor = offset
            for shot in production["shots"]:
                if shot["video_version_id"]:
                    doc["clips"].append({"id":new_id(),"track_id":prefix+'-video',"name":shot["title"],"start":cursor,"duration":shot["duration"],"trim_start":shot["trim_start"],"asset_version_id":shot["video_version_id"],"source_node_id":shot["video_node_id"],"volume":shot["video_volume"]})
                audio_duration = min(shot["duration"] - shot["audio_offset"], shot.get("audio_duration") or shot["duration"])
                if shot["audio_version_id"] and audio_duration > 0:
                    actual = self.store.version(shot["audio_version_id"])["duration"] or 0
                    if actual > shot["duration"] - shot["audio_offset"] + .05:
                        raise DomainError(422, f"镜头 {shot['order']} 配音超出镜头时长，请先修正。", "production_audio_overflow")
                    doc["clips"].append({"id":new_id(),"track_id":prefix+'-audio',"name":shot["speaker"] or shot["title"],"start":cursor+shot["audio_offset"],"duration":audio_duration,"asset_version_id":shot["audio_version_id"],"source_node_id":shot["audio_node_id"],"volume":shot["audio_volume"],"audio_preset":"dialogue"})
                if shot["dialogue"]:
                    subtitle_start = shot.get("subtitle_start", shot["audio_offset"] if shot["audio_version_id"] else 0)
                    subtitle_end = shot.get("subtitle_end", min(shot["duration"], subtitle_start+audio_duration) if shot["audio_version_id"] else shot["duration"])
                    if subtitle_end > subtitle_start:
                        doc["clips"].append({"id":new_id(),"track_id":prefix+'-text',"name":shot["title"]+"字幕","start":cursor+subtitle_start,"duration":subtitle_end-subtitle_start,"text":shot["dialogue"]})
                cursor += shot["duration"]
            background = production["settings"].get("background_audio_version_id")
            if background:
                track_id = prefix+'-music'
                doc["tracks"].append({"id":track_id,"name":"分镜配乐","type":"audio","order":order+3,"muted":False,"locked":False})
                duration = self.store.version(background)["duration"]
                if duration:
                    start = offset
                    while start < cursor - 1/doc["settings"]["fps"]:
                        part = min(duration, cursor-start)
                        doc["clips"].append({"id":new_id(),"track_id":track_id,"name":"配乐","start":start,"duration":part,"asset_version_id":background,"volume":production["settings"]["background_volume"]})
                        start += part
            if doc["settings"].get("duration") is not None:
                doc["settings"]["duration"] = max(doc["settings"]["duration"], cursor)
            result = self.save(project_id, doc)
            with self.store.tx():
                self.store.remember_request(key, route, payload, result)
            return result

    def render(self, project_id, payload):
        if not isinstance(payload, dict):
            raise DomainError(422, "导出请求格式不正确。", "invalid_timeline")
        key = identifier(payload.get("request_id"), "请求编号") or new_id()
        with self.store.tx():
            previous = self.store.conn.execute("SELECT * FROM production_renders WHERE request_id=?", (key,)).fetchone()
            request_hash = fingerprint({"kind":"timeline", "project_id":project_id, **payload})
            if previous:
                if previous["request_hash"] != request_hash:
                    raise DomainError(409, "请求编号已用于其他合成内容。", "idempotency_conflict")
                return self.production._decode(previous)
            self.store.project(project_id, include_deleted=False)
            doc = self.get(project_id)
            if payload.get("revision") is not None and payload["revision"] != doc["revision"]:
                raise DomainError(409, "时间线已更新，请重新确认后导出。", "revision_conflict", revision=doc["revision"])
            if not doc["clips"] or doc["total_duration"] <= 0:
                raise DomainError(422, "请先添加时间线片段。", "timeline_empty")
            if len(doc["clips"]) > 120:
                raise DomainError(422, "单次合成最多支持 120 个片段，请分段导出。", "timeline_render_limit")
            tracks = {t["id"]:t for t in doc["tracks"]}
            versions = set()
            for clip in doc["clips"]:
                track = tracks[clip["track_id"]]
                if track["muted"] or clip["muted"]:
                    continue
                if track["type"] == "text":
                    if not clip["text"]:
                        raise DomainError(422, "文字片段没有内容。", "timeline_text_empty")
                else:
                    if not clip["asset_version_id"]:
                        raise DomainError(422, "存在尚未选择素材的片段。", "timeline_media_missing")
                    version = self._media(clip, track["type"], render=True)
                    clip["source_hash"] = version["hash"]
                    versions.add(version["id"])
            doc.pop("renders", None)
            doc["kind"] = "timeline"
            doc["name"] = text(payload.get("name", self.store.project(project_id)["name"] + " · 多轨成片"), "成片名称", 240)
            job_id, timestamp = new_id(), now()
            self.store.conn.execute("INSERT INTO production_renders(id,project_id,request_id,request_hash,snapshot_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",(job_id,project_id,key,request_hash,encode(doc),timestamp,timestamp))
            self.store.conn.executemany("INSERT INTO production_inputs VALUES(?,?)",[(job_id,v) for v in versions])
            self.store.emit("production.updated",{"project_id":project_id,"render_id":job_id,"status":"pending"})
        return self.production.get_render(job_id)


def _text_image(clip, settings, path):
    style = clip["text_style"]
    font_path = next((p for p in (Path('C:/Windows/Fonts/msyh.ttc'),Path('C:/Windows/Fonts/simhei.ttf'),Path('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf')) if p.is_file()), None)
    font = ImageFont.truetype(str(font_path), style["font_size"]) if font_path else ImageFont.load_default()
    width = max(32, settings["width"]-80)
    draw = ImageDraw.Draw(Image.new('RGBA',(width,32)))
    lines = []
    for raw in clip["text"].splitlines():
        line = ''
        for char in raw:
            if line and draw.textlength(line+char,font=font)>width-16:
                lines.append(line)
                line=''
            line += char
        lines.append(line)
    content = '\n'.join(lines)
    bbox = draw.multiline_textbbox((0,0),content,font=font,spacing=6,stroke_width=2)
    height = max(style["font_size"]+16,bbox[3]-bbox[1]+20)
    if width*height > 16_000_000:
        raise DomainError(422,"文字层过大，请拆分文字片段。","timeline_text_large")
    background = (0,0,0,0) if style["background_color"]=='transparent' else ImageColor.getcolor(style["background_color"],'RGBA')
    image = Image.new('RGBA',(width,height),background)
    draw = ImageDraw.Draw(image)
    text_width = bbox[2]-bbox[0]
    x = 8 if style["align"]=='left' else width-text_width-8 if style["align"]=='right' else (width-text_width)/2
    draw.multiline_text((x,8-bbox[1]),content,font=font,fill=style["color"],spacing=6,align=style["align"],stroke_width=2,stroke_fill='#101010')
    image.save(path)
    return image.size


def render_timeline_job(service, job):
    """Called by the existing serialized durable production worker."""
    store = service.store
    ffmpeg, ffprobe = find_binary('ffmpeg'),find_binary('ffprobe')
    if not ffmpeg or not ffprobe:
        raise DomainError(503,'多轨合成需要 FFmpeg 和 FFprobe。','ffmpeg_missing')
    snapshot = job['snapshot']
    settings = snapshot['settings']
    width,height,fps = (settings[k] for k in ('width','height','fps'))
    total = snapshot['total_duration']
    folder = store.root/'exports'/('production-'+job['id'])
    folder.mkdir(parents=True,exist_ok=True)
    output,receipt_path = folder/'film.mp4',folder/'receipt.json'
    (folder/'timeline.json').write_text(json.dumps(snapshot,ensure_ascii=False,indent=2),encoding='utf-8')
    service._update(job['id'],status='running',progress=.05,message='正在合成多层画面、音轨和文字。',error=None)
    if output.is_file() and receipt_path.is_file():
        try:
            receipt=json.loads(receipt_path.read_text(encoding='utf-8'))
            if receipt['snapshot_hash']==fingerprint(snapshot) and receipt['digest']==service._hash_file(output):
                service._deliver(job,output,receipt['metadata'],receipt['digest'])
                return
        except (ValueError,KeyError,OSError):
            pass
    tracks={t['id']:t for t in snapshot['tracks']}
    clips=[c for c in snapshot['clips'] if not tracks[c['track_id']]['muted'] and not c['muted']]
    clips.sort(key=lambda c:tracks[c['track_id']]['order'])
    background=settings['background_color'].replace('#','0x')
    graph=[f'color=c={background}:s={width}x{height}:r={fps}:d={total},format=rgba[base]',f'anullsrc=r=48000:cl=stereo,atrim=duration={total}[silence]']
    command=[ffmpeg,'-hide_banner','-loglevel','error','-nostdin','-y','-filter_complex_threads','2']
    base='base';audio_labels=['[silence]'];input_count=0
    for index,clip in enumerate(clips):
        kind=tracks[clip['track_id']]['type'];transform=clip['transform'];text_size=None
        version=None
        if kind=='text':
            path=folder/f'text-{index:03}.png';text_size=_text_image(clip,settings,path)
            command.extend(['-threads','2','-loop','1','-framerate',str(fps),'-i',str(path)])
        else:
            version=store.version(clip['asset_version_id'])
            if version['missing']:
                raise DomainError(409,'时间线素材原件缺失。','missing_media')
            if version['mime'].startswith('image/'):
                command.extend(['-threads','2','-loop','1','-framerate',str(fps),'-i',version['path']])
            else:
                command.extend(['-threads','2','-ss',str(clip['trim_start']),'-i',version['path']])
        input_index=input_count;input_count+=1
        duration,start=clip['duration'],clip['start']
        if kind in ('video','text'):
            label=f'layer{index}'
            if kind=='text':
                tw,th=text_size
                prepare=f'format=rgba,scale={max(2,round(tw*transform["scale"]))}:{max(2,round(th*transform["scale"]))}'
            else:
                sw,sh=max(2,round(width*transform['scale'])),max(2,round(height*transform['scale']))
                if sw*sh>64_000_000:
                    raise DomainError(422,'视频图层缩放后过大，请降低缩放。','timeline_layer_large')
                prepare=f'scale={width}:{height}:force_original_aspect_ratio=decrease,format=rgba,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=0x00000000,scale={sw}:{sh}'
            filters=f'[{input_index}:v:0]{prepare},setsar=1,fps={fps},trim=duration={duration},setpts=PTS-STARTPTS,colorchannelmixer=aa={transform["opacity"]}'
            if clip['fade_in']:filters+=f',fade=t=in:st=0:d={clip["fade_in"]}:alpha=1'
            if clip['fade_out']:filters+=f',fade=t=out:st={duration-clip["fade_out"]}:d={clip["fade_out"]}:alpha=1'
            filters+=f',setpts=PTS+{start}/TB[{label}]'
            graph.append(filters)
            next_base=f'composite{index}'
            graph.append(f'[{base}][{label}]overlay=x={transform["x"]}:y={transform["y"]}:eof_action=pass:repeatlast=0:enable=\'gte(t,{start})*lt(t,{start+duration})\':format=auto[{next_base}]')
            base=next_base
        if kind=='audio' or kind=='video' and clip['volume']>0 and version and version['mime'].startswith('video/'):
            streams=json.loads(run_process([ffprobe,'-v','error','-show_streams','-of','json',version['path']]).stdout)['streams']
            has_audio=any(s.get('codec_type')=='audio' for s in streams)
            if not has_audio and kind=='audio':
                raise DomainError(422,'所选视频没有音轨，不能放在音频轨。','timeline_audio_missing')
            if has_audio:
                label=f'audio{index}'
                filters=f'[{input_index}:a:0]aresample=48000,aformat=channel_layouts=stereo,atrim=duration={duration},asetpts=PTS-STARTPTS'
                preset = clip.get('audio_preset', 'none')
                if preset == 'phone':
                    filters += ',highpass=f=300,highpass=f=300,lowpass=f=3400,equalizer=f=1600:t=q:w=1:g=2,acompressor=threshold=0.12:ratio=2:attack=8:release=120:makeup=1.25'
                elif preset == 'dialogue':
                    filters += ',highpass=f=80,lowpass=f=12000,acompressor=threshold=0.125:ratio=2:attack=10:release=150:makeup=1.2'
                elif preset == 'narration':
                    filters += ',highpass=f=65,lowpass=f=14000,acompressor=threshold=0.09:ratio=2.2:attack=15:release=180:makeup=1.2'
                filters += f',volume={clip["volume"]}'
                if clip['fade_in']:filters+=f',afade=t=in:d={clip["fade_in"]}'
                if clip['fade_out']:filters+=f',afade=t=out:st={duration-clip["fade_out"]}:d={clip["fade_out"]}'
                filters+=f',adelay={round(start*1000)}:all=1[{label}]'
                graph.append(filters);audio_labels.append(f'[{label}]')
        service._update(job['id'],progress=.05+.2*(index+1)/max(1,len(clips)),message=f'已准备片段 {index+1}/{len(clips)}。')
    graph.append(f'[{base}]format=yuv420p[v]')
    graph.append(''.join(audio_labels)+f'amix=inputs={len(audio_labels)}:duration=first:normalize=0,alimiter=limit=0.95:latency=1,atrim=duration={total}[a]')
    graph_file=folder/'filtergraph.txt';graph_file.write_text(';\n'.join(graph),encoding='utf-8')
    # FFmpeg 9 removed the legacy *_script option. The slash-prefixed option
    # reads its argument from a file on newer builds and avoids Windows' argv
    # size limit; retain the old spelling for older installed FFmpeg versions.
    help_text=run_process([ffmpeg,'-hide_banner','-h','full']).stdout.decode('utf-8',errors='replace')
    graph_option='-filter_complex_script' if '-filter_complex_script' in help_text else '-/filter_complex'
    command.extend([graph_option,str(graph_file),'-map','[v]','-map','[a]','-t',str(total),'-r',str(fps),'-c:v','libx264','-threads','4','-preset','fast','-crf','18','-pix_fmt','yuv420p','-c:a','aac','-b:a','192k','-ar','48000','-ac','2','-movflags','+faststart',str(output)])
    service._update(job['id'],progress=.3,message='正在编码多轨成片。')
    run_process(command,timeout=max(1800,round(total*20)))
    metadata=probe_media(output,'film.mp4')
    if abs((metadata.get('duration')or 0)-total)>max(.1,2/fps):
        raise RuntimeError('多轨成片时长校验失败。')
    digest=service._hash_file(output)
    pending=folder/'receipt.pending.json'
    pending.write_text(encode({'snapshot_hash':fingerprint(snapshot),'digest':digest,'metadata':metadata}),encoding='utf-8')
    pending.replace(receipt_path)
    service._deliver(job,output,metadata,digest)
