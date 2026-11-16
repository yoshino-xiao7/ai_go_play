import hashlib
import json
import os
import threading
import time
from pathlib import Path

import httpx
import pytest

from manju.setup_catalog import catalog, share_inventory, match_share
from manju.setup_jobs import SetupJobs, SetupCancelled
from manju.setup_models import import_files, verify_files
from manju.setup_readiness import check_packs
from manju.store import DomainError


class Job:
    def check_cancelled(self): pass
    def update(self, **values): pass


def model(data=b'valid-model'):
    return {'path': 'vae/demo.bin', 'size': len(data), 'sha256': hashlib.sha256(data).hexdigest(), 'packs': ['02-h3-image']}


def test_download_mirror_preserves_catalog_and_legacy_scan(tmp_path):
    release = tmp_path / 'release'
    release.mkdir()
    (release / 'models.json').write_text(json.dumps({'packs': [{'id': '02-h3-image', 'name': 'H3'}], 'files': [model()]}))
    (release / 'model-checksums.sha256').write_text(model()['sha256'] + '  vae/demo.bin\n')
    sources = {'models_share': {'id': 'quark-test', 'url': 'https://pan.quark.cn/s/test', 'passcode': 'test'}}
    source_file = release / 'setup-sources.json'
    source_file.write_text(json.dumps(sources))
    original = catalog(tmp_path)
    assert original['mirrors'] == []
    sources['models_mirrors'] = [{'id': 'baidu', 'name': '百度网盘', 'url': 'https://pan.baidu.com/s/test'}]
    source_file.write_text(json.dumps(sources, ensure_ascii=False), encoding='utf-8')
    updated = catalog(tmp_path)
    assert updated['mirrors'] == sources['models_mirrors']
    assert updated['share'] == original['share']
    assert updated['files'] == original['files']
    assert updated['files'][0]['download_path'] == '02-h3-image/models/vae/demo.bin'


def test_import_quark_layout_verified_without_moving_or_overwriting(tmp_path):
    source = tmp_path / 'download/ai-go-play/02-h3-image/models/vae/demo.bin'
    source.parent.mkdir(parents=True)
    source.write_bytes(b'valid-model')
    root = tmp_path / 'destination'
    result = import_files([model()], root, [tmp_path / 'download'], Job())
    assert result['imported'] == ['vae/demo.bin']
    assert source.read_bytes() == b'valid-model'
    assert verify_files([model()], root, Job())['verified'] == 1
    (root / 'vae/demo.bin').write_bytes(b'other-model')
    assert import_files([model()], root, [tmp_path / 'download'], Job())['conflicts'] == ['vae/demo.bin']
    assert (root / 'vae/demo.bin').read_bytes() == b'other-model'


def test_scan_offers_only_merged_root_and_verify_reuses_it_on_a_full_disk(client, tmp_path, monkeypatch):
    service = client.app.state.setup
    fixture = model()
    service.catalog['files'] = [fixture]
    packed = tmp_path / 'packed/02-h3-image/models/vae/demo.bin'
    merged = tmp_path / 'download/models/vae/demo.bin'
    for file in (packed, merged):
        file.parent.mkdir(parents=True)
        file.write_bytes(b'valid-model')
    destination = tmp_path / 'destination'
    monkeypatch.setattr('manju.setup_models.shutil.disk_usage', lambda _: type('Disk', (), {'free': 0})())
    assert client.patch('/api/setup', json={
        'step': 'models', 'packs': fixture['packs'], 'models_root': str(destination),
        'import_sources': [str(tmp_path / 'packed'), str(tmp_path / 'download')],
    }).is_success

    scan = client.get('/api/setup/models').json()
    assert scan['import_disk_full'] is True
    assert scan['copy_bytes'] == fixture['size']
    assert scan['reusable_roots'] == [{'path': str(merged.parents[1]), 'matched': 1, 'total': 1}]

    assert client.post('/api/setup/jobs', json={'kind': 'import'}).status_code == 202
    service.jobs.thread.join(timeout=3)
    failed = client.get('/api/setup').json()['job']
    assert failed['error_code'] == 'setup_disk_full'
    assert '直接使用并校验' in failed['error']

    assert client.patch('/api/setup', json={'step': 'verify', 'models_root': str(merged.parents[1])}).is_success
    assert client.post('/api/setup/jobs', json={'kind': 'verify'}).status_code == 202
    service.jobs.thread.join(timeout=3)
    result = client.get('/api/setup').json()
    assert result['step'] == 'verify'
    assert result['validation']['verified'] == 1
    assert not (destination / fixture['path']).exists()
    assert merged.read_bytes() == b'valid-model'


