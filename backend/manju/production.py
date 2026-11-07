"""Ordered, version-pinned shots and durable local FFmpeg film delivery."""
from __future__ import annotations

import copy
import hashlib
import json
import logging
import math
import os
from pathlib import Path
import re
import threading
import zipfile

from .media import find_binary, probe_media, run_process
from .store import DomainError, encode, fingerprint, new_id, now


SCHEMA = """
CREATE TABLE IF NOT EXISTS production_renders (
 id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
 request_id TEXT NOT NULL UNIQUE, request_hash TEXT NOT NULL, snapshot_json TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'pending', progress REAL NOT NULL DEFAULT 0, message TEXT NOT NULL DEFAULT '',
 error TEXT, output_version_id TEXT, output_asset_id TEXT, output_node_id TEXT,
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS production_inputs (
 render_id TEXT NOT NULL REFERENCES production_renders(id) ON DELETE CASCADE,
 version_id TEXT NOT NULL, PRIMARY KEY(render_id,version_id)
);
CREATE INDEX IF NOT EXISTS idx_production_status ON production_renders(status,created_at);
"""


def number(value, label, low, high):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high:
        raise DomainError(422, f"{label}须为 {low}–{high} 之间的数字。", "invalid_production")
    return float(value)


def text(value, label, limit=500):
    if not isinstance(value, str) or len(value) > limit:
        raise DomainError(422, f"{label}须为不超过 {limit} 字的文本。", "invalid_production")
    return value.strip()


def identifier(value, label):
    if value is None or value == "":
        return None
    if not isinstance(value, str) or len(value) > 200 or not value.strip():
        raise DomainError(422, f"{label}格式不正确。", "invalid_production")
    return value


def normalize_settings(raw, aspect="16:9"):
    if not isinstance(raw, dict):
        raise DomainError(422, "成片设置格式不正确。", "invalid_production")
    width = number(raw.get("width", 480 if aspect == "9:16" else 864), "宽度", 64, 3840)
    height = number(raw.get("height", 864 if aspect == "9:16" else 480), "高度", 64, 3840)
    if width % 2 or height % 2:
        raise DomainError(422, "成片宽高须为偶数。", "invalid_production")
    fps = raw.get("fps", 24)
    if isinstance(fps, bool) or fps not in (24, 25, 30, 50, 60):
        raise DomainError(422, "成片帧率须为 24、25、30、50 或 60。", "invalid_production")
    return {"width": int(width), "height": int(height), "fps": fps,
            "background_audio_version_id": identifier(raw.get("background_audio_version_id"), "配乐版本"),
            "background_volume": number(raw.get("background_volume", .15), "配乐音量", 0, 2)}


def normalize_shot(raw, index, fps):
    if not isinstance(raw, dict):
        raise DomainError(422, "镜头格式不正确。", "invalid_production")
    chars = raw.get("characters", [])
    if not isinstance(chars, list) or len(chars) > 50:
        raise DomainError(422, "镜头人物须为最多 50 个名称的列表。", "invalid_production")
    status = raw.get("status", "draft")
    if status not in ("draft", "ready", "approved"):
        raise DomainError(422, "镜头状态须为 draft、ready 或 approved。", "invalid_production")
    requested_duration = number(raw.get("duration", 5), "镜头时长", .1, 120)
    # Frame alignment must preserve the accepted minimum on subsequent reads.
    duration = max(math.ceil(.1 * fps), round(requested_duration * fps)) / fps
    shot = {"id": identifier(raw.get("id"), "镜头 ID") or new_id(), "order": index + 1,
            "title": text(raw.get("title", f"镜头 {index + 1:02}"), "镜头名称", 250),
            "scene": text(raw.get("scene", ""), "场景"), "characters": [text(c, "人物", 100) for c in chars],
            "dialogue": text(raw.get("dialogue", ""), "台词", 2000), "speaker": text(raw.get("speaker", ""), "说话人", 100),
            "notes": text(raw.get("notes", ""), "镜头备注", 5000), "duration": duration,
            "trim_start": number(raw.get("trim_start", 0), "视频入点", 0, 86400),
            "audio_offset": number(raw.get("audio_offset", 0), "配音起点", 0, 120),
            "video_volume": number(raw.get("video_volume", 0), "原声响度", 0, 2),
            "audio_volume": number(raw.get("audio_volume", 1), "配音响度", 0, 2), "status": status}
    for field in ("video_version_id", "audio_version_id", "video_node_id", "audio_node_id"):
        shot[field] = identifier(raw.get(field), field)
    for field in ("subtitle_start", "subtitle_end"):
        if raw.get(field) is not None:
            shot[field] = number(raw[field], "字幕时间", 0, duration)
    if shot.get("subtitle_end", duration) <= shot.get("subtitle_start", 0):
        raise DomainError(422, "字幕结束时间必须晚于开始时间。", "invalid_production")
    return shot


