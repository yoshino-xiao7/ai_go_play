"""Keep inference independent of ComfyUI's Python and global model caches."""
import os
from pathlib import Path


def worker_command(config, worker, payload):
    # -I ignores PYTHON* environment variables, so encoding/buffering need flags.
    return [config['python'], '-I', '-X', 'utf8', '-u', str(worker), str(payload)]


def worker_environment(config):
    env = dict(os.environ)
    for key in ('PYTHONPATH', 'PYTHONHOME', 'VIRTUAL_ENV', 'CONDA_PREFIX', 'HF_HUB_CACHE',
                'HUGGINGFACE_HUB_CACHE', 'TRANSFORMERS_CACHE', 'HF_DATASETS_CACHE'):
        env.pop(key, None)
    env.update(PYTHONNOUSERSITE='1', PYTHONUTF8='1', PYTHONIOENCODING='utf-8', PYTHONUNBUFFERED='1',
               HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1')
    root = Path(config.get('cache_dir') or Path(config['python']).parent.parent / 'manju-cache')
    for variable, name in (('HF_HOME', 'huggingface'), ('MODELSCOPE_CACHE', 'modelscope'),
                           ('NUMBA_CACHE_DIR', 'numba'), ('XDG_CACHE_HOME', 'xdg'),
                           ('TEMP', 'tmp'), ('TMP', 'tmp')):
        folder = root / name
        folder.mkdir(parents=True, exist_ok=True)
        env[variable] = str(folder)
    if config.get('ffmpeg'):
        env['PATH'] = str(Path(config['ffmpeg']).parent) + os.pathsep + env.get('PATH', '')
        env['IMAGEIO_FFMPEG_EXE'] = config['ffmpeg']
    return env
