"""Resumable first-run preparation, separate from the creative library and cloud identity."""
from __future__ import annotations
import copy
import json
import os
from pathlib import Path
import shutil
import threading
import time
import uuid
import httpx
from .setup_catalog import PROJECT, catalog, share_inventory, match_share
from .setup_jobs import SetupJobs, atomic_json
from .setup_models import IMPORT_HEADROOM, local_path, model_target, inspect_files, import_files, reusable_model_roots, verify_files
from .setup_install import install_comfy, install_nodes, install_setup_revision, run_installer
from .store import DomainError, now

POLICY_VERSION = '2026-11-13'


class SetupService:
    def __init__(self, store, comfy, share, *, project=PROJECT):
        self.store, self.comfy, self.share, self.project = store, comfy, share, Path(project)
        self.directory = store.config_file.with_suffix('.setup')
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / 'state.json'
        self.lock = threading.RLock()
        self.jobs = SetupJobs(self.directory)
        self.catalog = catalog(self.project)
        self.sources = json.loads((self.project / 'release/setup-sources.json').read_text())
        self.state = json.loads(self.path.read_text(encoding='utf-8')) if self.path.is_file() else {
            'version': 1, 'step': 'welcome', 'completed': False,
            'models_root': str(Path.home() / 'ManjuModels'), 'import_sources': [],
            'packs': [p['id'] for p in self.catalog['packs']], 'validation': None, 'share_scan': None,
            'mode': None, 'consent': None,
        }

    def close(self):
        self.jobs.close()

    def save(self):
        atomic_json(self.path, self.state)

    def status(self):
        with self.lock:
            state = copy.deepcopy(self.state)
        has_projects = bool(self.store.projects())
        state.update(job=self.jobs.snapshot(), busy=self.jobs.busy, policy_version=POLICY_VERSION,
                     default_comfy_path=str(Path.home() / 'ManjuApps/ComfyUI_windows_portable'),
                     default_models_root=str(Path.home() / 'ManjuModels'),
                     platform_supported=os.name == 'nt', library_has_projects=has_projects,
                     existing_library_installation=has_projects and not self.path.exists())
        return state

    def select(self, values):
        with self.lock:
            if self.jobs.busy:
                raise DomainError(409, '准备任务正在执行，结束后才能更改目录和模型选择。', 'setup_busy')
            changes = {}
            if 'models_root' in values:
                path = local_path(values['models_root'])
                if path == Path(path.anchor): raise DomainError(422, '请选择专用模型文件夹，不能直接使用磁盘根目录。', 'setup_path_invalid')
                changes['models_root'] = str(path)
            if 'import_sources' in values:
                raw = values['import_sources']
                if not isinstance(raw, list) or len(raw) > 12: raise DomainError(422, '最多选择 12 个来源目录。', 'setup_sources_invalid')
                changes['import_sources'] = list(dict.fromkeys(str(local_path(p, directory=True)) for p in raw))
            if 'packs' in values:
                packs = values['packs']
                valid = {p['id'] for p in self.catalog['packs']}
                if not isinstance(packs, list) or any(not isinstance(p, str) or p not in valid for p in packs):
                    raise DomainError(422, '模型分类无效。', 'setup_packs_invalid')
                selected = set(packs)
                if '06-indextts-emotion' in selected: selected.add('05-indextts')
                changes['packs'] = sorted(selected)
            if any(changes.get(key, self.state[key]) != self.state[key] for key in ('models_root', 'packs')):
                changes['validation'] = None
                changes['completed'] = False
            if 'step' in values:
                if values['step'] not in ('welcome', 'comfy', 'models', 'verify', 'identity'):
                    raise DomainError(422, '引导步骤无效。', 'setup_step_invalid')
                changes['step'] = values['step']
            self.state.update(changes)
            self.save()
        return self.status()

    def selected_files(self):
        packs = set(self.state['packs'])
        return [f for f in self.catalog['files'] if packs.intersection(f['packs'])]

    def model_scan(self):
        with self.lock:
            selected = self.selected_files()
            chosen_sources = [Path(p) for p in self.state['import_sources']]
            root = Path(self.state['models_root'])
        sources = [*chosen_sources, Path.home() / 'Downloads/ai-go-play', Path.home() / 'Downloads']
        installation = self.comfy.status().get('installation')
        if installation: sources.append(Path(installation['comfy_path']) / 'models')
        files = inspect_files(selected, root, sources)
        free = shutil.disk_usage(next(p for p in (root, *root.parents) if p.exists())).free
        copy_bytes = sum(item['size'] for item in files if item['status'] == 'missing' and item['source'])
        return {'files': files, 'sources': [str(p) for p in sources if p.is_dir()],
                'models_root': str(root), 'free_bytes': free, 'copy_bytes': copy_bytes,
                'import_disk_full': bool(copy_bytes and free < copy_bytes + IMPORT_HEADROOM),
                'reusable_roots': reusable_model_roots(selected, chosen_sources)}

    def browse(self, path=None):
        if not path:
            roots = [Path.home(), self.project, Path.home() / 'Downloads']
            if os.name == 'nt': roots += [Path(chr(n) + ':/') for n in range(65, 91) if Path(chr(n) + ':/').is_dir()]
            return {'path': None, 'parent': None, 'directories': [{'name': str(p), 'path': str(p)} for p in dict.fromkeys(roots) if p.is_dir()]}
        root = local_path(path, directory=True)
        directories = []
        try:
            with os.scandir(root) as entries:
                for entry in entries:
                    if len(directories) >= 500: break
                    if entry.is_dir(follow_symlinks=False) and not entry.name.startswith('.'):
                        directories.append({'name': entry.name, 'path': str(Path(entry.path))})
        except PermissionError as error:
            raise DomainError(403, '没有权限浏览这个目录，请选择其他位置。', 'setup_directory_forbidden') from error
        return {'path': str(root), 'parent': str(root.parent) if root.parent != root else None,
                'directories': sorted(directories, key=lambda row: row['name'].casefold())}

    def start(self, kind, payload):
        with self.lock:
            if self.jobs.busy: raise DomainError(409, '已有准备任务正在执行。', 'setup_busy')
            files = copy.deepcopy(self.selected_files())
            root = Path(self.state['models_root'])
            sources = self.model_scan()['sources'] if kind == 'import' else []
            def operation(job):
                if kind == 'share':
                    inventory = share_inventory(self.catalog['share'], check_cancelled=job.check_cancelled)
                    result = {'checked_at': now(), 'files': match_share(self.catalog['files'], inventory), 'remote_count': len(inventory)}
                    with self.lock:
                        self.state['share_scan'] = result
                        self.save()
                    return result
                if kind == 'import':
                    with self.lock:
                        self.state['validation'] = None
                        self.save()
                    return import_files(files, root, sources, job)
                if kind == 'verify':
                    result = verify_files(files, root, job)
                    result.update(checked_at=now(), models_root=str(root), packs=list(self.state['packs']))
                    with self.lock:
                        self.state['validation'] = result
                        self.save()
                    return result
                if kind == 'comfy-install':
                    destination = local_path(payload.get('destination'))
                    result = install_comfy(destination, self.directory / 'downloads', self.sources, job)
                    self.comfy.configure(result['path'], payload.get('port', 8188))
                    return result
                if kind == 'runtimes':
                    return self.install_runtimes(job)
                raise DomainError(422, '不支持的安装任务。', 'setup_job_invalid')
            if kind not in ('share', 'import', 'verify', 'comfy-install', 'runtimes'):
                raise DomainError(422, '不支持的安装任务。', 'setup_job_invalid')
            return self.jobs.start(kind, operation)

    def install_runtimes(self, job):
        state = self.comfy.status()
        if not state.get('installation'): raise DomainError(409, '请先选择完整的 ComfyUI 安装。', 'setup_comfy_required')
        if state.get('queue') and (state['queue'].get('running') or state['queue'].get('pending')):
            raise DomainError(409, '请先等待 ComfyUI 任务结束，再安装组件。', 'setup_comfy_busy')
        if state['status'] in ('running', 'external') and state.get('queue') is None:
            raise DomainError(409, '无法确认 ComfyUI 队列，请恢复连接后重试。', 'setup_comfy_busy')
        restart = state.get('managed', False) or state['status'] == 'stopped'
        if state.get('managed'):
            job.update(message='等待空闲引擎停止，准备安装组件')
            self.comfy.stop(force=False)
            deadline = time.monotonic() + 30
            while self.comfy.status()['status'] == 'stopping':
                job.check_cancelled()
                if time.monotonic() > deadline: raise TimeoutError('引擎未能停止，请检查 ComfyUI 日志后重试。')
                time.sleep(.4)
            if self.comfy.status()['status'] != 'stopped':
                raise RuntimeError('ComfyUI 尚未完全停止，暂不安装组件。')
        selected = set(self.state['packs'])
        speech, lipsync = '05-indextts' in selected, '07-latentsync' in selected
        root = Path(self.state['models_root'])
        self.configure_models(root)
        install_nodes(self.project, state['installation'], selected, self.sources, self.directory, job)
        if speech or lipsync:
            if os.name != 'nt': raise DomainError(422, '语音/口型自动安装目前支持 Windows + NVIDIA。', 'setup_platform_unsupported')
            command = [os.path.join(os.environ.get('SystemRoot', 'C:/Windows'), 'System32/WindowsPowerShell/v1.0/powershell.exe'),
                       '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', self.project / 'scripts/install_local_ai.ps1',
                       '-ComfyDir', state['installation']['comfy_path'], '-ModelsDir', root,
                       '-Components', 'all' if speech and lipsync else 'speech' if speech else 'lipsync',
                       '-Emotion', 'required' if '06-indextts-emotion' in selected else 'off']
            run_installer(command, self.directory / 'logs', job, cwd=self.project)
        revision = uuid.uuid4().hex
        install_setup_revision(self.project, state['installation'], revision, models_root=root)
        with self.lock:
            self.state['runtime_revision'] = revision
            self.save()
        if restart:
            job.update(message='组件已安装，正在重新启动 ComfyUI')
            self.comfy.start()
            deadline = time.monotonic() + 120
            while self.comfy.status()['status'] == 'starting':
                job.check_cancelled()
                if time.monotonic() > deadline: raise TimeoutError('组件已安装，但引擎启动超时，请查看 ComfyUI 日志。')
                time.sleep(.8)
            if self.comfy.status()['status'] != 'running': raise RuntimeError('组件已安装，但引擎未启动成功，请查看 ComfyUI 日志。')
            return {'message': '组件已安装并重新启动，请检查就绪状态。', 'restart_required': False}
        return {'message': '模型路径与所选组件已安装。请重启 ComfyUI 后检查组件。', 'restart_required': True}

    def configure_models(self, root):
        root.mkdir(parents=True, exist_ok=True)
        mapping = {'ai_go_play': {'base_path': str(root), **{name: name for name in (
            'diffusion_models', 'text_encoders', 'vae', 'loras', 'upscale_models', 'frame_interpolation', 'checkpoints')}}}
        path = self.comfy.directory / 'ai-go-play-model-paths.yaml'
        # JSON is valid YAML; only an app-owned extra-paths file is written.
        atomic_json(path, mapping)

    def readiness(self):
        state = self.comfy.status()
        nodes = {}
        if state['status'] in ('running', 'external'):
            try:
                with httpx.Client(timeout=8, trust_env=False) as client:
                    response = client.get(state['base_url'] + '/object_info')
                    response.raise_for_status()
                    nodes = response.json()
            except (httpx.HTTPError, ValueError): pass
        from .setup_readiness import check_packs, choices
        checks = check_packs(self.state['packs'], self.selected_files(), nodes)
        if self.state['packs'] and (not self.state.get('runtime_revision') or self.state['runtime_revision'] not in choices(nodes, 'ManjuSetupRevision', 'revision')):
            for check in checks:
                check['ready'] = False
                check['missing_nodes'].append('请安装 / 连接组件，并重启 ComfyUI')
        return {'comfy': state, 'packs': checks, 'ready': not self.state['packs'] or (state['status'] in ('running', 'external') and all(p['ready'] for p in checks))}

    def complete(self, body):
        with self.lock:
            if self.jobs.busy: raise DomainError(409, '请等待准备任务完成。', 'setup_busy')
            if body.get('privacy') is not True or body.get('manual') is not True or body.get('policy_version') != POLICY_VERSION:
                raise DomainError(422, '请阅读并勾选当前版本的隐私说明和用户手册。', 'setup_consent_required')
            mode = body.get('mode')
            if mode not in ('guest', 'yike'): raise DomainError(422, '请选择账号或游客入口。', 'setup_mode_invalid')
            if mode == 'yike' and not self.share.status()['connected']: raise DomainError(409, '亦可账号尚未完成授权。', 'setup_identity_required')
            validation = self.state.get('validation')
            if self.state['packs'] and (not validation or validation['missing']):
                raise DomainError(409, '所选模型还未完整通过校验，请补齐文件或调整模型选择。', 'setup_models_incomplete')
            if self.state['packs']:
                try:
                    for item in validation['files']:
                        stat = model_target(Path(self.state['models_root']), item['path']).stat()
                        if stat.st_size != item['size'] or stat.st_mtime_ns != item.get('mtime_ns'):
                            raise OSError('changed')
                except OSError:
                    self.state['validation'] = None
                    self.save()
                    raise DomainError(409, '模型在校验后发生变化，请重新校验。', 'setup_models_changed')
            readiness = self.readiness()
            if not readiness['ready']:
                raise DomainError(409, '所选功能的 ComfyUI 组件尚未准备好，请检查后重试。', 'setup_runtime_incomplete', readiness=readiness)
            if not self.state.get('project_id'):
                projects = self.store.projects()
                project = projects[0] if projects else self.store.create_project('我的第一张画布')
                self.state['project_id'] = project['id']
            self.state.update(completed=True, mode=mode, completed_at=now(), consent={'privacy': POLICY_VERSION, 'manual': POLICY_VERSION, 'accepted_at': now()})
            self.save()
            return {'route': '/canvas/' + self.state['project_id'], 'state': self.status()}
