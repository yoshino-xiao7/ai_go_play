import pytest
from conftest import project
from test_generation import generation
from test_video import video_service, h3_catalog, request


def test_unified_catalog_keeps_image_clients_compatible(client,video_service):
    images=client.get('/api/workflows').json()['items']
    assert all(item['mode']!='video' for item in images)
    all_items=client.get('/api/workflows?include_video=true').json()['items']
    assert len(all_items)==len(images)+1
    video=all_items[-1]
    assert video['id']=='builtin-h3-local' and video['ready']
    assert len(client.get('/api/workflows?include_video=true&mode=video').json()['items'])==1


def test_defaults_reach_actual_graph_and_repeated_request_is_stable(client,video_service):
    service,peer=video_service
    p=project(client)
    profile=client.get('/api/video/settings').json()
    defaults={**profile['defaults'],'steps':7,'cfg':3,'duration':6,'audio':False}
    saved=client.put('/api/video/settings',json={**profile,'defaults':defaults})
    assert saved.status_code==200,saved.text
    payload=request(p['id'],parameters={'width':256,'height':256,'seed':12},request_id='defaults-test')
    job=client.post('/api/generations',json=payload)
    assert job.status_code==202,job.text
    assert job.json()['request']['parameters']['steps']==7
    assert job.json()['request']['duration']==6 and not job.json()['request']['audio']
    changed=client.put('/api/video/settings',json={**saved.json(),'defaults':{**defaults,'steps':9}})
    assert changed.status_code==200
    again=client.post('/api/generations',json=payload)
    assert again.status_code==202 and again.json()['id']==job.json()['id']
    service.tick()
    result=service.get(job.json()['id'])
    assert result['mapped_graph']['sample']['inputs']['steps']==7
    assert 'audio' not in result['mapped_graph']['video']['inputs']
    assert client.put('/api/video/settings',json=saved.json()).status_code==409


@pytest.mark.parametrize('change',[{'duration':True},{'seed':1.5},{'cfg':21},{'width':257},{'height':2000},{'audio':'yes'},{'unknown':1}])
def test_invalid_defaults_do_not_write(client,video_service,change):
    before=client.get('/api/video/settings').json()
    response=client.put('/api/video/settings',json={**before,'defaults':{**before['defaults'],**change}})
    assert response.status_code==422,response.text
    assert client.get('/api/video/settings').json()['revision']==before['revision']


def test_legacy_model_update_preserves_defaults(client,video_service):
    profile=client.get('/api/video/settings').json()
    profile['defaults']['duration']=8
    saved=client.put('/api/video/settings',json=profile).json()
    response=client.put('/api/video/settings',json={'revision':saved['revision'],'models':saved['models']})
    assert response.json()['defaults']['duration']==8


def test_three_graph_templates_offline_and_no_submission(client,video_service,monkeypatch):
    service,peer=video_service
    for mode in ('text','frames','reference'):
        result=client.get('/api/video/workflow',params={'mode':mode})
        assert result.status_code==200,result.text
        template=result.json();graph=template['api_graph']
        assert graph['save']['class_type']=='SaveVideo'
        assert graph['condition']['class_type']==('MiniMaxH3ReferenceToVideo' if mode=='reference' else 'MiniMaxH3ImageToVideo')
        assert len(template['placeholder_files'])=={'text':0,'frames':2,'reference':3}[mode]
    assert not service.list()
    monkeypatch.setattr(service.workflows,'object_info',lambda:(_ for _ in ()).throw(RuntimeError('offline')))
    assert not client.get('/api/workflows?include_video=true').json()['items'][-1]['ready']
    assert client.get('/api/video/workflow?mode=reference').status_code==200
    assert client.get('/api/video/workflow?mode=unknown').status_code==422


def test_existing_video_settings_upgrade_and_reopen_preserve_values(client,video_service):
    from manju.video import H3Adapter, DEFAULTS
    service,_=video_service
    profile=client.get('/api/video/settings').json()
    saved=client.put('/api/video/settings',json=profile).json()
    with service.store.tx():
        service.store.conn.execute('ALTER TABLE video_settings DROP COLUMN defaults')
    upgraded=H3Adapter(service.store,service.workflows)
    assert upgraded.settings()=={'revision':saved['revision'],'models':saved['models'],'defaults':DEFAULTS}
    updated=upgraded.update({**upgraded.settings(),'defaults':{**DEFAULTS,'duration':9}})
    reopened=H3Adapter(service.store,service.workflows)
    assert reopened.settings()['defaults']['duration']==9
    assert reopened.settings()['revision']==updated['revision']
