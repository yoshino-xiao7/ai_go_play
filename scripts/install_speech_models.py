"""Download the pinned upstream inference files; resumable, no API credentials."""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import argparse, json, hashlib, time
import httpx

def install(root):
    root=Path(root);root.mkdir(parents=True,exist_ok=True)
    repos=[('IndexTeam/IndexTTS-2.5','',lambda n:'/' not in n and n not in ('.gitattributes','README.md')),
           ('facebook/w2v-bert-2.0','hf_cache/w2v-bert-2.0',lambda n:n in ('config.json','preprocessor_config.json','model.safetensors')),
           ('funasr/campplus','hf_cache',lambda n:n=='campplus_cn_common.bin'),
           ('nvidia/bigvgan_v2_22khz_80band_256x','hf_cache/bigvgan',lambda n:n in ('config.json','bigvgan_generator.pt'))]
    jobs=[];manifest=[]
    for repo,folder,accept in repos:
        info=httpx.get('https://huggingface.co/api/models/'+repo,timeout=60).raise_for_status().json()
        revision=info['sha'];manifest.append({'repo':repo,'revision':revision})
        for f in info['siblings']:
            name=f['rfilename']
            if accept(name):jobs.append((f'https://huggingface.co/{repo}/resolve/{revision}/{name}',root/folder/name))
    def download(job):
        url,path=job;path.parent.mkdir(parents=True,exist_ok=True)
        if path.exists():return
        part=path.with_suffix(path.suffix+'.partial')
        for attempt in range(8):
            try:
                offset=part.stat().st_size if part.exists() else 0
                with httpx.stream('GET',url,headers={'Range':f'bytes={offset}-'} if offset else {},follow_redirects=True,timeout=120) as r:
                    r.raise_for_status()
                    with part.open('ab' if offset and r.status_code==206 else 'wb') as out:
                        for chunk in r.iter_bytes(1024*1024):out.write(chunk)
                part.replace(path);print('Downloaded',path.name,flush=True);return
            except Exception as e:
                print(path.name,'retry',attempt+1,type(e).__name__,flush=True);time.sleep(2)
        raise RuntimeError('Download failed: '+path.name)
    with ThreadPoolExecutor(max_workers=3) as pool:list(pool.map(download,jobs))
    files=[{'path':str(p.relative_to(root)),'size':p.stat().st_size,'sha256':hashlib.file_digest(p.open('rb'),'sha256').hexdigest()} for _,p in jobs]
    (root/'manju-models.json').write_text(json.dumps({'sources':manifest,'files':files},indent=2),encoding='utf-8')
    print('Models ready',root,flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--directory',required=True);install(p.parse_args().directory)
