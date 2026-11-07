"""Design reusable character voices with local H3, independently of a scene."""
from copy import deepcopy

from .store import DomainError

PROFILE_ID = "builtin-h3-voice-design-local"
AUDITION_TEXT = "你好，很高兴认识你。今天的天气很好，我们一起出去走走吧。"
PARAMETERS = {"width": 864, "height": 480, "steps": 20, "cfg": 1, "denoise": 1}


def normalize_voice_design(payload, base):
    clean = deepcopy(payload)
    clean.pop("kind", None)
    clean["result_policy"] = "review"
    request = base(clean)
    options = payload.get("voice_design_options", {})
    if (payload.get("provider", "comfyui") != "comfyui"
            or request.get("mask_version_id") or request.get("prompt_parts") is not None
            or len(request["references"]) > 1
            or any(k != "seed" and (k not in PARAMETERS or v != PARAMETERS[k]) for k, v in request["parameters"].items())
            or not isinstance(options, dict) or set(options) - {"description"}):
        raise DomainError(422, "音色设计接受声线描述、一张可选角色图和随机种子。", "voice_design_invalid")
    description = options.get("description", "")
    if not isinstance(description, str) or not 1 <= len(description.strip()) <= 2000:
        raise DomainError(422, "请填写 1–2000 字的声线描述。", "voice_design_description_required")
    text = request["prompt"].strip()
    if not 4 <= len(text) <= 50:
        raise DomainError(422, "试听文本须为 4–50 字；请使用简短日常句子。", "voice_design_text_invalid")
    subject = payload.get("subject_node_id")
    if subject is not None and (not isinstance(subject, str) or not 1 <= len(subject) <= 200):
        raise DomainError(422, "人物标识无效。", "voice_design_subject_invalid")
    for index, ref in enumerate(request["references"]):
        ref.update(id=ref.get("id") or f"portrait-{index}", media_type="image", role="reference")
    request.update(kind="audio", subject_node_id=subject,
                   voice_design_options={"description": description.strip()}, dialogue_text=text)
    return request


class VoiceDesignAdapter:
    def __init__(self, video):
        self.video = video

    def status(self):
        status = self.video.status()
        errors = list(status["errors"])
        if status["ready"] and "SaveAudio" not in self.video.workflows.object_info():
            errors.append("缺少节点：SaveAudio")
        return {"profile_id": PROFILE_ID, "ready": not errors, "errors": errors,
                "audition_text": AUDITION_TEXT, "engine": "MiniMax H3 · 本地原生音色设计"}

    def snapshot(self):
        status = self.status()
        if not status["ready"]:
            raise DomainError(422, "本地 H3 音色设计尚未就绪。", "voice_design_not_ready", errors=status["errors"])
        workflow = self.video.snapshot()
        return {**workflow, "id": PROFILE_ID, "name": "H3 · 角色音色设计", "kind": "audio", "mode": "audio",
                "capabilities": {"min_images": 0, "max_images": 1}, "voice_design_revision": 1}

    def bind_subject(self, request, nodes):
        identifier = request.get("subject_node_id")
        if identifier:
            node = nodes.get(identifier, {})
            subject = node.get("data", {}).get("subject", {})
            if node.get("type") != "subject" or subject.get("kind") != "character":
                raise DomainError(422, "音色设计需要画布上的人物主体。", "voice_design_subject_missing")
            # Provenance only: generating a candidate never changes the binding.
            request["voice_design_subject"] = {"node_id": identifier, "name": subject.get("name", "")}

    def configure(self, request, payload, workflow):
        description = request["voice_design_options"]["description"]
        portrait = "<Picture 1> defines the appearance of this speaker only. " if request["references"] else ""
        request["compiled_prompt"] = (
            "subject_definitions: One Mandarin speaker (S1). " + portrait
            + "Voice identity and timbre design: " + description + "\n"
            "summary: A neutral character voice audition in a quiet recording room. One continuous take.\n"
            "retention_analysis: Preserve a single consistent vocal identity throughout the audition.\n"
            "detailed_description: The speaker looks relaxed and speaks clearly at a natural conversational pace, "
            "with neutral emotion. Only one person speaks. Say the following once in full: "
            + "<d>[Chinese] " + request["dialogue_text"] + "</d>. "
            "Keep the voice close and dry, with no theatrical acting, shouting, whispering or singing.\n"
            "overall_soundscape: Clean foreground speech only. No other voices or environmental sounds.\n"
            "non_diegetic_music: N/A"
        )
        request["parameters"] = {**PARAMETERS, "seed": request["parameters"].get("seed", -1)}
        request.update(duration=8, audio=True, video_mode="reference" if request["references"] else "text",
                       video_options={"engine": "native", "sampler": "res_multistep", "scheduler": "simple", "ref_image_size": "match"})

    def input_version(self, version_id):
        version = self.video.input_version(version_id)
        if not version["mime"].startswith("image/"):
            raise DomainError(422, "音色设计只接受可选角色图片，不需要已有声音。", "voice_design_portrait_required")
        return version

    def prepare(self, job, files):
        result = self.video.prepare(job, files)
        graph = result["api_graph"]
        # H3 jointly samples audio/video, but this task only decodes and saves audio.
        # Skipping video decode avoids creating an unrelated scene asset.
        del graph["decode"], graph["video"]
        graph["save"] = {"class_type": "SaveAudio", "inputs": {
            "audio": ["audio", 0], "filename_prefix": "Manju/voice-design/" + job["id"]}}
        return result
