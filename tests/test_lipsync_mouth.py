from io import BytesIO
import importlib.util
from pathlib import Path

from PIL import Image
import pytest

from manju.media import find_binary,run_process

spec=importlib.util.spec_from_file_location('lipsync_mouth_worker',Path(__file__).parents[1]/'integrations/comfyui_manju_lipsync/worker.py')
worker=importlib.util.module_from_spec(spec);spec.loader.exec_module(worker)
TRACK={'box':[16,8,32,56],'mouth':[32,48]}


def test_only_real_model_mouth_is_blended_and_surroundings_are_exact():
    source=Image.new('RGB',(64,80),(210,20,30));model=Image.new('RGB',(64,80),(10,40,230))
    result=worker.composite_mouth(source,model,TRACK)
    assert result.getpixel((32,49))==model.getpixel((32,49))
    assert result.getpixel((32,25))==source.getpixel((32,25))  # eyes
    assert result.getpixel((17,49))==source.getpixel((17,49))  # cheek
    assert result.getpixel((2,2))==source.getpixel((2,2))
    for y in range(38):
        for x in range(64):assert result.getpixel((x,y))==source.getpixel((x,y))
    edge=[result.getpixel((x,49))[2] for x in range(36,42)]
    assert edge==sorted(edge,reverse=True) and any(30<value<230 for value in edge)
    assert len(set(edge))>=4  # feathered transition, not a hard pasted ellipse
    # A translated detected mouth moves the changed region with the face.
    shifted=worker.composite_mouth(source,model,{'box':[26,8,32,56],'mouth':[42,48]})
    assert shifted.getpixel((42,49))==model.getpixel((42,49))
    assert shifted.getpixel((32,49))==source.getpixel((32,49))


@pytest.mark.parametrize('track',[None,{}, {'box':[],'mouth':[]},{'box':[16,8,0,56],'mouth':[32,48]},
                                  {'box':[16,8,32,56],'mouth':[32,20]}, {'box':[16,8,32,56],'mouth':[float('nan'),48]}])
def test_empty_or_invalid_tracking_fails_without_full_face_fallback(track):
    with pytest.raises(ValueError):worker.mouth_mask((64,80),track)


def test_streamed_video_keeps_exact_source_pixels_and_requested_frame_count(tmp_path):
    ffmpeg=find_binary('ffmpeg')
    if not ffmpeg or not find_binary('ffprobe'):pytest.skip('FFmpeg is required')
    source,model,result=(tmp_path/name for name in ('source.mkv','model.mkv','mouth-only.mkv'))
    for path,color,frames in ((source,'red',3),(model,'blue',4)):
        run_process([ffmpeg,'-v','error','-y','-f','lavfi','-i',f'color={color}:size=64x80:rate=25','-frames:v',str(frames),'-c:v','ffv1','-pix_fmt','bgr0',str(path)])
    def read_frames(path):
        return run_process([ffmpeg,'-v','error','-i',str(path),'-f','rawvideo','-pix_fmt','rgb24','pipe:1']).stdout
    source_bytes,model_bytes=read_frames(source),read_frames(model)
    progress=[]
    worker.preserve_source_outside_mouth(ffmpeg,source,model,result,[TRACK]*3,3,progress.append)
    rendered=read_frames(result)
    count=64*80*3
    assert len(rendered)==3*count  # padded model fourth frame is not delivered
    for index in range(3):
        original=Image.frombytes('RGB',(64,80),source_bytes[index*count:(index+1)*count])
        generated=Image.frombytes('RGB',(64,80),model_bytes[index*count:(index+1)*count])
        delivered=Image.frombytes('RGB',(64,80),rendered[index*count:(index+1)*count])
        assert delivered.getpixel((32,49))==generated.getpixel((32,49))
        assert delivered.getpixel((32,25))==original.getpixel((32,25))
        assert delivered.getpixel((2,2))==original.getpixel((2,2))
    assert progress[-1]==pytest.approx(.98)
    with pytest.raises(ValueError):worker.preserve_source_outside_mouth(ffmpeg,source,model,result,[],3)
    with pytest.raises(RuntimeError,match='帧数不足'):
        worker.preserve_source_outside_mouth(ffmpeg,source,model,tmp_path/'too-long.mkv',[TRACK]*4,4)
