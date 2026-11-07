import io
import json
from PIL import Image
import pytest
from manju.generation import GenerationService
from manju.media import find_binary, run_process
from manju.video_inputs import prepare_reference, has_audio
from manju.store import DomainError
from conftest import project, upload
from test_generation import generation
from test_video import video_service, request, av_bytes, h3_catalog


@pytest.mark.parametrize('structured',[True,False])
def test_duplicate_aliases_resolve_to_single_physical_reference(client,video_service,png_bytes,structured):
    service,peer=video_service;p=project(client);asset=upload(client,png_bytes())
    refs=[{'id':f'r{i}','version_id':asset['current_version_id'],'title':f'角色 · {i}'} for i in range(5)]
    extra={'prompt_parts':[{'type':'reference','reference_id':'r4'},{'type':'text','text':' 回头'}]} if structured else {}
    result=client.post('/api/generations',json=request(p['id'],video_mode='reference',references=refs,prompt='@角色 · 4 回头',**extra))
    assert result.status_code==202,result.text
    job=result.json();assert len(job['request']['references'])==1
    assert job['request']['compiled_prompt']=='<Picture 1> 回头'
    service.tick();job=service.get(job['id'])
    assert job['status']=='queued',job
    assert len(peer.uploads)==1
    assert job['mapped_graph']['sample']['inputs']['cfg']==1
    assert job['mapped_graph']['sample']['inputs']['sampler_name']=='res_multistep'
    assert job['mapped_graph']['condition']['inputs']['ref_image_size']=='max'
    assert job['mapped_graph']['input_image_1_size']['inputs']['largest_size']==1024


@pytest.mark.parametrize('use_audio,slot',[(False,1),(True,2)])
def test_soundtrack_offset_is_independent_of_reference_order(client,video_service,av_bytes,use_audio,slot):
    service,_=video_service;p=project(client)
    video=upload(client,av_bytes[0],'motion.mp4');audio=upload(client,av_bytes[1],'voice.wav')
    refs=[{'id':'voice','version_id':audio['current_version_id']},{'id':'video','version_id':video['current_version_id'],'use_audio':use_audio}]
    result=client.post('/api/generations',json=request(p['id'],video_mode='reference',references=refs,prompt_parts=[{'type':'reference','reference_id':'voice'}],audio=False))
    assert result.status_code==202,result.text
    job=result.json();assert job['request']['compiled_prompt']==f'<Audio {slot}>'
    service.tick();job=service.get(job['id']);assert job['status']=='queued',job
    assert ('ref_video_audios.ref_video_audio_1' in job['mapped_graph']['condition']['inputs'])==use_audio
    assert 'audio' not in job['mapped_graph']['video']['inputs']


def test_crop_and_frame_fit_are_real_pixels_and_do_not_modify_source(tmp_path):
    source=tmp_path/'three-views.png';image=Image.new('RGB',(300,100),'red');image.paste('green',(100,0,200,100));image.paste('blue',(200,0,300,100));image.save(source)
    before=source.read_bytes()
    ref={'media_type':'image','role':'first_frame','crop':{'x':1/3,'y':0,'width':1/3,'height':1},'fit':'contain'}
    output=prepare_reference(source,tmp_path/'prepared',ref,{'width':256,'height':512})
    with Image.open(output) as result:
        assert result.size==(256,512)
        assert result.getpixel((128,256))==(0,128,0)
        assert result.getpixel((128,0))==(24,24,24)
    output=prepare_reference(source,tmp_path/'cover',{**ref,'fit':'cover'},{'width':256,'height':512})
    with Image.open(output) as result:assert result.getpixel((128,0))==(0,128,0)
    assert source.read_bytes()==before


def test_clip_processing_removes_unwanted_sound_and_preserves_requested_interval(tmp_path,av_bytes):
    source=tmp_path/'source.mp4';source.write_bytes(av_bytes[0])
    ref={'media_type':'video','clip_start':.5,'clip_end':2.7,'use_audio':False}
    output=prepare_reference(source,tmp_path/'muted',ref,{})
    assert not has_audio(output)
    meta=json.loads(run_process([find_binary('ffprobe'),'-v','error','-show_format','-of','json',str(output)]).stdout)
    assert abs(float(meta['format']['duration'])-2.2)<.1
    output=prepare_reference(source,tmp_path/'sound',{**ref,'use_audio':True},{})
    assert has_audio(output)


@pytest.mark.parametrize('change',[{'crop':{'x':.8,'y':0,'width':.5,'height':1}}, {'clip_start':-1}, {'use_audio':'yes'}, {'fit':'stretch'}, {'purpose':'unknown'}])
def test_invalid_reference_controls_rejected(change):
    with pytest.raises(DomainError):GenerationService._validate_request(request('project',video_mode='reference',references=[{'version_id':'image',**change}]))


