"""Build a release ZIP from tracked source plus a freshly built frontend."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import zipfile
from check_release import ROOT, validate

REQUIRED = ('start.cmd', 'start.ps1', 'scripts/bootstrap.ps1', 'scripts/bootstrap_core.py',
            'backend/manju/setup_api.py', 'backend/manju/system_api.py',
            'LICENSE', 'release/NOTICE.txt', 'release/MODEL-LICENSES.md',
            'release/models.json', 'release/model-checksums.sha256',
            '首次启动先看我.md', '首次启动先看我.txt')
FORBIDDEN_PARTS = {'.qa', '.manju', '.venv', 'node_modules', '__pycache__'}


def package(root, output):
    version = validate(root, release=True)
    tracked = subprocess.check_output(['git', 'ls-files', '-z'], cwd=root).decode('utf-8').split('\0')
    tracked = [name for name in tracked if name]
    missing = set(REQUIRED) - set(tracked)
    if missing:
        raise ValueError('Required startup files are not committed: ' + ', '.join(sorted(missing)))
    if subprocess.check_output(['git', 'status', '--porcelain', '--untracked-files=no'], cwd=root).strip():
        raise ValueError('Tracked working tree must be clean before packaging')
    paths = []
    for name in tracked:
        path = Path(name)
        if FORBIDDEN_PARTS.intersection(path.parts) or path.name.startswith('.env') and path.name != '.env.example' or path.suffix.lower() in ('.sqlite', '.db', '.safetensors', '.pth', '.pt', '.ckpt', '.onnx'):
            raise ValueError('Private runtime data or model weights must not be tracked: ' + name)
        if (root / path).is_symlink():
            raise ValueError('Release source must not contain symlinks: ' + name)
        paths.append(name)
    dist = root / 'frontend/dist'
    if not (dist / 'index.html').is_file():
        raise ValueError('Build frontend/dist before packaging')
    for path in dist.rglob('*'):
        if path.is_symlink():
            raise ValueError('Built frontend must not contain symlinks: ' + str(path))
        if path.is_file():
            paths.append(path.relative_to(root).as_posix())
    output.mkdir(parents=True, exist_ok=True)
    target = output / f'ai-go-play-v{version}.zip'
    if target.exists():
        raise ValueError('Refusing to overwrite a release archive')
    prefix = f'ai-go-play-{version}/'
    with zipfile.ZipFile(target, 'x', compression=zipfile.ZIP_DEFLATED) as archive:
        for name in sorted(set(paths)):
            archive.write(root / name, prefix + name)
    with zipfile.ZipFile(target) as archive:
        bad = archive.testzip()
        if bad:
            raise ValueError('Archive failed CRC validation: ' + bad)
    with target.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    (output / 'SHA256SUMS').write_text(f'{digest}  {target.name}\n', encoding='utf-8')
    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip()
    (output / 'release-manifest.json').write_text(json.dumps({'version': version, 'commit': commit,
        'asset': target.name, 'size': target.stat().st_size, 'sha256': digest, 'model_weights_included': False}, indent=2)+'\n', encoding='utf-8')
    return target


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / '.qa/release-dist')
    args = parser.parse_args()
    try:
        print(package(ROOT, args.output.resolve()))
    except (ValueError, OSError) as error:
        parser.exit(1, str(error)+'\n')
