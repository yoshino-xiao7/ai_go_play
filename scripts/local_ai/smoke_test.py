"""Generate real speech/lip-sync outputs in the installed runtime, with Python networking blocked."""
import argparse
from array import array
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import time
import uuid
import wave

PROJECT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('local_ai_installer', PROJECT / 'scripts/install_local_ai.py')
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


def smoke(root, components, reference=None, video=None, emotion=False):
    state = json.loads((root / 'installation.json').read_text(encoding='utf-8'))
    kinds = list(state['components']) if components == 'all' else [components]
    # Public upstream test assets, never the user's private voice/video material.
    demo = root / 'sources/lipsync/assets'
    reference = reference or demo / 'demo1_audio.wav'
    video = video or demo / 'demo1_video.mp4'
    if not reference.is_file() or ('lipsync' in kinds and not video.is_file()):
        raise ValueError('Provide --reference (2-30s WAV) and --video, or install both components for upstream demo assets.')
    output = root / 'smoke' / uuid.uuid4().hex[:12]
    output.mkdir(parents=True)
    report = {'started_at': datetime.now(timezone.utc).isoformat(), 'checks': {}}
    for kind in kinds:
        config = state['components'][kind]
        folder = output / kind
        folder.mkdir()
        result = folder / ('speech.wav' if kind == 'speech' else 'lipsync.mp4')
        request = {**config, 'output': str(result)}
        if kind == 'speech':
            if emotion and not config.get('emotion'):
                raise ValueError('Emotion model is not installed/enabled.')
            request.update(reference=str(reference), text='你好，这是本地语音安装测试。', language='zh',
                           speed=1, emotion='neutral', intensity=.5, seed=42, use_emo_text=emotion,
                           emo_text='平静温柔' if emotion else '', quality='standard', temperature=.8, interval_silence=200)
        else:
            request.update(video=str(video), audio=str(reference), workspace=str(folder),
                           progress_path=str(folder / 'progress.json'), duration=1., video_start=0,
                           audio_offset=0, face_mode='auto', face_box=None, steps=10, guidance=1.5, seed=42)
        payload = folder / 'request.json'
        installer.write_json(payload, request)
        # Fresh per-run caches: existing Hugging Face / ModelScope data cannot mask a missing model.
        env = installer.child_environment(folder, config['ffmpeg'], offline=True)
        worker = PROJECT / 'integrations' / ('comfyui_manju_' + kind) / 'worker.py'
        started = time.monotonic()
        installer.run([config['python'], '-I', '-X', 'utf8', '-u', Path(__file__).with_name('offline_worker.py'), worker, payload],
                      log=folder / 'inference.log', env=env, cwd=folder, timeout=1800)
        probe = subprocess.run([str(Path(config['ffmpeg']).with_name('ffprobe.exe')), '-v', 'error',
                                '-show_streams', '-show_format', '-of', 'json', str(result)],
                               capture_output=True, check=True, timeout=30,
                               creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        metadata = json.loads(probe.stdout)
        duration = float(metadata['format']['duration'])
        streams = {stream['codec_type']: stream for stream in metadata['streams']}
        if duration <= 0 or 'audio' not in streams:
            raise RuntimeError('Generated output has no valid audio/duration.')
        if kind == 'speech':
            with wave.open(str(result), 'rb') as audio:
                if audio.getsampwidth() != 2:
                    raise RuntimeError('Speech output must be PCM16 WAV.')
                samples = array('h', audio.readframes(audio.getnframes()))
            if not samples or max(abs(value) for value in samples) < 100:
                raise RuntimeError('Generated speech is empty or silent.')
        if kind == 'lipsync' and ('video' not in streams or abs(duration - 1) > .15):
            raise RuntimeError('Lip-sync output has invalid video/duration.')
        report['checks'][kind] = {'output': str(result), 'bytes': result.stat().st_size,
                                 'elapsed_seconds': round(time.monotonic() - started, 2),
                                 'duration': duration, 'streams': list(streams), 'python_network_blocked': True,
                                 'fresh_cache': True, 'emotion_text': emotion if kind == 'speech' else None}
        installer.write_json(output / 'report.json', report)
    print('Real inference passed. Inspect/listen to outputs:', output, flush=True)
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime-root', type=Path, default=PROJECT / '.manju/local-ai')
    parser.add_argument('--components', choices=['all', 'speech', 'lipsync'], default='all')
    parser.add_argument('--reference', type=Path)
    parser.add_argument('--video', type=Path)
    parser.add_argument('--emotion', action='store_true')
    args = parser.parse_args()
    try:
        smoke(args.runtime_root.resolve(), args.components,
              args.reference.resolve() if args.reference else None,
              args.video.resolve() if args.video else None, args.emotion)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError, KeyError) as error:
        print('Inference check failed:', error, file=sys.stderr)
        raise SystemExit(1)
