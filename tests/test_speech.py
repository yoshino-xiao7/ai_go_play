import io
import wave
import pytest
from conftest import project,upload
from test_generation import generation
from manju.generation import GenerationService
from manju.speech import PROFILE_ID,NODE,ENGINE
from manju.store import DomainError


def advanced_catalog(emotion_text=True):
    return {NODE:{'input':{'required':{'model':[[ENGINE]]},'optional':{
        'emotion_audio':['AUDIO'],'use_emo_text':[[False,True] if emotion_text else [False]],
        'quality':[['studio','standard']],'interval_silence':['INT'],'temperature':['FLOAT']}}},'LoadAudio':{},'SaveAudio':{}}

def voice_bytes(seconds=3,sample=1000):
    data=io.BytesIO()
    with wave.open(data,'wb') as w:
        w.setparams((1,2,16000,0,'NONE','not compressed'))
        w.writeframes(int(sample).to_bytes(2,'little',signed=True)*int(16000*seconds))
    return data.getvalue()

@pytest.fixture
def speech(generation,monkeypatch):
    service,peer=generation
    monkeypatch.setattr(service.workflows,'object_info',lambda:{NODE:{'input':{'required':{'model':[[ENGINE]]}}},'LoadAudio':{},'SaveAudio':{}})
    return service,peer

def request(project_id,**extra):
    return dict(kind='audio',project_id=project_id,prompt='你好，今天我们一起去看星星吧。',references=[],parameters={'seed':42},**extra)

@pytest.mark.parametrize('extra',[{'speech_options':{'speed':0}},{'speech_options':{'speed':True}},{'speech_options':{'speed':float('nan')}},{'speech_options':{'language':'xx'}},{'speech_options':{'emotion':'xx'}},{'speech_options':{'intensity':1}},{'speech_options':{'unknown':1}},{'provider':'openai'},{'workflow_id':'other'},{'mask_version_id':'mask'}])
def test_invalid_speech(extra):
    with pytest.raises(DomainError):GenerationService._validate_request(request('p',subject_node_id='speaker',**extra))

def test_subject_binding_is_real_frozen_audio_and_delivered_to_same_card(client,speech):
    service,peer=speech;p=project(client);a=upload(client,voice_bytes(),'voice.wav');version=a['current_version_id']
    c=service.store.canvas(p['id']);c['nodes']=[{'id':'person','type':'subject','position':{'x':0,'y':0},'data':{'kind':'image','subject':{'name':'小雪','kind':'character','image_version_ids':[],'voice_version_id':version}}},{'id':'speech','type':'media','position':{'x':400,'y':0},'data':{'kind':'audio'}}];c['edges']=[{'id':'ref','source':'person','target':'speech','data':{'role':'reference'}}];service.store.save_canvas(p['id'],c)
    payload=request(p['id'],source_node_id='speech',subject_node_id='person',request_id='speech-one')
    r=client.post('/api/generations',json=payload);assert r.status_code==202,r.text
    job=r.json();assert job['request']['references'][0]['version_id']==version
    assert job['request']['speaker_snapshot']['name']=='小雪'
    # A binding change must not affect an accepted task, retry, or identical request ID.
    c=service.store.canvas(p['id']);c['nodes'][0]['data']['subject']['voice_version_id']=None;service.store.save_canvas(p['id'],c)
    assert client.post('/api/generations',json=payload).json()['id']==job['id']
    service.tick();job=service.get(job['id']);assert job['status']=='queued',job
    assert peer.uploads[0]['content']==voice_bytes()
    assert job['mapped_graph']['speech']['inputs']['reference_audio']==['voice',0]
    assert job['mapped_graph']['speech']['inputs']['text']==payload['prompt']
    peer.image=voice_bytes(4,1500)
    service._collect(job,{'outputs':{'save':{'audio':[{'filename':'speech.wav','type':'output'}]}}})
    saved=service.store.canvas(p['id']);assert len(saved['nodes'])==2
    assert saved['nodes'][1]['data']['kind']=='audio'
    result=saved['nodes'][1]['data']['asset_version_id'];assert service.store.version(result)['mime'].startswith('audio/')
    second=service.create({**job['request'],'request_id':'speech-two'})
    service._collect(second,{'outputs':{'save':{'audio':[{'filename':'other.wav','type':'output'}]}}})
    assert service.store.canvas(p['id'])['nodes'][1]['data']['asset_version_id']==result

