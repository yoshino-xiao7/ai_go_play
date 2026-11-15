"""Isolated inference with offline weights and safe per-task media processing."""
from pathlib import Path
import json,os,sys,subprocess,types,math,tempfile,time
from fractions import Fraction


def write_progress(path,value):
    """A Windows reader can briefly deny replace; progress must not fail inference."""
    pending=path.with_suffix('.pending')
    for attempt in range(6):
        try:
            pending.write_text(json.dumps({'progress':value}),encoding='utf-8')
            pending.replace(path)
            return True
        except PermissionError:
            # ComfyUI polls this file from another process. Keep the last valid
            # JSON if it remains locked; the next update can publish again.
            time.sleep(.01*(attempt+1))
    return False


def mouth_mask(size,track):
    """Keep a solid model-mouth core and a compact, smooth lower-face boundary."""
    from PIL import Image
    try:
        x,y,w,h=map(float,track['box']);mx,my=map(float,track['mouth'])
    except (TypeError,ValueError,KeyError) as error:
        raise ValueError('缺少有效的逐帧嘴部位置，已停止口型合成。') from error
    if not all(math.isfinite(v) for v in (x,y,w,h,mx,my)) or w<8 or h<8 or not x<=mx<=x+w or not y+.55*h<=my<=y+h:
        raise ValueError('人脸或嘴部跟踪框无效，已停止口型合成。')
    width,height=size
    cy=my+.025*h;rx=.24*w;ry=min(.16*h,cy-(y+.55*h),y+1.02*h-cy)
    if rx<2 or ry<2 or not 0<=mx<width or not 0<=cy<height:
        raise ValueError('嘴部跟踪超出画面，已停止口型合成。')
    mask=Image.new('L',size,0);pixels=mask.load()
    for py in range(max(0,math.floor(cy-ry)),min(height,math.ceil(cy+ry)+1)):
        for px in range(max(0,math.floor(mx-rx)),min(width,math.ceil(mx+rx)+1)):
            radius=math.sqrt(((px-mx)/rx)**2+((py-cy)/ry)**2)
            if radius<=.65:alpha=255
            elif radius<1:alpha=round(255*.5*(1+math.cos(math.pi*(radius-.65)/.35)))
            else:continue
            pixels[px,py]=alpha
    return mask


def composite_mouth(source,model,track):
    from PIL import Image
    if source.size!=model.size:raise ValueError('口型结果与原片分辨率不一致。')
    return Image.composite(model.convert('RGB'),source.convert('RGB'),mouth_mask(source.size,track))


