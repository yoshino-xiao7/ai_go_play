"""Durable, version-pinned execution of a canvas reference DAG.

Handlers implement create/get/cancel/retry like GenerationService. Additional
media processors can register a kind without changing the scheduler.
"""
from __future__ import annotations

import copy
import json
import logging
import threading

from .store import DomainError, encode, fingerprint, new_id, now

SCHEMA = """
CREATE TABLE IF NOT EXISTS canvas_runs (
 id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
 request_id TEXT NOT NULL, request_hash TEXT NOT NULL, revision INTEGER NOT NULL,
 status TEXT NOT NULL, plan_json TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
 UNIQUE(project_id,request_id)
);
CREATE TABLE IF NOT EXISTS canvas_run_nodes (
 run_id TEXT NOT NULL REFERENCES canvas_runs(id) ON DELETE CASCADE, node_id TEXT NOT NULL,
 ordinal INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'pending', attempt INTEGER NOT NULL DEFAULT 0,
 job_id TEXT, output_version_id TEXT, signature TEXT, resolved_json TEXT, error TEXT,
 PRIMARY KEY(run_id,node_id)
);
CREATE TABLE IF NOT EXISTS canvas_run_inputs (
 run_id TEXT NOT NULL REFERENCES canvas_runs(id) ON DELETE CASCADE, version_id TEXT NOT NULL,
 PRIMARY KEY(run_id,version_id)
);
CREATE TABLE IF NOT EXISTS canvas_run_cache (
 project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE, node_id TEXT NOT NULL,
 signature TEXT NOT NULL, version_id TEXT NOT NULL, job_id TEXT, updated_at TEXT NOT NULL,
 PRIMARY KEY(project_id,node_id,signature)
);
"""
ACTIVE = {'pending', 'running', 'cancelling'}
DONE = {'succeeded', 'reused'}
BAD = {'failed', 'blocked', 'cancelled'}
FIELDS = {'workflow_id', 'prompt', 'prompt_parts', 'parameters', 'negative_prompt', 'mask_version_id',
          'provider', 'model', 'quality', 'video_options', 'video_mode', 'duration', 'audio',
          'speech_options', 'subject_node_id', 'lip_sync_options'}


