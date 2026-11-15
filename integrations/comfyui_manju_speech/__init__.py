"""Manju local voice cloning. Inference runs in an isolated, short-lived process."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time

import numpy as np
import soundfile as sf
import torch
import folder_paths
from comfy import model_management

CONFIG = Path(__file__).with_name('runtime.json')

def runtime():
    try:
        config=json.loads(CONFIG.read_text(encoding='utf-8'))
        manifest=json.loads((Path(config['model_dir'])/'manju-models.json').read_text(encoding='utf-8'))
        if not all((Path(config['model_dir'])/f['path']).stat().st_size==f['size'] for f in manifest['files']):return None
        if not Path(config['python']).is_file() or not Path(config['repo']).is_dir():return None
        return config
    except (OSError,ValueError,KeyError):return None


def emotion_model_ready(config):
    if not config:return False
    if config.get('emotion') is False:return False
    root=Path(config['model_dir'])
    try:
        import yaml
        folder=root/yaml.safe_load((root/'config.yaml').read_text(encoding='utf-8'))['qwen_emo_path']
        return (folder/'config.json').is_file() and (folder/'tokenizer_config.json').is_file() and any(folder.glob('*.safetensors'))
    except (OSError,KeyError,ValueError,TypeError):return False

class ManjuIndexTTS25:
    @classmethod
    def INPUT_TYPES(cls):
        config=runtime()
        return {'required':{'model':(['IndexTTS-2.5'] if config else [],), 'reference_audio':('AUDIO',),
            'text':('STRING',{'multiline':True}), 'language':(['zh','en','ja','es','ar'],),
            'speed':('FLOAT',{'default':1.,'min':.5,'max':2.,'step':.05}),
            'emotion':(['reference','neutral','happy','angry','sad','afraid','disgusted','melancholic','surprised','calm'],),
            'intensity':('FLOAT',{'default':.5,'min':0.,'max':.8,'step':.05}),
            'seed':('INT',{'default':0,'min':0,'max':9007199254740991})},
            'optional':{'emotion_audio':('AUDIO',),
                        'use_emo_text':([False,True] if emotion_model_ready(config) else [False],{'default':False}),
                        'emo_text':('STRING',{'default':'','multiline':True}),
                        'interval_silence':('INT',{'default':200,'min':0,'max':1500,'step':25}),
                        'quality':(['studio','standard'],{'default':'studio'}),
                        'temperature':('FLOAT',{'default':.8,'min':.5,'max':1.2,'step':.05})}}
    RETURN_TYPES=('AUDIO',)
    FUNCTION='generate'
    CATEGORY='Manju/配音'

    def generate(self,model,reference_audio,text,language,speed,emotion,intensity,seed,emotion_audio=None,use_emo_text=False,emo_text='',interval_silence=200,quality='standard',temperature=.8):
        config=runtime()
        if not config:raise RuntimeError('IndexTTS local runtime or model files are incomplete.')
        if not text.strip() or len(text)>16000:raise ValueError('Compiled speech text must contain 1–16000 characters.')
        if use_emo_text and not emotion_model_ready(config):raise RuntimeError('QwenEmotion is not installed in the configured local model directory.')
        if use_emo_text and (not emo_text.strip() or emotion_audio is not None):raise ValueError('Choose emotion text or emotion audio; text guidance must not be empty.')
        if quality not in ('standard','studio') or not 0<=interval_silence<=1500 or not .5<=temperature<=1.2:raise ValueError('Invalid speech quality, interval, or temperature.')
        wave=reference_audio['waveform'].detach().cpu()
        rate=int(reference_audio['sample_rate'])
        if wave.ndim!=3 or wave.shape[0]!=1 or not 2<=wave.shape[-1]/rate<=30:raise ValueError('Voice reference must be 2–30 seconds, batch size 1.')
        # The Comfy execution queue serializes this with image/video jobs.
        model_management.unload_all_models();model_management.soft_empty_cache()
        with tempfile.TemporaryDirectory(prefix='manju-speech-',dir=folder_paths.get_temp_directory()) as folder:
            folder=Path(folder);source=folder/'voice.wav';output=folder/'speech.wav'
            sf.write(source,wave[0].mean(dim=0).numpy(),rate,subtype='PCM_16')
            emotion_source=None
            if emotion_audio is not None:
                emotion_wave=emotion_audio['waveform'].detach().cpu();emotion_rate=int(emotion_audio['sample_rate'])
                if emotion_wave.ndim!=3 or emotion_wave.shape[0]!=1 or not 2<=emotion_wave.shape[-1]/emotion_rate<=30:raise ValueError('Emotion reference must be 2–30 seconds, batch size 1.')
                emotion_source=folder/'emotion.wav'
                sf.write(emotion_source,emotion_wave[0].mean(dim=0).numpy(),emotion_rate,subtype='PCM_16')
            request={**config,'reference':str(source),'emotion_reference':str(emotion_source) if emotion_source else None,
                     'output':str(output),'text':text,'language':language,'speed':speed,'emotion':emotion,'intensity':intensity,'seed':seed,
                     'use_emo_text':use_emo_text,'emo_text':emo_text,'interval_silence':interval_silence,'quality':quality,'temperature':temperature}
            payload=folder/'request.json';payload.write_text(json.dumps(request,ensure_ascii=False),encoding='utf-8')
            log=folder/'inference.log';process=None
            try:
                with log.open('wb') as stream:
                    from .runtime_env import worker_command, worker_environment
                    process=subprocess.Popen(worker_command(config,Path(__file__).with_name('worker.py'),payload),cwd=folder,stdout=stream,stderr=subprocess.STDOUT,stdin=subprocess.DEVNULL,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),env=worker_environment(config))
                    deadline=time.monotonic()+1800
                    while process.poll() is None:
                        model_management.throw_exception_if_processing_interrupted()
                        if time.monotonic()>deadline:raise TimeoutError('Local speech exceeded 30 minutes.')
                        time.sleep(.25)
                if process.returncode or not output.is_file():
                    raise RuntimeError('IndexTTS failed: '+log.read_text(encoding='utf-8',errors='replace')[-5000:])
                audio,sr=sf.read(output,dtype='float32',always_2d=True)
                if not audio.size or not np.isfinite(audio).all():raise RuntimeError('Invalid speech output.')
                return ({'waveform':torch.from_numpy(audio.T.copy()).unsqueeze(0),'sample_rate':sr},)
            finally:
                if process and process.poll() is None:
                    process.terminate()
                    try:process.wait(timeout=10)
                    except subprocess.TimeoutExpired:process.kill();process.wait()

NODE_CLASS_MAPPINGS={'ManjuIndexTTS25':ManjuIndexTTS25}
NODE_DISPLAY_NAME_MAPPINGS={'ManjuIndexTTS25':'Manju · IndexTTS 2.5 人物配音'}
