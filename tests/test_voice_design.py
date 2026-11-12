"""Voice identity design is independent of dialogue synthesis and never auto-binds."""
import pytest

from conftest import project, upload
from test_generation import generation
from test_video import h3_catalog
from test_speech import advanced_catalog, voice_bytes
from manju.generation import GenerationService
from manju.store import DomainError
from manju.voice_design import PROFILE_ID, AUDITION_TEXT


@pytest.fixture
def designer(generation, monkeypatch):
    service, peer = generation
    monkeypatch.setattr(service.workflows, "object_info", lambda: {**h3_catalog(), "SaveAudio": {}})
    return service, peer


def request(project_id, **extra):
    return {"kind": "audio", "project_id": project_id, "workflow_id": PROFILE_ID,
            "prompt": AUDITION_TEXT, "voice_design_options": {"description": "年轻女性，温润清澈的中音，少量气声。"},
            "references": [], "parameters": {"seed": 42}, **extra}


def test_design_without_recording_and_audio_asset_delivery(client, designer):
    service, peer = designer
    p = project(client)
    assert client.get('/api/voice-design/settings').json()['ready']
    payload = request(p['id'], request_id='design-once')
    response = client.post('/api/generations', json=payload)
    assert response.status_code == 202, response.text
    job = response.json()
    assert job['request']['references'] == []
    assert job['workflow_snapshot']['id'] == PROFILE_ID
    assert job['request']['dialogue_text'] == AUDITION_TEXT
    assert '<d>[Chinese] ' + AUDITION_TEXT + '</d>' in job['request']['compiled_prompt']
    assert client.post('/api/generations', json=payload).json()['id'] == job['id']
    service.tick()
    job = service.get(job['id'])
    assert job['status'] == 'queued', job
    graph = job['mapped_graph']
    assert graph['save']['class_type'] == 'SaveAudio'
    assert graph['save']['inputs']['audio'] == ['audio', 0]
    assert not any(node['class_type'] in ('CreateVideo', 'SaveVideo', 'VAEDecodeTiled', 'LoadAudio') for node in graph.values())
    assert not peer.uploads
    peer.image = voice_bytes(8)
    service._collect(job, {'outputs': {'save': {'audio': [{'filename': 'voice.flac', 'type': 'output'}]}}})
    result = service.get(job['id'])
    assert result['status'] == 'succeeded', result
    version = service.store.version(result['outputs'][0]['version_id'])
    assert version['mime'].startswith('audio/')
    assert service.store.canvas(p['id'])['nodes'][0]['data']['kind'] == 'audio'


def test_portrait_frozen_retry_and_existing_binding_unchanged(client, designer, png_bytes):
    service, _ = designer
    p = project(client)
    portrait = upload(client, png_bytes())['current_version_id']
    voice = upload(client, voice_bytes(), 'existing.wav')['current_version_id']
    canvas = service.store.canvas(p['id'])
    canvas['nodes'] = [{'id': 'character', 'type': 'subject', 'position': {'x': 0, 'y': 0}, 'data': {
        'kind': 'image', 'asset_version_id': portrait,
        'subject': {'kind': 'character', 'name': '小雨', 'image_version_ids': [portrait], 'voice_version_id': voice}}}]
    service.store.save_canvas(p['id'], canvas)
    job = service.create(request(p['id'], subject_node_id='character', references=[{'version_id': portrait}]))
    assert job['request']['references'][0]['snapshot']['mime'].startswith('image/')
    assert service.store.canvas(p['id'])['nodes'][0]['data']['subject']['voice_version_id'] == voice
    service.tick()
    graph = service.get(job['id'])['mapped_graph']
    assert graph['condition']['class_type'] == 'MiniMaxH3ReferenceToVideo'
    assert graph['condition']['inputs']['ref_images.ref_image_1'] == ['input_image_1', 0]
    service._update(job['id'], status='failed')
    retry = service.retry(job['id'], 'voice-retry')
    assert retry['request']['parameters'] == job['request']['parameters']
    assert retry['workflow_snapshot']['models'] == job['workflow_snapshot']['models']
    assert retry['request']['references'][0]['version_id'] == portrait


