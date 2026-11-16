from hashlib import sha256

import httpx
import pytest

from manju import download_sources, setup_install


def test_prefers_domestic_then_project_mirror_and_keeps_overseas_first():
    spec = {
        'url': 'https://nodejs.org/dist/v22.23.5/node-v22.23.5-win-x64.zip',
        'sha256': 'a' * 64,
    }
    env = {'MANJU_PROJECT_MIRROR': 'https://downloads.example.test/env'}
    own = f"https://downloads.example.test/env/artifacts/{'a' * 64}/node-v22.23.5-win-x64.zip"
    china = 'https://npmmirror.com/mirrors/node/v22.23.5/node-v22.23.5-win-x64.zip'
    assert download_sources.artifact_urls(spec, {**env, 'MANJU_DOWNLOAD_SOURCE': 'china'}) == (china, own, spec['url'])
    assert download_sources.artifact_urls(spec, {**env, 'MANJU_DOWNLOAD_SOURCE': 'overseas'}) == (spec['url'], china, own)


def test_registry_failure_falls_back_without_changing_parent_environment():
    env = {'MANJU_DOWNLOAD_SOURCE': 'china', 'MANJU_PROJECT_MIRROR': 'https://downloads.example.test'}
    attempted = []

    def attempt(child, host):
        attempted.append((child['UV_DEFAULT_INDEX'], host))
        assert child['PIP_INDEX_URL'] == child['UV_DEFAULT_INDEX']
        if host == 'mirrors.aliyun.com':
            raise RuntimeError('temporary connection failure')
        return 'installed'

    assert download_sources.run_from_registry('pypi', env, attempt) == 'installed'
    assert attempted == [
        ('https://mirrors.aliyun.com/pypi/simple/', 'mirrors.aliyun.com'),
        ('https://downloads.example.test/pypi/simple/', 'downloads.example.test'),
    ]
    assert 'PIP_INDEX_URL' not in env


@pytest.mark.parametrize('broken', [403, 200])
def test_web_installer_uses_verified_alternate_source(tmp_path, monkeypatch, broken):
    expected = b'verified archive data'
    spec = {'url': 'https://origin.example.test/archive.7z', 'sha256': sha256(expected).hexdigest()}
    alternate = 'https://mirror.example.test/archive.7z'
    attempted = []

    def response(request):
        attempted.append(str(request.url))
        if request.url.host == 'origin.example.test':
            return httpx.Response(broken, stream=httpx.ByteStream(b'wrong bytes'))
        return httpx.Response(200, stream=httpx.ByteStream(expected))

    class Job:
        def check_cancelled(self):
            pass

        def update(self, **_):
            pass

    original_client = httpx.Client
    monkeypatch.setattr(setup_install, 'artifact_urls', lambda _: (spec['url'], alternate))
    monkeypatch.setattr(setup_install.httpx, 'Client',
                        lambda **kw: original_client(transport=httpx.MockTransport(response), **kw))
    target = setup_install.download(spec, tmp_path, Job(), '.7z')
    assert target.read_bytes() == expected
    assert attempted == [spec['url'], alternate]
    assert not target.with_suffix('.7z.partial').exists()
