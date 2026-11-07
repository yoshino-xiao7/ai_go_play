"""One canvas shot → one external Director group, sharing the H3 input contract."""


def director_graph(graph, request, options, length):
    p = request["parameters"]
    mode = request["video_mode"]
    graph = {key: value for key, value in graph.items() if key in ("model", "clip", "vvae", "avae", "video", "save", "condition") or key.startswith("input_")}
    inputs = graph.pop("condition")["inputs"]
    references = {key: value for key, value in inputs.items() if key.startswith("ref_") or key in ("first_frame", "last_frame")}
    references.pop("ref_image_size", None)
    # Director packs zero-based indices and filters prompt tags using those indices.
    # Standalone audio indices must include the video soundtrack offset as well.
    offset=sum(ref.get("media_type")=="video" and ref.get("use_audio",False) for ref in request["references"])
    references={((key.rsplit("_",1)[0]+"_"+str(int(key.rsplit("_",1)[1])-1+(offset if key.startswith("ref_audios.") else 0))) if "." in key else key):value for key,value in references.items()}
    task = {"text": "t2v — 文生视频(Text to Video)", "frames": "fl2v — 首尾帧生视频(First-Last Frame)", "reference": "r2v — 参考主体生视频(Reference to Video)"}[mode]
    if mode == "frames" and "last_frame" not in references:
        task = "i2v — 图生视频(Image to Video)"
    group = {"prompt": request["compiled_prompt"], "duration_sec": request["duration"], **references}
    if mode == "reference": group["ref_image_size"] = "match" if options["ref_image_size"]=="match" else "max"
    graph["shot"] = {"class_type": "MiniMaxH3DirectorGroupReferenceToVideo" if mode == "reference" else "MiniMaxH3DirectorGroupImageToVideo", "inputs": group}
    graph["director"] = {"class_type": "MiniMaxH3Director", "inputs": {
        "model": ["model", 0], "clip": ["clip", 0], "video_vae": ["vvae", 0], "audio_vae": ["avae", 0],
        "task_type": task, "global_prompt": "", "bd_grp_sample": "采样设置", "cfg": p["cfg"], "seed": p["seed"],
        "frame_rate": 24.0, "width": p["width"], "height": p["height"], "ref_max_size": max(p["width"], p["height"]),
        "total_frames": length, "timeline_data": "", "steps": p["steps"], "sampler": options["sampler"],
        "scheduler": options["scheduler"], "shift_video": 12.0, "shift_audio": 3.0,
        "r2v_groups" if mode == "reference" else "i2v_groups": ["shot", 0],
        "cache_frames_codec": "ffv1", "cache_name": "", "export_source_images": False,
    }}
    graph["video"]["inputs"] = {"images": ["director", 0], "fps": ["director", 2], **({"audio": ["director", 1]} if request["audio"] else {})}
    return graph
