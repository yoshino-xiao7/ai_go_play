import copy
import json

import pytest

from conftest import project, upload
from manju.speech import ENGINE, NODE
from manju.store import DomainError
from test_generation import generation
from test_speech import voice_bytes
from test_video import av_bytes, h3_catalog


@pytest.fixture
def batch(client, generation, monkeypatch):
    service, peer = generation
    catalog = h3_catalog()
    catalog.update({NODE: {'input': {'required': {'model': [[ENGINE]]}}}, 'LoadAudio': {}, 'SaveAudio': {}})
    monkeypatch.setattr(service.workflows, 'object_info', lambda: catalog)
    pid = project(client)['id']
    voice = upload(client, voice_bytes(), 'narrator.wav')['current_version_id']
    canvas = service.store.canvas(pid)
    canvas['nodes'] = [
        {'id':'v','type':'media','position':{'x':0,'y':0},'data':{'kind':'video','generation':{'kind':'video','mode':'text_to_image','workflow_id':'builtin-h3-local','prompt':'雨夜车站，女孩抬头。','references':[],'video_mode':'text','duration':6,'audio':False,'parameters':{'width':256,'height':256,'steps':1,'seed':42}}}},
        {'id':'a','type':'media','position':{'x':350,'y':0},'data':{'kind':'audio','generation':{'kind':'audio','mode':'text_to_image','workflow_id':'builtin-indextts25-local','prompt':'这是旧台词。','prompt_parts':[{'type':'text','text':'这是旧台词。'}],'references':[{'id':'voice','version_id':voice,'title':'旁白','media_type':'audio','source':'mention'}],'parameters':{'seed':42},'speech_options':{'language':'zh','speed':1,'emotion':'reference','intensity':.5}}}},
    ]
    service.store.save_canvas(pid, canvas)
    document = client.app.state.production.save(pid, {'revision':1,'settings':{'width':864,'height':480,'fps':24},'shots':[{'id':'shot-1','title':'归来','duration':5,'dialogue':'别怕，我来接你回家。','video_node_id':'v','audio_node_id':'a'}]})
    return pid, service, peer, voice, document


def test_batch_idempotency_active_sources_and_dialogue_snapshot(client, batch):
    pid, service, peer, _, _ = batch
    path = f'/api/projects/{pid}/production/generate'
    payload = {'request_id':'batch-one','kinds':['video','audio']}
    result = client.post(path, json=payload)
    assert result.status_code == 202, result.text
    data = result.json()
    assert len(data['jobs']) == 2 and not data['errors']
    assert client.post(path,json=payload).json() == data
    assert len(service.list(pid)) == 2
    later = client.post(path,json={**payload,'request_id':'batch-two'}).json()
    assert not later['jobs'] and len(later['skipped']) == 2
    audio = next(job for job in data['jobs'] if job['request']['kind'] == 'audio')
    assert audio['request']['compiled_prompt'] == '别怕，我来接你回家。'
    source = next(n for n in service.store.canvas(pid)['nodes'] if n['id'] == 'a')
    assert source['data']['generation']['prompt'] == audio['request']['prompt']
    assert source['data']['generation']['prompt_parts'] == [{'type':'text','text':'别怕，我来接你回家。'}]
    assert not peer.submissions  # creating durable jobs does not run a real generation


def test_batch_keeps_adopted_versions_and_project_scopes_keys(client, batch, av_bytes):
    pid, service, _, _, document = batch
    adopted = upload(client, av_bytes[0], 'adopted.mp4')['current_version_id']
    current = client.app.state.production.get(pid)
    current['shots'][0]['video_version_id'] = adopted
    client.app.state.production.save(pid, current)
    result = client.post(f'/api/projects/{pid}/production/generate',json={'request_id':'shared-key','kinds':['video','audio']}).json()
    assert len(result['jobs']) == 1 and len(result['skipped']) == 1
    assert client.app.state.production.get(pid)['shots'][0]['video_version_id'] == adopted
    duplicate = service.store.duplicate_project(pid)
    copied = client.post(f'/api/projects/{duplicate["id"]}/production/generate',json={'request_id':'shared-key','kinds':['video','audio']}).json()
    assert not copied['errors'] and len(copied['jobs']) == 1
    assert copied['jobs'][0]['request_id'] != result['jobs'][0]['request_id']
    regenerated = client.post(f'/api/projects/{pid}/production/generate',json={'request_id':'regenerate-video','kinds':['video'],'only_missing':False}).json()
    assert len(regenerated['jobs']) == 1 and regenerated['jobs'][0]['request']['result_policy'] == 'review'
    assert client.app.state.production.get(pid)['shots'][0]['video_version_id'] == adopted


