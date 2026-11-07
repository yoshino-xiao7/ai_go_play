"""Stable prompt references, independent of mutable canvas placements."""
from .store import DomainError


def normalize_references(payload, request):
    identities = set()
    extended = "prompt_parts" in payload or any(any(key in ref for key in ("id", "title", "description", "use_description")) for ref in payload.get("references", []))
    for index, (raw, ref) in enumerate(zip(payload.get("references", []), request["references"])):
        identity = raw.get("id", f"ref-{index + 1}")
        if not isinstance(identity, str) or not identity or len(identity) > 200 or identity in identities:
            raise DomainError(422, "引用 ID 必须唯一。", "invalid_reference_identity")
        identities.add(identity)
        if not extended:
            continue
        ref["id"] = identity
        for key, limit in (("title", 250), ("description", 6000)):
            value = raw.get(key, "")
            if not isinstance(value, str) or len(value) > limit:
                raise DomainError(422, "引用名称或设定格式无效。", "invalid_reference_identity")
            ref[key] = value
        ref["use_description"] = raw.get("use_description", True) is True
    parts = payload.get("prompt_parts")
    if parts is not None:
        if not isinstance(parts, list) or len(parts) > 2000:
            raise DomainError(422, "结构化提示词格式无效。", "invalid_prompt_parts")
        clean = []
        for part in parts:
            if not isinstance(part, dict):
                raise DomainError(422, "提示词片段格式无效。", "invalid_prompt_parts")
            if part.get("type") == "text" and isinstance(part.get("text"), str):
                clean.append({"type": "text", "text": part["text"]})
            elif part.get("type") == "reference" and part.get("reference_id") in identities:
                clean.append({"type": "reference", "reference_id": part["reference_id"]})
            else:
                raise DomainError(422, "提示词引用不存在，请重新选择。", "prompt_reference_missing")
        if sum(len(p.get("text", "")) for p in clean) > 32000:
            raise DomainError(422, "提示词过长。", "invalid_prompt_parts")
        request["prompt_parts"] = clean
    policy = payload.get("result_policy", "replace")
    if policy not in ("replace", "review"):
        raise DomainError(422, "结果处理方式无效。", "invalid_result_policy")
    if "result_policy" in payload:
        request["result_policy"] = policy


def compile_prompt(request, workflow):
    parts = request.get("prompt_parts")
    if parts is None:
        return request["prompt"]
    refs = request["references"]
    slots, versions = {}, []
    for ref in refs:
        if ref["version_id"] not in versions:
            versions.append(ref["version_id"])
        slots[ref["id"]] = versions.index(ref["version_id"]) + 1
    has_mentions = any(p["type"] == "reference" for p in parts)
    numbered = workflow.get("capabilities", {}).get("reference_mapping") == "numbered"
    # The built-in Qwen encoder numbers images in exactly the supplied order.
    numbered = numbered or workflow.get("id", "").startswith("builtin-qwen21-")
    if has_mentions and not numbered:
        raise DomainError(422, "此工作流尚未适配主体名称映射，请在工作流中配置后使用 @ 引用。", "reference_mapping_unsupported")
    result = "".join(p["text"] if p["type"] == "text" else f"参考图{slots[p['reference_id']]}中的主体" for p in parts)
    settings = []
    for ref in refs:
        description = ref.get("description") if ref.get("use_description") else ""
        if description:
            settings.append(f"参考图{slots[ref['id']]}的主体设定：{description}")
    return result + ("\n" + "\n".join(settings) if settings else "")
