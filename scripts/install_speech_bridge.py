"""Install the isolated speech bridge into an existing local ComfyUI.

Does not edit ComfyUI packages or start/stop the service. Run after installing
the IndexTTS environment and model manifest; restart ComfyUI when its queue is idle.
"""
import argparse
import json
from pathlib import Path
import shutil

def install(comfy,runtime,models):
    root=Path(__file__).resolve().parents[1]
    comfy,runtime,models=map(lambda x:Path(x).resolve(),(comfy,runtime,models))
    python=runtime/'.venv/Scripts/python.exe'
    if not python.is_file() or not (comfy/'main.py').is_file() or not (models/'manju-models.json').is_file():raise RuntimeError('ComfyUI, isolated runtime or verified models are missing.')
    destination=comfy/'custom_nodes/comfyui_manju_speech'
    destination.mkdir(parents=True,exist_ok=True)
    for name in ('__init__.py','worker.py','runtime_env.py'):shutil.copy2(root/'integrations/comfyui_manju_speech'/name,destination/name)
    (destination/'runtime.json').write_text(json.dumps({'python':str(python),'repo':str(runtime),'model_dir':str(models)},indent=2),encoding='utf-8')
    print('Installed bridge:',destination)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--comfy',required=True);p.add_argument('--runtime',required=True);p.add_argument('--models',required=True)
    a=p.parse_args();install(a.comfy,a.runtime,a.models)
