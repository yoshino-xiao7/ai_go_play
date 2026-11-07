"""Audio-driven local lip synchronization, using the durable generation queue."""
from copy import deepcopy
import math
from .store import DomainError

PROFILE_ID = 'builtin-latentsync15-local'
NODE = 'ManjuLatentSync15'
ENGINE = 'LatentSync-1.5'
DEFAULTS = {'audio_offset': 0, 'video_start': 0, 'duration': None, 'face_mode': 'auto', 'face_box': None}


def normalize_lipsync(payload, base):
    clean = deepcopy(payload)
    clean.pop('kind', None)
    clean['prompt'] = payload.get('prompt') or '按配音同步人物口型'
    clean['workflow_id'] = PROFILE_ID
    request = base(clean)
    if request.get('mask_version_id') or payload.get('provider', 'comfyui') != 'comfyui':
        raise DomainError(422, '口型同步使用本地视频与配音，不接受图片蒙版。', 'lipsync_parameters_invalid')
    raw = payload.get('lip_sync_options', {})
    if not isinstance(raw, dict) or set(raw) - DEFAULTS.keys():
        raise DomainError(422, '口型参数格式无效。', 'lipsync_parameters_invalid')
    options = {**DEFAULTS, **raw}
    for key, upper in [('audio_offset', 120), ('video_start', 86400), ('duration', 120)]:
        value = options[key]
        if key == 'duration' and value is None:
            continue
        if isinstance(value, bool) or not isinstance(value, (int,float)) or not math.isfinite(value) or not 0 <= value <= upper or key == 'duration' and value < .2:
            raise DomainError(422, '口型片段时间超出范围。', 'lipsync_parameters_invalid')
    if options['face_mode'] not in ('auto', 'manual'):
        raise DomainError(422, '人脸定位须选择自动或手工框选。', 'lipsync_face_invalid')
    box = options['face_box']
    if options['face_mode'] == 'manual':
        if not isinstance(box, list) or len(box) != 4 or any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) for v in box) or min(box) < 0 or min(box[2:]) < 40:
            raise DomainError(422, '请框选至少 40×40 像素的人脸区域。', 'lipsync_face_invalid')
    else:
        options['face_box'] = None
    parameters = {'steps': 20, 'cfg': 1.5, 'seed': -1, **request['parameters']}
    if set(parameters)-{'steps','cfg','seed'} or not 10 <= parameters['steps'] <= 50 or not 1 <= parameters['cfg'] <= 3:
        raise DomainError(422, '口型采样为 10–50 步，同步强度为 1–3。', 'lipsync_parameters_invalid')
    if len(request['references']) != 2:
        raise DomainError(422, '口型同步需要一段视频和一段配音。', 'lipsync_inputs_invalid')
    roles=[]
    for index,(ref,raw_ref) in enumerate(zip(request['references'],payload['references'])):
        role=raw_ref.get('role') or raw_ref.get('media_type')
        if role not in ('video','audio'):
            raise DomainError(422, '口型输入须标明视频和配音用途。', 'lipsync_inputs_invalid')
        ref.update(id=ref.get('id') or role,role=role,media_type=role)
        roles.append(role)
    if set(roles) != {'video','audio'}:
        raise DomainError(422, '口型同步需要不同的视频和配音输入。', 'lipsync_inputs_invalid')
    request.update(kind='video',lip_sync_options=options,parameters=parameters,result_policy=payload.get('result_policy','review'))
    return request


class LipSyncAdapter:
    def __init__(self,store,workflows):
        self.store,self.workflows=store,workflows

    def status(self):
        try: catalog=self.workflows.object_info()
        except Exception: catalog={}
        engines=catalog.get(NODE,{}).get('input',{}).get('required',{}).get('engine',[[]])[0]
        ready=ENGINE in engines
        return {'id':PROFILE_ID,'name':'LatentSync 1.5 · 精确口型','kind':'video','builtin':True,'ready':ready,'errors':[] if ready else ['本地 LatentSync 模型或运行环境尚未就绪。'],'defaults':DEFAULTS,'engine':ENGINE}

    def snapshot(self,options=None):
        status=self.status()
        if not status['ready']:
            raise DomainError(422,'本地口型引擎尚未就绪。','lipsync_not_ready',errors=status['errors'])
        return {**status,'revision':2,'mode':'lip_sync','defaults':{},'bindings':{'seed':[{}]},'capabilities':{'min_images':2,'max_images':2},'output_nodes':['sync']}

    def compile_prompt(self,request):
        versions={}
        for reference in request['references']:
            version=self.store.version(reference['version_id'])
            if version['missing'] or not version['mime'].startswith(reference['role']+'/'):
                raise DomainError(422,'口型输入原件缺失或类型不匹配。','lipsync_inputs_invalid')
            if self.store.asset(version['asset_id'],details=False)['deleted_at']:
                raise DomainError(409,'请先恢复回收站中的口型输入素材。','asset_trashed')
            versions[reference['role']]=version
        options=request['lip_sync_options'];video=versions['video'];audio=versions['audio']
        available=(video.get('duration') or 0)-options['video_start']
        duration=options['duration'] or available
        if not .2 <= duration <= 120 or duration > available+.05:
            raise DomainError(422,'口型片段必须位于原视频范围内，且不超过 120 秒。','lipsync_duration_invalid')
        if not audio.get('duration') or audio['duration']+options['audio_offset'] > duration+.05:
            raise DomainError(422,'配音超过视频片段，请加长片段或先修剪配音。','lipsync_audio_overflow')
        if options['face_mode']=='manual':
            x,y,w,h=options['face_box']
            if x+w > video['width'] or y+h > video['height']:
                raise DomainError(422,'人脸框超出视频尺寸。','lipsync_face_invalid')
        options['duration']=duration
        request['audio']=True
        return request['prompt']

    @staticmethod
    def prepare(job,files):
        request=job['request'];options=request['lip_sync_options']
        roles={ref['role']:files[ref['id']] for ref in request['references']}
        import json
        inputs={'engine':ENGINE,'video':roles['video'],'audio':roles['audio'],
                'audio_offset':options['audio_offset'],'video_start':options['video_start'],'duration':options['duration'],
                'face_mode':options['face_mode'],'face_box':json.dumps(options['face_box']),
                'steps':request['parameters']['steps'],'guidance':request['parameters']['cfg'],'seed':request['parameters']['seed'],
                'filename_prefix':'Manju/'+job['id']}
        return {'api_graph':{'sync':{'class_type':NODE,'inputs':inputs}},'parameters':{**options,**request['parameters']},'output_nodes':['sync']}
