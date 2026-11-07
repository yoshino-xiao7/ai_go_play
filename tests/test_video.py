"""H3 contracts run against a protocol peer, never the user's GPU or library."""
import pytest
from manju.generation import GenerationService
from manju.video import REQUIRED, PROFILE_ID
from manju.media import find_binary, run_process
from conftest import project, upload
from test_generation import generation


def h3_catalog():
    catalog={name:{"input":{"required":{}}} for name in REQUIRED}
    catalog["UNETLoader"]["input"]["required"]["unet_name"]=[["minimax_h3_fl2va_pruned.safetensors","minimax_h3_hybrid_fl2va_ref2va.safetensors"]]
    catalog["CLIPLoader"]["input"]["required"]["clip_name"]=[["qwen3vl_minimax_h3_int8.safetensors"]]
    catalog["VAELoader"]["input"]["required"]["vae_name"]=[["minimax_h3_video_vae_fp16.safetensors","minimax_h3_audio_vae_fp32.safetensors"]]
    return catalog


@pytest.fixture
def video_service(generation,monkeypatch):
    service,peer=generation
    monkeypatch.setattr(service.workflows,"object_info",h3_catalog)
    return service,peer


def request(project_id,**values):
    return {"kind":"video","project_id":project_id,"workflow_id":PROFILE_ID,"prompt":"二次元少女向镜头挥手，轻柔的风声。","references":[],"parameters":{"width":256,"height":256,"steps":1,"seed":42},**values}


@pytest.mark.parametrize("values",[
    {"duration":3},{"duration":16},{"duration":True},{"audio":"false"},
    {"video_mode":"unsupported"},{"provider":"cloud"},{"mask_version_id":"mask"},
    {"parameters":{"width":1376,"height":768}},{"parameters":{"width":257}},
    {"parameters":{"steps":0}},{"parameters":{"cfg":21}},{"parameters":{"denoise":.5}},
    {"video_mode":"frames"},{"video_mode":"reference"},
    {"video_mode":"text","references":[{"version_id":"image"}]},
    {"video_mode":"frames","references":[{"version_id":"image","role":"first_frame"},{"version_id":"image2","role":"first_frame"}]},
])
def test_rejects_incompatible_requests(values):
    from manju.store import DomainError
    with pytest.raises(DomainError):GenerationService._validate_request(request("project",**values))


def test_settings_cas_and_missing_models(client,video_service,monkeypatch):
    service,_=video_service
    status=client.get('/api/video/settings').json()
    assert status['ready'] and status['models']['fl2va'].startswith('minimax_h3_fl2va')
    assert client.put('/api/video/settings',json={'revision':status['revision'],'models':status['models']}).status_code==200
    assert client.put('/api/video/settings',json={'revision':status['revision'],'models':status['models']}).status_code==409
    monkeypatch.setattr(service.workflows,'object_info',lambda:{})
    assert not client.get('/api/video/settings').json()['ready']
    r=client.post('/api/generations',json=request(project(client)['id']))
    assert r.status_code==422 and not service.list()


def test_first_last_frame_graph_and_stable_reference_ids(client,video_service,png_bytes):
    service,peer=video_service
    p=project(client);first=upload(client,png_bytes('red'));last=upload(client,png_bytes('blue'))
    refs=[{'id':'end','version_id':last['current_version_id'],'role':'last_frame','title':'尾帧'}, {'id':'start','version_id':first['current_version_id'],'role':'first_frame','title':'首帧'}]
    r=client.post('/api/generations',json=request(p['id'],video_mode='frames',references=refs,prompt_parts=[{'type':'reference','reference_id':'start'},{'type':'text','text':'逐渐变成'},{'type':'reference','reference_id':'end'}],audio=False,request_id='first-last'))
    assert r.status_code==202,r.text
    service.tick();job=service.get(r.json()['id'])
    assert job['status']=='queued',job
    graph=job['mapped_graph']
    assert graph['condition']['inputs']['first_frame']==['input_image_2',0]
    assert graph['condition']['inputs']['last_frame']==['input_image_1',0]
    assert graph['condition']['inputs']['prompt']=='首帧逐渐变成尾帧'
    assert graph['condition']['inputs']['length']==107
    assert 'audio' not in graph['video']['inputs']
    assert len(peer.uploads)==2
    assert job['request']['resolved_parameters']['actual_duration']==107/24


