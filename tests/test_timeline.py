from array import array
import copy
import hashlib
from io import BytesIO
import json
import math
from pathlib import Path

from PIL import Image
import pytest

from manju.media import find_binary, probe_media, run_process
from manju.store import DomainError, Store
from manju.timeline import TimelineService, normalize_timeline
from manju.transfers import export_project, import_project
from test_production import production, materials


@pytest.fixture
def timeline(production):
    return TimelineService(production.store, production)


def document(timeline, materials):
    project=timeline.store.create_project('多轨真实合成')
    payload={'revision':0,'request_id':'timeline-save','settings':{'width':160,'height':96,'fps':24,'background_color':'#000000'},
             'tracks':[{'id':'video','name':'底层','type':'video','order':0},
                       {'id':'overlay','name':'叠加','type':'video','order':1},
                       {'id':'muted','name':'隐藏轨','type':'video','order':2,'muted':True},
                       {'id':'voice','name':'声音一','type':'audio','order':3},
                       {'id':'music','name':'声音二','type':'audio','order':4},
                       {'id':'text','name':'文字','type':'text','order':5}],
             'clips':[{'id':'red','track_id':'video','start':0,'duration':2,'asset_version_id':materials['red'],'volume':0},
                      {'id':'blue','track_id':'overlay','start':.5,'duration':.5,'trim_start':.25,'asset_version_id':materials['blue'],'volume':0,'transform':{'x':20,'y':10,'scale':.25,'opacity':.5}},
                      {'id':'hidden-blue','track_id':'muted','start':0,'duration':2,'asset_version_id':materials['blue'],'volume':0},
                      {'id':'tone220','track_id':'music','start':0,'duration':2,'asset_version_id':materials['red'],'volume':.4},
                      {'id':'tone880','track_id':'voice','start':.5,'duration':.375,'asset_version_id':materials['audio'],'volume':.6,'fade_in':.04,'fade_out':.04},
                      {'id':'caption','track_id':'text','start':1.25,'duration':.5,'text':'测试','transform':{'x':0,'y':45,'scale':1,'opacity':1},'text_style':{'font_size':20,'color':'#ffffff','background_color':'#00000080','align':'center'}}]}
    return project['id'],timeline.save(project['id'],payload),payload


def frame(path, second):
    raw=run_process([find_binary('ffmpeg'),'-v','error','-ss',str(second),'-i',str(path),'-frames:v','1','-f','image2pipe','-vcodec','png','pipe:1']).stdout
    return Image.open(BytesIO(raw)).convert('RGB')


def test_true_layer_composite_and_concurrent_audio_mix(timeline,materials):
    pid,saved,_=document(timeline,materials)
    payload={'revision':saved['revision'],'request_id':'timeline-render','name':'多轨合成'}
    job=timeline.render(pid,payload)
    assert timeline.render(pid,payload)['id']==job['id']
    timeline.production.tick()
    result=timeline.production.get_render(job['id'])
    assert result['status']=='succeeded', result['error']
    assert result['kind']=='timeline'
    output=timeline.store.version(result['output_version_id'])
    assert abs(output['duration']-2)<.08
    before,during,after=(frame(output['path'],t) for t in (.25,.7,1.1))
    assert before.getpixel((30,20))[0]>220 and before.getpixel((30,20))[2]<25
    pixel=during.getpixel((30,20))
    assert 95<pixel[0]<160 and 95<pixel[2]<160, pixel
    assert during.getpixel((100,20))[0]>220
    assert after.getpixel((30,20))[0]>220 and after.getpixel((30,20))[2]<25
    caption=frame(output['path'],1.5)
    assert any(all(channel>200 for channel in caption.getpixel((x,y))) for x in range(5,80) for y in range(50,85))
    raw=run_process([find_binary('ffmpeg'),'-v','error','-ss','0.6','-t','0.15','-i',output['path'],'-vn','-ac','1','-ar','8000','-f','s16le','pipe:1']).stdout
    samples=array('h',raw)
    def amplitude(hz):
        return abs(sum(value*complex(math.cos(2*math.pi*hz*i/8000),math.sin(2*math.pi*hz*i/8000)) for i,value in enumerate(samples)))/len(samples)
    assert amplitude(220)>150 and amplitude(880)>150
    assert timeline.get(pid)['renders'][0]['id']==job['id']