def test_character_auditions_stay_in_assets_and_can_be_bound_for_speech(client, designer, monkeypatch):
    service, peer = designer
    p = project(client)
    project_id = p["id"]
    original_voice = upload(client, voice_bytes(), "original.wav")["current_version_id"]
    canvas = service.store.canvas(project_id)
    canvas["nodes"] = [{"id": "character", "type": "subject", "position": {"x": 0, "y": 0}, "data": {
        "kind": "image",
        "subject": {"kind": "character", "name": "小雨", "image_version_ids": [], "voice_version_id": original_voice},
    }}]
    before = service.store.save_canvas(project_id, canvas)
    job = service.create(request(project_id, subject_node_id="character"))
    peer.image = voice_bytes(8, 2000)
    result = {"outputs": {"save": {"audio": [{"filename": "candidate.wav", "type": "output"}]}}}
    service._collect(job, result)
    delivered = service.get(job["id"])
    output = delivered["outputs"][0]
    assert delivered["status"] == "succeeded"
    assert output["node_id"] is None
    assert service.store.canvas(project_id) == before

    service._collect(job, result)
    assert service.get(job["id"])["outputs"] == delivered["outputs"]
    assert service.store.canvas(project_id) == before
    assert client.get(f"/api/media/{output['version_id']}").content == peer.image
    assets = client.get("/api/assets", params={"project_id": project_id, "type": "audio"}).json()["items"]
    assert output["asset_id"] in {asset["id"] for asset in assets}

    canvas = service.store.canvas(project_id)
    canvas["nodes"][0]["data"]["subject"].update(
        voice_version_id=output["version_id"], voice_name="小雨 · 专属音色", voice_transcript=AUDITION_TEXT,
    )
    saved = client.put(f"/api/projects/{project_id}/canvas", json=canvas)
    assert saved.status_code == 200, saved.text
    assert client.delete(f"/api/assets/{output['asset_id']}").status_code == 409

    monkeypatch.setattr(service.workflows, "object_info", advanced_catalog)
    speech = service.create({
        "kind": "audio", "project_id": project_id, "subject_node_id": "character", "prompt": "明天我们再见。",
    })
    assert speech["request"]["references"][0]["version_id"] == output["version_id"]
    service.tick()
    assert service.get(speech["id"])["status"] == "queued"
    assert peer.uploads[-1]["content"] == peer.image


@pytest.mark.parametrize('changes', [
    {'voice_design_options': {}}, {'voice_design_options': {'description': '  '}},
    {'voice_design_options': {'description': 'a', 'emotion': 'sad'}},
    {'prompt': '太短'}, {'prompt': '字' * 51}, {'provider': 'openai'},
    {'parameters': {'steps': 1}}, {'references': [{'version_id': 'a'}, {'version_id': 'b'}]},
])
def test_rejects_invalid_design(changes):
    with pytest.raises(DomainError):
        GenerationService._validate_request(request('p', **changes))


def test_no_audio_reference_or_silent_fallback(client, designer, monkeypatch):
    service, _ = designer
    p = project(client)
    audio = upload(client, voice_bytes(), 'reference.wav')['current_version_id']
    response = client.post('/api/generations', json=request(p['id'], references=[{'version_id': audio}]))
    assert response.status_code == 422
    assert response.json()['detail']['code'] == 'voice_design_portrait_required'
    monkeypatch.setattr(service.workflows, 'object_info', h3_catalog)
    assert not client.get('/api/voice-design/settings').json()['ready']
    assert client.post('/api/generations', json=request(p['id'])).status_code == 422


def test_video_voice_reference_preserves_native_audio_and_current_delivery(client, designer):
    service, _ = designer
    p = project(client)
    audio = upload(client, voice_bytes(), 'identity.wav')['current_version_id']
    job = service.create({'kind': 'video', 'project_id': p['id'], 'workflow_id': 'builtin-h3-local',
        'prompt': '她哽咽着说：妈，我回来了。', 'video_mode': 'reference', 'audio': True,
        'references': [{'version_id': audio, 'purpose': 'voice'}], 'parameters': {'seed': 20}})
    assert 'NEW dialogue' in job['request']['compiled_prompt']
    assert 'Do not copy the reference words' in job['request']['compiled_prompt']
    service.tick()
    graph = service.get(job['id'])['mapped_graph']
    assert graph['video']['inputs']['audio'] == ['audio', 0]
    assert graph['audio']['inputs']['samples'] == ['split', 1]


def test_voice_identity_is_assigned_to_its_character_picture(client, designer, png_bytes):
    service, _ = designer
    p = project(client)
    a = upload(client, png_bytes('red'))['current_version_id']
    b = upload(client, png_bytes('blue'))['current_version_id']
    voice = upload(client, voice_bytes(), 'identity.wav')['current_version_id']
    job = service.create({'kind': 'video', 'project_id': p['id'], 'workflow_id': 'builtin-h3-local',
        'prompt': 'Two characters have a conversation.', 'video_mode': 'reference',
        'references': [{'id': 'other', 'node_id': 'other', 'version_id': a, 'purpose': 'identity'},
                       {'id': 'speaker', 'node_id': 'speaker', 'version_id': b, 'purpose': 'identity'},
                       {'id': 'voice', 'node_id': 'speaker', 'version_id': voice, 'purpose': 'voice'}]})
    assert '<Audio 1> provides the voice identity of the character shown in <Picture 2>.' in job['request']['compiled_prompt']
