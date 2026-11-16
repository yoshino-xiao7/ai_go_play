"""Validate release metadata; never chooses a version or publishes anything."""
import argparse
import json
import os
from pathlib import Path
import re
import tomllib

ROOT = Path(__file__).resolve().parents[1]
SEMVER = re.compile(r'(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)')


def validate(root=ROOT, version=None, release=False):
    read = lambda path: (root / path).read_text(encoding='utf-8')
    actual = read('VERSION').strip()
    if not SEMVER.fullmatch(actual) or (version is not None and version != actual):
        raise ValueError('VERSION must match the merger-confirmed X.Y.Z version')
    package = json.loads(read('frontend/package.json'))
    lock = json.loads(read('frontend/package-lock.json'))
    backend = re.search(r'^__version__ = "([^"]+)"', read('backend/manju/__init__.py'), re.M)
    versions = [tomllib.loads(read('pyproject.toml'))['project']['version'], package['version'], lock['version'], lock['packages']['']['version'], backend.group(1) if backend else None]
    if any(value != actual for value in versions):
        raise ValueError('Python, backend, frontend and lock-file versions must all match VERSION')
    if release:
        notes = re.search(
            rf'^## \[{re.escape(actual)}\] - \d{{4}}-\d{{2}}-\d{{2}}[^\S\n]*\n(.*?)(?=^## |\Z)',
            read('CHANGELOG.md'), re.M | re.S,
        )
        if not notes:
            raise ValueError('CHANGELOG.md needs a dated section for the confirmed release version')
        scope = re.search(r'^### 验收范围[^\S\n]*\n(.*?)(?=^### |\Z)', notes[1], re.M | re.S)
        if not scope or not re.search(r'^- 未验证：[ \t]*\S[^\n]*$', scope[1], re.M):
            raise ValueError('The current release notes must disclose unverified coverage under 验收范围')
    return actual


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--version')
    parser.add_argument('--release', action='store_true')
    parser.add_argument('--pull-request', action='store_true', help='Bind version to Release-Version in the Actions PR event')
    args = parser.parse_args()
    try:
        if args.pull_request:
            event = json.loads(Path(os.environ['GITHUB_EVENT_PATH']).read_text(encoding='utf-8'))
            declared = re.search(r'^Release-Version:\s*(\S+)\s*$', event['pull_request'].get('body') or '', re.M)
            if not declared:
                raise ValueError('Release PR is missing Release-Version: X.Y.Z')
            args.version = declared.group(1)
        print('Release metadata valid: ' + validate(version=args.version, release=args.release))
    except (ValueError, KeyError, OSError) as error:
        parser.exit(1, str(error) + '\n')
