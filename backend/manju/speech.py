"""Local character speech, using the shared ComfyUI queue and asset delivery."""
from copy import deepcopy
import json
import math
import re
from .store import DomainError, encode

PROFILE_ID = "builtin-indextts25-local"
ENGINE = "IndexTTS-2.5"
NODE = "ManjuIndexTTS25"
DEFAULTS = {"language":"zh", "speed":1.0, "emotion":"reference", "intensity":0.5,
            "use_emo_text":False,"emo_text":"","pronunciation":"","interval_silence":200,"quality":"studio","temperature":0.8}
EMOTIONS = ("reference","neutral","happy","angry","sad","afraid","disgusted","melancholic","surprised","calm")


def pronunciation_entries(value):
    if not isinstance(value,str) or len(value)>4000:
        raise DomainError(422,"发音表最多 4000 字，每行使用“词语=带声调拼音”。","speech_pronunciation_invalid")
    entries={}
    for line in value.splitlines():
        line=line.strip()
        if not line or line.startswith('#'):continue
        if '=' not in line:
            raise DomainError(422,"发音表每行须为“末班车=MO4 BAN1 CHE1”格式。","speech_pronunciation_invalid")
        word,pronunciation=(part.strip() for part in line.split('=',1))
        syllables=pronunciation.upper().replace('Ü','V').split()
        if not re.fullmatch(r'[\u3400-\u9fff]{1,40}',word) or len(syllables)!=len(word) or any(not re.fullmatch(r'[A-ZV]{1,8}[1-5]',p) for p in syllables) or word in entries:
            raise DomainError(422,"发音表须使用不重复的中文词语，每个字对应一个 1–5 声调的拼音。","speech_pronunciation_invalid")
        entries[word]=' '.join(syllables)
    if len(entries)>100:raise DomainError(422,"发音表最多 100 个词语。","speech_pronunciation_invalid")
    return entries


def compile_pronunciation(dialogue,pronunciation):
    entries=pronunciation_entries(pronunciation)
    if not entries:return dialogue
    pattern=re.compile('|'.join(re.escape(word) for word in sorted(entries,key=len,reverse=True)))
    # Keep existing explicit IndexTTS annotations intact and never rewrite the
    # user's original dialogue, which remains available for subtitles/history.
    return ''.join(part if re.fullmatch(r'<[^<>]*\|[^<>]*>',part) else pattern.sub(lambda m:f'<{m[0]}|{entries[m[0]]}>',part)
                   for part in re.split(r'(<[^<>]*\|[^<>]*>)',dialogue))


def normalize_options(raw):
    if not isinstance(raw,dict) or set(raw)-DEFAULTS.keys():
        raise DomainError(422,"配音参数格式无效。","speech_parameters_invalid")
    options={**DEFAULTS,**raw}
    def bounded(key,low,high):
        value=options[key]
        return type(value) in (float,int) and math.isfinite(value) and low<=value<=high
    if (options['language'] not in ('zh','en','ja','es','ar') or options['emotion'] not in EMOTIONS
        or not bounded('speed',.5,2) or not bounded('intensity',0,.8) or not bounded('temperature',.5,1.2)
        or not bounded('interval_silence',0,1500) or options['quality'] not in ('standard','studio')
        or not isinstance(options['use_emo_text'],bool) or not isinstance(options['emo_text'],str) or len(options['emo_text'])>1000):
        raise DomainError(422,"语言、情绪、语速、停顿或采样参数超出支持范围。","speech_parameters_invalid")
    options['emo_text']=options['emo_text'].strip()
    options['interval_silence']=round(options['interval_silence'])
    if options['use_emo_text'] and not options['emo_text']:
        raise DomainError(422,"请填写情绪演绎指导。","speech_emotion_text_required")
    pronunciation_entries(options['pronunciation'])
    if options['pronunciation'].strip() and options['language']!='zh':
        raise DomainError(422,"当前发音表用于中文台词。","speech_pronunciation_language")
    return options


