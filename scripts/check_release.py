"""Validate release metadata; never chooses a version or publishes anything."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
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
        if not re.search(r'^## \[' + re.escape(actual) + r'\] - \d{4}-\d{2}-\d{2}\s*$', read('CHANGELOG.md'), re.M):
            raise ValueError('CHANGELOG.md needs a dated section for the confirmed release version')
        approval = json.loads(read('release/release-approval.json'))
        if approval.get('version') != actual or approval.get('ready') is not True:
            raise ValueError('release/release-approval.json must record readiness for this exact version')
        required = ('fresh_install', 'core_regression', 'generation_scope', 'license_disclosures', 'backup_and_rollback')
        if any(approval.get('checks', {}).get(key) is not True for key in required):
            raise ValueError('Release readiness checks are incomplete; record actual evidence before release')
        evidence = approval.get('evidence')
        if not isinstance(evidence, list) or not evidence or any(not isinstance(item, str) or not item.strip() for item in evidence):
            raise ValueError('Release acceptance evidence is required')
        for item in evidence:
            relative = Path(item)
            if relative.is_absolute() or relative.drive or '..' in relative.parts or any(
                part in {'.qa', '.manju', '.git', '.venv', 'node_modules', '__pycache__'}
                for part in relative.parts
            ):
                raise ValueError('Evidence must be a distributable repository-relative file: ' + item)
            evidence_path = (root / relative).resolve()
            if not evidence_path.is_relative_to(root.resolve()) or not evidence_path.is_file():
                raise ValueError('Evidence must reference an existing repository file: ' + item)
            # A local log or merely staged file is not evidence a reviewer can
            # retrieve from the candidate commit or the source archive.
            committed = subprocess.run(
                ['git', 'cat-file', '-e', 'HEAD:' + relative.as_posix()],
                cwd=root, capture_output=True,
            )
            if committed.returncode:
                raise ValueError('Evidence must be committed in the candidate: ' + item)
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
