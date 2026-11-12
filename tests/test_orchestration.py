"""Real persistence, isolated execution handlers; never contacts a provider."""
import copy
import hashlib
from types import SimpleNamespace

import pytest

from manju.generation import GenerationService
from manju.orchestration import OrchestrationService
from manju.store import DomainError, Store
from conftest import project, upload
from test_generation import generation
from test_workflows import catalog
from test_video import h3_catalog, av_bytes


class Jobs:
    _validate_request = staticmethod(GenerationService._validate_request)

    def __init__(self, store):
        self.store = store
        import threading
        self.operation_lock = threading.RLock()
        self.jobs, self.requests = {}, []
        self.workflows = SimpleNamespace(get=lambda identity: {'id': identity, 'capabilities': {'min_images': 1 if identity.endswith('reference') else 0, 'max_images': 4 if identity.endswith('reference') else 0}})
        self.video = SimpleNamespace(snapshot=lambda options=None: {'revision': 1, 'capabilities': {'min_images': 0, 'max_images': 12}})
        self.speech = SimpleNamespace(snapshot=lambda: {'revision': 1, 'capabilities': {'min_images': 1, 'max_images': 1}})
        self.lipsync = SimpleNamespace(snapshot=lambda: {'revision': 1, 'capabilities': {'min_images': 2, 'max_images': 2}})
        with store.lock:
            store.conn.execute('CREATE TABLE generation_jobs(id TEXT,project_id TEXT,source_node_id TEXT,status TEXT)')
            store.conn.commit()

    def create(self, request, **kwargs):
        found = next((j for j in self.jobs.values() if j['request']['request_id'] == request['request_id']), None)
        if found:
            assert found['request'] == request
            return copy.deepcopy(found)
        self._validate_request(request)
        identity = 'job-' + str(len(self.jobs))
        job = {'id': identity, 'status': 'pending', 'request': copy.deepcopy(request), 'outputs': []}
        self.jobs[identity] = job
        self.requests.append(copy.deepcopy(request))
        return copy.deepcopy(job)

    def get(self, identity):
        return copy.deepcopy(self.jobs[identity])

    def cancel(self, identity, interrupt_running=False):
        job = self.jobs[identity]
        if job['status'] == 'running':
            raise DomainError(409, '正在执行', 'generation_interrupt_confirmation')
        job['status'] = 'cancelled'
        return copy.deepcopy(job)

    def retry(self, identity, request_id=None):
        return self.create({**self.jobs[identity]['request'], 'request_id': request_id})

    def finish(self, identity, version_id=None, failed=False):
        self.jobs[identity].update(status='failed' if failed else 'succeeded', outputs=[] if failed else [{'version_id': version_id}], error='fixture failure' if failed else None)


@pytest.fixture
def graph(tmp_path):
    store = Store(tmp_path / 'library', tmp_path / 'config.json')
    jobs = Jobs(store)
    service = OrchestrationService(store, jobs)
    project = store.create_project('依赖测试')
    versions = {}
    for kind in ('image', 'video', 'audio'):
        content = (kind + ' isolated fixture').encode()
        source = tmp_path / (kind + '.bin')
        source.write_bytes(content)
        asset = store.ingest(source, kind + '.bin', {'type': kind, 'mime': kind + '/fixture', 'size': len(content), 'width': 256, 'height': 256, 'duration': 5}, hashlib.sha256(content).hexdigest())
        versions[kind] = asset['imported_version_id']
    yield service, jobs, project['id'], versions
    service.close()
    store.close()


def card(identity, kind='image', **draft):
    return {'id': identity, 'type': 'media', 'position': {'x': 0, 'y': 0}, 'data': {'kind': kind, 'title': identity, 'generation': {'mode': 'text_to_image', 'prompt': identity + ' scene', 'references': [], 'parameters': {}, **({'kind': kind} if kind != 'image' else {}), **draft}}}


def put(service, pid, nodes, edges=None):
    canvas = service.store.canvas(pid)
    return service.store.save_canvas(pid, {**canvas, 'nodes': nodes, 'edges': edges or []})


def edge(source, target):
    return {'id': source + '-' + target, 'source': source, 'target': target, 'data': {'role': 'reference'}}


