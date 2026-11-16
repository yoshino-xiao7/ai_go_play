"""Pinned downloads and supervised installers used by the Web setup service."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import time
import uuid
import zipfile
import httpx
import psutil
from urllib.parse import urlsplit
from .comfy import detect_installation
from .download_sources import artifact_urls, run_from_registry
from .setup_jobs import atomic_json
from .store import DomainError


def install_nodes(project, installation, selected, sources, directory, job):
    """Install pinned node archives without replacing an existing checkout or Torch."""
    comfy = Path(installation['comfy_path'])
    custom = comfy / 'custom_nodes'
    custom.mkdir(exist_ok=True)
    python = installation['python_path']
    env = dict(os.environ)
    for name in ('PYTHONHOME', 'PYTHONPATH', 'VIRTUAL_ENV', 'CONDA_PREFIX'):
        env.pop(name, None)
    env.update(PYTHONUTF8='1', PYTHONIOENCODING='utf-8', PIP_DISABLE_PIP_VERSION_CHECK='1')
    constraints = directory / 'comfy-core-constraints.txt'
    probe = subprocess.run([python, '-s', '-c', "import importlib.metadata as m; print('\\n'.join(n+'=='+m.version(n) for n in ('torch','torchvision','torchaudio','numpy')))"],
                           capture_output=True, text=True, env=env, timeout=30, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if probe.returncode:
        raise RuntimeError('ComfyUI 的 PyTorch / NumPy 环境不完整，请先修复或安装官方便携版。')
    constraints.write_text(probe.stdout, encoding='utf-8')
    if '04-h3-turbo' in selected:
        acceleration = subprocess.run([python, '-s', '-c', 'from sageattention.core import get_cuda_arch_versions; import triton; assert get_cuda_arch_versions()'],
                                      capture_output=True, env=env, timeout=45, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if acceleration.returncode:
            version = subprocess.run([python, '-s', '-c', "import torch,json; print(json.dumps({'torch':torch.__version__,'cuda':torch.version.cuda}))"],
                                     capture_output=True, text=True, env=env, timeout=30, check=True, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            version = json.loads(version.stdout)
            if version['cuda'] != '13.0' or not version['torch'].startswith('2.14.'):
                raise RuntimeError('Turbo 自动补全支持本向导提供的 PyTorch 2.14 / CUDA 13 便携版。当前引擎缺少兼容的 SageAttention / Triton；请使用向导安装独立便携版，或暂不选择 Turbo。')
            spec = sources['sageattention']
            wheel = download(spec, directory / 'downloads', job, '.whl')
            named = wheel.parent / spec['filename']
            shutil.copy2(wheel, named)
            install_from_pypi([python, '-s', '-m', 'pip', 'install', '-c', constraints, named, 'triton-windows==3.8.0.post29'],
                              directory / 'logs', job, cwd=comfy, env=env)
        headers = subprocess.run([python, '-s', '-c', "import sys,json,platform; print(json.dumps({'version':platform.python_version(),'prefix':sys.base_prefix}))"],
                                 capture_output=True, text=True, env=env, timeout=30, check=True, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        headers = json.loads(headers.stdout)
        prefix = Path(headers['prefix'])
        if not (prefix / 'include/Python.h').is_file() or not list((prefix / 'libs').glob('python3*.lib')):
            spec = sources['python_headers']
            if headers['version'] != spec['version']:
                raise RuntimeError('当前 Python 缺少 Triton 编译头文件。请使用向导提供的官方便携版，或为现有 Python 安装对应版本的 include 和 libs。')
            archive = download(spec, directory / 'downloads', job, '.zip')
            with zipfile.ZipFile(archive) as package:
                for entry in package.infolist():
                    if not entry.filename.startswith(('tools/include/', 'tools/libs/')) or entry.is_dir(): continue
                    target = prefix / entry.filename.removeprefix('tools/')
                    if not target.resolve().is_relative_to(prefix.resolve()): raise ValueError('Python 开发文件包含越界路径。')
                    target.parent.mkdir(parents=True, exist_ok=True)
                    if not target.exists():
                        pending = target.with_name(target.name + '.' + uuid.uuid4().hex[:8] + '.pending')
                        try:
                            with package.open(entry) as incoming, pending.open('xb') as outgoing:
                                shutil.copyfileobj(incoming, outgoing)
                            pending.rename(target)
                        finally: pending.unlink(missing_ok=True)
        run_installer([python, '-s', project / 'scripts/local_ai/turbo_probe.py'], directory / 'logs', job, cwd=comfy, env=env, timeout=180)
    for spec in sources.get('nodes', []):
        if not selected.intersection(spec['packs']): continue
        job.check_cancelled()
        target = custom / spec['name']
        if not target.resolve().is_relative_to(comfy.resolve()): raise ValueError('节点目录不能指向安装目录之外。')
        if not target.exists():
            archive = download(spec, directory / 'downloads', job, '.zip')
            staging = custom / ('.manju-node-' + uuid.uuid4().hex[:8])
            staging.mkdir()
            try:
                with zipfile.ZipFile(archive) as package:
                    roots = {PurePosixPath(entry.filename).parts[0] for entry in package.infolist()}
                    if len(roots) != 1: raise ValueError('节点压缩包结构不正确。')
                    for entry in package.infolist():
                        parts = PurePosixPath(entry.filename).parts
                        if '..' in parts or any(':' in part or '\\' in part for part in parts):
                            raise ValueError('节点压缩包包含无效路径。')
                        target_file = staging.joinpath(*parts[1:])
                        if not target_file.resolve().is_relative_to(staging.resolve()):
                            raise ValueError('节点压缩包包含越界路径。')
                        if entry.external_attr >> 16 & 0o170000 == 0o120000:
                            raise ValueError('节点压缩包包含不支持的符号链接。')
                        if entry.is_dir(): target_file.mkdir(parents=True, exist_ok=True)
                        else:
                            target_file.parent.mkdir(parents=True, exist_ok=True)
                            with package.open(entry) as incoming, target_file.open('xb') as outgoing:
                                shutil.copyfileobj(incoming, outgoing)
                atomic_json(staging / '.ai-go-play-source.json', spec)
                staging.rename(target)
            finally:
                if staging.exists() and staging.parent.resolve() == custom.resolve() and staging.name.startswith('.manju-node-'):
                    shutil.rmtree(staging)
        # The Qwen encoder only imports cv2 + ComfyUI's existing tensor stack.
        # Other Goohai workflows aren't exposed by ai-go-play; do not add dlib/mediapipe.
        requirements = ['opencv-python-headless'] if spec['name'] == 'Goohaitools-comfyui' else ['-r', target / 'requirements.txt'] if (target / 'requirements.txt').is_file() else []
        if requirements:
            install_from_pypi([python, '-s', '-m', 'pip', 'install', '-c', constraints, *requirements],
                              directory / 'logs', job, cwd=comfy, env=env)
    if '08-video-enhance' in selected:
        source = project / 'integrations/comfyui_manju_enhance/__init__.py'
        target = custom / 'comfyui_manju_enhance/__init__.py'
        if not target.resolve().is_relative_to(comfy.resolve()): raise ValueError('后期节点目录包含外部链接。')
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and target.read_bytes() != source.read_bytes():
            shutil.copy2(target, directory / ('enhance-backup-' + uuid.uuid4().hex + '.py'))
        shutil.copy2(source, target)


def install_setup_revision(project, installation, revision, models_root=None):
    comfy = Path(installation['comfy_path'])
    target = comfy / 'custom_nodes/comfyui_manju_setup'
    if not target.resolve().is_relative_to(comfy.resolve()): raise ValueError('安装检查节点包含外部链接。')
    target.mkdir(parents=True, exist_ok=True)
    shutil.copy2(project / 'integrations/comfyui_manju_setup/__init__.py', target / '__init__.py')
    temporary = target / 'revision.pending'
    if models_root is not None:
        atomic_json(target / 'models.json', {'root': str(Path(models_root).resolve())})
    temporary.write_text(revision, encoding='utf-8')
    temporary.replace(target / 'revision.txt')


def download(spec, directory, job, suffix):
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / (spec['sha256'] + suffix)
    def sha(path):
        with path.open('rb') as stream:
            result = hashlib.sha256()
            while block := stream.read(8 * 1024**2):
                job.check_cancelled()
                result.update(block)
            return result.hexdigest()
    if target.is_file() and sha(target) == spec['sha256']:
        return target
    part = target.with_suffix(target.suffix + '.partial')
    failures = []
    filename = urlsplit(spec['url']).path.rsplit('/', 1)[-1]
    with httpx.Client(follow_redirects=True, timeout=httpx.Timeout(30, connect=8)) as client:
        for url in artifact_urls(spec):
            host = urlsplit(url).hostname
            job.check_cancelled()
            job.update(message=f'连接下载源 {host}')
            try:
                for _ in range(2):
                    offset = part.stat().st_size if part.exists() else 0
                    headers = {'Accept-Encoding': 'identity'}
                    if offset:
                        headers['Range'] = f'bytes={offset}-'
                    with client.stream('GET', url, headers=headers) as response:
                        if response.status_code == 416 and offset:
                            if sha(part) == spec['sha256']:
                                part.replace(target)
                                return target
                            part.unlink()
                            continue
                        response.raise_for_status()
                        if response.status_code != 206:
                            offset = 0
                        elif not response.headers.get('content-range', '').startswith(f'bytes {offset}-'):
                            raise ValueError('下载源返回了无效的续传范围')
                        size = int(response.headers.get('content-length', 0))
                        total = offset + size if size else spec.get('size', 0)
                        with part.open('ab' if offset else 'wb') as stream:
                            for chunk in response.iter_raw(1024**2):
                                job.check_cancelled()
                                stream.write(chunk)
                                offset += len(chunk)
                                job.update(message=f'下载 {filename} · {host}',
                                           progress=min(.85, offset / total * .85) if total else 0,
                                           completed_bytes=offset, total_bytes=total)
                    break
                job.update(message='校验下载文件', progress=.87)
                if not part.is_file() or sha(part) != spec['sha256']:
                    part.unlink(missing_ok=True)
                    raise ValueError('SHA-256 校验失败')
                part.replace(target)
                return target
            except httpx.HTTPStatusError as error:
                failures.append(f'{host}: HTTP {error.response.status_code}')
            except httpx.RequestError as error:
                failures.append(f'{host}: {type(error).__name__}')
            except ValueError as error:
                failures.append(f'{host}: {error}')
    raise RuntimeError('所有下载源均失败：\n' + '\n'.join(failures))


def install_from_pypi(command, directory, job, *, cwd, env):
    def attempt(child, host):
        job.check_cancelled()
        job.update(message=f'连接 Python 安装源 {host}')
        return run_installer(command, directory, job, cwd=cwd, env=child)
    return run_from_registry('pypi', env, attempt)


def run_installer(command, directory, job, *, cwd=None, env=None, timeout=7200):
    log = directory / ('install-' + job.snapshot()['id'] + '-' + uuid.uuid4().hex[:8] + '.log')
    directory.mkdir(parents=True, exist_ok=True)
    with log.open('wb', buffering=0) as output:
        process = subprocess.Popen([str(x) for x in command], cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                                   stdout=output, stderr=subprocess.STDOUT, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        started = time.monotonic()
        try:
            while process.poll() is None:
                if hasattr(job, 'track_process'): job.track_process(process.pid)
                job.check_cancelled()
                if time.monotonic() - started > timeout:
                    raise TimeoutError('安装超时，请查看日志后重试。')
                try:
                    with log.open('rb') as stream:
                        stream.seek(max(0, log.stat().st_size - 12000))
                        tail = stream.read().decode('utf-8', 'replace')
                    job.update(log_tail=tail, message='正在安装，请保持本机服务运行')
                except OSError:
                    pass
                time.sleep(.4)
            if process.returncode:
                tail = log.read_text(encoding='utf-8', errors='replace')[-5000:]
                raise RuntimeError('安装失败：\n' + tail)
        finally:
            if process.poll() is None:
                try:
                    tree = psutil.Process(process.pid)
                    children = tree.children(recursive=True)
                    for child in reversed(children):
                        try: child.terminate()
                        except psutil.Error: pass
                    process.terminate()
                    _, alive = psutil.wait_procs(children, timeout=5)
                    for child in alive:
                        try: child.kill()
                        except psutil.Error: pass
                    process.wait(timeout=10)
                except (psutil.Error, subprocess.TimeoutExpired):
                    process.kill()
                    process.wait()
            if hasattr(job, 'clear_process'): job.clear_process()
    return str(log)


def install_comfy(destination, cache, sources, job):
    if os.name != 'nt':
        raise DomainError(422, '自动安装目前支持 Windows x64 + NVIDIA；其他系统请使用官方安装指引。', 'setup_platform_unsupported')
    existing = detect_installation(destination)
    if existing: return existing
    if destination.exists() and any(destination.iterdir()):
        raise DomainError(409, '请选择一个新的空目录，已有文件不会被覆盖。', 'setup_target_not_empty')
    ancestor = destination.parent
    ancestor.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(ancestor).free < 16 * 1024**3:
        raise DomainError(409, 'ComfyUI 安装需要至少 16 GiB 空闲空间。', 'setup_disk_full')
    archive = download(sources['comfyui'], cache, job, '.7z')
    extractor = download(sources['sevenzip'], cache, job, '.exe')
    staging = ancestor / ('.manju-comfy-' + uuid.uuid4().hex)
    staging.mkdir()
    # Only this exact newly-created staging path is owned by this operation.
    try:
        run_installer([extractor, 'x', archive, '-o' + str(staging), '-y'], cache, job, timeout=1800)
        found = next((entry for entry in staging.iterdir() if detect_installation(entry)), None)
        if not found:
            raise ValueError('解压后没有找到可运行的 ComfyUI。')
        if destination.exists():
            if any(destination.iterdir()): raise ValueError('目标目录在安装期间发生变化，请选择新的目录。')
            destination.rmdir()
        found.rename(destination)
        atomic_json(destination / '.ai-go-play-install.json', sources['comfyui'])
        return detect_installation(destination)
    finally:
        if staging.exists() and staging.parent.resolve() == ancestor.resolve() and staging.name.startswith('.manju-comfy-'):
            shutil.rmtree(staging)
