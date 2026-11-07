"""Local H3 profiles and deterministic multimodal graph compilation."""
from copy import deepcopy
from pathlib import Path
import json, math
from .store import DomainError, encode, now
from .video_inputs import VIDEO_OPTIONS, normalize_options, normalize_inputs, has_audio

MODES = ("text", "frames", "reference")
PROFILE_ID = "builtin-h3-local"
DEFAULTS = {"width":864,"height":480,"steps":20,"cfg":1,"seed":-1,"duration":4,"audio":True}
DIRECTOR_NODES = ["MiniMaxH3Director", "MiniMaxH3DirectorGroupReferenceToVideo", "MiniMaxH3DirectorGroupImageToVideo"]
MODEL_FIELDS = {"fl2va": ("UNETLoader", "unet_name"), "ref2va": ("UNETLoader", "unet_name"),
                "clip": ("CLIPLoader", "clip_name"), "video_vae": ("VAELoader", "vae_name"), "audio_vae": ("VAELoader", "vae_name")}
REQUIRED = ["UNETLoader","CLIPLoader","VAELoader","MiniMaxH3ImageToVideo","MiniMaxH3ReferenceToVideo","MiniMaxH3SigmaShift","KSampler","ConditioningZeroOut","LTXVSeparateAVLatent","VAEDecodeTiled","VAEDecodeAudio","CreateVideo","SaveVideo","LoadImage","LoadAudio","LoadVideo","GetVideoComponents","ImageScaleToMaxDimension"]

def compatible_model(role, filename):
    name=filename.lower()
    return "h3" in name and any(token in name for token in {
        "fl2va":("fl2va","hybrid"), "ref2va":("ref2va","hybrid"),
        "clip":("qwen",), "video_vae":("video",), "audio_vae":("audio",),
    }[role])

def normalize_video(payload, base):
    clean = deepcopy(payload)
    clean.pop("kind", None)
    clean["workflow_id"] = payload.get("workflow_id", PROFILE_ID)
    clean["result_policy"] = payload.get("result_policy", "review")
    request = base(clean)
    mode = payload.get("video_mode", "text")
    duration = payload.get("duration", 4)
    if mode not in MODES or isinstance(duration,bool) or not isinstance(duration,int) or not 4 <= duration <= 15:
        raise DomainError(422,"视频模式或时长无效，时长须为 4–15 秒整数。","video_parameters_invalid")
    if request.get("mask_version_id"):
        raise DomainError(422,"H3 视频模板不支持图片蒙版。","video_mask_unsupported")
    if request["workflow_id"] != PROFILE_ID:
        raise DomainError(422,"请选择本地 H3 工作流。","video_workflow_invalid")
    if payload.get("provider","comfyui") != "comfyui":
        raise DomainError(422,"当前工作流在本地 ComfyUI 执行，不会自动上传云端。","video_provider_unconfigured")
    if not isinstance(payload.get("audio", True), bool):
        raise DomainError(422,"声音选项须为布尔值。","video_parameters_invalid")
    request.update(kind="video",video_mode=mode,duration=duration,audio=payload.get("audio",True))
    request["video_options"] = normalize_options(payload.get("video_options", {}))
    defaults = {"width":864,"height":480,"steps":20,"cfg":1,"seed":-1,"denoise":1}
    defaults.update(request["parameters"])
    if any(not 256 <= defaults[k] <= 1344 or defaults[k]%32 for k in ("width","height")) or defaults["width"]*defaults["height"] > 1344*768:
        raise DomainError(422,"本地 H3 尺寸须为 32 的倍数，范围 256–1344，面积不超过 1344×768。","video_dimensions_invalid")
    if not 1 <= defaults["steps"] <= 100 or not 0 <= defaults["cfg"] <= 20 or defaults["denoise"] != 1:
        raise DomainError(422,"视频步数为 1–100，CFG 为 0–20；当前模板使用完整采样。","video_parameters_invalid")
    request["parameters"] = defaults
    roles=[]
    for index,(ref,raw) in enumerate(zip(request["references"],payload.get("references",[]))):
        ref.setdefault("id",f"ref-{index+1}")
        ref["role"]=raw.get("role","reference")
        if ref["role"] not in ("reference","first_frame","last_frame"):
            raise DomainError(422,"未知的参考素材用途。","video_reference_role")
        roles.append(ref["role"])
    normalize_inputs(request, payload.get("references", []))
    roles = [ref["role"] for ref in request["references"]]
    if mode=="text" and roles or mode=="frames" and (not roles or len(roles)>2 or "reference" in roles or len(set(roles))!=len(roles)) or mode=="reference" and (not roles or any(r!="reference" for r in roles)):
        raise DomainError(422,"文生视频无需素材；首尾帧分别最多一张；全参考模式需要参考素材。","video_reference_roles")
    if len(request["references"])>12:
        raise DomainError(422,"H3 全参考最多 12 个素材。","video_reference_count")
    return request