def normalize_speech(payload, base):
    clean=deepcopy(payload);clean.pop("kind",None)
    clean["workflow_id"]=payload.get("workflow_id",PROFILE_ID)
    clean["result_policy"]=payload.get("result_policy","review")
    request=base(clean)
    if request["workflow_id"]!=PROFILE_ID or payload.get("provider","comfyui")!="comfyui":
        raise DomainError(422,"请选择本地 IndexTTS 配音工作流。","speech_workflow_invalid")
    if request.get("mask_version_id") or len(request["references"])>2 or set(request["parameters"])-{"seed"}:
        raise DomainError(422,"配音接受一份音色、一份可选情绪参考和随机种子。","speech_parameters_invalid")
    if len(request["prompt"].strip())>2000:
        raise DomainError(422,"单次配音台词最多 2000 字，请按镜头拆分。","speech_text_too_long")
    options=normalize_options(payload.get("speech_options",{}))
    roles=set()
    for index,(raw,ref) in enumerate(zip(payload.get('references',[]),request['references'])):
        role=raw.get('role')
        if not role or role in ('reference','generic'):role='voice' if index==0 else 'emotion'
        if role not in ('voice','emotion') or role in roles:
            raise DomainError(422,"请分别选择一份角色音色和一份情绪参考。","speech_reference_role")
        roles.add(role);ref.update(role=role,media_type='audio',id=ref.get('id') or raw.get('id') or role)
    request['references'].sort(key=lambda ref:ref['role']!='voice')
    if options['use_emo_text'] and 'emotion' in roles:
        raise DomainError(422,"情绪文字与情绪参考音频不能同时使用，请选择一种方式。","speech_emotion_conflict")
    subject=payload.get("subject_node_id")
    if subject is not None and (not isinstance(subject,str) or not subject or len(subject)>200):
        raise DomainError(422,"人物主体标识无效。","speech_subject_invalid")
    if 'voice' not in roles and not subject:
        raise DomainError(422,"请选择已绑定音色的人物，或添加一份参考音频。","speech_voice_required")
    # @ denotes a voice selection, never text to read aloud.
    parts=request.get("prompt_parts")
    text="".join(p["text"] for p in parts if p["type"]=="text").strip() if parts is not None else request["prompt"].strip()
    if not text:raise DomainError(422,"请填写需要朗读的台词。","speech_text_required")
    if len(text)>2000:raise DomainError(422,"单次配音台词最多 2000 字，请按镜头拆分。","speech_text_too_long")
    request.update(kind="audio",speech_options=options,subject_node_id=subject,dialogue_text=text,compiled_prompt=compile_pronunciation(text,options['pronunciation']))
    return request


