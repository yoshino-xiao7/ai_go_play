"""The verified H3 Turbo 8-step reference workflow."""

MODELS = {
    "fl2va": "minimax_h3_fl2va_int8_convrot.safetensors",
    "clip": "qwen3vl_32b_minimax_h3_ultra_uncensored_heretic_int8_convrot.safetensors",
    "video_vae": "minimax_h3_video_vae_int8_convrot.safetensors",
    "audio_vae": "minimax_h3_audio_vae_fp32.safetensors",
    "lora": "minimax_h3_turbo_v4_step600_ema.safetensors",
}
PARAMETERS = {"steps": 8, "cfg": 1}


def environment_errors(catalog, models, model_fields):
    nodes = (
        "MiniMaxH3ReferenceToVideo", "MiniMaxH3SigmaShift",
        "MiniMaxH3MemoryEfficientSageAttentionPatch", "ModelAttentionBackend",
        "SolAttnMiniMax", "MiniMaxH3TurboLoRA", "RandomNoise", "BasicGuider",
        "KSamplerSelect", "BasicScheduler", "SamplerCustomAdvanced",
        "LTXVSeparateAVLatent", "VAEDecodeTiled", "VAEDecodeAudio", "CreateVideo",
        "SaveVideo", "LoadImage", "LoadVideo", "GetVideoComponents", "LoadAudio",
    )
    fields = {**model_fields, "lora": ("MiniMaxH3TurboLoRA", "lora_name")}
    errors = [f"缺少节点：{name}" for name in nodes if name not in catalog]
    for key, filename in models.items():
        node, field = fields[key]
        choices = catalog.get(node, {}).get("input", {}).get("required", {}).get(field, [[]])[0]
        if not isinstance(choices, list) or filename not in choices:
            errors.append(f"缺少模型：{filename}")
    return errors


def apply_sampling(graph, node, models, seed):
    del graph["negative"]
    graph.update(
        sage=node("MiniMaxH3MemoryEfficientSageAttentionPatch", model=["model", 0]),
        backend=node("ModelAttentionBackend", model=["sage", 0], attention="pytorch attention"),
        sol=node("SolAttnMiniMax", model=["backend", 0], tau=1.3, start_percent=0.2,
                 end_percent=0.9, min_tokens=12288, sink_conditioning="exact_kv_and_rows",
                 morton=False, morton_curve="2d_frame", centroid_tail=True, routed_cap_percent=0,
                 reuse_qkv_memory=False, verbose=False, dense_blocks="0-2,-1"),
        turbo=node("MiniMaxH3TurboLoRA", model=["sol", 0], lora_name=models["lora"],
                   strength=1, low_vram=True),
        noise=node("RandomNoise", noise_seed=seed),
        guider=node("BasicGuider", model=["shift", 0], conditioning=["condition", 0]),
        sampler=node("KSamplerSelect", sampler_name="euler"),
        schedule=node("BasicScheduler", model=["shift", 0], scheduler="beta",
                      steps=PARAMETERS["steps"], denoise=1.0),
        sample=node("SamplerCustomAdvanced", noise=["noise", 0], guider=["guider", 0],
                    sampler=["sampler", 0], sigmas=["schedule", 0], latent_image=["condition", 1]),
    )
    graph["shift"]["inputs"]["model"] = ["turbo", 0]
