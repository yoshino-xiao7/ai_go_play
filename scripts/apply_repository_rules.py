"""Preview desired rules; --apply uses an already authenticated GitHub CLI."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess

ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply',action='store_true')
    args=parser.parse_args()
    repo=json.loads((ROOT/'.github/governance.json').read_text(encoding='utf-8'))['repository']
    files=sorted((ROOT/'.github/rulesets').glob('*.json'))
    for path in files:
        spec=json.loads(path.read_text(encoding='utf-8'))
        print(spec['name']+': '+', '.join(spec['conditions']['ref_name']['include']))
    if not args.apply:
        print('Preview only. No remote configuration changed. Review docs/REPOSITORY-SETUP.md before applying.')
        return
    if not shutil.which('gh'):
        parser.exit(1,'Install GitHub CLI and authenticate with repository administration permission first.\n')
    def api(*arguments):
        result=subprocess.run(['gh','api',*arguments],capture_output=True,text=True,encoding='utf-8')
        if result.returncode:
            # gh errors do not require printing credentials or request headers.
            raise RuntimeError(result.stderr.strip())
        return json.loads(result.stdout) if result.stdout.strip() else None
    try:
        # Fail before mutation if the private-repository plan does not support rulesets.
        existing=[]
        page=1
        while True:
            batch=api(f'repos/{repo}/rulesets?per_page=100&page={page}')
            existing.extend(batch)
            if len(batch)<100:
                break
            page+=1
        by_name={rule['name']:rule for rule in existing}
        for path in files:
            spec=json.loads(path.read_text(encoding='utf-8'))
            old=by_name.get(spec['name'])
            endpoint=f'repos/{repo}/rulesets'+('/'+str(old['id']) if old else '')
            saved=api('--method','PUT' if old else 'POST',endpoint,'--input',str(path))
            verified=api(f"repos/{repo}/rulesets/{saved['id']}")
            if any(verified.get(key)!=spec[key] for key in ('name','target','enforcement','conditions')) or {json.dumps(rule,sort_keys=True) for rule in verified.get('rules',[])}!={json.dumps(rule,sort_keys=True) for rule in spec['rules']} or verified.get('bypass_actors',[])!=spec['bypass_actors']:
                raise RuntimeError('Read-back verification failed: '+spec['name'])
            print('Applied and read back: '+spec['name'])
    except RuntimeError as error:
        parser.exit(1,str(error)+'\nAny earlier successful updates remain active; inspect before retrying.\n')


if __name__=='__main__':
    main()