def test_reference_clip_bounds_and_silent_source_rejected(client,video_service,av_bytes,tmp_path):
    p=project(client);video=upload(client,av_bytes[0],'video.mp4')
    for start,end in [(2,3),(0,8),(3,2)]:
        r=client.post('/api/generations',json=request(p['id'],video_mode='reference',references=[{'version_id':video['current_version_id'],'clip_start':start,'clip_end':end}]))
        assert r.status_code==422,r.text
    path=tmp_path/'silent.mp4';source=tmp_path/'source.mp4';source.write_bytes(av_bytes[0])
    run_process([find_binary('ffmpeg'),'-y','-i',str(source),'-an','-c:v','copy',str(path)])
    silent=upload(client,path.read_bytes(),'silent.mp4')
    r=client.post('/api/generations',json=request(p['id'],video_mode='reference',references=[{'version_id':silent['current_version_id'],'use_audio':True}]))
    assert r.status_code==422 and r.json()['detail']['code']=='video_reference_audio_missing'


@pytest.mark.parametrize('mode',['text','frames','reference'])
def test_director_uses_external_shot_group_and_common_output(client,video_service,monkeypatch,mode):
    service,_=video_service
    from manju.video import DIRECTOR_NODES
    monkeypatch.setattr(service.workflows,'object_info',lambda:{**h3_catalog(),**{name:{} for name in DIRECTOR_NODES}})
    result=client.get(f'/api/video/workflow?mode={mode}&engine=director')
    assert result.status_code==200,result.text
    graph=result.json()['api_graph']
    assert graph['director']['inputs']['r2v_groups' if mode=='reference' else 'i2v_groups']==['shot',0]
    assert graph['video']['inputs']['images']==['director',0]
    assert graph['shot']['inputs']['prompt']=='在此输入视频描述'
    assert not service.list()  # Export/inspection must never submit a generation.
    if mode=='reference':
        assert graph['shot']['inputs']['ref_images.ref_image_0']==['input_image_1_size',0]
        assert graph['shot']['inputs']['ref_audios.ref_audio_0']==['input_audio_1',0]


def test_director_missing_is_not_silently_replaced(client,video_service):
    p=project(client)
    result=client.post('/api/generations',json=request(p['id'],video_options={'engine':'director'}))
    assert result.status_code==422
    assert not video_service[0].list()


def test_director_soundtrack_and_voice_keep_global_audio_slot(client,video_service,av_bytes,monkeypatch):
    from manju.video import DIRECTOR_NODES
    service,_=video_service
    monkeypatch.setattr(service.workflows,'object_info',lambda:{**h3_catalog(),**{name:{} for name in DIRECTOR_NODES}})
    p=project(client);video=upload(client,av_bytes[0],'video.mp4');voice=upload(client,av_bytes[1],'voice.wav')
    refs=[{'id':'voice','version_id':voice['current_version_id']},{'id':'motion','version_id':video['current_version_id'],'use_audio':True}]
    result=client.post('/api/generations',json=request(p['id'],video_mode='reference',references=refs,video_options={'engine':'director'},prompt_parts=[{'type':'reference','reference_id':'voice'}]))
    assert result.status_code==202,result.text
    service.tick();job=service.get(result.json()['id']);assert job['status']=='queued',job
    group=job['mapped_graph']['shot']['inputs']
    assert group['prompt']=='<Audio 2>'
    assert group['ref_audios.ref_audio_1']==['input_audio_1',0]
    assert group['ref_video_audios.ref_video_audio_0']==['input_video_1_parts',1]
    assert group['ref_videos.ref_video_0']==['input_video_1_parts',0]


def test_nine_director_images_use_all_zero_based_slots():
    from manju.video import H3Adapter
    refs=[{'id':str(i),'version_id':str(i),'media_type':'image','role':'reference'} for i in range(9)]
    graph=H3Adapter.build_graph({'id':'job','request':{'parameters':{'width':864,'height':480,'steps':20,'cfg':1,'seed':1},'references':refs,'video_mode':'reference','duration':4,'audio':False,'compiled_prompt':'<Picture 9>','video_options':{'engine':'director'}},'workflow_snapshot':{'models':dict.fromkeys(['clip','ref2va','fl2va','video_vae','audio_vae'],'model')}},{str(i):str(i)+'.png' for i in range(9)})['api_graph']
    slots=graph['shot']['inputs']
    assert 'ref_images.ref_image_0' in slots and 'ref_images.ref_image_8' in slots
    assert 'ref_images.ref_image_9' not in slots