def stamp(seconds, ass=False):
    factor = 100 if ass else 1000
    value = round(seconds * factor)
    whole, fraction = divmod(value, factor)
    hours, remainder = divmod(whole, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours}:{minutes:02}:{secs:02}.{fraction:02}" if ass else f"{hours:02}:{minutes:02}:{secs:02},{fraction:03}"


def subtitle_entries(snapshot):
    cursor = 0
    entries = []
    for shot in snapshot["shots"]:
        dialogue = shot["dialogue"].strip()
        if dialogue:
            start = shot.get("subtitle_start", shot["audio_offset"] if shot.get("audio_version_id") else 0)
            end = shot.get("subtitle_end", min(shot["duration"], start + (shot.get("audio_duration") or shot["duration"])))
            if end > start:
                entries.append((cursor + start, cursor + end, dialogue))
        cursor += shot["duration"]
    return entries


def srt_text(snapshot):
    return "\n\n".join(f"{i}\n{stamp(a)} --> {stamp(b)}\n{line}" for i, (a, b, line) in enumerate(subtitle_entries(snapshot), 1)) + "\n"


def ass_text(snapshot):
    width, height = snapshot["settings"]["width"], snapshot["settings"]["height"]
    font = "Microsoft YaHei" if os.name == "nt" else "Noto Sans CJK SC"
    size = max(20, round(min(width, height) * .055))
    lines = ["[Script Info]", "ScriptType: v4.00+", f"PlayResX: {width}", f"PlayResY: {height}", "WrapStyle: 0", "", "[V4+ Styles]",
             "Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding",
             f"Style: Default,{font},{size},&H00FFFFFF,&H00FFFFFF,&H00101010,&H80000000,0,0,0,0,100,100,0,0,1,2,1,2,24,24,{max(20, round(height*.06))},1", "", "[Events]",
             "Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text"]
    for start, end, line in subtitle_entries(snapshot):
        safe = line.replace("\\", "＼").replace("{", "｛").replace("}", "｝").replace("\r", "").replace("\n", "\\N")
        lines.append(f"Dialogue: 0,{stamp(start, True)},{stamp(end, True)},Default,,0,0,0,,{safe}")
    return "\n".join(lines) + "\n"


