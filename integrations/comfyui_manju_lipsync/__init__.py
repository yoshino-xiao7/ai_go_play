"""Local LatentSync, serialized with the existing ComfyUI generation queue."""
from pathlib import Path
import json,os,subprocess,tempfile,time
import folder_paths
from comfy import model_management
from comfy.utils import ProgressBar

CONFIG=Path(__file__).with_name('runtime.json')
def runtime():
    try:
        cfg=json.loads(CONFIG.read_text(encoding='utf-8'));root=Path(cfg['model_dir'])
        required=['latentsync_unet.pt','whisper/tiny.pt','vae/config.json','vae/diffusion_pytorch_model.safetensors']
        if not all((root/name).is_file() for name in required):return None
        if not all(Path(cfg[key]).exists() for key in ['python','repo','face_detector','ffmpeg']):return None
        return cfg
    except (OSError,ValueError,KeyError):return None

class ManjuLatentSync15:
    @classmethod
    def INPUT_TYPES(cls):
        return {'required':{
            'engine':(['LatentSync-1.5'] if runtime() else [],),
            'video':('STRING',{'default':''}),'audio':('STRING',{'default':''}),
            'audio_offset':('FLOAT',{'default':0,'min':0,'max':120}),
            'video_start':('FLOAT',{'default':0,'min':0,'max':86400}),
            'duration':('FLOAT',{'default':5,'min':.2,'max':120}),
            'face_mode':(['auto','manual'],),'face_box':('STRING',{'default':'null'}),
            'steps':('INT',{'default':20,'min':10,'max':50}),
            'guidance':('FLOAT',{'default':1.5,'min':1,'max':3}),
            'seed':('INT',{'default':0,'min':0,'max':9007199254740991}),
            'filename_prefix':('STRING',{'default':'Manju/lipsync'})}}
    RETURN_TYPES=()
    OUTPUT_NODE=True
    FUNCTION='synchronize'
    CATEGORY='Manju/口型'

    def synchronize(self,engine,video,audio,audio_offset,video_start,duration,face_mode,face_box,steps,guidance,seed,filename_prefix):
        cfg=runtime()
        if not cfg:raise RuntimeError('LatentSync runtime or model files are incomplete.')
        inputs=[]
        for name in (video,audio):
            path=Path(folder_paths.get_annotated_filepath(name)).resolve()
            if not path.is_relative_to(Path(folder_paths.get_input_directory()).resolve()) or not path.is_file():
                raise ValueError('Lip-sync inputs must be uploaded ComfyUI input files.')
            inputs.append(path)
        output_root=Path(folder_paths.get_output_directory()).resolve()
        output=(output_root/(filename_prefix+'-lipsync.mp4')).resolve()
        if not output.is_relative_to(output_root):raise ValueError('Output prefix leaves the output directory.')
        output.parent.mkdir(parents=True,exist_ok=True)
        model_management.unload_all_models();model_management.soft_empty_cache()
        progress=ProgressBar(1000)
        with tempfile.TemporaryDirectory(prefix='manju-lipsync-',dir=folder_paths.get_temp_directory()) as temp:
            folder=Path(temp);payload=folder/'request.json';log=folder/'inference.log';progress_file=folder/'progress.json'
            payload.write_text(json.dumps({**cfg,'video':str(inputs[0]),'audio':str(inputs[1]),'output':str(output),'workspace':str(folder),
                'audio_offset':audio_offset,'video_start':video_start,'duration':duration,'face_mode':face_mode,'face_box':json.loads(face_box),
                'steps':steps,'guidance':guidance,'seed':seed,'progress_path':str(progress_file)},ensure_ascii=False),encoding='utf-8')
            process=None
            try:
                with log.open('wb') as stream:
                    process=subprocess.Popen([cfg['python'],str(Path(__file__).with_name('worker.py')),str(payload)],cwd=folder,stdout=stream,stderr=subprocess.STDOUT,stdin=subprocess.DEVNULL,
                        creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),env={**os.environ,'PYTHONIOENCODING':'utf-8','HF_HUB_OFFLINE':'1','TRANSFORMERS_OFFLINE':'1'})
                    deadline=time.monotonic()+3600
                    while process.poll() is None:
                        model_management.throw_exception_if_processing_interrupted()
                        if time.monotonic()>deadline:raise TimeoutError('Lip synchronization exceeded one hour.')
                        try:progress.update_absolute(int(json.loads(progress_file.read_text())['progress']*1000))
                        except (OSError,ValueError,KeyError):pass
                        time.sleep(.3)
                if process.returncode or not output.is_file():raise RuntimeError('LatentSync failed: '+log.read_text(encoding='utf-8',errors='replace')[-5000:])
                progress.update_absolute(1000)
            finally:
                if process and process.poll() is None:
                    process.terminate()
                    try:process.wait(timeout=10)
                    except subprocess.TimeoutExpired:process.kill();process.wait()
        return {'ui':{'videos':[{'filename':output.name,'subfolder':output.parent.relative_to(output_root).as_posix(),'type':'output'}]},'result':()}

NODE_CLASS_MAPPINGS={'ManjuLatentSync15':ManjuLatentSync15}
NODE_DISPLAY_NAME_MAPPINGS={'ManjuLatentSync15':'Manju · LatentSync 精确口型'}