def test_reference_name_is_not_spoken_and_invalid_voices_rejected(client,speech,png_bytes):
    service,_=speech;p=project(client);voice=upload(client,voice_bytes(),'voice.wav')
    payload=request(p['id']);payload.update(prompt='@小雪 你好',references=[{'id':'v','version_id':voice['current_version_id'],'title':'小雪'}],prompt_parts=[{'type':'reference','reference_id':'v'},{'type':'text','text':' 你好'}])
    r=client.post('/api/generations',json=payload);assert r.status_code==202,r.text
    assert r.json()['request']['compiled_prompt']=='你好'
    for data,name in [(png_bytes(),'image.png'),(voice_bytes(1),'short.wav'),(voice_bytes(31),'long.wav')]:
        asset=upload(client,data,name)
        bad=request(p['id']);bad['references']=[{'version_id':asset['current_version_id']}]
        assert client.post('/api/generations',json=bad).status_code==422

def test_workflow_catalog_and_settings_cas(client,speech):
    p=client.get('/api/audio/settings').json();assert p['ready']
    assert any(x['id']==PROFILE_ID for x in client.get('/api/workflows?include_audio=true').json()['items'])
    assert [x['id'] for x in client.get('/api/workflows?include_audio=true&mode=audio').json()['items']]==[PROFILE_ID]
    body={'revision':p['revision'],'defaults':{**p['defaults'],'speed':1.25}}
    assert client.put('/api/audio/settings',json=body).status_code==200
    assert client.put('/api/audio/settings',json=body).status_code==409
    assert client.get('/api/audio/workflow').json()['api_graph']['speech']['inputs']['speed']==1.25
    assert client.get('/api/workflows/'+PROFILE_ID).json()['api_graph']['speech']['class_type']==NODE
    assert client.post('/api/workflows/'+PROFILE_ID+'/validate').json()['valid']

def test_audio_draft_and_subject_survive_project_export(client,speech):
    service,_=speech;p=project(client);voice=upload(client,voice_bytes(),'voice.wav');v=voice['current_version_id']
    c=service.store.canvas(p['id']);c['nodes']=[{'id':'a','type':'media','position':{'x':0,'y':0},'data':{'kind':'audio','generation':{'kind':'audio','mode':'text_to_image','workflow_id':PROFILE_ID,'prompt':'明天见','references':[{'version_id':v,'title':'音色','source':'mention'}],'parameters':{'seed':5},'speech_options':{'language':'zh','speed':1.25,'emotion':'happy','intensity':.5}}}}];service.store.save_canvas(p['id'],c)
    exported=client.get(f'/api/projects/{p["id"]}/export');assert exported.status_code==200
    r=client.post('/api/projects/import',files={'file':('配音.manju',exported.content,'application/zip')});assert r.status_code==201,r.text
    imported=service.store.canvas(r.json()['id']);draft=imported['nodes'][0]['data']['generation']
    assert draft['workflow_id']==PROFILE_ID and not draft.get('workflow_import_warning')
    assert draft['speech_options']['emotion']=='happy'
    assert service.store.version(draft['references'][0]['version_id'])['hash']==service.store.version(v)['hash']


@pytest.mark.parametrize('options',[{'quality':'fake'},{'temperature':float('nan')},{'temperature':2},{'interval_silence':-1},
                                    {'interval_silence':True},{'use_emo_text':1},{'use_emo_text':True,'emo_text':''},
                                    {'pronunciation':'妈妈=MA1'},{'pronunciation':'妈妈 MA1 MA5'},
                                    {'pronunciation':'妈妈=MA1 MA5\n妈妈=MA1 MA1'},{'language':'en','pronunciation':'妈妈=MA1 MA5'}])
def test_new_speech_options_reject_invalid_values(options):
    with pytest.raises(DomainError):GenerationService._validate_request(request('p',subject_node_id='speaker',speech_options=options))


