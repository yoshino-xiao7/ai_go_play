from io import BytesIO
from PIL import Image

from conftest import project, upload


def test_frame_flattens_images_in_layer_order_and_is_idempotent(client, png_bytes):
    pid = project(client)['id']
    red = upload(client, png_bytes('red'))['current_version_id']
    blue = upload(client, png_bytes('blue'))['current_version_id']
    canvas = client.get(f'/api/projects/{pid}/canvas').json()
    canvas['nodes'] = [
        {'id':'f','type':'frame','position':{'x':0,'y':0},'style':{'width':64,'height':48},'data':{'title':'layers'}},
        {'id':'a','type':'media','position':{'x':0,'y':0},'style':{'width':64,'height':48},'data':{'kind':'image','asset_version_id':red}},
        {'id':'b','type':'media','position':{'x':16,'y':12},'style':{'width':32,'height':24},'zIndex':2,'data':{'kind':'image','asset_version_id':blue,'opacity':.5}},
    ]
    assert client.put(f'/api/projects/{pid}/canvas',json=canvas).status_code == 200
    path = f'/api/projects/{pid}/frames/f/render-image'
    result = client.post(path,json={'request_id':'flatten'})
    assert result.status_code == 201, result.text
    assert client.post(path,json={'request_id':'flatten'}).json() == result.json()
    data = client.get('/api/media/'+result.json()['version_id']+'?variant=original').content
    with Image.open(BytesIO(data)) as image:
        assert image.size == (64,48)
        assert image.getpixel((2,2)) == (255,0,0,255)
        assert image.getpixel((20,20))[:3] in ((127,0,128),(128,0,127))
    saved = client.get(f'/api/projects/{pid}/canvas').json()
    assert len(saved['nodes']) == 4


def test_frame_rejects_stale_revision(client):
    pid = project(client)['id']
    result = client.post(f'/api/projects/{pid}/frames/f/render-image',json={'revision':-1})
    assert result.status_code == 409


def test_frame_scope_and_saved_result_recovery(client, png_bytes, monkeypatch):
    from manju.frames import render_frame
    pid = project(client)['id']
    version = upload(client, png_bytes('red'))['current_version_id']
    store = client.app.state.store
    canvas = store.canvas(pid)
    canvas['nodes'] = [
        {'id':'f','type':'frame','position':{'x':0,'y':0},'style':{'width':64,'height':48},'data':{'title':'first'}},
        {'id':'f2','type':'frame','position':{'x':0,'y':0},'style':{'width':64,'height':48},'data':{'title':'second'}},
        {'id':'a','type':'media','position':{'x':0,'y':0},'style':{'width':64,'height':48},'data':{'kind':'image','asset_version_id':version}},
    ]
    store.save_canvas(pid, canvas)
    payload = {'request_id':'same-key','revision':1}
    remember = store.remember_request
    def interrupted(key, route, body, result):
        if route.startswith('frame-render:'):
            raise OSError('interrupted after canvas commit')
        return remember(key, route, body, result)
    monkeypatch.setattr(store, 'remember_request', interrupted)
    import pytest
    with pytest.raises(OSError):
        render_frame(store,pid,'f',payload)
    monkeypatch.setattr(store, 'remember_request', remember)
    first = render_frame(store,pid,'f',payload)
    assert len([n for n in store.canvas(pid)['nodes'] if n['id'] == first['node_id']]) == 1
    second = render_frame(store,pid,'f2',{'request_id':'same-key'})
    assert first['node_id'] != second['node_id']
    # Input version provenance participates in archive remapping.
    archive = client.get(f'/api/projects/{pid}/export')
    imported = client.post('/api/projects/import',files={'file':('layers.manju',archive.content,'application/zip')})
    assert imported.status_code == 201, imported.text
    restored = store.canvas(imported.json()['id'])
    composite = next(n for n in restored['nodes'] if n['id'] == first['node_id'])['data']['composite']
    assert composite['frame_id'] == 'f'
    assert composite['input_versions'][0] != version
    assert store.version(composite['input_versions'][0])['hash'] == store.version(version)['hash']
