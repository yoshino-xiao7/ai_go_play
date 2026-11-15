"""Invoked only by the Comfy node using its trusted runtime configuration."""
import json
import random
import re
import sys
import wave
from pathlib import Path


def sentence_segments(text):
    """Split explicit sentence boundaries while preserving pronunciation tags."""
    segments=[];current=''
    for part in re.split(r'(<[^<>]*\|[^<>]*>)',text):
        if part.startswith('<') and part.endswith('>'):
            current+=part
            continue
        for token in re.split(r'([。！？!?；;\n]+|\.(?!\d))',part):
            current+=token
            if re.fullmatch(r'[。！？!?；;\n]+|\.',token):
                if current.strip():segments.append(current.strip())
                current=''
    if current.strip():segments.append(current.strip())
    return segments


def configure_quality(engine,quality):
    # IndexTTS 2.5 currently fixes this argument to 25 inside infer_generator.
    # Override the concrete CFM call on this one isolated engine instance;
    # passing an ignored **generation_kwargs flag would not change diffusion.
    steps=40 if quality=='studio' else 25
    cfm=engine.s2mel.models['cfm']
    original=cfm.inference
    def inference(mu,x_lens,prompt,style,f0,n_timesteps,*args,**kwargs):
        return original(mu,x_lens,prompt,style,f0,steps,*args,**kwargs)
    cfm.inference=inference
    return steps


def synthesis_arguments(request):
    use_text=bool(request.get('use_emo_text',False))
    emotion_reference=request.get('emotion_reference')
    emotion=request['emotion'];vector=None
    if not use_text and not emotion_reference and emotion!='reference':
        vector=[0.]*8
        order=['happy','angry','sad','afraid','disgusted','melancholic','surprised','calm']
        vector[order.index('calm' if emotion=='neutral' else emotion)]=request['intensity']
    return dict(spk_audio_prompt=request['reference'],lang=request['language'],emo_vector=vector,
                emo_audio_prompt=emotion_reference,use_emo_text=use_text,emo_text=request.get('emo_text') or None,
                emo_alpha=request['intensity'] if use_text or emotion_reference else 1.0,
                duration_factor=1/request['speed'],use_random=False,verbose=False,
                temperature=request.get('temperature',.8),interval_silence=request.get('interval_silence',200))


def concatenate_sentences(paths,output,interval_ms):
    """Append silence between PCM originals without altering their amplitudes."""
    with wave.open(str(output),'wb') as destination:
        expected=None
        for index,path in enumerate(paths):
            with wave.open(str(path),'rb') as source:
                shape=(source.getnchannels(),source.getsampwidth(),source.getframerate(),source.getcomptype())
                if shape[1]!=2 or shape[3]!='NONE':raise RuntimeError('Expected 16-bit PCM sentence audio.')
                if expected is None:
                    expected=shape
                    destination.setnchannels(shape[0]);destination.setsampwidth(shape[1]);destination.setframerate(shape[2])
                elif shape!=expected:raise RuntimeError('Sentence audio formats differ.')
                if index:destination.writeframes(b'\0'*(round(shape[2]*interval_ms/1000)*shape[0]*shape[1]))
                destination.writeframes(source.readframes(source.getnframes()))


def main():
    request=json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
    sys.path.insert(0,request['repo'])
    import numpy as np
    import torch
    from indextts.infer_v2_5 import IndexTTS2
    seed=request['seed'];random.seed(seed);np.random.seed(seed%(2**32));torch.manual_seed(seed)
    root=Path(request['model_dir'])
    engine=IndexTTS2(cfg_path=str(root/'config.yaml'),model_dir=str(root),device='cuda:0',use_bf16=torch.cuda.is_bf16_supported(),use_cuda_kernel=False,use_deepspeed=False,use_accel=False,use_torch_compile=False,use_qwen_emo=bool(request.get('use_emo_text',False)))
    steps=configure_quality(engine,request.get('quality','standard'))
    arguments=synthesis_arguments(request)
    segments=sentence_segments(request['text'])
    output=Path(request['output'])
    if len(segments)==1:
        engine.infer(text=segments[0],output_path=str(output),**arguments)
    else:
        paths=[]
        for index,segment in enumerate(segments):
            path=output.with_name(f'sentence-{index:03}.wav')
            engine.infer(text=segment,output_path=str(path),**arguments)
            paths.append(path)
        if not paths:raise ValueError('No speech text remains after sentence splitting.')
        # Preserve the generated dynamics. No loudness normalization, noise
        # removal, time stretching, or pitch shifting is applied here.
        concatenate_sentences(paths,output,request.get('interval_silence',200))
    output.with_suffix('.quality.json').write_text(json.dumps({'quality':request.get('quality','standard'),'diffusion_steps':steps,'segments':len(segments),'interval_silence_ms':request.get('interval_silence',200),'temperature':request.get('temperature',.8),'emotion_text':bool(request.get('use_emo_text',False))},ensure_ascii=False),encoding='utf-8')

if __name__=='__main__':main()