def preserve_source_outside_mouth(ffmpeg,source,model,output,tracks,frames,progress=None):
    """Stream corresponding frames into a lossless intermediate before muxing."""
    from PIL import Image
    if frames<1 or len(tracks)<frames:raise ValueError('逐帧嘴部跟踪数量不足，已停止口型合成。')
    ffprobe=str(Path(ffmpeg).with_name('ffprobe'+Path(ffmpeg).suffix))
    def dimensions(path):
        result=subprocess.run([ffprobe,'-v','error','-select_streams','v:0','-show_entries','stream=width,height,avg_frame_rate','-of','json',str(path)],capture_output=True,check=True,timeout=30,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        stream=json.loads(result.stdout)['streams'][0]
        if Fraction(stream['avg_frame_rate'])!=25:raise ValueError('口型合成需要对应的 25 fps 视频。')
        return int(stream['width']),int(stream['height'])
    size=dimensions(source)
    if dimensions(model)!=size:raise ValueError('口型结果与原片分辨率不一致。')
    # Validate all tracking before starting encoders; never fall back to a
    # full-face replacement when detection or optical flow becomes invalid.
    for track in tracks[:frames]:mouth_mask(size,track)
    flags=getattr(subprocess,'CREATE_NO_WINDOW',0);processes=[]
    with tempfile.TemporaryFile() as source_log,tempfile.TemporaryFile() as model_log,tempfile.TemporaryFile() as encode_log:
        logs=[source_log,model_log,encode_log]
        try:
            for path,log in ((source,source_log),(model,model_log)):
                processes.append(subprocess.Popen([ffmpeg,'-v','error','-nostdin','-threads','1','-i',str(path),'-an','-f','rawvideo','-pix_fmt','rgb24','pipe:1'],stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=log,creationflags=flags))
            processes.append(subprocess.Popen([ffmpeg,'-v','error','-y','-f','rawvideo','-pix_fmt','rgb24','-s',f'{size[0]}x{size[1]}','-r','25','-i','pipe:0','-an','-frames:v',str(frames),'-c:v','ffv1','-level','3','-pix_fmt','bgr0',str(output)],stdin=subprocess.PIPE,stdout=subprocess.DEVNULL,stderr=encode_log,creationflags=flags))
            frame_bytes=size[0]*size[1]*3
            for index in range(frames):
                original=processes[0].stdout.read(frame_bytes);generated=processes[1].stdout.read(frame_bytes)
                if len(original)!=frame_bytes or len(generated)!=frame_bytes:raise RuntimeError('口型视频与原片帧数不足或未对齐。')
                image=composite_mouth(Image.frombytes('RGB',size,original),Image.frombytes('RGB',size,generated),tracks[index])
                processes[2].stdin.write(image.tobytes())
                if progress and (index%25==0 or index==frames-1):progress(.94+.04*(index+1)/frames)
            processes[2].stdin.close()
            if processes[2].wait(timeout=120):
                encode_log.seek(0);raise RuntimeError('口部局部合成编码失败：'+encode_log.read().decode('utf-8','replace')[-2000:])
        finally:
            # Model output can contain Whisper padding past the requested end.
            # Stop only these child decoders after consuming the paired frames.
            for process in processes:
                if process.poll() is None:
                    process.terminate()
                    try:process.wait(timeout=10)
                    except subprocess.TimeoutExpired:process.kill();process.wait()
                for stream in (process.stdin,process.stdout):
                    if stream:
                        try:stream.close()
                        except OSError:pass

def mux_command(ffmpeg,folder,output,frames,video_source=None):
    """Whisper windows may pad video; retain the requested frame boundary."""
    return [ffmpeg,'-v','error','-y','-i',str(video_source or folder/'video.mp4'),'-i',str(folder/'audio.wav'),
            '-c:v','libx264','-crf','18','-pix_fmt','yuv420p','-r','25','-frames:v',str(frames),
            '-af',f'apad,atrim=duration={frames/25}','-t',str(frames/25),
            '-c:a','aac','-movflags','+faststart',str(output)]

def main():
    request=json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
    repo=Path(request['repo']);root=Path(request['model_dir']);workspace=Path(request['workspace']).resolve()
    sys.path.insert(0,str(repo));os.environ['PATH']=str(Path(request['ffmpeg']).parent)+os.pathsep+os.environ.get('PATH','')
    os.environ['IMAGEIO_FFMPEG_EXE']=request['ffmpeg']
    progress_path=Path(request['progress_path'])
    def progress(value):
        write_progress(progress_path,value)
    def run(args):
        completed=subprocess.run(args,capture_output=True,timeout=300,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        if completed.returncode:raise RuntimeError(completed.stderr.decode('utf-8','replace')[-3000:])
    progress(.01)
    import cv2,numpy as np,torch
    from einops import rearrange
    from omegaconf import OmegaConf
    from diffusers import AutoencoderKL,DDIMScheduler
    from accelerate.utils import set_seed
    torch.set_num_threads(4);set_seed(int(request['seed'])%(2**32))
    ffmpeg=request['ffmpeg'];frames=round(request['duration']*25);duration=frames/25
    video=workspace/'source.mp4';audio=workspace/'dialogue.wav'
    run([ffmpeg,'-v','error','-y','-ss',str(request['video_start']),'-i',request['video'],'-an','-vf','fps=25','-frames:v',str(frames),'-c:v','libx264','-crf','16','-pix_fmt','yuv420p',str(video)])
    run([ffmpeg,'-v','error','-y','-i',request['audio'],'-af',f'adelay={round(request["audio_offset"]*1000)}:all=1,apad,atrim=duration={duration}','-ar','16000','-ac','1',str(audio)])
    # A lightweight OpenCV detector avoids native InsightFace build dependencies.
    # Manual selection uses optical-flow tracking; no synthetic or procedural mouth is drawn.
    mouth_tracks=[]
    class FaceDetector:
        def __init__(self,device='cuda'):
            self.detector=cv2.FaceDetectorYN.create(request['face_detector'],'',(320,320),.5,.3,5000)
            self.previous=None;self.points=None;self.landmarks=None;self.box=None;self.mouth=None;self.missing=0
        def __call__(self,frame):
            gray=cv2.cvtColor(frame,cv2.COLOR_RGB2GRAY);height,width=gray.shape
            self.detector.setInputSize((width,height));_,detected=self.detector.detect(cv2.cvtColor(frame,cv2.COLOR_RGB2BGR))
            faces=[] if detected is None else list(detected)
            if request['face_mode']=='manual':
                selected=request['face_box'] if self.box is None else self.box
                x,y,w,h=selected
                faces=[face for face in faces if x<=face[0]+face[2]/2<=x+w and y<=face[1]+face[3]/2<=y+h]
            face=max(faces,key=lambda f:f[2]*f[3]) if faces else None
            if face is not None:
                self.box=face[:4].astype(float)
                self.mouth=np.mean([face[10:12],face[12:14]],axis=0).astype(np.float32)
                eyes=sorted([face[4:6],face[6:8]],key=lambda p:p[0]);self.landmarks=np.array([eyes[0],eyes[1],face[8:10]],dtype=np.float32);self.missing=0
            elif self.previous is None and request['face_mode']=='manual':
                x,y,w,h=request['face_box'];self.box=np.array([x,y,w,h],dtype=float)
                self.landmarks=np.array([[x+.28*w,y+.38*h],[x+.72*w,y+.38*h],[x+.50*w,y+.60*h]],dtype=np.float32)
                self.mouth=np.array([x+.50*w,y+.77*h],dtype=np.float32)
            elif self.previous is not None and self.points is not None and len(self.points)>=6:
                moved,status,_=cv2.calcOpticalFlowPyrLK(self.previous,gray,self.points,None)
                good=status.reshape(-1)==1
                matrix,_=cv2.estimateAffinePartial2D(self.points[good],moved[good],method=cv2.RANSAC) if good.sum()>=6 else (None,None)
                if matrix is None:raise RuntimeError('人脸跟踪失败，请缩短片段或重新框选人脸。')
                self.landmarks=cv2.transform(self.landmarks[None],matrix)[0]
                self.mouth=cv2.transform(self.mouth[None,None],matrix)[0,0]
                corners=np.array([self.box[:2],self.box[:2]+self.box[2:]],dtype=np.float32)
                corners=cv2.transform(corners[None],matrix)[0];self.box=np.r_[corners[0],corners[1]-corners[0]]
                self.missing+=1
                if request['face_mode']=='auto' and self.missing>25:raise RuntimeError('持续未检测到人脸，请使用手工框选或可见人脸片段。')
            else:raise RuntimeError('没有检测到可见人脸，请在口型面板手工框选人物。')
            x,y,w,h=self.box;mask=np.zeros_like(gray);mask[max(0,int(y)):min(height,int(y+h)),max(0,int(x)):min(width,int(x+w))]=255
            self.points=cv2.goodFeaturesToTrack(gray,maxCorners=100,qualityLevel=.01,minDistance=4,mask=mask)
            self.previous=gray
            mouth_tracks.append({'box':[float(v) for v in self.box],'mouth':[float(v) for v in self.mouth]})
            points=np.zeros((106,2),dtype=np.float32)
            points[[43,48,49,51,50]]=self.landmarks[0];points[101:106]=self.landmarks[1];points[[74,77,83,86]]=self.landmarks[2]
            return (x,y,x+w,y+h),points
    detector_module=types.ModuleType('latentsync.utils.face_detector');detector_module.FaceDetector=FaceDetector
    sys.modules['latentsync.utils.face_detector']=detector_module
    import latentsync.pipelines.lipsync_pipeline as pipeline_module
    from latentsync.models.unet import UNet3DConditionModel
    from latentsync.whisper.audio2feature import Audio2Feature
    from latentsync.utils.util import read_video_cv2
    # Input is already normalized. Never use the upstream shell-based read_video helper.
    pipeline_module.read_video=lambda path,**kwargs:read_video_cv2(path)
    original_run=subprocess.run
    def safe_run(command,*args,**kwargs):
        if isinstance(command,str):
            # Upstream's final mux builds an unquoted shell string. Replace it with fixed arguments.
            folder=workspace/'render'
            preserved=folder/'mouth-only.mkv'
            (workspace/'mouth-tracking.json').write_text(json.dumps(mouth_tracks),encoding='utf-8')
            preserve_source_outside_mouth(ffmpeg,video,folder/'video.mp4',preserved,mouth_tracks,frames,progress)
            command=mux_command(ffmpeg,folder,request['output'],frames,video_source=preserved)
            kwargs.pop('shell',None);kwargs.update(check=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        return original_run(command,*args,**kwargs)
    # Replace only the pipeline's subprocess binding, not Python's shared module.
    # Its utility helpers also call subprocess for FFmpeg capability checks.
    pipeline_module.subprocess=types.SimpleNamespace(run=safe_run)
    pipeline_module.check_ffmpeg_installed=lambda:run([ffmpeg,'-version'])
    config=OmegaConf.load(repo/'configs/unet/stage2.yaml')
    dtype=torch.float16
    progress(.05)
    encoder=Audio2Feature(model_path=str(root/'whisper/tiny.pt'),device='cuda',num_frames=16,audio_feat_length=config.data.audio_feat_length)
    vae=AutoencoderKL.from_pretrained(str(root/'vae'),torch_dtype=dtype,local_files_only=True)
    vae.config.scaling_factor=.18215;vae.config.shift_factor=0
    unet,_=UNet3DConditionModel.from_pretrained(OmegaConf.to_container(config.model),str(root/'latentsync_unet.pt'),device='cpu')
    pipeline=pipeline_module.LipsyncPipeline(vae=vae,audio_encoder=encoder,unet=unet.to(dtype=dtype),scheduler=DDIMScheduler.from_pretrained(str(repo/'configs'))).to('cuda')
    pipeline.enable_vae_slicing()
    progress(.12);counter=0;total=math.ceil(frames/16)*request['steps']
    def callback(step,timestep,latents):
        nonlocal counter
        counter+=1;progress(.15+.79*min(1,counter/total))
    pipeline(video_path=str(video),audio_path=str(audio),video_out_path=request['output'],num_frames=16,num_inference_steps=request['steps'],guidance_scale=request['guidance'],
        weight_dtype=dtype,width=256,height=256,mask_image_path=str(repo/'latentsync/utils/mask.png'),temp_dir=str(workspace/'render'),callback=callback,callback_steps=1)
    output=Path(request['output'])
    if not output.is_file() or output.stat().st_size<1000:raise RuntimeError('口型模型没有生成有效视频。')
    progress(1)

if __name__=='__main__':main()