def test_timeline_locked_cas_trim_and_media_reference_portability(timeline,materials,tmp_path):
    pid,saved,_=document(timeline,materials)
    saved['tracks'][0]['locked']=True
    locked=timeline.save(pid,saved)
    modified=copy.deepcopy(locked);modified['clips'][0]['duration']=1
    with pytest.raises(DomainError) as error:timeline.save(pid,modified)
    assert error.value.detail['code']=='timeline_locked'
    modified['tracks'][0]['locked']=False
    shortened=timeline.save(pid,modified)
    assert shortened['clips'][0]['trim_end']==1
    with pytest.raises(DomainError) as error:
        timeline.store.unlink_asset(pid,timeline.store.version(materials['red'])['asset_id'],True)
    assert error.value.detail['code']=='timeline_referenced'
    assert len(timeline.get(pid)['clips'])==len(shortened['clips'])
    with pytest.raises(DomainError) as error:timeline.save(pid,locked)
    assert error.value.detail['code']=='revision_conflict'
    duplicate=timeline.store.duplicate_project(pid)
    assert timeline.get(duplicate['id'])['clips'][0]['asset_version_id']==materials['red']
    archive=export_project(timeline.store,pid)
    target=Store(tmp_path/'imported-timeline',tmp_path/'imported-config.json')
    try:
        from manju.production import ProductionService
        other=TimelineService(target,ProductionService(target))
        imported=import_project(target,archive)
        copied=other.get(imported['id'])
        assert len(copied['tracks'])==6
        version=copied['clips'][0]['asset_version_id']
        assert version!=materials['red']
        assert target.version(version)['hash']==timeline.store.version(materials['red'])['hash']
    finally:target.close()


def test_import_storyboard_appends_and_preserves_existing_clips(timeline,materials):
    pid,saved,_=document(timeline,materials)
    production=timeline.production
    source=production.get(pid)
    source['shots']=[{'id':'shot','title':'独立镜头','duration':1,'video_version_id':materials['blue'],'audio_version_id':materials['audio'],'audio_offset':.25,'dialogue':'你好。'}]
    production.save(pid,source)
    current=timeline.get(pid)
    request={'revision':current['revision'],'request_id':'import-shots'}
    imported=timeline.import_production(pid,request)
    assert len(imported['tracks'])==9
    assert len(imported['clips'])==9
    assert imported['clips'][0]['id']=='red'
    assert timeline.import_production(pid,request)['revision']==imported['revision']
    assert len(timeline.get(pid)['clips'])==9


def test_timeline_image_video_fades_and_out_validation(timeline,materials,tmp_path):
    png=tmp_path/'green.png';Image.new('RGB',(80,96),'green').save(png)
    asset=timeline.store.ingest(png,'green.png',probe_media(png,'green.png'),hashlib.sha256(png.read_bytes()).hexdigest())
    pid=timeline.store.create_project('淡入淡出')['id']
    saved=timeline.save(pid,{'revision':0,'settings':{'width':160,'height':96,'fps':24},'tracks':[{'id':'base','type':'video'},{'id':'v','type':'video','order':1}],
                             'clips':[{'id':'i','track_id':'v','asset_version_id':asset['imported_version_id'],'start':0,'duration':1,'fade_in':.25,'fade_out':.25,'transform':{'scale':1,'opacity':1}},
                                      {'id':'base','track_id':'base','asset_version_id':materials['red'],'start':0,'duration':1,'volume':0}]})
    job=timeline.render(pid,{});timeline.production.tick();result=timeline.production.get_render(job['id'])
    assert result['status']=='succeeded',result['error']
    path=timeline.store.version(result['output_version_id'])['path']
    early,full,late=(frame(path,t).getpixel((80,48))[1] for t in (.04,.5,.91))
    assert full>100 and early<full*.6 and late<full*.6
    assert frame(path,.5).getpixel((5,48))[0]>220  # contain padding is transparent
    current=timeline.get(pid);current['clips'][0].update(asset_version_id=materials['red'],trim_start=1.8,duration=1)
    timeline.save(pid,current)
    with pytest.raises(DomainError) as error:timeline.render(pid,{})
    assert error.value.detail['code']=='timeline_media_too_short'


