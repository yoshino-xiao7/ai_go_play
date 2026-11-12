"""Reusable, prompt-based camera directions for the local H3 workflow."""
import re

from .store import DomainError

MOVEMENTS = {
    "static": "镜头固定，保持机位和构图",
    "follow_front": "摄影机在主体前方沿行进路线后退，正面跟拍，保持主体在画面中稳定",
    "follow_side": "摄影机沿主体的行进路线平行移动，侧面跟拍，保持主体在画面中稳定",
    "truck_left": "摄影机机身向画面左侧横移，保持镜头朝向，前后景产生自然视差",
    "truck_right": "摄影机机身向画面右侧横移，保持镜头朝向，前后景产生自然视差",
    "pedestal_up": "摄影机机身垂直升高，保持镜头俯仰角",
    "pedestal_down": "摄影机机身垂直降低，保持镜头俯仰角",
    "dolly_in": "摄影机沿光轴向主体推进，保持焦距，主体逐渐占据更多画面",
    "dolly_out": "摄影机沿光轴远离主体，保持焦距，逐渐展露周围环境",
    "orbit": "摄影机沿弧线环绕主体，镜头持续朝向主体",
    "handheld": "使用手持机位，保留自然的手持起伏",
    "rack_focus": "保持机位和构图，焦点由前景平顺转移到背景主体",
}
AMPLITUDES = {"small": "小幅度", "medium": "", "large": "大幅度"}
SPEEDS = {"slow": "缓慢", "normal": "", "fast": "快速"}
VISUAL_FIELD = re.compile(r"(?m)^[ \t]*(?:integrated_multimodal_description|detailed_description)[ \t]*[:：]")
NEXT_FIELD = re.compile(r"(?m)^[ \t]*(?:overall_soundscape|non_diegetic_music|subject_definitions|summary|retention_analysis)[ \t]*[:：]")
SHOT = re.compile(r"\[Shot\s+\d+\]", re.IGNORECASE)


def normalize_camera_motion(value):
    if (not isinstance(value, dict) or set(value) != {"preset", "amplitude", "speed"}
        or not all(isinstance(item, str) for item in value.values())
        or value["preset"] not in MOVEMENTS
        or value["amplitude"] not in AMPLITUDES
        or value["speed"] not in SPEEDS):
        raise DomainError(422, "运镜预设、幅度或速度无效。", "camera_motion_invalid")
    return dict(value)


def linked_camera_motion(nodes, edges, target_id):
    source_id = next((edge["source"] for edge in edges
                      if edge["target"] == target_id and edge.get("data", {}).get("role") == "camera_motion"), None)
    return nodes[source_id]["data"]["camera_motion"] if source_id else None


def compile_camera_motion(prompt, motion):
    if motion is None:
        return prompt
    preset = motion["preset"]
    qualifiers = [] if preset in ("static", "rack_focus") else [
        text for text in (AMPLITUDES[motion["amplitude"]], SPEEDS[motion["speed"]]) if text
    ]
    direction = "运镜：" + MOVEMENTS[preset] + ("，" + "、".join(qualifiers) + "完成" if qualifiers else "") + "。"
    field = VISUAL_FIELD.search(prompt)
    start = field.end() if field else 0
    following = NEXT_FIELD.search(prompt, start) if field else None
    end = following.start() if following else len(prompt)
    boundaries = [match.start() for match in SHOT.finditer(prompt, start, end)][1:] + [end]
    parts = [prompt[:start]]
    for boundary in boundaries:
        section = prompt[start:boundary]
        body = section.rstrip()
        parts.extend((body, "\n", direction, section[len(body):] or ("\n" if boundary < len(prompt) else "")))
        start = boundary
    return "".join(parts) + prompt[end:]