class SpeechAdapter:
    def __init__(self,store,workflows):
        self.store,self.workflows=store,workflows
        with store.tx():
            store.conn.execute("CREATE TABLE IF NOT EXISTS speech_settings(id INTEGER PRIMARY KEY, revision INTEGER NOT NULL, defaults_json TEXT NOT NULL)")
            store.conn.execute("INSERT OR IGNORE INTO speech_settings VALUES(1,1,?)",(encode(DEFAULTS),))

    def settings(self):
        with self.store.lock:
            row=self.store.conn.execute("SELECT * FROM speech_settings WHERE id=1").fetchone()
            return {"revision":row["revision"],"defaults":normalize_options(json.loads(row["defaults_json"]))}

    def update(self,payload):
        from .generation import GenerationService
        defaults=normalize_speech({"project_id":"validate","prompt":"校验","subject_node_id":"voice","speech_options":payload.get("defaults"),"parameters":{}},GenerationService._validate_request)["speech_options"]
        with self.store.tx():
            if payload.get("revision")!=self.settings()["revision"]:raise DomainError(409,"配音设置已更新，请刷新后重试。","revision_conflict")
            self.store.conn.execute("UPDATE speech_settings SET revision=revision+1,defaults_json=? WHERE id=1",(encode(defaults),))
        return self.status()

    def status(self):
        errors=[]
        try:catalog=self.workflows.object_info()
        except Exception:catalog={};errors.append("ComfyUI 尚未连接。")
        for name in (NODE,"LoadAudio","SaveAudio"):
            if name not in catalog:errors.append(f"缺少节点：{name}")
        choices=catalog.get(NODE,{}).get("input",{}).get("required",{}).get("model",[[]])[0]
        if ENGINE not in choices:errors.append("IndexTTS 本地运行环境或模型尚未安装完整。")
        inputs=catalog.get(NODE,{}).get('input',{})
        optional=inputs.get('optional',{})
        emotion_text=optional.get('use_emo_text',[[]])[0]
        capabilities={'emotion_text':isinstance(emotion_text,list) and True in emotion_text,
                      'emotion_reference':'emotion_audio' in optional,'pronunciation':'quality' in optional,
                      'studio_quality':'quality' in optional,'interval_silence':'interval_silence' in optional,
                      'temperature':'temperature' in optional}
        return {"id":PROFILE_ID,"kind":"audio","mode":"audio","builtin":True,**self.settings(),"name":"IndexTTS 2.5 · 人物配音","ready":not errors,"errors":errors,"languages":["zh","en","ja","es","ar"],"emotions":list(EMOTIONS),'capabilities':capabilities}

    def snapshot(self):
        status=self.status()
        if not status["ready"]:raise DomainError(422,"本地配音尚未就绪。","speech_not_ready",errors=status["errors"])
        return {**status,"bindings":{"seed":[{}]},"capabilities":{**status['capabilities'],"min_images":1,"max_images":2},"output_nodes":["save"]}

    def configure(self,request,payload,workflow):
        options=normalize_options({**workflow.get('defaults',{}),**payload.get('speech_options',{})})
        if options['use_emo_text'] and any(ref['role']=='emotion' for ref in request['references']):
            raise DomainError(422,"情绪文字与情绪音频不能同时使用，请选择一种方式。","speech_emotion_conflict")
        capabilities=workflow.get('capabilities',{})
        if options['use_emo_text'] and not capabilities.get('emotion_text'):
            raise DomainError(422,"情绪文字需要本地 QwenEmotion 模型与新版配音节点，请先安装后刷新。","speech_emotion_model_missing")
        if any(ref['role']=='emotion' for ref in request['references']) and not capabilities.get('emotion_reference'):
            raise DomainError(422,"请更新本地配音节点以支持独立情绪参考。","speech_node_upgrade_required")
        # Legacy Comfy nodes can still execute old drafts with their original
        # 25-step defaults. New controls must never silently do nothing.
        explicit=payload.get('speech_options',{})
        if not capabilities.get('studio_quality'):
            if explicit.get('quality','standard')!='standard' or explicit.get('temperature',.8)!=.8 or explicit.get('interval_silence',200)!=200 or explicit.get('pronunciation','').strip():
                raise DomainError(422,"请更新本地配音节点后使用质量、停顿或发音控制。","speech_node_upgrade_required")
            options['quality']='standard'
        request['speech_options']=options
        request['compiled_prompt']=compile_pronunciation(request['dialogue_text'],options['pronunciation'])

    def bind_subject(self,request,nodes):
        subject=nodes.get(request.get("subject_node_id"),{}).get("data",{}).get("subject")
        if not any(ref['role']=='voice' for ref in request['references']):
            if not subject or subject.get("kind")!="character" or not subject.get("voice_version_id"):
                raise DomainError(422,"所选人物尚未绑定音色，请先添加参考音频。","speech_voice_required")
            identity='voice' if all(ref.get('id')!='voice' for ref in request['references']) else 'speaker-voice'
            request["references"].insert(0,{"id":identity,"role":"voice","version_id":subject["voice_version_id"],"node_id":request["subject_node_id"],"title":subject["name"],"media_type":"audio"})
        if subject and subject.get("voice_version_id")==request["references"][0]["version_id"]:
            request["speaker_snapshot"]={k:subject.get(k) for k in ("name","voice_version_id","voice_name","voice_transcript","library_id")}
        for ref in request['references']:
            ref['media_type']='audio'
            self.input_version(ref['version_id'])

    def input_version(self,version_id):
        v=self.store.version(version_id)
        if v["missing"] or not v["mime"].startswith("audio/"):
            raise DomainError(422,"音色参考必须是可读取的音频原件。","speech_voice_invalid")
        if self.store.asset(v["asset_id"],details=False)["deleted_at"]:
            raise DomainError(409,"请先恢复回收站中的音色参考。","asset_trashed")
        if v["size"]>64*1024**2 or v.get("duration") is None or not 2<=v["duration"]<=30:
            raise DomainError(422,"音色参考需为 2–30 秒、64 MiB 以内的单人清晰语音。","speech_voice_duration")
        return v

    @staticmethod
    def prepare(job,files):
        r=job["request"];o=normalize_options(r["speech_options"])
        refs=r.get('references',[])
        voice=next((ref for ref in refs if ref.get('role','voice')=='voice'),None)
        graph={"voice":{"class_type":"LoadAudio","inputs":{"audio":files[voice['version_id']] if voice else next(iter(files.values()))}},
               "speech":{"class_type":NODE,"inputs":{"model":ENGINE,"reference_audio":["voice",0],"text":r["compiled_prompt"],"language":o["language"],"speed":o["speed"],"emotion":o["emotion"],"intensity":o["intensity"],"seed":r["parameters"]["seed"]}},
               "save":{"class_type":"SaveAudio","inputs":{"audio":["speech",0],"filename_prefix":"Manju/"+job["id"]}}}
        features=job.get('workflow_snapshot',{}).get('capabilities',{})
        if features.get('studio_quality',True):
            graph['speech']['inputs'].update({key:o[key] for key in ('use_emo_text','emo_text','interval_silence','quality','temperature')})
        emotion=next((ref for ref in refs if ref.get('role')=='emotion'),None)
        if emotion:
            graph['emotion']={'class_type':'LoadAudio','inputs':{'audio':files[emotion['version_id']]}}
            graph['speech']['inputs']['emotion_audio']=['emotion',0]
        return {"api_graph":graph,"parameters":{**o,**r["parameters"]},"output_nodes":["save"]}

    def template(self):
        options=self.settings()['defaults']
        request={"speech_options":options,"compiled_prompt":compile_pronunciation("你好，我们开始今天的故事吧。",options['pronunciation']),"parameters":{"seed":0}}
        return self.prepare({"id":"speech-template","request":request,'workflow_snapshot':{'capabilities':self.status()['capabilities']}},{"voice":"REPLACE_VOICE.wav"})