def test_thirty_second_snapshot_restart_and_delivery_recovery(timeline,materials,tmp_path,monkeypatch):
    versions=[]
    for name in ('red','blue'):
        path=tmp_path/(name+'.png');Image.new('RGB',(160,96),name).save(path)
        versions.append(timeline.store.ingest(path,path.name,probe_media(path,path.name),hashlib.sha256(path.read_bytes()).hexdigest())['imported_version_id'])
    pid=timeline.store.create_project('三十秒持久合成')['id']
    timeline.save(pid,{'revision':0,'settings':{'width':160,'height':96,'fps':24},
                       'tracks':[{'id':'v','type':'video'},{'id':'a','type':'audio','order':1}],
                       'clips':[{'id':str(i),'track_id':'v','start':i*5,'duration':5,'asset_version_id':versions[i%2]} for i in range(6)]+
                               [{'id':'phone','track_id':'a','start':0,'duration':2,'asset_version_id':materials['red'],'audio_preset':'phone'}]})
    job=timeline.render(pid,{'request_id':'thirty-seconds'})
    # Editing the document cannot change the accepted snapshot or remove its
    # active inputs. A new worker requeues an interrupted render on startup.
    current=timeline.get(pid);current['clips']=[];timeline.save(pid,current)
    with pytest.raises(DomainError) as error:timeline.store.trash_project(pid)
    assert error.value.detail['code']=='production_in_progress'
    asset_id=timeline.store.version(versions[0])['asset_id']
    with pytest.raises(DomainError) as error:timeline.store.unlink_asset(pid,asset_id,True)
    assert error.value.detail['code']=='production_in_progress'
    timeline.production._update(job['id'],status='running')
    from manju.production import ProductionService
    restarted=ProductionService(timeline.store)
    assert restarted.get_render(job['id'])['status']=='pending'
    deliver=restarted._deliver
    def interruption(*args):raise RuntimeError('simulated interruption after encoding')
    monkeypatch.setattr(restarted,'_deliver',interruption)
    restarted.tick()
    assert restarted.get_render(job['id'])['status']=='failed'
    output=timeline.store.root/'exports'/('production-'+job['id'])/'film.mp4'
    encoded_at=output.stat().st_mtime_ns
    monkeypatch.setattr(restarted,'_deliver',deliver)
    restarted.retry_render(job['id']);restarted.tick()
    result=restarted.get_render(job['id'])
    assert result['status']=='succeeded',result['error']
    assert output.stat().st_mtime_ns==encoded_at
    video=json.loads(run_process([find_binary('ffprobe'),'-v','error','-show_streams','-of','json',str(output)]).stdout)['streams'][0]
    assert int(video['nb_frames'])==720 and float(video['duration'])==30
    assert frame(output,2).getpixel((80,48))[0]>220
    assert frame(output,27).getpixel((80,48))[2]>220
    assert len([n for n in timeline.store.canvas(pid)['nodes'] if n.get('data',{}).get('production_render_id')==job['id']])==1
    restarted.close()


def test_voice_presets_apply_real_frequency_filtering(timeline,materials):
    pid,saved,_=document(timeline,materials)
    def tone_level(path,hz):
        samples=array('h',run_process([find_binary('ffmpeg'),'-v','error','-ss','0.6','-t','0.15','-i',path,'-vn','-ac','1','-ar','8000','-f','s16le','pipe:1']).stdout)
        return abs(sum(value*complex(math.cos(2*math.pi*hz*i/8000),math.sin(2*math.pi*hz*i/8000)) for i,value in enumerate(samples)))/len(samples)
    first=timeline.render(pid,{});timeline.production.tick()
    path=timeline.store.version(timeline.production.get_render(first['id'])['output_version_id'])['path']
    original=tone_level(path,220)
    current=timeline.get(pid)
    for clip in current['clips']:
        if clip['track_id'] in ('music','voice'):clip['audio_preset']='phone'
    timeline.save(pid,current)
    second=timeline.render(pid,{});timeline.production.tick()
    result=timeline.production.get_render(second['id'])
    assert result['status']=='succeeded',result['error']
    path=timeline.store.version(result['output_version_id'])['path']
    assert tone_level(path,220)<original*.55
    assert tone_level(path,880)>150


@pytest.mark.parametrize('fps',[24,25,30,50,60])
def test_single_frame_decimal_round_trip(fps):
    # The editor serializes times to microseconds. 1/30 rounded to .033333
    # must remain a legal one-frame clip instead of failing the lower bound.
    value=round(1/fps,6)
    doc=normalize_timeline({'settings':{'fps':fps,'duration':value},'tracks':[{'id':'t','type':'text'}],
                            'clips':[{'id':'c','track_id':'t','text':'一帧','duration':value,'fade_in':value}]})
    assert doc['clips'][0]['duration']==1/fps
    assert doc['clips'][0]['fade_in']<=1/fps
    assert normalize_timeline(doc)['clips']==doc['clips']
