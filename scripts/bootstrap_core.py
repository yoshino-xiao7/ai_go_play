"""Prepare core dependencies and built frontend with a private, pinned toolchain."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import traceback
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parent))
from install_local_ai import download, find_system_media, load_media_settings, unpack, usable_media_binary, write_json
from manju.download_sources import run_from_registry


def prepare_media(project, runtime, env, status):
    status('检查本机 FFmpeg 和 FFprobe', .85)
    progress = .85
    phase = '检查本机 FFmpeg 和 FFprobe'
    log = runtime / 'logs/ffmpeg.log'

    def stage(label, value, **fields):
        nonlocal phase, progress
        phase, progress = label, value
        status(phase, progress, **fields)

    def report(event, *, received=0, total=None, attempt=1, attempts=3, host='', error=''):
        if event == 'connect':
            stage('正在连接 FFmpeg 下载源', .85, detail=f'{host} · 第 {attempt} / {attempts} 次尝试')
        elif event == 'download':
            amount = f'{received / 1024**2:.1f} MiB'
            if total:
                fraction = min(received / total, 1)
                detail = f'已下载 {amount} / {total / 1024**2:.1f} MiB（{fraction:.1%}）'
                stage('正在下载 FFmpeg', .85 + .08 * fraction, detail=detail)
            else:
                stage('正在下载 FFmpeg', .85, detail=f'已下载 {amount}，下载源未提供总大小', indeterminate=True)
        elif event == 'verify':
            stage('正在校验 FFmpeg 压缩包', .93)
        elif event == 'retry':
            stage('FFmpeg 下载失败，正在切换下载源', progress, detail=f'{host} · 第 {attempt} / {attempts} 次尝试', error=error)

    try:
        settings = project / '.manju/local-ai-paths.json'
        existing = load_media_settings(settings)
        binaries = find_system_media(env, existing)
        if binaries:
            stage('已找到可用的 FFmpeg 和 FFprobe', .95)
        else:
            media = json.loads((project / 'scripts/local_ai/sources.json').read_text())['ffmpeg']
            archive = download(media, runtime / 'downloads', on_progress=report, timeout=25, env=env)
            stage('正在解压或检查已安装的 FFmpeg', .94)
            folder = unpack(archive, runtime / 'ffmpeg', media['sha256']) / 'bin'
            stage('正在验证 FFmpeg 和 FFprobe', .95)
            binaries = {}
            for name in ('ffmpeg', 'ffprobe'):
                path = folder / (name + '.exe')
                if not usable_media_binary(path, name, env):
                    raise RuntimeError(f'{path.name} 无法运行或未返回版本信息')
                binaries[name] = str(path)
        write_json(settings, {**existing, **binaries})
    except Exception as exc:
        with log.open('a', encoding='utf-8') as output:
            traceback.print_exc(file=output)
        reason = str(exc) or type(exc).__name__
        status('准备 FFmpeg 和 FFprobe 失败', progress, status='failed',
               detail=f'出错步骤：{phase}', error=f'{reason}\n日志：{log}')
        raise


def bootstrap(project, uv, state_dir):
    sources = json.loads((project / 'release/setup-sources.json').read_text())
    runtime = project / '.manju/bootstrap'
    logs = runtime / 'logs'
    logs.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    for key in ('PYTHONHOME', 'PYTHONPATH', 'VIRTUAL_ENV', 'CONDA_PREFIX'): env.pop(key, None)
    env.update(PYTHONUTF8='1', PYTHONIOENCODING='utf-8', UV_NO_CONFIG='1', UV_NO_PROJECT='1', UV_LINK_MODE='copy',
               UV_CACHE_DIR=str(runtime / 'cache/uv'), TEMP=str(runtime / 'tmp'), TMP=str(runtime / 'tmp'))
    def status(phase, progress, **fields):
        write_json(state_dir / 'status.json', {'status': 'running', 'phase': phase, 'progress': progress, **fields})
    def run(command, log, child_env=None):
        with (logs / log).open('ab', buffering=0) as output:
            result = subprocess.run([str(x) for x in command], cwd=project, env=child_env or env, stdin=subprocess.DEVNULL,
                                    stdout=output, stderr=subprocess.STDOUT, timeout=3600, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if result.returncode: raise RuntimeError((logs / log).read_text(encoding='utf-8', errors='replace')[-3500:])
    def install_from_registry(kind, command, log, label, progress):
        def attempt(child_env, host):
            status(label, progress, detail=f'下载源：{host}')
            return run(command, log, child_env)
        return run_from_registry(kind, env, attempt)
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
        install_from_registry('pypi', [uv, 'pip', 'install', '--python', python, '-c', project / 'requirements.lock', '-e', project],
                              'dependencies.log', '安装 Python 项目依赖', .25)
    status('准备网页运行环境', .4)
    def report_node(event, *, host='', **_):
        if event == 'connect':
            status('准备网页运行环境', .4, detail=f'下载 Node.js：{host}')
    node = unpack(download(sources['node'], runtime / 'downloads', on_progress=report_node, timeout=25, env=env),
                  runtime / ('node-' + sources['node']['version']), sources['node']['sha256'])
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
        install_from_registry('npm', [*npm, 'ci', '--no-audit', '--no-fund'],
                              'frontend.log', '安装网页依赖', .55)
        status('构建创作工作台', .7)
        run([*npm, 'run', 'build'], 'frontend.log')
    prepare_media(project, runtime, env, status)
    write_json(stamp, {'dependencies': manifest, 'frontend': frontend.hexdigest()})
    status('正在启动本机服务', .96)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--uv', type=Path, required=True)
    parser.add_argument('--state-dir', type=Path, required=True)
    args = parser.parse_args()
    bootstrap(args.project.resolve(), args.uv.resolve(), args.state_dir.resolve())
