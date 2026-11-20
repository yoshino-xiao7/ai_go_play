"""Verify the distributable agent skills offline, without running media jobs."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import posixpath
import re
import tempfile
from urllib.parse import unquote, urlsplit


ROOT = Path(__file__).resolve().parents[1]
SKILLS = (
    'ai-go-play-canvas',
    'ai-go-play-h3-official',
    'ai-go-play-h3-enhancer',
    'ai-go-play-maimai',
)
ORIGINAL_ENTRIES = {
    'ai-go-play-h3-official': ('skills/h3-prompt-writing/SKILL.md',),
    'ai-go-play-h3-enhancer': ('minimaxh3-enh/SKILL.md',),
    'ai-go-play-maimai': (
        'skills/maimai-tangtang-animation/SKILL.md',
        'skills/mmt-cel-first-frame/SKILL.md',
    ),
}
CANVAS_REFERENCES = (
    'references/control-api.md',
    'references/assets-and-generation.md',
    'references/production-and-timeline.md',
)


def _required_file(package, name):
    path = package / name
    if not path.is_file():
        raise ValueError(f'{package.name}: missing required file {name}')
    return path


def _windows_path(path):
    """Keep check cleanup working even with Windows' deep sandbox TEMP roots."""
    value = str(Path(path).absolute())
    if os.name == 'nt' and not value.startswith('\\\\?\\'):
        value = '\\\\?\\UNC\\' + value[2:] if value.startswith('\\\\') else '\\\\?\\' + value
    return value


def _local_links(files, entrypoints):
    """Require skill-local links; supplemental repository galleries stay optional."""
    prefixes = tuple(str(PurePosixPath(entry).parent) + '/' for entry in entrypoints)
    checked = 0
    for name, data in files.items():
        if not name.endswith('.md') or not name.startswith(prefixes):
            continue
        content = re.sub(r'```.*?```', '', data.decode('utf-8-sig'), flags=re.S)
        links = re.finditer(r'!?\[[^\]]*\]\((<?[^\s)]+>?)(?:\s+"[^"]*")?\)', content)
        for match in links:
            value = match[1].strip('<>')
            if value.startswith(('#', '//')) or urlsplit(value).scheme:
                continue
            relative = unquote(value.split('#', 1)[0].split('?', 1)[0])
            if not relative:
                continue
            target = posixpath.normpath(posixpath.join(posixpath.dirname(name), relative))
            if target in files:
                checked += 1
            elif target.startswith(prefixes):
                raise ValueError(f'{name}: missing skill-local target {value}')
            # Supplemental docs may refer to the full upstream repository.
            # They are deliberately not treated as bundled wardrobe galleries.
    return checked


def _source_collection(package):
    # Check all shipped pieces before executing even the local reading helper.
    for name in ('NOTICE.md', 'scripts/source.py', 'sources/manifest.json', 'sources/upstream.zip'):
        _required_file(package, name)
    loader = package / 'scripts/source.py'
    namespace = {'__name__': '_collected_skill_check', '__file__': str(loader)}
    exec(compile(loader.read_text(encoding='utf-8-sig'), str(loader), 'exec'), namespace)
    manifest, files = namespace['verified_files'](package)
    expected = ORIGINAL_ENTRIES[package.name]
    if manifest['name'] != package.name or tuple(manifest['entrypoints']) != expected:
        raise ValueError('Source manifest does not identify the expected original entrypoints')
    for entry in manifest['files']:
        data = files[entry['path']]
        if 'git_blob_sha' in entry:
            blob = f'blob {len(data)}\0'.encode('ascii') + data
            if hashlib.sha1(blob).hexdigest() != entry['git_blob_sha']:
                raise ValueError(f"Upstream Git blob mismatch: {entry['path']}")
    links = _local_links(files, expected)
    # A new cache proves no previously installed skill or cached source is needed.
    # The TemporaryDirectory owns and cleans up only this newly created directory.
    with tempfile.TemporaryDirectory(prefix='ai-go-play-skill-check-', dir=_windows_path(tempfile.gettempdir())) as cache:
        result = namespace['materialize'](package, cache)
        extracted = Path(result['root'])
        for name, data in files.items():
            if (extracted / name).read_bytes() != data:
                raise ValueError(f'Materialized bytes differ: {name}')
        for entry in result['entrypoints']:
            if not Path(entry).read_text(encoding='utf-8-sig').strip():
                raise ValueError(f'Original skill is empty: {entry}')
    return {
        'source_files': len(files),
        'source_entrypoints': list(expected),
        'local_links_checked': links,
        'repository': manifest['repository'],
        'commit': manifest['commit'],
    }


def check(root=ROOT, tracked=None):
    """Return four summaries, or ValueError when an entry or its sources fail.

    When ``tracked`` is provided, every meaningful package file must be included
    in that repository-relative path set, as required by the release packager.
    No network, application service, third-party Python package or GPU is used.
    """
    root = Path(root).resolve()
    directory = root / '.agents/skills'
    discovered = {path.relative_to(directory).as_posix() for path in directory.rglob('SKILL.md')}
    expected = {name + '/SKILL.md' for name in SKILLS}
    if discovered != expected:
        missing = sorted(expected - discovered)
        extra = sorted(discovered - expected)
        raise ValueError(f'Expected exactly four project skill entrypoints; missing={missing}, extra={extra}')
    tracked = {str(name).replace('\\', '/') for name in tracked} if tracked is not None else None
    summaries = []
    for name in SKILLS:
        package = directory / name
        try:
            body = (package / 'SKILL.md').read_text(encoding='utf-8-sig')
            frontmatter = re.match(r'\A---[ \t]*\n(.*?)\n---(?:\n|\Z)', body, flags=re.S)
            declared = re.search(r'^name:[ \t]*(.+?)[ \t]*$', frontmatter[1], re.M) if frontmatter else None
            if declared is None or declared[1].strip('\"\'') != name:
                raise ValueError('SKILL.md frontmatter name must match its directory')
            description = re.search(r'^description:[ \t]*(.+?)[ \t]*$', frontmatter[1], re.M)
            if description is None or not description[1].strip('\"\' \t'):
                raise ValueError('SKILL.md requires a non-empty discovery description')
            interface = _required_file(package, 'agents/openai.yaml').read_text(encoding='utf-8-sig')
            if not interface.strip():
                raise ValueError('agents/openai.yaml is empty')
            shipped = [file for file in package.rglob('*') if file.is_file()
                       and '__pycache__' not in file.parts and file.suffix != '.pyc']
            if tracked is not None:
                untracked = sorted(file.relative_to(root).as_posix() for file in shipped
                                   if file.relative_to(root).as_posix() not in tracked)
                if untracked:
                    raise ValueError('Skill files are not committed: ' + ', '.join(untracked))
            summary = {'name': name, 'package_files': len(shipped)}
            if name == 'ai-go-play-canvas':
                for reference in CANVAS_REFERENCES:
                    if not _required_file(package, reference).read_text(encoding='utf-8-sig').strip():
                        raise ValueError(f'Canvas reference is empty: {reference}')
                summary['canvas_references'] = len(CANVAS_REFERENCES)
            else:
                summary.update(_source_collection(package))
            summaries.append(summary)
        except Exception as error:
            raise ValueError(f'{name}: {error}') from error
    return summaries


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT, help='Repository or extracted package root')
    args = parser.parse_args()
    try:
        summaries = check(args.root)
    except (ValueError, OSError) as error:
        parser.exit(1, f'Agent skill check failed: {error}\n')
    print(json.dumps({'skills': summaries, 'offline_source_check': 'passed'}, ensure_ascii=False, indent=2))