def test_image_video_waits_and_pins_actual_output_then_reuses(graph):
    service, jobs, pid, versions = graph
    put(service, pid, [card('image'), card('video', 'video', video_mode='reference')], [edge('image', 'video')])
    plan = service.plan(pid, {})
    assert plan['valid'], plan['errors']
    assert [s['node_id'] for s in plan['nodes']] == ['image', 'video']
    run = service.create(pid, {'request_id': 'chain', 'revision': 1})
    service.tick()
    assert len(jobs.requests) == 1
    jobs.finish('job-0', versions['image'])
    service.tick()
    assert len(jobs.requests) == 2
    assert jobs.requests[-1]['references'][0]['version_id'] == versions['image']
    jobs.finish('job-1', versions['video'])
    service.tick()
    assert service.get(run['id'])['status'] == 'succeeded'
    # Browser reference reconciliation adds presentation metadata after delivery.
    canvas = service.store.canvas(pid)
    canvas['nodes'][1]['data']['generation']['references'] = [{'id': 'edge-image-video', 'edge_id': 'image-video', 'source': 'connection', 'node_id': 'image', 'version_id': versions['image'], 'title': 'image', 'description': '', 'use_description': True, 'media_type': 'image', 'role': 'reference'}]
    service.store.save_canvas(pid, canvas)
    cached = service.plan(pid, {})
    assert [s['action'] for s in cached['nodes']] == ['reuse', 'reuse']
    again = service.create(pid, {'request_id': 'reuse'})
    service.tick()
    assert service.get(again['id'])['status'] == 'succeeded'
    assert [n['status'] for n in service.get(again['id'])['nodes']] == ['reused', 'reused']
    assert len(jobs.requests) == 2
    forced = service.create(pid, {'request_id': 'force', 'force': True})
    service.tick()
    assert len(jobs.requests) == 3
    assert service.get(forced['id'])['status'] == 'running'


def test_preflight_cycles_missing_inputs_and_selection(graph):
    service, jobs, pid, versions = graph
    put(service, pid, [card('a', mode='reference'), card('b', mode='reference')], [edge('a', 'b'), edge('b', 'a')])
    assert any(e['code'] == 'canvas_run_cycle' for e in service.plan(pid, {})['errors'])
    with pytest.raises(DomainError):
        service.create(pid, {})
    assert not jobs.requests
    put(service, pid, [card('a'), card('b', mode='reference'), card('bad', 'audio')], [edge('a', 'b')])
    plan = service.plan(pid, {'scope': 'downstream', 'node_ids': ['b']})
    assert plan['valid'] and {n['node_id'] for n in plan['nodes']} == {'a', 'b'}
    assert not service.plan(pid, {})['valid']


def test_failure_blocks_downstream_retry_uses_original_snapshot(graph):
    service, jobs, pid, versions = graph
    put(service, pid, [card('a'), card('b', mode='reference')], [edge('a', 'b')])
    run = service.create(pid, {'request_id': 'failure'})
    service.tick()
    jobs.finish('job-0', failed=True)
    service.tick()
    assert [n['status'] for n in service.get(run['id'])['nodes']] == ['failed', 'blocked']
    assert len(jobs.requests) == 1
    canvas = service.store.canvas(pid)
    canvas['nodes'][0]['data']['generation']['prompt'] = 'edited after failure'
    service.store.save_canvas(pid, canvas)
    service.retry(run['id'])
    service.tick()
    assert jobs.requests[-1]['prompt'] == 'a scene'
    jobs.finish('job-1', versions['image'])
    service.tick()
    jobs.finish('job-2', versions['image'])
    service.tick()
    assert service.get(run['id'])['status'] == 'succeeded'
    assert service.plan(pid, {})['nodes'][0]['action'] == 'generate'


def test_restart_after_submission_does_not_duplicate_and_cancel_stops_descendants(graph, monkeypatch):
    service, jobs, pid, versions = graph
    put(service, pid, [card('a'), card('b', mode='reference')], [edge('a', 'b')])
    run = service.create(pid, {'request_id': 'restart'})
    update = service._update
    def crash(run_id, node_id=None, **fields):
        if fields.get('job_id'):
            raise KeyboardInterrupt('process died after durable submission')
        return update(run_id, node_id, **fields)
    monkeypatch.setattr(service, '_update', crash)
    with pytest.raises(KeyboardInterrupt):
        service.tick()
    recovered = OrchestrationService(service.store, jobs)
    recovered.tick()
    assert len(jobs.requests) == 1
    jobs.jobs['job-0']['status'] = 'running'
    recovered.cancel(run['id'])
    recovered.tick()
    assert recovered.get(run['id'])['status'] == 'cancelling'
    jobs.finish('job-0', versions['image'])
    recovered.tick()
    assert recovered.get(run['id'])['status'] == 'cancelled'
    assert len(jobs.requests) == 1


