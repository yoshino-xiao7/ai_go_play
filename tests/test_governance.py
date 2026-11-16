"""Release and push gates use disposable repositories, never the working checkout."""
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import zipfile

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'


def load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f'{name}.py')
    module = importlib.util.module_from_spec(spec)
    # These standalone scripts import their sibling check_release module.
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


release = load('check_release')
push = load('check_push')
packager = load('package_release')
versions = load('set_version')
docs = load('check_docs')


def write(root, name, content):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding='utf-8')


def git(root, *args):
    return subprocess.check_output(['git', '-c', 'core.hooksPath=', *args], cwd=root, stderr=subprocess.STDOUT)


@pytest.fixture
def candidate(tmp_path):
    write(tmp_path, 'VERSION', '1.2.3\n')
    write(tmp_path, 'pyproject.toml', '[project]\nversion = "1.2.3"\n')
    write(tmp_path, 'backend/manju/__init__.py', '__version__ = "1.2.3"\n')
    write(tmp_path, 'frontend/package.json', '{"version":"1.2.3"}')
    write(tmp_path, 'frontend/package-lock.json', '{"version":"1.2.3","packages":{"":{"version":"1.2.3"}}}')
    write(tmp_path, 'CHANGELOG.md', '## [1.2.3] - 2026-11-14\n### 验收范围\n- 未验证：实体电脑和 GPU。\n')
    git(tmp_path, 'init', '--initial-branch=dev')
    git(tmp_path, 'config', 'user.email', 'test@example.invalid')
    git(tmp_path, 'config', 'user.name', 'Governance test')
    git(tmp_path, 'add', '.')
    git(tmp_path, 'commit', '-m', 'candidate fixture')
    return tmp_path


def test_release_rejects_inconsistent_or_unconfirmed_version(candidate):
    assert release.validate(candidate, '1.2.3', release=True) == '1.2.3'
    with pytest.raises(ValueError, match='merger-confirmed'):
        release.validate(candidate, '1.2.4', release=True)
    write(candidate, 'backend/manju/__init__.py', '__version__ = "1.2.2"\n')
    with pytest.raises(ValueError, match='all match'):
        release.validate(candidate)


@pytest.mark.parametrize('notes', [
    '### 验收范围\n- 未验证：\n',
    '### 验收范围\n- 未验证：  \n### 升级\n下一行有内容\n',
    '### 验收范围\n- Windows CI\n### 安装\n- 未验证：实体电脑和 GPU。\n',
    '### 安装\n- 未验证：实体电脑和 GPU。\n',
    '测试发布。\n## [1.2.2] - 2026-11-13\n### 验收范围\n- 未验证：实体电脑和 GPU。\n',
])
def test_release_requires_unverified_scope_in_current_version(candidate, notes):
    write(candidate, 'CHANGELOG.md', '## [1.2.3] - 2026-11-14\n' + notes)
    with pytest.raises(ValueError, match='disclose unverified coverage'):
        release.validate(candidate, release=True)


def test_release_requires_dated_notes(candidate):
    write(candidate, 'CHANGELOG.md', '## [Unreleased]\n')
    with pytest.raises(ValueError, match='dated section'):
        release.validate(candidate, release=True)


@pytest.mark.parametrize('target', ['refs/heads/main', 'refs/heads/integration', 'refs/tags/v1.2.3'])
def test_push_rejects_aliases_and_deletions(target):
    assert push.blocked_updates([f'refs/heads/dev {"a"*40} {target} {"b"*40}']) == [target]
    assert push.blocked_updates([f'(delete) {"0"*40} {target} {"b"*40}']) == [target]


def test_push_allows_development():
    assert push.blocked_updates([f'refs/heads/dev {"a"*40} refs/heads/dev {"b"*40}']) == []
    with pytest.raises(ValueError):
        push.blocked_updates(['invalid input'])


def test_version_preparation_still_requires_release_notes(candidate):
    changes = versions.prepare(candidate, '2.0.0')
    assert (candidate / 'VERSION').read_text().strip() == '1.2.3'
    for name, contents in changes.items():
        write(candidate, name, contents)
    assert release.validate(candidate) == '2.0.0'
    with pytest.raises(ValueError, match='dated section'):
        release.validate(candidate, release=True)


@pytest.fixture
def repository(candidate):
    for name in packager.REQUIRED:
        write(candidate, name, 'fixture startup source\n')
    write(candidate, '.gitignore', 'frontend/dist/\n.qa/\n.env\n')
    git(candidate, 'init', '--initial-branch=dev')
    git(candidate, 'config', 'user.email', 'test@example.invalid')
    git(candidate, 'config', 'user.name', 'Governance test')
    git(candidate, 'add', '.')
    git(candidate, 'commit', '-m', 'test fixture')
    write(candidate, 'frontend/dist/index.html', '<!doctype html><title>Fixture</title>')
    return candidate


def test_package_contains_only_source_and_build_with_valid_hash(repository):
    write(repository, '.env', 'PRIVATE_TEST_VALUE=never-package\n')
    write(repository, '.qa/private.txt', 'private fixture\n')
    target = packager.package(repository, repository / '.qa/release-dist')
    with zipfile.ZipFile(target) as archive:
        names = archive.namelist()
        assert 'ai-go-play-1.2.3/frontend/dist/index.html' in names
        assert 'ai-go-play-1.2.3/start.cmd' in names
        assert not any('/.env' in n or '/.qa/' in n for n in names)
        assert archive.testzip() is None
    manifest = json.loads(target.with_name('release-manifest.json').read_text())
    assert manifest['sha256'] == hashlib.sha256(target.read_bytes()).hexdigest()
    assert manifest['commit'] == git(repository, 'rev-parse', 'HEAD').decode().strip()
    with pytest.raises(ValueError, match='overwrite'):
        packager.package(repository, repository / '.qa/release-dist')


def test_package_rejects_missing_tracked_files_and_dirty_source(repository):
    write(repository, 'start.cmd', 'changed after review')
    with pytest.raises(ValueError, match='clean'):
        packager.package(repository, repository / '.qa/output')
    git(repository, 'rm', '--cached', 'start.cmd')
    with pytest.raises(ValueError, match='not committed'):
        packager.package(repository, repository / '.qa/output')


@pytest.mark.parametrize('name', ['model.safetensors', 'library.sqlite', '.env', '.qa/private.txt'])
def test_package_rejects_accidentally_committed_private_data(repository, name):
    write(repository, name, 'fixture only')
    git(repository, 'add', '-f', name)
    git(repository, 'commit', '-m', 'unsafe fixture')
    with pytest.raises(ValueError, match='must not be tracked'):
        packager.package(repository, repository / '.qa/output')


def test_documentation_check_catches_missing_and_escaping_links(repository):
    write(repository, 'README.md', '[valid](VERSION)\n[missing](absent.md)\n[escape](../outside.md)\n[web](https://example.invalid)\n<img src="missing.svg">\n```\n[example](ignored.md)\n```\n')
    _, errors = docs.check(repository)
    assert len(errors) == 3
    assert any('absent.md' in error for error in errors)
    assert any('../outside.md' in error for error in errors)