@pytest.fixture
def av_bytes(tmp_path):
    ffmpeg=find_binary('ffmpeg')
    if not ffmpeg:pytest.skip('FFmpeg unavailable')
    path=tmp_path/'reference.mp4'
    run_process([ffmpeg,'-y','-f','lavfi','-i','color=c=blue:s=64x64:r=24:d=3','-f','lavfi','-i','sine=frequency=440:duration=3','-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac','-shortest',str(path)])
    wav=tmp_path/'voice.wav'
    run_process([ffmpeg,'-y','-i',str(path),'-vn',str(wav)])
    output=tmp_path/'result.mp4'
    run_process([ffmpeg,'-y','-i',str(path),'-metadata','comment=generated output','-c','copy',str(output)])
    return path.read_bytes(),wav.read_bytes(),output.read_bytes()


def test_multimodal_slots_graph_and_same_card_candidates(client,video_service,png_bytes,av_bytes):
    service,peer=video_service;p=project(client)
    image=upload(client,png_bytes());video=upload(client,av_bytes[0],'motion.mp4');audio=upload(client,av_bytes[1],'voice.wav')
    canvas=service.store.canvas(p['id']);canvas['nodes']=[{'id':'video','type':'media','position':{'x':20,'y':30},'data':{'kind':'video','asset_version_id':video['current_version_id']}}];service.store.save_canvas(p['id'],canvas)
    refs=[{'id':'voice','version_id':audio['current_version_id'],'title':'音色'}, {'id':'character','version_id':image['current_version_id'],'title':'人物'}, {'id':'motion','version_id':video['current_version_id'],'title':'动作'}]
    r=client.post('/api/generations',json=request(p['id'],source_node_id='video',video_mode='reference',references=refs,prompt_parts=[{'type':'reference','reference_id':'character'},{'type':'text','text':'参考'},{'type':'reference','reference_id':'motion'},{'type':'reference','reference_id':'voice'}],request_id='reference'))
    assert r.status_code==202,r.text
    job=r.json();assert job['request']['compiled_prompt']=='<Picture 1>参考<Video 1><Audio 1>'
    service.tick();job=service.get(job['id']);assert job['status']=='queued',job
    graph=job['mapped_graph'];condition=graph['condition']['inputs']
    assert condition['ref_images.ref_image_1']==['input_image_1_size',0]
    assert condition['ref_videos.ref_video_1']==['input_video_1_parts',0]
    assert 'ref_video_audios.ref_video_audio_1' not in condition  # Reference sound is opt-in.
    assert condition['ref_audios.ref_audio_1']==['input_audio_1',0]
    assert graph['video']['inputs']['audio']==['audio',0]
    assert len(peer.uploads)==3
    # A duplicated output descriptor is delivered once, and never creates a second card.
    peer.image=av_bytes[2]
    descriptor={'filename':'result.mp4','type':'output'}
    service._collect(job,{'outputs':{'save':{'videos':[descriptor],'images':[descriptor]}}})
    finished=service.get(job['id']);assert finished['status']=='succeeded'
    assert len(finished['outputs'])==1
    saved=service.store.canvas(p['id']);assert len(saved['nodes'])==1 and not saved['edges']
    assert saved['nodes'][0]['data']['asset_version_id']==video['current_version_id']
    assert saved['nodes'][0]['data']['kind']=='video'
    assert len(saved['nodes'][0]['data']['image_history'])==2
    assert saved['nodes'][0]['data']['image_history'][1]['candidate'] is True
    assert service.store.version(finished['outputs'][0]['version_id'])['mime']=='video/mp4'
    # Repeat delivery cannot overwrite any later user position change.
    saved['nodes'][0]['position']['x']=123;service.store.save_canvas(p['id'],saved)
    service._collect(job,{'outputs':{'save':{'videos':[descriptor]}}})
    assert service.store.canvas(p['id'])['nodes'][0]['position']['x']==123