def test_voice_and_emotion_references_freeze_separately_and_pronunciation_preserves_dialogue(client,speech,monkeypatch):
    service,peer=speech;monkeypatch.setattr(service.workflows,'object_info',lambda:advanced_catalog())
    p=project(client);voice=upload(client,voice_bytes(3,1000),'speaker.wav');emotion=upload(client,voice_bytes(4,2300),'emotion.wav')
    payload=request(p['id'],speech_options={'pronunciation':'那头=NA4 TOU2\n妈妈=MA1 MA5','quality':'studio','temperature':.75,'interval_silence':350})
    payload.update(prompt='电话那头，妈妈说，别怕。',references=[{'id':'emotion','role':'emotion','version_id':emotion['current_version_id']},
                                                            {'id':'voice','role':'voice','version_id':voice['current_version_id']}])
    response=client.post('/api/generations',json=payload);assert response.status_code==202,response.text
    job=response.json();saved=job['request']
    assert [r['role'] for r in saved['references']]==['voice','emotion']
    assert saved['dialogue_text']==payload['prompt']==saved['prompt']
    assert saved['compiled_prompt']=='电话<那头|NA4 TOU2>，<妈妈|MA1 MA5>说，别怕。'
    assert all(ref['snapshot']['mime'].startswith('audio/') for ref in saved['references'])
    assert service.store.conn.execute('SELECT COUNT(*) FROM generation_inputs WHERE job_id=?',(job['id'],)).fetchone()[0]==2
    service.tick();mapped=service.get(job['id'])['mapped_graph'];inputs=mapped['speech']['inputs']
    assert inputs['reference_audio']==['voice',0] and inputs['emotion_audio']==['emotion',0]
    assert mapped['voice']['inputs']['audio']!=mapped['emotion']['inputs']['audio']
    assert inputs['quality']=='studio' and inputs['temperature']==.75 and inputs['interval_silence']==350
    assert {upload['content'] for upload in peer.uploads}=={voice_bytes(3,1000),voice_bytes(4,2300)}


def test_emotion_text_requires_real_model_and_is_not_spoken(client,speech,monkeypatch):
    service,_=speech;p=project(client);voice=upload(client,voice_bytes(),'voice.wav')
    payload=request(p['id'],speech_options={'use_emo_text':True,'emo_text':'克制的温暖，母亲在安慰女儿','intensity':.4})
    payload['references']=[{'version_id':voice['current_version_id'],'role':'voice'}]
    monkeypatch.setattr(service.workflows,'object_info',lambda:advanced_catalog(False))
    assert client.get('/api/audio/settings').json()['capabilities']['emotion_text'] is False
    failed=client.post('/api/generations',json=payload)
    assert failed.status_code==422 and failed.json()['detail']['code']=='speech_emotion_model_missing'
    monkeypatch.setattr(service.workflows,'object_info',lambda:advanced_catalog(True))
    response=client.post('/api/generations',json=payload);assert response.status_code==202,response.text
    service.tick();job=service.get(response.json()['id']);inputs=job['mapped_graph']['speech']['inputs']
    assert inputs['use_emo_text'] is True and inputs['emo_text']==payload['speech_options']['emo_text']
    assert inputs['text']==payload['prompt'] and inputs['emo_text'] not in inputs['text']
    payload['references'].append({'version_id':voice['current_version_id'],'role':'emotion'})
    assert client.post('/api/generations',json=payload).json()['detail']['code']=='speech_emotion_conflict'


def test_subject_voice_can_be_bound_with_separate_emotion_and_generic_legacy_role(client,speech,monkeypatch):
    service,_=speech;monkeypatch.setattr(service.workflows,'object_info',lambda:advanced_catalog())
    p=project(client);voice=upload(client,voice_bytes(),'voice.wav');emotion=upload(client,voice_bytes(3,2222),'feeling.wav')
    canvas=service.store.canvas(p['id']);canvas['nodes']=[{'id':'person','type':'subject','position':{'x':0,'y':0},'data':{'kind':'image','subject':{'name':'母亲','kind':'character','image_version_ids':[],'voice_version_id':voice['current_version_id']}}}]
    service.store.save_canvas(p['id'],canvas)
    payload=request(p['id'],subject_node_id='person');payload['references']=[{'role':'emotion','version_id':emotion['current_version_id']}]
    response=client.post('/api/generations',json=payload);assert response.status_code==202,response.text
    assert response.json()['request']['references'][0]['version_id']==voice['current_version_id']
    assert response.json()['request']['speaker_snapshot']['name']=='母亲'
    payload['references']=[{'role':'reference','version_id':voice['current_version_id']}]
    assert client.post('/api/generations',json=payload).json()['request']['references'][0]['role']=='voice'