class OrchestrationService:
    def __init__(self, store, generations):
        self.store, self.generations = store, generations
        self.handlers = dict.fromkeys(('image', 'video', 'audio'), generations)
        self.operation_lock = threading.RLock()
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self.run, daemon=True, name='manju-canvas-runs')
        with store.lock:
            store.conn.executescript(SCHEMA)
            store.conn.commit()

    def register_handler(self, kind, handler):
        self.handlers[kind] = handler

    def start(self):
        self.thread.start()

    def close(self):
        self.stop_event.set()
        if self.thread.is_alive():
            self.thread.join(timeout=10)

    @staticmethod
    def _kind(node):
        data = node.get('data', {})
        kind = data.get('orchestration', {}).get('kind') or data.get('generation', {}).get('kind') or data.get('kind', 'image')
        return 'video' if kind == 'lip_sync' else kind

    def _present(self, version_id, kind=None):
        try:
            version = self.store.version(version_id)
            return not version['missing'] and not self.store.asset(version['asset_id'], details=False)['deleted_at'] and (kind is None or version['mime'].startswith(kind + '/'))
        except DomainError:
            return False

    def _cached(self, project_id, node_id, signature):
        row = self.store.conn.execute('SELECT * FROM canvas_run_cache WHERE project_id=? AND node_id=? AND signature=?', (project_id, node_id, signature)).fetchone()
        return dict(row) if row and self._present(row['version_id']) else None

    def _request(self, project_id, node, nodes, edges, executable):
        data, kind = node['data'], self._kind(node)
        draft = data.get('generation', {})
        request = {k: copy.deepcopy(v) for k, v in draft.items() if k in FIELDS}
        request.update(project_id=project_id, source_node_id=node['id'], result_policy='review')
        if kind != 'image':
            request['kind'] = kind
        references = copy.deepcopy(draft.get('references', []))
        if not isinstance(references, list):
            raise DomainError(422, '参考输入列表无效。', 'canvas_run_reference')
        base_version = draft.get('edit_base_version_id') or data.get('asset_version_id')
        if kind == 'image' and base_version and (draft.get('mode') == 'edit' or draft.get('mode') == 'reference' and draft.get('use_current_image') is True) and not any(r.get('source') == 'base' for r in references):
            references.insert(0, {'version_id': base_version, 'source': 'base', 'title': '底图'})
        if kind == 'audio' and draft.get('subject_node_id') and not references:
            subject = nodes.get(draft['subject_node_id'], {}).get('data', {}).get('subject', {})
            references.append({'version_id': subject.get('voice_version_id'), 'node_id': draft['subject_node_id'], 'media_type': 'audio', 'title': subject.get('name', '音色')})
        for edge in edges:
            if edge['target'] != node['id'] or edge.get('data', {}).get('role') != 'reference' or edge['id'] in draft.get('excluded_edge_ids', []):
                continue
            if any(r.get('edge_id') == edge['id'] or r.get('node_id') == edge['source'] for r in references):
                continue
            source = nodes[edge['source']]
            source_data = source.get('data', {})
            voice = kind == 'audio' and source.get('type') == 'subject'
            references.append({'id': 'edge-' + edge['id'], 'node_id': source['id'], 'edge_id': edge['id'], 'source': 'connection',
                               'version_id': source_data.get('subject', {}).get('voice_version_id') if voice else source_data.get('asset_version_id'),
                               'title': source_data.get('title', source['id']), 'media_type': 'audio' if voice else source_data.get('kind', 'image'),
                               'role': source_data.get('kind') if draft.get('workflow_id') == 'builtin-latentsync15-local' else edge.get('data', {}).get('reference_role', 'first_frame' if draft.get('video_mode') == 'frames' and not references else 'last_frame' if draft.get('video_mode') == 'frames' else 'reference')})
        dependencies, bindings = set(), []
        for index, ref in enumerate(references):
            source_id = ref.get('node_id')
            ref.setdefault('id', 'ref-' + str(index + 1))
            if source_id in executable and not (source_id == node['id'] and ref.get('source') == 'base'):
                dependencies.add(source_id)
                bindings.append({'index': index, 'node_id': source_id})
                ref['version_id'] = 'pending:' + source_id
            if not ref.get('version_id'):
                raise DomainError(422, '参考节点没有素材，也没有可执行的生成配置。', 'canvas_run_input_missing')
            source_kind = self._kind(nodes[source_id]) if source_id in executable else ref.get('media_type')
            if source_kind == 'lip_sync':
                source_kind = 'video'
            if source_kind and (kind == 'image' and source_kind != 'image' or kind == 'audio' and source_kind != 'audio'):
                raise DomainError(422, '参考连线的素材类型与目标节点不兼容。', 'canvas_run_input_type')
            if source_kind:
                ref['media_type'] = source_kind
            if draft.get('workflow_id') == 'builtin-latentsync15-local' and ref.get('role') not in ('video', 'audio'):
                ref['role'] = source_kind or ref.get('media_type')
            # Browser reconciliation can add these defaults after an output is
            # delivered. They must not make an unchanged graph look different.
            ref.setdefault('title', '')
            ref.setdefault('description', '')
            ref.setdefault('use_description', True)
        request['references'] = references
        if not request.get('workflow_id') and kind in ('image', 'audio', 'video'):
            request['workflow_id'] = 'builtin-h3-local' if kind == 'video' else 'builtin-indextts25-local' if kind == 'audio' else 'builtin-qwen21-' + draft.get('mode', 'text_to_image')
        # Negative prompts are stored in the image form's parameters.
        params = request.setdefault('parameters', {})
        if 'negative_prompt' in params:
            request['negative_prompt'] = params.pop('negative_prompt')
        return request, sorted(dependencies), bindings

    def plan(self, project_id, payload):
        if not isinstance(payload, dict) or payload.get('scope', 'all') not in ('all', 'downstream') or not isinstance(payload.get('force', False), bool):
            raise DomainError(422, '执行范围或强制重做设置无效。', 'canvas_run_invalid')
        with self.store.lock:
            self.store.project(project_id, include_deleted=False)
            canvas = self.store.canvas(project_id)
            revision = payload.get('revision')
            if revision is not None and (type(revision) is not int or revision != canvas['revision']):
                raise DomainError(409, '画布已更新，请重新预检。', 'revision_conflict', revision=canvas['revision'])
            nodes = {n['id']: n for n in canvas['nodes']}
            executable = {i for i, n in nodes.items() if n.get('type') == 'media' and isinstance(n.get('data', {}).get('generation'), dict)}
            specs, errors, warnings = {}, [], []
            for node_id in executable:
                node, kind = nodes[node_id], self._kind(nodes[node_id])
                try:
                    if kind not in self.handlers:
                        raise DomainError(422, '此节点尚未配置执行器：' + kind, 'canvas_run_handler')
                    if node['data'].get('locked') or node['data']['generation'].get('pending_submission'):
                        raise DomainError(409, '节点已锁定或有待确认的提交。', 'canvas_run_node_unready')
                    request, dependencies, bindings = self._request(project_id, node, nodes, canvas['edges'], executable)
                    specs[node_id] = {'node_id': node_id, 'title': node['data'].get('title', node_id), 'kind': kind, 'dependencies': dependencies, 'bindings': bindings, 'request': request}
                except DomainError as error:
                    specs[node_id] = {'node_id': node_id, 'title': node.get('data', {}).get('title', node_id), 'kind': kind, 'dependencies': [], 'bindings': [], 'request': {}}
                    errors.append({'node_id': node_id, **error.detail})
            selected = set(executable)
            if payload.get('scope') == 'downstream':
                seeds = payload.get('node_ids')
                if not isinstance(seeds, list) or not seeds or any(not isinstance(i, str) or i not in nodes for i in seeds):
                    raise DomainError(422, '请选择仍存在的起点节点。', 'canvas_run_selection')
                reached = set(seeds)
                while True:
                    expanded = reached | {i for i, spec in specs.items() if set(spec['dependencies']) & reached or any(r.get('node_id') in reached for r in spec['request'].get('references', []))}
                    if expanded == reached:
                        break
                    reached = expanded
                selected = reached & executable
                # Include required ancestors so selected downstream cards never use an unresolved input.
                while True:
                    expanded = selected | {d for i in selected for d in specs[i]['dependencies']}
                    if expanded == selected:
                        break
                    selected = expanded
            errors = [error for error in errors if error['node_id'] in selected]
            remaining, ordered = set(selected), []
            while remaining:
                ready = sorted(i for i in remaining if not set(specs[i]['dependencies']) & remaining)
                if not ready:
                    errors.append({'code': 'canvas_run_cycle', 'message': '参考依赖形成循环，请断开循环后重试。', 'node_ids': sorted(remaining)})
                    ordered.extend(sorted(remaining))
                    break
                ordered.extend(ready)
                remaining.difference_update(ready)
            if not selected:
                errors.append({'code': 'canvas_run_empty', 'message': '范围内没有已配置的生成节点。'})
            predicted, profiles = {}, {}
            for node_id in ordered:
                spec = specs[node_id]
                if not spec['request']:
                    continue
                request = copy.deepcopy(spec['request'])
                try:
                    handler = self.handlers[spec['kind']]
                    if handler is self.generations:
                        self.generations._validate_request(request)
                        profile_key = fingerprint([request['workflow_id'], request.get('video_options')])
                        if profile_key not in profiles:
                            if request['workflow_id'].startswith('builtin-openai-'):
                                workflow = self.generations.openai.snapshot(request['workflow_id'].removeprefix('builtin-openai-'))
                            elif request['workflow_id'] == 'builtin-latentsync15-local':
                                workflow = self.generations.lipsync.snapshot()
                            elif spec['kind'] == 'video':
                                workflow = self.generations.video.snapshot(request.get('video_options'))
                            elif spec['kind'] == 'audio':
                                workflow = self.generations.speech.snapshot()
                            else:
                                workflow = self.generations.workflows.get(request['workflow_id'])
                            profiles[profile_key] = workflow
                        workflow = profiles[profile_key]
                        if workflow.get('ready') is False:
                            raise DomainError(422, '所选生成服务尚未就绪，请先完成配置。', 'canvas_run_workflow_unready')
                        capabilities = workflow.get('capabilities', {})
                        if not capabilities.get('min_images', 0) <= len(request['references']) <= capabilities.get('max_images', 0):
                            raise DomainError(422, '参考素材数量不符合所选工作流。', 'generation_reference_count')
                        if capabilities.get('requires_mask') and not request.get('mask_version_id'):
                            raise DomainError(422, '所选工作流需要蒙版。', 'generation_mask_required')
                        if request.get('mask_version_id') and not capabilities.get('supports_mask'):
                            raise DomainError(422, '所选工作流不支持蒙版。', 'generation_mask_unsupported')
                        spec['workflow_snapshot'] = workflow
                        spec['workflow_signature'] = fingerprint(workflow)
                        if request.get('workflow_id') == 'builtin-latentsync15-local':
                            spec['label'] = '口型同步'
                    elif hasattr(handler, 'validate_plan'):
                        handler.validate_plan(request)
                    for ref in request['references']:
                        if not ref['version_id'].startswith('pending:') and not self._present(ref['version_id'], 'image' if spec['kind'] == 'image' else 'audio' if spec['kind'] == 'audio' else ref.get('media_type')):
                            raise DomainError(422, '固定参考素材缺失、已删除或类型不符。', 'canvas_run_input_missing')
                    if request.get('mask_version_id') and not self._present(request['mask_version_id'], 'image'):
                        raise DomainError(422, '蒙版原件缺失。', 'canvas_run_input_missing')
                    for binding in spec['bindings']:
                        request['references'][binding['index']]['version_id'] = predicted.get(binding['node_id'], 'pending:' + binding['node_id'])
                    signature = self._signature(spec, request)
                    cached = None if payload.get('force', False) or any(r['version_id'].startswith('pending:') for r in request['references']) else self._cached(project_id, node_id, signature)
                    spec.update(action='reuse' if cached else 'generate', reason='输入和配置未改动，复用已完成版本。' if cached else '等待依赖后生成。' if spec['dependencies'] else '按已保存配置生成。')
                    if cached:
                        predicted[node_id] = cached['version_id']
                        spec['cached_version_id'] = cached['version_id']
                except DomainError as error:
                    errors.append({'node_id': node_id, **error.detail})
                    spec.update(action='blocked', reason=error.detail['message'])
            return {'project_id': project_id, 'revision': canvas['revision'], 'scope': payload.get('scope', 'all'), 'force': payload.get('force', False), 'nodes': [specs[i] for i in ordered], 'errors': errors, 'warnings': warnings, 'valid': not errors}

    def _signature(self, spec, request):
        canonical = self.generations._validate_request(request) if self.handlers[spec['kind']] is self.generations else request
        return fingerprint({'kind': spec['kind'], 'workflow': spec.get('workflow_signature'), 'request': canonical})

    def create(self, project_id, payload):
        if not isinstance(payload, dict):
            raise DomainError(422, '执行请求格式无效。', 'canvas_run_invalid')
        key = payload.get('request_id') or new_id()
        if not isinstance(key, str) or not 1 <= len(key) <= 200:
            raise DomainError(422, '执行请求编号无效。', 'invalid_request_id')
        with self.operation_lock, self.generations.operation_lock, self.store.media_lock, self.store.lock:
            previous = self.store.conn.execute('SELECT id,request_hash FROM canvas_runs WHERE project_id=? AND request_id=?', (project_id, key)).fetchone()
            if previous:
                if previous['request_hash'] != fingerprint(payload):
                    raise DomainError(409, '请求编号已用于不同执行计划。', 'idempotency_conflict')
                return self.get(previous['id'])
            plan = self.plan(project_id, payload)
            if not plan['valid']:
                raise DomainError(422, '画布依赖预检未通过。', 'canvas_run_preflight', plan=plan)
            busy = self.store.conn.execute("SELECT id FROM canvas_runs WHERE project_id=? AND status IN ('pending','running','cancelling')", (project_id,)).fetchone()
            if busy:
                raise DomainError(409, '此项目已有未结束的画布运行。', 'canvas_run_busy', run_id=busy['id'])
            for spec in plan['nodes']:
                active = self.store.conn.execute("SELECT id FROM generation_jobs WHERE project_id=? AND source_node_id=? AND status IN ('pending','submitting','queued','running','collecting','unknown')", (project_id, spec['node_id'])).fetchone()
                if active:
                    raise DomainError(409, '节点已有未结束的生成，请先等待或核对。', 'generation_source_busy', node_id=spec['node_id'], job_id=active['id'])
            run_id, timestamp = new_id(), now()
            versions = {r['version_id'] for s in plan['nodes'] for r in s['request']['references'] if not r['version_id'].startswith('pending:')}
            versions.update(s['request']['mask_version_id'] for s in plan['nodes'] if s['request'].get('mask_version_id'))
            versions.update(s['cached_version_id'] for s in plan['nodes'] if s.get('cached_version_id'))
            with self.store.tx():
                self.store.conn.execute('INSERT INTO canvas_runs VALUES(?,?,?,?,?,?,?,?,?)', (run_id, project_id, key, fingerprint(payload), plan['revision'], 'pending', encode(plan), timestamp, timestamp))
                self.store.conn.executemany('INSERT INTO canvas_run_nodes(run_id,node_id,ordinal) VALUES(?,?,?)', [(run_id, s['node_id'], i) for i, s in enumerate(plan['nodes'])])
                self.store.conn.executemany('INSERT INTO canvas_run_inputs VALUES(?,?)', [(run_id, v) for v in versions])
                self.store.emit('canvas-run.updated', {'project_id': project_id, 'run_id': run_id, 'status': 'pending'})
            return self.get(run_id)

    def get(self, run_id):
        with self.store.lock:
            row = self.store.conn.execute('SELECT * FROM canvas_runs WHERE id=?', (run_id,)).fetchone()
            if not row:
                raise DomainError(404, '画布运行不存在。', 'canvas_run_missing')
            result = dict(row)
            result.pop('request_hash')
            plan = json.loads(result.pop('plan_json'))
            specs = {s['node_id']: s for s in plan['nodes']}
            result['nodes'] = []
            for item in self.store.conn.execute('SELECT * FROM canvas_run_nodes WHERE run_id=? ORDER BY ordinal', (run_id,)):
                value = dict(item)
                value['request'] = json.loads(value.pop('resolved_json')) if value['resolved_json'] else None
                if value['job_id'] and value['status'] == 'running':
                    try:
                        job = self.handlers[specs[value['node_id']]['kind']].get(value['job_id'])
                        value.update(job_status=job['status'], job_progress=job.get('progress'), message=job.get('message'))
                    except (DomainError, KeyError):
                        pass
                result['nodes'].append({**specs[value['node_id']], **value})
            result.update(scope=plan['scope'], force=plan['force'], progress=sum(n['status'] in DONE | BAD for n in result['nodes']) / max(1, len(result['nodes'])))
            return result

    def list(self, project_id):
        with self.store.lock:
            self.store.project(project_id)
            ids = [r[0] for r in self.store.conn.execute('SELECT id FROM canvas_runs WHERE project_id=? ORDER BY created_at DESC LIMIT 50', (project_id,))]
            return [self.get(i) for i in ids]

    def _update(self, run_id, node_id=None, **fields):
        with self.store.tx():
            if node_id:
                self.store.conn.execute('UPDATE canvas_run_nodes SET ' + ','.join(k + '=?' for k in fields) + ' WHERE run_id=? AND node_id=?', (*fields.values(), run_id, node_id))
            else:
                self.store.conn.execute('UPDATE canvas_runs SET ' + ','.join(k + '=?' for k in fields) + ' WHERE id=?', (*fields.values(), run_id))
            self.store.conn.execute('UPDATE canvas_runs SET updated_at=? WHERE id=?', (now(), run_id))
            self.store.emit('canvas-run.updated', {'run_id': run_id, 'node_id': node_id})

    def cancel(self, run_id):
        with self.operation_lock:
            run = self.get(run_id)
            if run['status'] in ACTIVE:
                self._update(run_id, status='cancelling')
            return self.get(run_id)

    def retry(self, run_id):
        with self.operation_lock, self.store.media_lock, self.store.lock:
            run = self.get(run_id)
            if run['status'] in ACTIVE:
                return run
            if run['status'] not in ('failed', 'cancelled'):
                raise DomainError(409, '只有失败或取消的运行可以重试。', 'canvas_run_retry')
            self.store.project(run['project_id'], include_deleted=False)
            if self.store.conn.execute("SELECT id FROM canvas_runs WHERE project_id=? AND status IN ('pending','running','cancelling')", (run['project_id'],)).fetchone():
                raise DomainError(409, '请先等待当前运行结束。', 'canvas_run_busy')
            for row in self.store.conn.execute('SELECT version_id FROM canvas_run_inputs WHERE run_id=?', (run_id,)):
                if not self._present(row[0]):
                    raise DomainError(409, '请先修复运行使用的固定素材。', 'canvas_run_input_missing')
            with self.store.tx():
                self.store.conn.execute("UPDATE canvas_run_nodes SET status='pending',attempt=attempt+1,error=NULL WHERE run_id=? AND status IN ('failed','blocked','cancelled')", (run_id,))
                self.store.conn.execute("UPDATE canvas_runs SET status='pending',updated_at=? WHERE id=?", (now(), run_id))
            return self.get(run_id)

    def run(self):
        while not self.stop_event.is_set():
            try:
                self.tick()
            except Exception:
                logging.getLogger(__name__).exception('Canvas scheduler failed')
            self.stop_event.wait(.75)

    def tick(self):
        if self.stop_event.is_set() or self.store.maintenance:
            return
        with self.operation_lock, self.generations.operation_lock, self.store.media_lock:
            with self.store.lock:
                ids = [r[0] for r in self.store.conn.execute("SELECT id FROM canvas_runs WHERE status IN ('pending','running','cancelling') ORDER BY created_at")]
            for run_id in ids:
                self._tick_run(run_id)

    def _tick_run(self, run_id):
        run = self.get(run_id)
        with self.store.lock:
            plan = json.loads(self.store.conn.execute('SELECT plan_json FROM canvas_runs WHERE id=?', (run_id,)).fetchone()[0])
        specs = {s['node_id']: s for s in plan['nodes']}
        cancelling = run['status'] == 'cancelling'
        if not cancelling:
            self._update(run_id, status='running')
        by_id = {n['node_id']: n for n in run['nodes']}
        for node in run['nodes']:
            if node['status'] in DONE | BAD:
                continue
            handler = self.handlers.get(node['kind'])
            try:
                if handler is None:
                    raise DomainError(422, '执行器尚未注册：' + node['kind'], 'canvas_run_handler')
                if cancelling and not node['job_id']:
                    self._update(run_id, node['node_id'], status='cancelled')
                    node['status'] = 'cancelled'
                    continue
                if node['status'] == 'pending' and not cancelling:
                    dependencies = [by_id[i] for i in node['dependencies']]
                    if any(d['status'] in BAD for d in dependencies):
                        self._update(run_id, node['node_id'], status='blocked', error='上游未成功，未提交下游。')
                        node['status'] = 'blocked'
                        continue
                    if not all(d['status'] in DONE for d in dependencies):
                        continue
                    # Always recover the immutable template, never a mutable live card.
                    spec = specs[node['node_id']]
                    request = copy.deepcopy(spec['request'])
                    for binding in spec['bindings']:
                        request['references'][binding['index']]['version_id'] = by_id[binding['node_id']]['output_version_id']
                    signature = self._signature(spec, request)
                    with self.store.lock:
                        cached = None if run['force'] else self._cached(run['project_id'], node['node_id'], signature)
                    if cached:
                        self._complete(run, node, cached['version_id'], signature, cached['job_id'], 'reused')
                        continue
                    request['request_id'] = 'canvas-run:' + fingerprint([run_id, node['node_id'], node['attempt']])
                    self._update(run_id, node['node_id'], status='submitting', resolved_json=encode(request), signature=signature)
                    node.update(status='submitting', request=request, signature=signature)
                if node['status'] == 'submitting':
                    # Deterministic request IDs close the crash window after child creation.
                    if node['job_id']:
                        job = handler.retry(node['job_id'], request_id=node['request']['request_id'])
                    else:
                        job = handler.create(node['request'], workflow_snapshot=node.get('workflow_snapshot')) if handler is self.generations else handler.create(node['request'])
                    self._update(run_id, node['node_id'], status='running', job_id=job['id'])
                    node.update(status='running', job_id=job['id'])
                job = handler.get(node['job_id'])
                if cancelling and job['status'] not in ('succeeded', 'failed', 'cancelled'):
                    try:
                        job = handler.cancel(job['id'], interrupt_running=False)
                    except DomainError:
                        # Already submitted work may be non-cancellable; keep tracking it.
                        continue
                if job['status'] == 'succeeded':
                    outputs = job.get('outputs') or []
                    if not outputs:
                        raise DomainError(422, '任务完成但未返回可用素材。', 'canvas_run_output_missing')
                    self._complete(run, node, outputs[0]['version_id'], node['signature'], job['id'])
                elif job['status'] in ('failed', 'cancelled'):
                    reason = job.get('error') or job.get('message') or '生成未完成。'
                    self._update(run_id, node['node_id'], status=job['status'], error=reason if isinstance(reason, str) else encode(reason))
                    node['status'] = job['status']
            except Exception as error:
                reason = error.detail['message'] if isinstance(error, DomainError) else str(error)
                self._update(run_id, node['node_id'], status='failed', error=reason[:3000])
                node['status'] = 'failed'
        latest = self.get(run_id)
        states = {n['status'] for n in latest['nodes']}
        if states <= DONE | BAD:
            self._update(run_id, status='cancelled' if cancelling else 'failed' if states & BAD else 'succeeded')

    def _complete(self, run, node, version_id, signature, job_id, status='succeeded'):
        if not self._present(version_id, node['kind'] if node['kind'] in ('image', 'video', 'audio') else None):
            raise DomainError(409, '执行结果原件缺失。', 'canvas_run_output_missing')
        with self.store.tx():
            self.store.conn.execute('UPDATE canvas_run_nodes SET status=?,output_version_id=?,signature=?,job_id=?,error=NULL WHERE run_id=? AND node_id=?', (status, version_id, signature, job_id, run['id'], node['node_id']))
            self.store.conn.execute('INSERT OR IGNORE INTO canvas_run_inputs VALUES(?,?)', (run['id'], version_id))
            self.store.conn.execute('INSERT OR REPLACE INTO canvas_run_cache VALUES(?,?,?,?,?,?)', (run['project_id'], node['node_id'], signature, version_id, job_id, now()))
        node.update(status=status, output_version_id=version_id, signature=signature, job_id=job_id)