def test_references_type_and_duration_are_read_from_assets(client,video_service,av_bytes):
    service,_=video_service;p=project(client);audio=upload(client,av_bytes[1],'voice.wav')
    ref={'id':'audio','version_id':audio['current_version_id'],'media_type':'image','role':'first_frame'}
    assert client.post('/api/generations',json=request(p['id'],video_mode='frames',references=[ref])).status_code==422
    refs=[{'id':str(i),'version_id':audio['current_version_id']} for i in range(4)]
    result=client.post('/api/generations',json=request(p['id'],video_mode='reference',references=refs))
    assert result.status_code==202
    assert len(result.json()['request']['references'])==1


def test_video_reference_edges_preserve_canvas_contract(client,video_service,png_bytes):
    service,_=video_service;p=project(client);asset=upload(client,png_bytes())
    canvas=service.store.canvas(p['id']);canvas['nodes']=[{'id':'image','type':'media','position':{'x':0,'y':0},'data':{'kind':'image','asset_version_id':asset['current_version_id']}},{'id':'video','type':'media','position':{'x':300,'y':0},'data':{'kind':'video'}}]
    canvas['edges']=[{'id':'ref','source':'image','target':'video','data':{'role':'reference'}}]
    result=client.put('/api/projects/'+p['id']+'/canvas',json=canvas)
    assert result.status_code==200,result.text


def test_video_archive_preserves_versions_and_clears_live_job_state(client,video_service,av_bytes,tmp_path):
    from fastapi.testclient import TestClient
    from manju.app import create_app
    service,_=video_service;p=project(client)
    video=upload(client,av_bytes[0],'reference.mp4');audio=upload(client,av_bytes[1],'voice.wav')
    canvas=service.store.canvas(p['id'])
    canvas['nodes']=[{'id':'video','type':'media','position':{'x':1,'y':2},'data':{'kind':'video','asset_version_id':video['current_version_id'],'image_history':[{'version_id':video['current_version_id']}],'generation':{'kind':'video','mode':'text_to_image','video_mode':'reference','workflow_id':PROFILE_ID,'duration':6,'audio':True,'prompt':'参考声音','parameters':{},'references':[{'id':'voice','version_id':audio['current_version_id'],'media_type':'audio','role':'reference'}],'last_job_id':'old','pending_submission':{'request_id':'old'}}}}]
    service.store.save_canvas(p['id'],canvas)
    archive=client.get('/api/projects/'+p['id']+'/export');assert archive.status_code==200
    with TestClient(create_app(data_dir=tmp_path/'destination',config_file=tmp_path/'destination.json'),base_url='http://127.0.0.1') as other:
        imported=other.post('/api/projects/import',files={'file':('video.manju',archive.content)})
        assert imported.status_code==201,imported.text
        assert not imported.json().get('import_warnings')
        restored=other.get('/api/projects/'+imported.json()['id']+'/canvas').json()['nodes'][0]['data']
        assert restored['kind']=='video' and restored['generation']['video_mode']=='reference'
        assert restored['generation']['duration']==6 and restored['generation']['audio'] is True
        assert not restored['generation'].get('pending_submission') and not restored['generation'].get('last_job_id')
        voice=restored['generation']['references'][0]['version_id']
        assert other.get('/api/media/'+voice+'?variant=original').content==av_bytes[1]
        assert other.get('/api/media/'+restored['asset_version_id']+'?variant=original').content==av_bytes[0]