class H3Adapter:
    def __init__(self, store, workflows):
        self.store,self.workflows=store,workflows
        with store.tx():
            store.conn.execute("CREATE TABLE IF NOT EXISTS video_settings(id INTEGER PRIMARY KEY,revision INTEGER NOT NULL,settings TEXT NOT NULL)")
            store.conn.execute("INSERT OR IGNORE INTO video_settings(id,revision,settings) VALUES(1,1,'{}')")
            if "defaults" not in {row[1] for row in store.conn.execute("PRAGMA table_info(video_settings)")}:
                store.conn.execute("ALTER TABLE video_settings ADD COLUMN defaults TEXT NOT NULL DEFAULT '{}'")
            if "pipeline_revision" not in {row[1] for row in store.conn.execute("PRAGMA table_info(video_settings)")}:
                store.conn.execute("ALTER TABLE video_settings ADD COLUMN pipeline_revision INTEGER NOT NULL DEFAULT 2")
                row=store.conn.execute("SELECT defaults FROM video_settings WHERE id=1").fetchone()
                saved=json.loads(row[0])
                # Only migrate the old shipped preset. Preserve non-default tuning and old job snapshots.
                if saved.get("cfg")==4 and saved.get("steps",20)==20:
                    saved["cfg"]=1
                    store.conn.execute("UPDATE video_settings SET defaults=?,revision=revision+1 WHERE id=1",(encode(saved),))

    def settings(self):
        with self.store.lock:
            row=self.store.conn.execute("SELECT * FROM video_settings WHERE id=1").fetchone()
            return {"revision":row["revision"],"models":json.loads(row["settings"]),"defaults":{**DEFAULTS,**json.loads(row["defaults"])}}

    def update(self,payload):
        models=payload.get("models")
        if not isinstance(models,dict) or set(models)-MODEL_FIELDS.keys() or any(not isinstance(v,str) or not v or len(v)>400 for v in models.values()):
            raise DomainError(422,"模型配置格式无效。","video_models_invalid")
        with self.store.tx():
            current=self.settings()
            if payload.get("revision")!=current["revision"]:
                raise DomainError(409,"模型配置已更新，请刷新后重试。","revision_conflict")
            defaults=payload.get("defaults",current["defaults"])
            if not isinstance(defaults,dict) or set(defaults)-DEFAULTS.keys():
                raise DomainError(422,"默认视频参数格式无效。","video_defaults_invalid")
            defaults={**DEFAULTS,**defaults}
            for key in ("width","height","steps","seed","duration"):
                if type(defaults[key]) is not int:
                    raise DomainError(422,"尺寸、步数、种子和时长须为整数。","video_defaults_invalid")
            if (type(defaults["audio"]) is not bool or type(defaults["cfg"]) not in (int,float)
                or not 0<=defaults["cfg"]<=20 or not 1<=defaults["steps"]<=100
                or not -1<=defaults["seed"]<=9007199254740991 or not 4<=defaults["duration"]<=15
                or any(not 256<=defaults[k]<=1344 or defaults[k]%32 for k in ("width","height"))
                or defaults["width"]*defaults["height"]>1344*768):
                raise DomainError(422,"默认参数超出本地 H3 支持范围。","video_defaults_invalid")
            self.store.conn.execute("UPDATE video_settings SET settings=?,defaults=?,revision=revision+1 WHERE id=1",(encode(models),encode(defaults)))
        return self.status()

    def status(self):
        saved=self.settings()
        try: catalog=self.workflows.object_info()
        except Exception:
            return {**saved,"ready":False,"errors":["ComfyUI 尚未连接，请先启动本地服务。"],"catalog":{},"profile_id":PROFILE_ID}
        options={}
        for key,(node,field) in MODEL_FIELDS.items():
            spec=catalog.get(node,{}).get("input",{}).get("required",{}).get(field,[[]])[0]
            options[key]=spec if isinstance(spec,list) else []
        def pick(key,need,preferred):
            names=[n for n in options[key] if need(n.lower())]
            return next((n for p in preferred for n in names if p in n.lower()),names[0] if names else "")
        defaults={
            "fl2va":pick("fl2va",lambda n:"h3" in n and ("fl2va" in n or "hybrid" in n),["fl2va_pruned","hybrid"]),
            "ref2va":pick("ref2va",lambda n:"h3" in n and ("ref2va" in n or "hybrid" in n),["hybrid_fl2va_ref2va","ref2va"]),
            "clip":pick("clip",lambda n:"h3" in n and "qwen" in n,["nvfp4","int8"]),
            "video_vae":pick("video_vae",lambda n:"h3" in n and "video" in n,["int8","fp16"]),
            "audio_vae":pick("audio_vae",lambda n:"h3" in n and "audio" in n,["fp32"]),
        }
        models={**defaults,**saved["models"]}
        errors=[f"缺少节点：{name}" for name in REQUIRED if name not in catalog]
        errors.extend(f"缺少模型或用途不匹配：{key}" for key in MODEL_FIELDS if models[key] not in options[key] or not compatible_model(key,models[key]))
        director_errors=[f"缺少节点：{name}" for name in DIRECTOR_NODES if name not in catalog]
        return {**saved,"models":models,"catalog":options,"ready":not errors,"errors":errors,"profile_id":PROFILE_ID,
                "video_options":VIDEO_OPTIONS,"pipeline_revision":2,"engines":{"native":{"ready":not errors,"errors":errors},"director":{"ready":not errors and not director_errors,"errors":errors+director_errors}},
                "modes":list(MODES),"limits":{"images":9,"videos":3,"audios":3,"total":12,"duration_min":4,"duration_max":15,"fps":24}}

    def snapshot(self,options=None):
        status=self.status()
        if not status["ready"]: raise DomainError(422,"本地 H3 尚未就绪。","video_not_ready",errors=status["errors"])
        options=normalize_options(options or {})
        if not status["engines"][options["engine"]]["ready"]:
            raise DomainError(422,"所选 H3 流程尚未就绪。","video_not_ready",errors=status["engines"][options["engine"]]["errors"])
        return {"id":PROFILE_ID,"name":"MiniMax H3 · 本地音视频","mode":"video","models":status["models"],"revision":status["revision"],"pipeline_revision":2,"video_options":options,"defaults":status["defaults"],"bindings":{"seed":[{}]},"capabilities":{"min_images":0,"max_images":12},"output_nodes":["save"],"kind":"video"}

    def library_entry(self):
        return {**self.status(),"id":PROFILE_ID,"name":"MiniMax H3 · 本地音视频","kind":"video","mode":"video","builtin":True}

    def template(self,mode,engine="native"):
        if mode not in MODES:
            raise DomainError(422,"未知的视频模式。","video_parameters_invalid")
        profile=self.status()
        models={key:profile["models"].get(key) or f"<请选择 {key} 模型>" for key in MODEL_FIELDS}
        refs=[]
        if mode=="frames":
            refs=[{"version_id":role,"media_type":"image","role":role} for role in ("first_frame","last_frame")]
        elif mode=="reference":
            refs=[{"version_id":kind,"media_type":kind,"role":"reference"} for kind in ("image","video","audio")]
        defaults=profile["defaults"]
        request={"video_mode":mode,"video_options":normalize_options({"engine":engine}),"compiled_prompt":"在此输入视频描述","duration":defaults["duration"],"audio":defaults["audio"],
                 "parameters":{k:defaults[k] for k in ("width","height","steps","cfg","seed")},"references":refs}
        request["parameters"]["seed"]=max(0,request["parameters"]["seed"])
        files={ref["version_id"]:"REPLACE_"+ref["version_id"]+{"image":".png","video":".mp4","audio":".wav"}[ref["media_type"]] for ref in refs}
        result=self.build_graph({"id":"workflow-preview","request":request,"workflow_snapshot":{"models":models}},files)
        return {**result,"mode":mode,"revision":profile["revision"],"template":True,"placeholder_files":list(files.values())}

    def input_version(self,version_id):
        version=self.store.version(version_id)
        if version["missing"] or not version["mime"].split("/")[0] in ("image","video","audio"):
            raise DomainError(422,"参考素材缺失或类型不支持。","video_reference_missing",version_id=version_id)
        if self.store.asset(version["asset_id"],details=False)["deleted_at"]:
            raise DomainError(409,"请先恢复回收站中的参考素材。","asset_trashed")
        if version["size"]>512*1024**2:
            raise DomainError(413,"单个参考素材最大 512 MiB。","video_reference_too_large")
        return version

    def compile_prompt(self,request):
        counters={"image":0,"video":0,"audio":0};seconds={"video":0,"audio":0};slots={}
        for ref in request["references"]:
            v=self.input_version(ref["version_id"]);kind=v["mime"].split("/")[0]
            if request["video_mode"]=="frames" and kind!="image":
                raise DomainError(422,"首尾帧只接受图片。","video_reference_type")
            counters[kind]+=1
            if counters[kind]>{"image":9,"video":3,"audio":3}[kind]:
                raise DomainError(422,"参考图片最多9张，视频和音频分别最多3段。","video_reference_count")
            if kind!="image":
                total=v.get("duration");start=ref.get("clip_start",0);end=ref.get("clip_end")
                if total is None:raise DomainError(422,"无法读取参考片段时长。","video_reference_duration")
                end=total if end is None else end
                duration=end-start
                if start>=end or end>total+.05 or not 2<=duration<=15.05:
                    raise DomainError(422,"请选择原素材范围内的 2–15 秒片段。","video_reference_duration")
                # Native H3 truncates videos at output frame count; require an explicit shorter selection instead.
                frame_duration=(math.ceil((request["duration"]*24-5)/17)*17+5)/24
                if kind=="video" and duration>frame_duration+.05:
                    raise DomainError(422,"参考视频片段比生成时长更长，请缩短片段或增加生成时长。","video_reference_clip_too_long")
                ref["clip_end"]=end
                if kind=="video" and ref.get("use_audio") and not has_audio(Path(v["path"])):
                    raise DomainError(422,"该参考视频没有声音轨道，请关闭参考原声。","video_reference_audio_missing")
                seconds[kind]+=duration
                if seconds[kind]>15.05:raise DomainError(422,"参考视频、参考音频的各自总时长不得超过15秒。","video_reference_duration")
            ref["media_type"]=kind
            slots[ref["id"]]=f"<{ {'image':'Picture','video':'Video','audio':'Audio'}[kind]} {counters[kind]}>" if request["video_mode"]=="reference" else ("首帧" if ref["role"]=="first_frame" else "尾帧")
        if request["video_mode"]=="reference":
            # Comfy orders video soundtracks BEFORE standalone audios, regardless of UI ordering.
            offset=sum(r["media_type"]=="video" and r.get("use_audio",False) for r in request["references"])
            if request.get("video_options",{}).get("engine")=="director" and offset+counters["audio"]>3:
                raise DomainError(422,"Director 最多映射 3 个声音槽位（含视频原声）；请减少声音参考，或切换原生基线。","director_audio_slots_exceeded")
            audio_index=0
            for ref in request["references"]:
                if ref["media_type"]=="audio":
                    audio_index+=1;slots[ref["id"]]=f"<Audio {offset+audio_index}>"
        parts=request.get("prompt_parts")
        if parts is None:
            prompt=request["prompt"]
            for ref in sorted(request["references"],key=lambda r:len(r.get("title","")),reverse=True):
                if ref.get("title"):prompt=prompt.replace("@"+ref["title"],slots[ref["id"]])
        else:prompt="".join(p["text"] if p["type"]=="text" else slots[p["reference_id"]] for p in parts)
        settings=[slots[r["id"]]+" 的设定："+r["description"] for r in request["references"] if r.get("use_description") and r.get("description")]
        intents={"identity":"只参考人物外貌、服装与身份；画面中是同一个角色，不复制参考图的多视图排版或背景。", "composition":"参考构图和场景布局。", "motion":"参考动作节奏和镜头运动。", "voice":"Use this audio only for speaker identity and vocal timbre. Speak the NEW dialogue specified in the current scene. Emotion, pace, pauses and delivery must follow the current scene. Do not copy the reference words, rhythm, performance or background sound."}
        settings.extend(slots[r["id"]]+"："+intents[r["purpose"]] for r in request["references"] if r.get("purpose") in intents)
        for ref in request["references"]:
            if ref.get("purpose") == "voice" and ref["media_type"] == "audio" and ref.get("node_id"):
                portrait = next((image for image in request["references"] if image["media_type"] == "image" and image.get("node_id") == ref["node_id"]), None)
                if portrait:
                    settings.append(slots[ref["id"]] + " provides the voice identity of the character shown in " + slots[portrait["id"]] + ".")
        request["reference_slots"]=slots
        return prompt+("\n"+"\n".join(settings) if settings else "")

    def prepare(self,job,files):
        r=job["request"];m=job["workflow_snapshot"]["models"];p=r["parameters"]
        catalog=self.workflows.object_info()
        for key,(node,field) in MODEL_FIELDS.items():
            if key=="ref2va" and r["video_mode"]!="reference" or key=="fl2va" and r["video_mode"]=="reference":continue
            if m[key] not in catalog.get(node,{}).get("input",{}).get("required",{}).get(field,[[]])[0]:
                raise DomainError(422,f"任务快照中的模型已不可用：{key}","video_model_missing")
        return self.build_graph(job,files)

    @staticmethod
    def build_graph(job,files):
        r=job["request"];m=job["workflow_snapshot"]["models"];p=r["parameters"]
        options=normalize_options(r.get("video_options",{}))
        length=math.ceil((r["duration"]*24-5)/17)*17+5
        def node(kind,**inputs):return {"class_type":kind,"inputs":inputs}
        graph={
          "model":node("UNETLoader",unet_name=m["ref2va" if r["video_mode"]=="reference" else "fl2va"],weight_dtype="default"),
          "clip":node("CLIPLoader",clip_name=m["clip"],type="minimax",device="default"),
          "vvae":node("VAELoader",vae_name=m["video_vae"]),
          "avae":node("VAELoader",vae_name=m["audio_vae"]),
          "condition":node("MiniMaxH3ReferenceToVideo" if r["video_mode"]=="reference" else "MiniMaxH3ImageToVideo",clip=["clip",0],vae=["vvae",0],prompt=r["compiled_prompt"],width=p["width"],height=p["height"],length=length),
          "negative":node("ConditioningZeroOut",conditioning=["condition",0]),
          "shift":node("MiniMaxH3SigmaShift",model=["model",0],shift_video=12.0,shift_audio=3.0),
          "sample":node("KSampler",model=["shift",0],positive=["condition",0],negative=["negative",0],latent_image=["condition",1],seed=p["seed"],steps=p["steps"],cfg=p["cfg"],sampler_name=options["sampler"],scheduler=options["scheduler"],denoise=1.0),
          "split":node("LTXVSeparateAVLatent",av_latent=["sample",0]),
          "decode":node("VAEDecodeTiled",samples=["split",0],vae=["vvae",0],tile_size=256,overlap=64,temporal_size=32,temporal_overlap=8),
          "audio":node("VAEDecodeAudio",samples=["split",1],vae=["avae",0]),
          "video":node("CreateVideo",images=["decode",0],fps=24.0,**({"audio":["audio",0]} if r["audio"] else {})),
          "save":node("SaveVideo",video=["video",0],filename_prefix="Manju/"+job["id"],format="mp4",**{"format.codec":"h264"}),
        }
        if r["video_mode"]=="reference":
            graph["condition"]["inputs"].update(audio_vae=["avae",0],ref_image_size="match" if options["ref_image_size"]=="match" else "max")
        counters={"image":0,"audio":0,"video":0}
        for ref in r["references"]:
            kind=ref["media_type"];counters[kind]+=1;n=counters[kind];key=f"input_{kind}_{n}"
            filename=files.get(ref.get("id")) or files[ref["version_id"]]
            if kind=="image":
                graph[key]=node("LoadImage",image=filename);link=[key,0]
                if r["video_mode"]=="reference" and options["ref_image_size"].isdigit():
                    graph[key+"_size"]=node("ImageScaleToMaxDimension",image=link,upscale_method="lanczos",largest_size=int(options["ref_image_size"]))
                    link=[key+"_size",0]
            elif kind=="audio":graph[key]=node("LoadAudio",audio=filename);link=[key,0]
            else:
                # A normalized 24fps copy preserves video/audio temporal correspondence.
                graph[key]=node("LoadVideo",file=filename)
                graph[key+"_parts"]=node("GetVideoComponents",video=[key,0]);link=[key+"_parts",0]
                if ref.get("use_audio"):
                    graph["condition"]["inputs"][f"ref_video_audios.ref_video_audio_{n}"]=[key+"_parts",1]
            if r["video_mode"]=="frames":
                graph["condition"]["inputs"][ref["role"]]=link
            else:graph["condition"]["inputs"][f"ref_{'images' if kind=='image' else 'videos' if kind=='video' else 'audios'}.ref_{kind}_{n}"]=link
        if options["engine"]=="director":
            from .video_director import director_graph
            graph=director_graph(graph,r,options,length)
        return {"api_graph":graph,"parameters":{**p,**options,"frame_count":length,"fps":24,"actual_duration":length/24},"output_nodes":["save"]}
