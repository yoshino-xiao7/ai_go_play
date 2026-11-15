"""Prepare the version explicitly selected by the maintainer on a development branch."""
import argparse
import json
import re
import subprocess
from check_release import ROOT, SEMVER


def prepare(root, version):
    if not SEMVER.fullmatch(version):
        raise ValueError('Use an explicit X.Y.Z version; no automatic increment is performed')
    changes = {'VERSION': version + '\n'}
    for path in ('frontend/package.json', 'frontend/package-lock.json'):
        doc = json.loads((root / path).read_text(encoding='utf-8'))
        doc['version'] = version
        if 'packages' in doc:
            doc['packages']['']['version'] = version
        changes[path] = json.dumps(doc, ensure_ascii=False, indent=2) + '\n'
    for path, pattern, replacement in (
        ('pyproject.toml', r'^version = "[^"]+"', f'version = "{version}"'),
        ('backend/manju/__init__.py', r'^__version__ = "[^"]+"', f'__version__ = "{version}"'),
    ):
        contents, count = re.subn(pattern, replacement, (root / path).read_text(encoding='utf-8'), count=1, flags=re.M)
        if count != 1:
            raise ValueError('Version declaration not found: ' + path)
        changes[path] = contents
    return changes


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('version')
    parser.add_argument('--write', action='store_true', help='Without this flag only list planned changes')
    args = parser.parse_args()
    branch = subprocess.check_output(['git', 'branch', '--show-current'], cwd=ROOT, text=True).strip()
    if branch in ('main', 'integration', ''):
        parser.exit(1, 'Prepare versions on dev or a development branch, then submit to integration.\n')
    changes = prepare(ROOT, args.version)
    for name, content in changes.items():
        if args.write:
            (ROOT / name).write_text(content, encoding='utf-8')
        print(('Updated ' if args.write else 'Would update ') + name)
    print('Also prepare CHANGELOG.md and release/release-approval.json; this does not confirm or publish a release.')