def test_corrupt_source_is_not_committed(tmp_path):
    source = tmp_path / 'download/vae/demo.bin'
    source.parent.mkdir(parents=True)
    source.write_bytes(b'wrong-model')
    root = tmp_path / 'destination'
    assert import_files([model()], root, [source.parents[1]], Job())['conflicts']
    assert not (root / 'vae/demo.bin').exists()
    assert not list(root.rglob('*.partial'))


def test_cancel_import_removes_partial_and_keeps_source(tmp_path):
    data = b'x' * (9 * 1024**2)
    source = tmp_path / 'source/vae/demo.bin'
    source.parent.mkdir(parents=True)
    source.write_bytes(data)
    class Cancel(Job):
        calls = 0
        def check_cancelled(self):
            self.calls += 1
            if self.calls == 3: raise SetupCancelled()
    root = tmp_path / 'models'
    with pytest.raises(SetupCancelled): import_files([model(data)], root, [source.parents[1]], Cancel())
    assert source.stat().st_size == len(data)
    assert not (root / 'vae/demo.bin').exists()
    assert not list(root.rglob('*.partial'))


def test_import_rejects_target_link_escape(tmp_path):
    root, outside = tmp_path / 'models', tmp_path / 'outside'
    root.mkdir(); outside.mkdir()
    try: (root / 'vae').symlink_to(outside, target_is_directory=True)
    except OSError: pytest.skip('symlink creation not permitted')
    with pytest.raises(DomainError, match='外部'):
        import_files([model()], root, [], Job())
    assert not list(outside.iterdir())


def test_job_refresh_cancel_and_restart(tmp_path):
    jobs = SetupJobs(tmp_path)
    entered = threading.Event()
    def run(job):
        entered.set()
        while True:
            job.check_cancelled()
            time.sleep(.01)
    first = jobs.start('import', run)
    assert entered.wait(2)
    assert jobs.snapshot()['id'] == first['id']
    with pytest.raises(DomainError): jobs.start('verify', run)
    jobs.cancel(); jobs.close()
    assert jobs.snapshot()['status'] == 'cancelled'
    saved = json.loads((tmp_path / 'job.json').read_text(encoding='utf-8'))
    saved['status'] = 'running'
    (tmp_path / 'job.json').write_text(json.dumps(saved))
    recovered = SetupJobs(tmp_path)
    assert recovered.snapshot()['status'] == 'interrupted'
    assert not recovered.busy


def test_public_share_scan_uses_public_token_and_matches_models():
    seen = []
    def handle(request):
        seen.append(request)
        if request.url.path.endswith('/token'): return httpx.Response(200, json={'code': 0, 'data': {'stoken': 'public-share-token'}})
        fid = request.url.params['pdir_fid']
        rows = {'0': [{'dir': True, 'fid': 'pack', 'file_name': '02-h3-image'}],
                'pack': [{'dir': True, 'fid': 'models', 'file_name': 'models'}],
                'models': [{'dir': True, 'fid': 'vae', 'file_name': 'vae'}],
                'vae': [{'file_name': 'demo.bin', 'size': 11}]}[fid]
        return httpx.Response(200, json={'code': 0, 'data': {'list': rows}})
    result = share_inventory({'id': 'test', 'passcode': 'code'}, transport=httpx.MockTransport(handle))
    assert match_share([model()], result)[0]['status'] == 'listed'
    assert all('cookie' not in r.headers and 'authorization' not in r.headers for r in seen)
    assert 'public-share-token' not in json.dumps(result)


def test_setup_guest_requires_both_consents_and_is_idempotent(client):
    assert client.get('/api/setup').json()['completed'] is False
    assert client.patch('/api/setup', json={'packs': [], 'step': 'identity'}).status_code == 200
    body = {'mode': 'guest', 'privacy': True, 'manual': False, 'policy_version': '2026-11-13'}
    assert client.post('/api/setup/complete', json=body).status_code == 422
    body['manual'] = True
    first = client.post('/api/setup/complete', json=body)
    assert first.status_code == 200, first.text
    assert first.json()['route'].startswith('/canvas/')
    assert client.post('/api/setup/complete', json=body).json()['route'] == first.json()['route']
    assert len(client.get('/api/projects').json()) == 1


