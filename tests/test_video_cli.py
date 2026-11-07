import json
import httpx
import pytest
from manju.cli import build_parser,generate_command,CliError

def test_video_cli_maps_typed_inputs_and_default_profile():
    args=build_parser().parse_args(['generate','--kind','video','--project','project','--source-node','video','--prompt','角色回头','--first-frame','image-v1','--last-frame','image-v2','--duration','6','--silent','--json'])
    captured=[]
    def handler(request):
        captured.append(json.loads(request.content));return httpx.Response(202,json={'id':'job'})
    with httpx.Client(base_url='http://127.0.0.1:8765',transport=httpx.MockTransport(handler)) as client:
        assert generate_command(client,args)=={'id':'job'}
    payload=captured[0]
    assert payload['kind']=='video' and payload['workflow_id']=='builtin-h3-local'
    assert payload['video_mode']=='frames' and payload['audio'] is False
    assert payload['references']==[{'version_id':'image-v1','role':'first_frame'},{'version_id':'image-v2','role':'last_frame'}]
    assert payload['duration']==6 and payload['source_node_id']=='video'

def test_video_options_cannot_silently_create_image_job():
    args=build_parser().parse_args(['generate','--project','project','--prompt','测试','--duration','4'])
    with pytest.raises(CliError):generate_command(None,args)

def test_video_json_cannot_mix_flags(tmp_path):
    path=tmp_path/'request.json';path.write_text('{}')
    args=build_parser().parse_args(['generate','--file',str(path),'--kind','video'])
    with pytest.raises(CliError):generate_command(None,args)


def test_cli_director_options_reach_shared_api():
    args=build_parser().parse_args(['generate','--kind','video','--project','project','--prompt','回头','--video-engine','director','--ref-image-size','1280'])
    captured=[]
    def handler(request):
        captured.append(json.loads(request.content));return httpx.Response(202,json={'id':'job'})
    with httpx.Client(base_url='http://127.0.0.1:8765',transport=httpx.MockTransport(handler)) as client:generate_command(client,args)
    assert captured[0]['video_options']=={'engine':'director','ref_image_size':'1280'}