class ProductionService:
    def __init__(self, store):
        self.store = store
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self.run, daemon=True, name="manju-production")
        self.operation_lock = threading.RLock()
        with store.lock:
            store.conn.executescript(SCHEMA)
            store.conn.execute("UPDATE production_renders SET status='pending',message='服务重启，继续合成已保存的镜头快照。',updated_at=? WHERE status='running'", (now(),))
            store.conn.commit()

    def start(self):
        self.thread.start()

    def close(self):
        self.stop_event.set()
        if self.thread.is_alive():
            self.thread.join(timeout=20)

    def get(self, project_id):
        with self.store.lock:
            project = self.store.project(project_id)
            canvas = self.store.canvas(project_id)
            settings = normalize_settings(next((n["data"]["production_settings"] for n in canvas["nodes"] if isinstance(n.get("data", {}).get("production_settings"), dict)), {}), project["aspect_ratio"])
            source_nodes = {n["id"]: n for n in canvas["nodes"]}
            raw = [(n["id"], n["data"]["shot"]) for n in canvas["nodes"] if isinstance(n.get("data", {}).get("shot"), dict)]
            raw.sort(key=lambda item: (number(item[1].get("order", 0), "镜头顺序", 0, 20000), item[0]))
            shots = []
            for index, (node_id, value) in enumerate(raw):
                shot = normalize_shot({**value, "id": node_id}, index, settings["fps"])
                shot["stale_fields"] = []
                shot["warnings"] = []
                for kind in ("video", "audio"):
                    source = source_nodes.get(shot[kind + "_node_id"])
                    latest = source.get("data", {}).get("asset_version_id") if source else None
                    shot["latest_" + kind + "_version_id"] = latest
                    if source and latest and latest != shot[kind + "_version_id"]:
                        shot["stale_fields"].append(kind)
                    if shot[kind + "_version_id"]:
                        try:
                            version = self.store.version(shot[kind + "_version_id"])
                            shot[kind + "_duration"] = version["duration"]
                            if version["missing"]:
                                shot["warnings"].append("视频原件缺失" if kind == "video" else "配音原件缺失")
                        except DomainError:
                            shot["warnings"].append("采用的素材版本不存在")
                shot["stale"] = bool(shot["stale_fields"])
                shots.append(shot)
            return {"revision": canvas["revision"], "settings": settings, "shots": shots,
                    "total_duration": round(sum(s["duration"] for s in shots), 6), "renders": self.list_renders(project_id)}

    def _version(self, version_id, kind):
        version = self.store.version(version_id)
        if not version["mime"].startswith(kind + "/"):
            raise DomainError(422, f"请选择{ '视频' if kind == 'video' else '音频' }素材。", "production_media_type")
        if version["missing"]:
            raise DomainError(409, "采用的素材原件缺失，请先修复。", "missing_media", version_id=version_id)
        return version

    def save(self, project_id, payload):
        if not isinstance(payload, dict) or not isinstance(payload.get("shots"), list) or len(payload["shots"]) > 300:
            raise DomainError(422, "镜头清单须为最多 300 个镜头。", "invalid_production")
        key = identifier(payload.get("request_id"), "请求编号")
        with self.store.lock:
            previous = self.store.request_result(key, f"production:{project_id}", payload)
            if previous is not None:
                return previous
            project = self.store.project(project_id, include_deleted=False)
            settings = normalize_settings(payload.get("settings", {}), project["aspect_ratio"])
            shots = [normalize_shot(raw, i, settings["fps"]) for i, raw in enumerate(payload["shots"])]
            if len({s["id"] for s in shots}) != len(shots):
                raise DomainError(422, "镜头 ID 重复。", "invalid_production")
            canvas = self.store.canvas(project_id)
            if payload.get("revision") != canvas["revision"]:
                raise DomainError(409, "画布或镜头清单已更新，请载入最新内容后保存。", "revision_conflict", revision=canvas["revision"])
            original = {n["id"]: n for n in canvas["nodes"]}
            for shot in shots:
                old = original.get(shot["id"])
                if old and "shot" not in old.get("data", {}):
                    raise DomainError(422, "镜头 ID 与已有画布卡片冲突。", "invalid_production")
                for kind in ("video", "audio"):
                    source = original.get(shot[kind + "_node_id"])
                    if not shot[kind + "_version_id"] and source:
                        shot[kind + "_version_id"] = source.get("data", {}).get("asset_version_id")
                    if shot[kind + "_version_id"]:
                        self._version(shot[kind + "_version_id"], kind)
            if settings["background_audio_version_id"]:
                self._version(settings["background_audio_version_id"], "audio")
            removed = {n["id"] for n in canvas["nodes"] if "shot" in n.get("data", {}) and n["id"] not in {s["id"] for s in shots}}
            settings_node = next((n for n in canvas["nodes"] if "production_settings" in n.get("data", {})), None)
            nodes = [n for n in canvas["nodes"] if "shot" not in n.get("data", {}) and "production_settings" not in n.get("data", {})]
            for i, shot in enumerate(shots):
                node = copy.deepcopy(original.get(shot["id"])) or {"id": shot["id"], "type": "frame", "position": {"x": i * 420, "y": -360}, "style": {"width": 380, "height": 240}, "data": {}}
                node["data"].update({"title": f"{i+1:02} · {shot['title']}", "shot": shot})
                nodes.append(node)
            node = copy.deepcopy(settings_node) if settings_node else {"id": "production-" + new_id(), "type": "frame", "position": {"x": -420, "y": -360}, "style": {"width": 340, "height": 220}, "data": {}}
            node["data"].update({"title": "成片设置", "production_settings": settings})
            node["hidden"] = True
            nodes.append(node)
            # Removing a frame leaves its previously grouped children usable on the canvas.
            for node in nodes:
                if node.get("parentId") in removed:
                    parent = original[node["parentId"]]
                    node["position"] = {axis: node["position"][axis] + parent["position"][axis] for axis in ("x", "y")}
                    node.pop("parentId", None)
                    node.pop("extent", None)
            self.store.save_canvas(project_id, {**canvas, "nodes": nodes, "edges": [e for e in canvas["edges"] if e["source"] not in removed and e["target"] not in removed]})
            result = self.get(project_id)
            with self.store.tx():
                self.store.remember_request(key, f"production:{project_id}", payload, result)
            return result

    def _snapshot(self, project_id, *, render=False):
        production = self.get(project_id)
        if not production["shots"]:
            raise DomainError(422, "请先添加镜头。", "production_empty")
        production.pop("renders", None)
        for shot in production["shots"]:
            for key in ("stale", "stale_fields", "latest_video_version_id", "latest_audio_version_id", "warnings"):
                shot.pop(key, None)
            if render and not shot["video_version_id"]:
                raise DomainError(422, f"镜头 {shot['order']} 尚未采用视频。", "production_video_missing")
            if shot["video_version_id"]:
                video = self._version(shot["video_version_id"], "video")
                if render and (video["duration"] is None or video["duration"] + .03 < shot["trim_start"] + shot["duration"]):
                    raise DomainError(422, f"镜头 {shot['order']} 的视频不够长，请调整入点或时长。", "production_video_too_short")
                shot["video_hash"] = video["hash"]
            if shot["audio_version_id"]:
                audio = self._version(shot["audio_version_id"], "audio")
                shot["audio_duration"] = audio["duration"]
                shot["audio_hash"] = audio["hash"]
                if render and (audio["duration"] is None or shot["audio_offset"] + audio["duration"] > shot["duration"] + .03):
                    raise DomainError(422, f"镜头 {shot['order']} 配音超出镜头时长，请加长镜头或调整配音，避免截断台词。", "production_audio_overflow")
        if production["settings"]["background_audio_version_id"]:
            background = self._version(production["settings"]["background_audio_version_id"], "audio")
            production["settings"]["background_audio_hash"] = background["hash"]
        return production

    def render(self, project_id, payload):
        if not isinstance(payload, dict):
            raise DomainError(422, "合成请求格式不正确。", "invalid_production")
        key = identifier(payload.get("request_id"), "请求编号") or new_id()
        if not isinstance(payload.get("burn_subtitles", True), bool):
            raise DomainError(422, "字幕开关须为布尔值。", "invalid_production")
        with self.store.tx():
            previous = self.store.conn.execute("SELECT * FROM production_renders WHERE request_id=?", (key,)).fetchone()
            if previous:
                if previous["request_hash"] != fingerprint({"project_id": project_id, **payload}):
                    raise DomainError(409, "同一请求编号已用于其他合成内容。", "idempotency_conflict")
                return self._decode(previous)
            self.store.project(project_id, include_deleted=False)
            snapshot = self._snapshot(project_id, render=True)
            if payload.get("revision") is not None and payload["revision"] != snapshot["revision"]:
                raise DomainError(409, "镜头清单已更新，请重新确认后合成。", "revision_conflict", revision=snapshot["revision"])
            snapshot["name"] = text(payload.get("name", self.store.project(project_id)["name"] + " · 成片"), "成片名称", 240)
            snapshot["burn_subtitles"] = payload.get("burn_subtitles", True)
            job_id, timestamp = new_id(), now()
            self.store.conn.execute("INSERT INTO production_renders(id,project_id,request_id,request_hash,snapshot_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?)", (job_id, project_id, key, fingerprint({"project_id": project_id, **payload}), encode(snapshot), timestamp, timestamp))
            versions = {shot[k] for shot in snapshot["shots"] for k in ("video_version_id", "audio_version_id") if shot[k]}
            if snapshot["settings"]["background_audio_version_id"]:
                versions.add(snapshot["settings"]["background_audio_version_id"])
            self.store.conn.executemany("INSERT INTO production_inputs VALUES(?,?)", [(job_id, v) for v in versions])
            self.store.emit("production.updated", {"project_id": project_id, "render_id": job_id, "status": "pending"})
        return self.get_render(job_id)

    @staticmethod
    def _decode(row):
        value = dict(row)
        value["snapshot"] = json.loads(value.pop("snapshot_json"))
        value["kind"] = value["snapshot"].get("kind", "production")
        return value

    def get_render(self, job_id):
        with self.store.lock:
            row = self.store.conn.execute("SELECT * FROM production_renders WHERE id=?", (job_id,)).fetchone()
            if row is None:
                raise DomainError(404, "成片任务不存在。", "production_not_found")
            return self._decode(row)

    def list_renders(self, project_id):
        with self.store.lock:
            rows = self.store.conn.execute("SELECT * FROM production_renders WHERE project_id=? ORDER BY created_at DESC LIMIT 30", (project_id,)).fetchall()
            return [{k: v for k, v in self._decode(row).items() if k not in ("snapshot", "request_hash")} for row in rows]

    def retry_render(self, job_id):
        with self.store.tx():
            job = self.get_render(job_id)
            if job["status"] != "failed":
                raise DomainError(409, "只有失败的成片任务可以重试。", "production_retry_unavailable")
            self.store.project(job["project_id"], include_deleted=False)
            for row in self.store.conn.execute("SELECT version_id FROM production_inputs WHERE render_id=?", (job_id,)):
                if self.store.version(row[0])["missing"]:
                    raise DomainError(409, "请先修复缺失素材。", "missing_media")
            self.store.conn.execute("UPDATE production_renders SET status='pending',error=NULL,progress=0,message='按原镜头快照重试合成。',updated_at=? WHERE id=?", (now(), job_id))
        return self.get_render(job_id)

    def _update(self, job_id, **fields):
        with self.store.tx():
            fields["updated_at"] = now()
            self.store.conn.execute("UPDATE production_renders SET " + ",".join(k + "=?" for k in fields) + " WHERE id=?", (*fields.values(), job_id))
            row = self.store.conn.execute("SELECT project_id,status FROM production_renders WHERE id=?", (job_id,)).fetchone()
            self.store.emit("production.updated", {"project_id": row["project_id"], "render_id": job_id, "status": row["status"]})

    def run(self):
        while not self.stop_event.is_set():
            try:
                self.tick()
            except Exception:
                logging.getLogger(__name__).exception("Production worker failed")
            self.stop_event.wait(.5)

    def tick(self):
        if self.store.maintenance:
            return
        with self.operation_lock, self.store.media_lock:
            if self.store.maintenance or self.stop_event.is_set():
                return
            with self.store.lock:
                row = self.store.conn.execute("SELECT id FROM production_renders WHERE status='pending' ORDER BY created_at LIMIT 1").fetchone()
            if not row:
                return
            try:
                self._execute(self.get_render(row["id"]))
            except Exception as error:
                self._update(row["id"], status="failed", error=str(error)[-3000:], message="成片失败，修复素材或配置后可按原快照重试。")

    def _execute(self, job):
        if job["snapshot"].get("kind") == "timeline":
            from .timeline import render_timeline_job
            return render_timeline_job(self, job)
        ffmpeg = find_binary("ffmpeg")
        if not ffmpeg or not find_binary("ffprobe"):
            raise DomainError(503, "成片导出需要 FFmpeg 和 FFprobe。", "ffmpeg_missing")
        snapshot = job["snapshot"]
        settings, shots = snapshot["settings"], snapshot["shots"]
        width, height, fps = settings["width"], settings["height"], settings["fps"]
        folder = self.store.root / "exports" / ("production-" + job["id"])
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "subtitles.srt").write_text(srt_text(snapshot), encoding="utf-8")
        (folder / "subtitles.ass").write_text(ass_text(snapshot), encoding="utf-8-sig")
        (folder / "production.json").write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
        output = folder / "film.mp4"
        self._update(job["id"], status="running", progress=.02, message="正在按镜头顺序裁剪和对齐配音。", error=None)
        receipt_path = folder / "receipt.json"
        if receipt_path.is_file() and output.is_file():
            try:
                receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
                if receipt["snapshot_hash"] == fingerprint(snapshot) and receipt["digest"] == self._hash_file(output):
                    self._deliver(job, output, receipt["metadata"], receipt["digest"])
                    return
            except (ValueError, KeyError, OSError):
                pass
        clips = []
        for index, shot in enumerate(shots):
            if self.stop_event.is_set():
                self._update(job["id"], status="pending", message="已暂停，服务启动后继续。")
                return
            video = self._version(shot["video_version_id"], "video")
            clip = folder / f"shot-{index+1:03}.mp4"
            clips.append(clip)
            command = [ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-y", "-ss", str(shot["trim_start"]), "-i", video["path"]]
            filters = [f"[0:v:0]scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={fps},trim=duration={shot['duration']},setpts=PTS-STARTPTS[v]",
                       f"anullsrc=r=48000:cl=stereo,atrim=duration={shot['duration']}[silence]"]
            audio_labels = ["[silence]"]
            if shot["video_volume"]:
                probe = find_binary("ffprobe")
                streams = json.loads(run_process([probe, "-v", "error", "-show_streams", "-of", "json", video["path"]]).stdout)["streams"]
                if any(s.get("codec_type") == "audio" for s in streams):
                    filters.append(f"[0:a:0]aresample=48000,volume={shot['video_volume']},atrim=duration={shot['duration']},asetpts=PTS-STARTPTS[original]")
                    audio_labels.append("[original]")
            if shot["audio_version_id"]:
                audio = self._version(shot["audio_version_id"], "audio")
                command.extend(["-i", audio["path"]])
                delay = round(shot["audio_offset"] * 1000)
                filters.append(f"[1:a:0]aresample=48000,volume={shot['audio_volume']},adelay={delay}:all=1[voice]")
                audio_labels.append("[voice]")
            filters.append("".join(audio_labels) + f"amix=inputs={len(audio_labels)}:duration=first:normalize=0,alimiter=limit=0.95:latency=1,atrim=duration={shot['duration']}[a]")
            command.extend(["-filter_complex", ";".join(filters), "-map", "[v]", "-map", "[a]", "-t", str(shot["duration"]), "-c:v", "libx264", "-preset", "fast", "-crf", "18", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2", "-movflags", "+faststart", str(clip)])
            run_process(command, timeout=1800)
            self._update(job["id"], progress=.05 + .7 * (index+1)/len(shots), message=f"已完成镜头 {index+1}/{len(shots)}。")
        listing = folder / "concat.txt"
        listing.write_text("\n".join("file '" + clip.name + "'" for clip in clips), encoding="utf-8")
        command = [ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-y", "-f", "concat", "-safe", "0", "-i", str(listing)]
        background = settings["background_audio_version_id"]
        if background:
            command.extend(["-stream_loop", "-1", "-i", self._version(background, "audio")["path"]])
        total = snapshot["total_duration"]
        if snapshot["burn_subtitles"] and subtitle_entries(snapshot):
            escaped = str(folder / "subtitles.ass").replace("\\", "/").replace(":", "\\:").replace("'", "'\\''")
            command.extend(["-vf", f"subtitles=filename='{escaped}'"])
        if background:
            command.extend(["-filter_complex", f"[1:a:0]aresample=48000,volume={settings['background_volume']},atrim=duration={total}[bg];[0:a:0][bg]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.95:latency=1[a]", "-map", "0:v:0", "-map", "[a]"])
        else:
            command.extend(["-map", "0:v:0", "-map", "0:a:0"])
        command.extend(["-t", str(total), "-r", str(fps), "-c:v", "libx264", "-preset", "fast", "-crf", "18", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(output)])
        self._update(job["id"], progress=.8, message="正在合并镜头、混音并写入字幕。")
        run_process(command, timeout=3600)
        metadata = probe_media(output, "film.mp4")
        if abs((metadata.get("duration") or 0) - total) > max(.1, 2/fps):
            raise RuntimeError("成片时长与镜头清单不一致，已停止交付。")
        digest = self._hash_file(output)
        receipt = {"snapshot_hash": fingerprint(snapshot), "digest": digest, "metadata": metadata}
        temporary = folder / "receipt.pending.json"
        temporary.write_text(encode(receipt), encoding="utf-8")
        temporary.replace(receipt_path)
        self._deliver(job, output, metadata, digest)

    @staticmethod
    def _hash_file(path):
        hasher = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                hasher.update(chunk)
        return hasher.hexdigest()

    def _deliver(self, job, output, metadata, digest):
        snapshot = job["snapshot"]
        asset = self.store.ingest(output, snapshot["name"] + ".mp4", metadata, digest, project_id=job["project_id"], request_id="production-output:" + job["id"], source="production")
        version_id = asset["imported_version_id"]
        node_id = "production-result-" + job["id"]
        with self.store.lock:
            canvas = self.store.canvas(job["project_id"])
            if not any(n["id"] == node_id for n in canvas["nodes"]):
                right = max((n["position"]["x"] + float(n.get("style", {}).get("width", 320)) for n in canvas["nodes"]), default=0)
                canvas["nodes"].append({"id": node_id, "type": "media", "position": {"x": right + 100, "y": 0}, "style": {"width": 400, "height": 260}, "data": {"title": snapshot["name"], "kind": "video", "asset_version_id": version_id, "production_render_id": job["id"]}})
                self.store.save_canvas(job["project_id"], canvas)
        self._update(job["id"], status="succeeded", progress=1, message="成片已进入项目画布和资产库。", output_version_id=version_id, output_asset_id=asset["id"], output_node_id=node_id)

    def subtitle(self, project_id):
        return srt_text(self._snapshot(project_id))

    def handoff(self, project_id):
        with self.store.media_lock, self.store.lock:
            snapshot = self._snapshot(project_id)
            path = self.store.root / "temp" / ("production-handoff-" + new_id() + ".zip")
            try:
                with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_STORED) as archive:
                    manifest = copy.deepcopy(snapshot)
                    files = {}
                    for shot in manifest["shots"]:
                        for kind in ("video", "audio"):
                            version_id = shot[kind + "_version_id"]
                            if not version_id:
                                continue
                            version = self._version(version_id, kind)
                            suffix = Path(version["filename"]).suffix or (".mp4" if kind == "video" else ".wav")
                            filename = f"media/{shot['order']:03}-{kind}{suffix}"
                            archive.write(version["path"], filename)
                            shot[kind + "_file"] = filename
                            files[version_id] = filename
                    background = manifest["settings"]["background_audio_version_id"]
                    if background:
                        version = self._version(background, "audio")
                        filename = "media/background" + Path(version["filename"]).suffix
                        archive.write(version["path"], filename)
                        manifest["settings"]["background_audio_file"] = filename
                    archive.writestr("production.json", json.dumps(manifest, ensure_ascii=False, indent=2))
                    archive.writestr("subtitles.srt", srt_text(snapshot))
                    archive.writestr("README.txt", "镜头按 production.json 的 order 排列。video_file 为采用的视频原件，trim_start 是入点，duration 是剪辑时长；audio_file 从 audio_offset 开始。subtitles.srt 使用整片时间码。素材使用固定版本，包含清单记录的原件。\n")
                return path
            except BaseException:
                path.unlink(missing_ok=True)
                raise
