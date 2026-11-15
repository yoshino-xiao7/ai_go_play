"""Check the actual published workflows against a running ComfyUI catalog."""
from .workflows import builtin_workflows
from .video import REQUIRED, DIRECTOR_NODES, MODEL_FIELDS
from . import video_turbo


def choices(nodes, node, field, section='required'):
    spec = nodes.get(node, {}).get('input', {}).get(section, {}).get(field, [[]])
    if spec and isinstance(spec[0], list): return spec[0]
    if len(spec) > 1 and isinstance(spec[1], dict): return spec[1].get('options', [])
    return []


def check_packs(packs, files, nodes):
    required = {
        '01-qwen-image': set(), '02-h3-image': set(),
        '03-h3-video': set(REQUIRED + DIRECTOR_NODES), '04-h3-turbo': set(),
        '05-indextts': {'ManjuIndexTTS25', 'LoadAudio', 'SaveAudio'},
        '06-indextts-emotion': {'ManjuIndexTTS25'},
        '07-latentsync': {'ManjuLatentSync15'},
        '08-video-enhance': {'ManjuVideoEnhance', 'FrameInterpolationModelLoader', 'UpscaleModelLoader'},
    }
    for workflow in builtin_workflows():
        pack = '01-qwen-image' if workflow['id'].startswith('builtin-qwen') else '02-h3-image'
        required[pack].update(node['class_type'] for node in workflow['api_graph'].values())
    loaders = {'diffusion_models': ('UNETLoader', 'unet_name'), 'text_encoders': ('CLIPLoader', 'clip_name'),
               'vae': ('VAELoader', 'vae_name'), 'loras': ('MiniMaxH3TurboLoRA', 'lora_name'),
               'upscale_models': ('UpscaleModelLoader', 'model_name'), 'frame_interpolation': ('FrameInterpolationModelLoader', 'model_name')}
    result = []
    for pack in packs:
        errors = [name for name in sorted(required[pack]) if name not in nodes]
        for item in files:
            if pack not in item['packs']: continue
            category, _, relative = item['path'].partition('/')
            if category not in loaders: continue
            loader, field = loaders[category]
            available = {str(v).replace('\\', '/') for v in choices(nodes, loader, field)}
            if relative not in available:
                errors.append('引擎未识别模型：' + relative)
        if pack == '04-h3-turbo':
            errors.extend(video_turbo.environment_errors(nodes, video_turbo.MODELS, MODEL_FIELDS))
        if pack == '05-indextts' and 'IndexTTS-2.5' not in choices(nodes, 'ManjuIndexTTS25', 'model'):
            errors.append('IndexTTS 模型或环境')
        if pack == '06-indextts-emotion' and True not in choices(nodes, 'ManjuIndexTTS25', 'use_emo_text', 'optional'):
            errors.append('文本情绪模型或环境')
        if pack == '07-latentsync' and 'LatentSync-1.5' not in choices(nodes, 'ManjuLatentSync15', 'engine'):
            errors.append('LatentSync 模型或环境')
        result.append({'pack': pack, 'ready': not errors, 'missing_nodes': list(dict.fromkeys(errors))})
    return result
