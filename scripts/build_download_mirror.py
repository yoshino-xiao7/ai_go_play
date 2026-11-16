"""Export the fixed installation artifacts and package registries for HTTPS hosting."""
from __future__ import annotations

import argparse
import base64
from concurrent.futures import ThreadPoolExecutor
import hashlib
import html
import json
from pathlib import Path
import re
import shutil
import sys
from urllib.parse import quote, unquote, urlsplit
from urllib.error import URLError
from urllib.request import urlopen

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / 'backend'))
from manju.download_sources import artifact_path, artifact_urls, managed_python_sources, source_config


def collect():
    core = json.loads((PROJECT / 'release/setup-sources.json').read_text(encoding='utf-8'))
    local = json.loads((PROJECT / 'scripts/local_ai/sources.json').read_text(encoding='utf-8'))
    assets = [item for item in [*core.values(), *local.values(), *core['nodes']]
              if isinstance(item, dict) and 'url' in item and 'sha256' in item]
    config = source_config()
    assets.append(config['uv_wheel'])
    wheel_urls = re.compile(r'^\w+ @ (https://\S+) \\\n\s+--hash=sha256:([a-f0-9]{64})', re.MULTILINE)
    for lock in ('speech.lock', 'lipsync.lock'):
        source = (PROJECT / 'scripts/local_ai' / lock).read_text(encoding='utf-8')
        assets.extend({'url': url, 'sha256': sha} for url, sha in wheel_urls.findall(source))
    index = {artifact_path(item): (item['url'], 'sha256', item['sha256']) for item in assets}
    python_base = managed_python_sources({'MANJU_DOWNLOAD_SOURCE': 'overseas'})[0]
    for item in config['managed_python'].values():
        index[f"python-build-standalone/{item['path']}"] = (
            f"{python_base}/{item['path']}", 'sha256', item['sha256'])
    lock = json.loads((PROJECT / 'frontend/package-lock.json').read_text(encoding='utf-8'))
    for entry in lock['packages'].values():
        url = entry.get('resolved', '')
        if url.startswith('https://registry.npmjs.org/') and entry.get('integrity'):
            algorithm, expected = entry['integrity'].split('-', 1)
            index['npm' + urlsplit(url).path] = (url, algorithm, base64.b64decode(expected).hex())
    return index


def export_file(output, path, url, algorithm, expected):
    target = output.joinpath(*unquote(path).split('/'))
    if not target.resolve().is_relative_to(output):
        raise ValueError(f'Invalid mirror path: {path}')
    if target.is_file():
        with target.open('rb') as stream:
            if hashlib.file_digest(stream, algorithm).hexdigest() == expected:
                return
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.name + '.partial')
    print('Exporting', path, flush=True)
    try:
        with urlopen(url, timeout=45) as response, partial.open('wb') as stream:
            shutil.copyfileobj(response, stream, length=1024 * 1024)
        with partial.open('rb') as stream:
            if hashlib.file_digest(stream, algorithm).hexdigest() != expected:
                raise ValueError(f'{path}: upstream checksum mismatch')
        partial.replace(target)
    finally:
        partial.unlink(missing_ok=True)


def export_wheelhouse(output, directory):
    packages = {}
    index = {}
    for distribution in sorted(directory.iterdir()):
        if not distribution.is_file():
            continue
        filename = distribution.name
        if filename.endswith('.whl'):
            project = filename.split('-', 1)[0]
        elif filename.endswith(('.tar.gz', '.zip')):
            project = filename.split('.tar.gz')[0].removesuffix('.zip').rsplit('-', 1)[0]
        else:
            continue
        name = re.sub(r'[-_.]+', '-', project).lower()
        if not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', name):
            raise ValueError(f'Invalid package name: {filename}')
        with distribution.open('rb') as stream:
            sha = hashlib.file_digest(stream, 'sha256').hexdigest()
        relative = f'pypi/files/{sha}/{quote(filename)}'
        export_file(output, relative, distribution.resolve().as_uri(), 'sha256', sha)
        index[relative] = {'sha256': sha}
        packages.setdefault(name, []).append((filename, sha))
    for name, wheels in packages.items():
        folder = output / 'pypi/simple' / name
        folder.mkdir(parents=True, exist_ok=True)
        links = [f'<a href="../../files/{sha}/{quote(file)}#sha256={sha}">{html.escape(file)}</a>'
                 for file, sha in wheels]
        (folder / 'index.html').write_text('\n'.join(links) + '\n', encoding='utf-8')
    if packages:
        root = output / 'pypi/simple/index.html'
        root.write_text('\n'.join(f'<a href="{p}/">{p}</a>' for p in sorted(packages)) + '\n', encoding='utf-8')
    return index


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    parser.add_argument('--plan', action='store_true', help='report the inventory without downloading')
    parser.add_argument('--wheelhouse', type=Path, help='add a pre-resolved Windows wheelhouse to the static PyPI index')
    parser.add_argument('--reuse', type=Path, action='append', default=[],
                        help='scan an existing installer download or cache directory for pinned files')
    args = parser.parse_args()
    output = args.output.resolve()
    index = collect()
    if args.plan:
        print(json.dumps({path: {'upstream': url, algorithm: sha}
                          for path, (url, algorithm, sha) in index.items()}, indent=2))
        return
    cached = {}
    for directory in args.reuse:
        for file in directory.rglob('*'):
            if file.is_file() and file.suffix not in ('.partial', '.tmp'):
                cached.setdefault(file.name, []).append(file)

    def export(entry):
        path, (url, algorithm, sha) = entry
        target = output / unquote(path)
        if target.is_file():
            with target.open('rb') as stream:
                if hashlib.file_digest(stream, algorithm).hexdigest() == sha:
                    return
        name = unquote(urlsplit(url).path.rsplit('/', 1)[-1])
        paths = [*cached.get(name, []), *(file for extension in ('.zip', '.7z', '.exe', '.whl')
                                         for file in cached.get(sha + extension, []))]
        for candidate in paths:
            with candidate.open('rb') as stream:
                if hashlib.file_digest(stream, algorithm).hexdigest() == sha:
                    return export_file(output, path, candidate.resolve().as_uri(), algorithm, sha)
        if path.startswith('python-build-standalone/'):
            relative = path.split('/', 1)[1]
            urls = [f'{base}/{relative}' for base in managed_python_sources({'MANJU_DOWNLOAD_SOURCE': 'china'})]
        elif path.startswith('artifacts/'):
            urls = artifact_urls({'url': url, 'sha256': sha}, {'MANJU_DOWNLOAD_SOURCE': 'china'})
        else:
            urls = [url]
        failures = []
        for candidate in urls:
            try:
                return export_file(output, path, candidate, algorithm, sha)
            except (URLError, TimeoutError, ValueError) as error:
                failures.append(f'{urlsplit(candidate).hostname}: {error}')
        raise RuntimeError(f'{path}: ' + '; '.join(failures))

    with ThreadPoolExecutor(max_workers=3) as pool:
        list(pool.map(export, index.items()))
    inventory = {path: {'upstream': url, algorithm: sha} for path, (url, algorithm, sha) in index.items()}
    if args.wheelhouse:
        inventory.update(export_wheelhouse(output, args.wheelhouse))
    (output / 'mirror-index.json').write_text(json.dumps(inventory, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