def test_cas_idempotency_and_reference_only_inputs(graph):
    service, jobs, pid, versions = graph
    put(service, pid, [card('a'), card('voice', 'audio', references=[{'version_id': versions['audio'], 'media_type': 'audio'}])])
    with pytest.raises(DomainError) as error:
        service.create(pid, {'revision': 0, 'request_id': 'cas'})
    assert error.value.detail['code'] == 'revision_conflict'
    assert not jobs.requests
    payload = {'revision': 1, 'request_id': 'cas'}
    run = service.create(pid, payload)
    canvas = service.store.canvas(pid)
    canvas['nodes'][0]['position']['x'] = 500
    service.store.save_canvas(pid, canvas)
    assert service.create(pid, payload)['id'] == run['id']
    service.tick()
    assert len(jobs.requests) == 2
    assert jobs.requests[1]['references'][0]['version_id'] == versions['audio']
    with pytest.raises(DomainError):
        service.create(pid, {**payload, 'force': True})


def test_canvas_run_pins_timed_guide_and_preserves_exact_frame_count(graph):
    service, jobs, pid, versions = graph
    guide = {'version_id': versions['image'], 'media_type': 'image', 'frame_idx': 12}
    put(service, pid, [card('timed', 'video', video_mode='reference', frame_count=73, h3_guides=[guide],
                            references=[{'version_id': versions['video'], 'media_type': 'video'}])])
    plan = service.plan(pid, {})
    assert plan['valid'], plan['errors']
    request = plan['nodes'][0]['request']
    assert request['h3_guides'] == [guide]
    assert request['frame_count'] == 73
    run = service.create(pid, {'request_id': 'timed-guide'})
    pinned = service.store.conn.execute('SELECT version_id FROM canvas_run_inputs WHERE run_id=?', (run['id'],)).fetchall()
    assert {row['version_id'] for row in pinned} == {versions['image'], versions['video']}
    service.tick()
    assert jobs.requests[0]['h3_guides'] == [guide]
    assert jobs.requests[0]['frame_count'] == 73


def test_real_generation_protocol_image_to_video_and_result_archive(client, generation, av_bytes, monkeypatch, tmp_path):
    from manju.transfers import export_project, import_project
    generations, peer = generation
    if getattr(client.app.state, 'orchestration', None):
        client.app.state.orchestration.close()
    combined = catalog()
    for name, info in h3_catalog().items():
        if name not in combined:
            combined[name] = info
        else:
            for field, value in info.get('input', {}).get('required', {}).items():
                previous = combined[name].get('input', {}).get('required', {}).get(field)
                if previous and isinstance(previous[0], list) and isinstance(value[0], list):
                    value = [list(dict.fromkeys(previous[0] + value[0]))]
                combined[name].setdefault('input', {}).setdefault('required', {})[field] = value
    monkeypatch.setattr(generations.workflows, 'object_info', lambda: combined)
    service = OrchestrationService(generations.store, generations)
    pid = project(client)['id']
    put(service, pid, [card('image', parameters={'width': 512, 'height': 512, 'steps': 4}), card('video', 'video', video_mode='reference', parameters={'width': 256, 'height': 256, 'steps': 1})], [edge('image', 'video')])
    run = service.create(pid, {'request_id': 'protocol'})
    service.tick()
    generations.tick()
    first = generations.list(pid)[0]
    assert first['status'] == 'queued', first['error']
    assert len(peer.submissions) == 1
    peer.complete(first['prompt_id'])
    generations.tick()
    actual_image = generations.get(first['id'])['outputs'][0]['version_id']
    service.tick()
    video = next(j for j in generations.list(pid) if j['request'].get('kind') == 'video')
    assert video['request']['references'][0]['version_id'] == actual_image
    assert video['request']['references'][0]['snapshot']['hash'] == service.store.version(actual_image)['hash']
    generations.tick()
    video = generations.get(video['id'])
    assert video['status'] == 'queued', video
    peer.image = av_bytes[0]
    generations._collect(video, {'outputs': {'save': {'videos': [{'filename': 'result.mp4', 'type': 'output'}]}}})
    service.tick()
    result = service.get(run['id'])
    assert result['status'] == 'succeeded', result
    assert service.store.canvas(pid)['nodes'][1]['data']['asset_version_id'] == result['nodes'][1]['output_version_id']
    with pytest.raises(DomainError):
        # Running guards are covered separately; completed output remains a normal project reference.
        service.store.trash_asset(service.store.version(actual_image)['asset_id'])
    target = Store(tmp_path / 'restored', tmp_path / 'restored.json')
    try:
        restored = import_project(target, export_project(service.store, pid))
        nodes = target.canvas(restored['id'])['nodes']
        assert target.version(nodes[1]['data']['asset_version_id'])['hash'] == service.store.version(result['nodes'][1]['output_version_id'])['hash']
        assert target.conn.execute("SELECT 1 FROM sqlite_master WHERE name='canvas_runs'").fetchone() is None
    finally:
        target.close()


