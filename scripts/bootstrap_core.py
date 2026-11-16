"""Prepare core dependencies and built frontend with a private, pinned toolchain."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parent))
from install_local_ai import download, unpack, write_json


def bootstrap(project, uv, state_dir):
    sources = json.loads((project / 'release/setup-sources.json').read_text())
    runtime = project / '.manju/bootstrap'
    logs = runtime / 'logs'
    logs.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    for key in ('PYTHONHOME', 'PYTHONPATH', 'VIRTUAL_ENV', 'CONDA_PREFIX'): env.pop(key, None)
    env.update(PYTHONUTF8='1', PYTHONIOENCODING='utf-8', UV_NO_CONFIG='1', UV_NO_PROJECT='1', UV_LINK_MODE='copy',
               UV_CACHE_DIR=str(runtime / 'cache/uv'), TEMP=str(runtime / 'tmp'), TMP=str(runtime / 'tmp'))
    def status(phase, progress): write_json(state_dir / 'status.json', {'status': 'running', 'phase': phase, 'progress': progress})
    def run(command, log):
        with (logs / log).open('ab', buffering=0) as output:
            result = subprocess.run([str(x) for x in command], cwd=project, env=env, stdin=subprocess.DEVNULL,
                                    stdout=output, stderr=subprocess.STDOUT, timeout=3600, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if result.returncode: raise RuntimeError((logs / log).read_text(encoding='utf-8', errors='replace')[-3500:])
    python = project / '.venv/Scripts/python.exe'
    status('准备 Python 项目环境', .2)
    if python.is_file():
        try:
            compatible = subprocess.run([str(python), '-I', '-c', 'import sys; assert sys.version_info >= (3,12)'],
                                        env=env, capture_output=True, timeout=20, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)).returncode == 0
        except OSError: compatible = False
        if not compatible:
            backups = runtime / 'backups'
            backups.mkdir(parents=True, exist_ok=True)
            (project / '.venv').rename(backups / ('venv-' + uuid.uuid4().hex[:8]))
    if not python.is_file(): run([uv, 'venv', '--python', sys.executable, project / '.venv'], 'python.log')
    manifest = hashlib.sha256((project / 'requirements.lock').read_bytes() + (project / 'pyproject.toml').read_bytes()).hexdigest()
    stamp = runtime / 'core-stamp.json'
    previous = json.loads(stamp.read_text()) if stamp.is_file() else {}
    checked = subprocess.run([str(python), '-X', 'utf8', '-c', 'import manju.cli, fastapi, uvicorn, PIL, httpx, psutil, websocket'], cwd=project, env=env, capture_output=True, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)).returncode == 0
    if not checked or previous.get('dependencies') != manifest:
        run([uv, 'pip', 'install', '--python', python, '-c', project / 'requirements.lock', '-e', project], 'dependencies.log')
    status('准备网页运行环境', .4)
    node = unpack(download(sources['node'], runtime / 'downloads'), runtime / ('node-' + sources['node']['version']), sources['node']['sha256'])
    env['PATH'] = str(node) + os.pathsep + env.get('PATH', '')
    frontend = hashlib.sha256()
    source_files = []
    for directory, folders, names in os.walk(project / 'frontend'):
        folders[:] = [name for name in folders if name not in ('node_modules', 'dist', '.git')]
        source_files.extend(Path(directory) / name for name in names if not name.endswith('.tsbuildinfo'))
    for file in sorted(source_files):
        if file.is_file():
            frontend.update(file.relative_to(project).as_posix().encode())
            frontend.update(file.read_bytes())
    if previous.get('frontend') != frontend.hexdigest() or not (project / 'frontend/dist/index.html').is_file():
        status('安装网页依赖', .55)
        npm = [node / 'node.exe', node / 'node_modules/npm/bin/npm-cli.js', '--prefix', project / 'frontend']
        run([*npm, 'ci', '--no-audit', '--no-fund'], 'frontend.log')
        status('构建创作工作台', .7)
        run([*npm, 'run', 'build'], 'frontend.log')
    status('准备音视频工具', .85)
    media = json.loads((project / 'scripts/local_ai/sources.json').read_text())['ffmpeg']
    ffmpeg = unpack(download(media, runtime / 'downloads'), runtime / 'ffmpeg', media['sha256']) / 'bin/ffmpeg.exe'
    write_json(project / '.manju/local-ai-paths.json', {'ffmpeg': str(ffmpeg), 'ffprobe': str(ffmpeg.with_name('ffprobe.exe'))})
    write_json(stamp, {'dependencies': manifest, 'frontend': frontend.hexdigest()})
    status('正在启动本机服务', .96)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--uv', type=Path, required=True)
    parser.add_argument('--state-dir', type=Path, required=True)
    args = parser.parse_args()
    bootstrap(args.project.resolve(), args.uv.resolve(), args.state_dir.resolve())