def test_batch_skips_unknown_and_archive_preserves_source_and_fixed_inputs(client, batch, av_bytes):
    pid, service, _, voice, _ = batch
    submitted = client.post(f'/api/projects/{pid}/production/generate',json={'request_id':'unknown-first','kinds':['audio']}).json()['jobs'][0]
    service._update(submitted['id'],status='unknown',message='模拟响应丢失')
    result = client.post(f'/api/projects/{pid}/production/generate',json={'request_id':'unknown-second','kinds':['audio']}).json()
    assert not result['jobs'] and result['skipped'][0]['job_id'] == submitted['id']
    adopted = upload(client, av_bytes[0], 'fixed.mp4')['current_version_id']
    current = client.app.state.production.get(pid)
    current['shots'][0].update(video_version_id=adopted,audio_version_id=voice)
    client.app.state.production.save(pid,current)
    archive = client.get(f'/api/projects/{pid}/export')
    assert archive.status_code == 200, archive.text
    imported = client.post('/api/projects/import',files={'file':('shots.manju',archive.content,'application/zip')})
    assert imported.status_code == 201, imported.text
    copy_id = imported.json()['id']
    copied = client.app.state.production.get(copy_id)['shots'][0]
    assert copied['video_node_id'] == 'v' and copied['audio_node_id'] == 'a'
    assert copied['video_version_id'] != adopted and copied['audio_version_id'] != voice
    assert service.store.version(copied['video_version_id'])['hash'] == service.store.version(adopted)['hash']
    canvas = service.store.canvas(copy_id)
    source = next(n for n in canvas['nodes'] if n['id'] == 'a')
    assert source['data']['generation']['references'][0]['version_id'] == copied['audio_version_id']
    assert not source['data']['generation'].get('last_job_id')


def test_batch_video_covers_shot_duration_and_rejects_overlong_shot(client, batch):
    pid, service, _, _, _ = batch
    canvas = service.store.canvas(pid)
    next(n for n in canvas['nodes'] if n['id'] == 'v')['data']['generation']['duration'] = 4
    service.store.save_canvas(pid, canvas)
    result = client.post(f'/api/projects/{pid}/production/generate',json={'request_id':'cover-duration','kinds':['video']}).json()
    assert result['jobs'][0]['request']['duration'] == 5
    assert next(n for n in service.store.canvas(pid)['nodes'] if n['id'] == 'v')['data']['generation']['duration'] == 5
    service._update(result['jobs'][0]['id'],status='cancelled')
    current = client.app.state.production.get(pid)
    current['shots'][0]['duration'] = 16
    client.app.state.production.save(pid,current)
    rejected = client.post(f'/api/projects/{pid}/production/generate',json={'request_id':'too-long','kinds':['video']}).json()
    assert not rejected['jobs'] and rejected['errors'][0]['code'] == 'production_generation_too_long'


def test_batch_revision_checked_before_any_submission_and_idempotent_replay(client, batch):
    pid, service, _, _, document = batch
    path = f'/api/projects/{pid}/production/generate'
    original_revision = document['revision']
    canvas = service.store.canvas(pid)
    next(n for n in canvas['nodes'] if n['id'] == 'a')['data']['generation']['prompt'] = '另一个窗口刚修改的台词'
    service.store.save_canvas(pid, canvas)
    current_revision = service.store.canvas(pid)['revision']
    stale = client.post(path, json={'request_id':'stale-batch','revision':original_revision,'kinds':['video','audio']})
    assert stale.status_code == 409
    assert stale.json()['detail']['code'] == 'revision_conflict'
    assert not service.list(pid), 'A stale batch must not partially enqueue expensive jobs'
    payload = {'request_id':'current-batch','revision':current_revision,'kinds':['video','audio']}
    response = client.post(path,json=payload)
    assert response.status_code == 202,response.text
    result = response.json()
    assert len(result['jobs']) == 2
    assert service.store.canvas(pid)['revision'] > current_revision
    replay = client.post(path,json=payload)
    assert replay.status_code == 202 and replay.json() == result
    assert len(service.list(pid)) == 2
