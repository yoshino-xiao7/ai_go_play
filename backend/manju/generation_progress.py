"""Job-scoped ComfyUI execution telemetry. Never estimate whole-job completion."""
from __future__ import annotations

import json
import math
import threading
from urllib.parse import urlencode

from websocket import create_connection, WebSocketTimeoutException

from .store import now


def stage_label(node_type):
    if node_type == "ManjuLatentSync15":
        return "LatentSync 正在按配音同步人物口型"
    if node_type == "ManjuIndexTTS25":
        return "IndexTTS 正在加载音色并合成配音"
    if node_type == "MiniMaxH3Director":
        return "Director 正在生成镜头"
    if "Sampler" in node_type:
        return "正在采样"
    if "DecodeAudio" in node_type:
        return "正在解码声音"
    if "Decode" in node_type:
        return "正在解码画面"
    if node_type in ("CreateVideo", "SaveVideo", "VHS_VideoCombine"):
        return "正在合成视频"
    if "Save" in node_type:
        return "正在输出媒体"
    if "Loader" in node_type:
        return "正在加载模型"
    if "TextEncode" in node_type:
        return "正在编码描述"
    if "LoadImage" in node_type or "Encode" in node_type or "Reference" in node_type:
        return "正在处理参考素材"
    return "正在执行工作流"


class JobProgress:
    def __init__(self, job):
        self.job_id = job["id"]
        self.prompt_id = job["prompt_id"]
        self.graph = job.get("mapped_graph") or {}
        self.url = job["backend_url"].replace("http://", "ws://", 1).replace("https://", "wss://", 1) + "/ws?" + urlencode({"clientId": self.job_id})
        self.stop = threading.Event()
        self.lock = threading.Lock()
        self.state = {"connected": False, "source": "comfyui"}
        self.thread = threading.Thread(target=self.run, name="progress-" + self.job_id[:8], daemon=True)

    def snapshot(self):
        with self.lock:
            return dict(self.state)

    def connection(self, connected):
        with self.lock:
            # Reconnect only knows the current node, not the last sample count.
            self.state = {"connected": connected, "source": "comfyui"}

    def consume(self, event):
        if not isinstance(event, dict) or not isinstance(event.get("data"), dict):
            return
        kind, data = event.get("type"), event["data"]
        if kind == "minimax_director_progress":
            # This extension sends job-client-scoped events without prompt_id.
            # Accept them only after our own executing event selected this node.
            node=str(data.get("node_id", ""))
            with self.lock:
                if (data.get("prompt_id",self.prompt_id)!=self.prompt_id or self.state.get("node_id")!=node
                    or self.graph.get(node,{}).get("class_type")!="MiniMaxH3Director"):
                    return
                phase=data.get("phase")
                labels={"plan":"Director 正在准备镜头","prepare":"正在准备参考素材","context_encode":"正在编码镜头描述与参考","sample":"正在采样","decode":"正在解码音视频","upscale":"正在放大画面","refine":"正在精修采样","finish":"正在完成镜头"}
                state={"connected":True,"source":"comfyui","node_id":node,"node_type":"MiniMaxH3Director","label":labels.get(phase,"Director 正在生成镜头"),"updated_at":now()}
                value,maximum=data.get("phase_value"),data.get("phase_max")
                if phase in ("sample","refine") and all(type(v) in (int,float) and math.isfinite(v) for v in (value,maximum)) and maximum>1 and 0<=value<=maximum:
                    state.update(value=value,max=maximum)
                self.state=state
            return
        if data.get("prompt_id") != self.prompt_id:
            # ComfyUI's job-specific reconnect message omits prompt_id.
            if kind != "executing" or "prompt_id" in data:
                return
        if kind == "progress_state":
            nodes = data.get("nodes", {})
            if not isinstance(nodes, dict):
                return
            running = [dict(state, node=node) for node, state in nodes.items() if isinstance(state, dict) and state.get("state") == "running"]
            if not running:
                return
            data = next((state for state in running if state.get("max", 0) > 1), running[-1])
        elif kind not in ("executing", "progress"):
            return
        node = data.get("node")
        if node is None:
            with self.lock:
                self.state = {"connected": True, "source": "comfyui", "label": "正在完成工作流", "updated_at": now()}
            return
        node = str(node)
        node_type = self.graph.get(node, {}).get("class_type", "")
        if node_type=="MiniMaxH3Director" and kind!="executing":
            # Director publishes an equally weighted six-phase estimate here.
            # Use its real per-phase callback above instead of displaying fake steps.
            return
        state = {"connected": True, "source": "comfyui", "node_id": node, "node_type": node_type,
                 "label": stage_label(node_type), "updated_at": now()}
        value, maximum = data.get("value"), data.get("max")
        if kind != "executing" and all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in (value, maximum)) and maximum > 0 and 0 <= value <= maximum:
            state.update(value=value, max=maximum)
        with self.lock:
            self.state = state

    def run(self):
        while not self.stop.is_set():
            socket = None
            try:
                socket = create_connection(self.url, timeout=2, http_no_proxy=["127.0.0.1", "localhost"], suppress_origin=True)
                socket.settimeout(1)
                self.connection(True)
                while not self.stop.is_set():
                    try:
                        raw = socket.recv()
                    except WebSocketTimeoutException:
                        continue
                    if not raw:
                        break
                    if isinstance(raw, str):
                        try:
                            self.consume(json.loads(raw))
                        except (ValueError, TypeError, KeyError):
                            continue
            except Exception:
                # Telemetry loss must never fail, cancel or resubmit a generation.
                pass
            finally:
                self.connection(False)
                if socket is not None:
                    socket.close()
            self.stop.wait(2)


class GenerationProgress:
    def __init__(self, enabled=True):
        self.enabled = enabled
        self.items = {}
        self.lock = threading.Lock()

    def ensure(self, job):
        if not self.enabled or not job.get("prompt_id"):
            return
        with self.lock:
            if job["id"] not in self.items:
                item = self.items[job["id"]] = JobProgress(job)
                item.thread.start()
            else:
                # Older ComfyUI builds assign their own prompt ID.
                self.items[job["id"]].prompt_id = job["prompt_id"]

    def snapshot(self, job_id):
        with self.lock:
            item = self.items.get(job_id)
            return item.snapshot() if item else None

    def retain(self, active_ids):
        with self.lock:
            for job_id in list(self.items):
                if job_id not in active_ids:
                    self.items.pop(job_id).stop.set()

    def close(self):
        with self.lock:
            items = list(self.items.values())
            self.items.clear()
        for item in items:
            item.stop.set()
        for item in items:
            item.thread.join(timeout=4)