def test_lipsync_accepts_waiting_video_and_audio_roles(graph):
    service, jobs, pid, versions = graph
    put(service, pid, [card('video', 'video', video_mode='text'), card('voice', 'audio', references=[{'version_id': versions['audio'], 'media_type': 'audio'}]),
                       card('sync', 'video', workflow_id='builtin-latentsync15-local', lip_sync_options={'audio_offset': 0})],
        [edge('video', 'sync'), edge('voice', 'sync')])
    plan = service.plan(pid, {})
    assert plan['valid'], plan['errors']
    run = service.create(pid, {})
    service.tick()
    assert len(jobs.requests) == 2
    for job in list(jobs.jobs.values()):
        jobs.finish(job['id'], versions['video'] if job['request']['kind'] == 'video' else versions['audio'])
    service.tick()
    request = jobs.requests[-1]
    assert request['workflow_id'] == 'builtin-latentsync15-local'
    assert {r['role']: r['version_id'] for r in request['references']} == {'video': versions['video'], 'audio': versions['audio']}
    jobs.finish('job-2', versions['video'])
    service.tick()
    assert service.get(run['id'])['status'] == 'succeeded'


@pytest.mark.parametrize(('workflow_id', 'options'), [
    ('builtin-video-interpolate-local', {'method': 'hold', 'fps': 48, 'cuts': []}),
    ('builtin-video-upscale-local', {'method': 'remacri', 'width': 1024, 'height': 576}),
])
def test_video_enhancement_reads_legacy_canvas_draft(graph, workflow_id, options):
    service, jobs, pid, versions = graph
    jobs.video_adapter = lambda request: SimpleNamespace(
        snapshot=lambda: {'revision': 2, 'capabilities': {'min_images': 1, 'max_images': 1}}
    )
    legacy = {'parameters': {'width': 864, 'height': 480, 'steps': 20},
              'video_options': {'engine': 'native'}, 'video_mode': 'frames', 'duration': 4, 'audio': True,
              'h3_guides': [{'version_id': versions['image'], 'media_type': 'image', 'frame_idx': 0}], 'frame_count': 90}
    source = {'id': 'clip', 'type': 'media', 'position': {'x': 0, 'y': 0},
              'data': {'kind': 'video', 'asset_version_id': versions['video']}}
    put(service, pid, [source, card('post', 'video', workflow_id=workflow_id, enhance_options=options, **legacy)],
        [edge('clip', 'post')])

    plan = service.plan(pid, {})
    assert plan['valid'], plan['errors']
    request = plan['nodes'][0]['request']
    assert request['parameters'] == {}
    assert not (legacy.keys() - {'parameters'}) & request.keys()
    assert request['enhance_options'] == options
    assert [(ref['version_id'], ref['edge_id'], ref['role']) for ref in request['references']] == [
        (versions['video'], 'clip-post', 'reference')
    ]
    with pytest.raises(DomainError) as error:
        GenerationService._validate_request({**request, **legacy})
    assert error.value.detail['code'] == 'video_enhance_parameters'

    service.create(pid, {})
    service.tick()
    assert jobs.requests[-1]['enhance_options'] == options
    persisted = service.store.canvas(pid)['nodes'][1]['data']['generation']
    assert {key: persisted[key] for key in legacy} == legacy


def test_pending_run_guards_fixed_inputs_and_project(graph):
    service, jobs, pid, versions = graph
    put(service, pid, [card('voice', 'audio', references=[{'version_id': versions['audio'], 'media_type': 'audio'}])])
    run = service.create(pid, {'request_id': 'guard'})
    with pytest.raises(DomainError) as error:
        service.store.trash_project(pid)
    assert error.value.detail['code'] == 'orchestration_in_progress'
    asset_id = service.store.version(versions['audio'])['asset_id']
    with pytest.raises(DomainError) as error:
        service.store._guard_orchestration(asset_id=asset_id)
    assert error.value.detail['code'] == 'orchestration_in_progress'
    service.cancel(run['id'])
    service.tick()
    assert service.get(run['id'])['status'] == 'cancelled'
    service.store._guard_orchestration(asset_id=asset_id)