def test_setup_cannot_bypass_missing_models_or_identity(client):
    body = {'mode': 'guest', 'privacy': True, 'manual': True, 'policy_version': '2026-11-13'}
    assert client.post('/api/setup/complete', json=body).status_code == 409
    client.patch('/api/setup', json={'packs': []})
    assert client.post('/api/setup/complete', json={**body, 'mode': 'yike'}).status_code == 409
    assert client.post('/api/setup/complete', json={**body, 'policy_version': 'old'}).status_code == 422


def test_setup_rejects_cross_origin_and_invalid_paths(client):
    assert client.patch('/api/setup', json={'packs': []}, headers={'Origin': 'https://untrusted.example'}).status_code == 403
    assert client.patch('/api/setup', json={'models_root': '../models'}).status_code == 422
    assert client.patch('/api/setup', json={'packs': ['fake']}).status_code == 422
    assert client.patch('/api/setup', json={'completed': True}).json()['completed'] is False


def test_changing_models_invalidates_validation_and_emotion_requires_speech(client, tmp_path):
    service = client.app.state.setup
    service.state['validation'] = {'missing': []}
    value = client.patch('/api/setup', json={'models_root': str(tmp_path / 'new'), 'packs': ['06-indextts-emotion']}).json()
    assert value['validation'] is None
    assert value['packs'] == ['05-indextts', '06-indextts-emotion']


def test_completion_rechecks_verified_files(client, tmp_path, monkeypatch):
    service = client.app.state.setup
    root = tmp_path / 'models'
    path = root / 'vae/demo.bin';path.parent.mkdir(parents=True);path.write_bytes(b'valid-model')
    service.state.update(models_root=str(root), packs=['02-h3-image'], validation=verify_files([model()], root, Job()))
    monkeypatch.setattr(service, 'readiness', lambda: {'ready': True})
    path.write_bytes(b'wrong-model')
    response = client.post('/api/setup/complete', json={'mode':'guest','privacy':True,'manual':True,'policy_version':'2026-11-13'})
    assert response.status_code == 409
    assert service.state['validation'] is None


def test_readiness_requires_actual_runtime_and_emotion_capability():
    nodes = {'ManjuIndexTTS25': {'input': {'required': {'model': [['IndexTTS-2.5']]}, 'optional': {'use_emo_text': [[False]]}}}, 'LoadAudio': {}, 'SaveAudio': {}}
    checked = check_packs(['05-indextts', '06-indextts-emotion', '07-latentsync'], [], nodes)
    assert [row['ready'] for row in checked] == [True, False, False]


def test_install_refuses_running_or_unknown_queue(client, monkeypatch):
    service = client.app.state.setup
    for queue in ({'running': 1, 'pending': 0}, {'running': 0, 'pending': 1}, None):
        monkeypatch.setattr(service.comfy, 'status', lambda: {'status':'running','installation':{'comfy_path':'unused'},'queue':queue})
        with pytest.raises(DomainError) as error: service.install_runtimes(Job())
        assert error.value.detail['code'] == 'setup_comfy_busy'


def test_readiness_requires_new_revision_loaded_after_restart(client, monkeypatch):
    service = client.app.state.setup
    service.state.update(packs=['07-latentsync'], runtime_revision='new-install')
    monkeypatch.setattr(service.comfy, 'status', lambda: {'status':'running','base_url':'http://127.0.0.1:8199'})
    nodes = {'ManjuLatentSync15': {'input': {'required': {'engine': [['LatentSync-1.5']]}}},
             'ManjuSetupRevision': {'input': {'required': {'revision': [['old-install']]}}}}
    original = httpx.Client
    monkeypatch.setattr('manju.setup_service.httpx.Client', lambda **kwargs: original(transport=httpx.MockTransport(lambda request: httpx.Response(200,json=nodes))))
    assert service.readiness()['ready'] is False
    nodes['ManjuSetupRevision']['input']['required']['revision'] = [['new-install']]
    assert service.readiness()['ready'] is True
