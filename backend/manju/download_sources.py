"""Source selection shared by the bootstrappers and the Web installer."""
from __future__ import annotations

from functools import lru_cache
import json
import os
from pathlib import Path
import re
from urllib.parse import urlsplit


PROJECT = Path(__file__).resolve().parents[2]


@lru_cache(maxsize=1)
def source_config():
    return json.loads((PROJECT / 'release/download-sources.json').read_text(encoding='utf-8'))


def mirror_base(env, config):
    base = env.get('MANJU_PROJECT_MIRROR') or config.get('project_mirror')
    if not base:
        return ''
    parsed = urlsplit(base)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError('项目镜像需要使用不含凭据、查询参数或片段的 HTTPS 地址。')
    return base.rstrip('/')


def artifact_path(spec):
    name = urlsplit(spec['url']).path.rsplit('/', 1)[-1]
    if not re.fullmatch('[a-f0-9]{64}', spec['sha256']) or not name or name in ('.', '..'):
        raise ValueError('固定版本下载条目缺少有效的完整性信息。')
    return f"artifacts/{spec['sha256']}/{name}"


def ordered_sources(overseas, china, own, env):
    if env.get('MANJU_DOWNLOAD_SOURCE') == 'china':
        candidates = [*china, *own, *overseas]
    else:
        candidates = [*overseas, *china, *own]
    return tuple(dict.fromkeys(candidates))


def artifact_urls(spec, env=None):
    env = os.environ if env is None else env
    config = source_config()
    url = spec['url']
    china = config['artifact_mirrors'].get(url, [])
    if url.startswith('https://download.pytorch.org/whl/'):
        china = [config['china']['pytorch'] + url.removeprefix('https://download.pytorch.org/whl/')]
    base = mirror_base(env, config)
    own = [f'{base}/{artifact_path(spec)}'] if base and urlsplit(url).scheme == 'https' else []
    return ordered_sources([url, *config['artifact_fallbacks'].get(url, [])], china, own, env)


def registry_urls(kind, env):
    config = source_config()
    base = mirror_base(env, config)
    own_path = 'pypi/simple/' if kind == 'pypi' else 'npm/'
    return ordered_sources([config['overseas'][kind]], [config['china'][kind]],
                           [f'{base}/{own_path}'] if base else [], env)


def managed_python_sources(env):
    config = source_config()
    base = mirror_base(env, config)
    official = 'https://releases.astral.sh/github/python-build-standalone/releases/download'
    github = 'https://github.com/astral-sh/python-build-standalone/releases/download'
    return ordered_sources([official, github], [config['china']['python']],
                           [f'{base}/python-build-standalone'] if base else [], env)


def run_from_registry(kind, env, run):
    failures = []
    for registry in registry_urls(kind, env):
        child = dict(env)
        if kind == 'pypi':
            for key in ('UV_INDEX', 'UV_DEFAULT_INDEX', 'UV_INDEX_URL', 'UV_EXTRA_INDEX_URL',
                        'PIP_EXTRA_INDEX_URL', 'PIP_FIND_LINKS'):
                child.pop(key, None)
            child.update(UV_DEFAULT_INDEX=registry, PIP_INDEX_URL=registry, PIP_CONFIG_FILE=os.devnull,
                         UV_HTTP_TIMEOUT='30', UV_HTTP_RETRIES='1', PIP_TIMEOUT='30', PIP_RETRIES='1')
        else:
            child.update(npm_config_registry=registry, npm_config_replace_registry_host='npmjs',
                         npm_config_fetch_retries='1', npm_config_fetch_timeout='30000')
        try:
            return run(child, urlsplit(registry).hostname)
        except RuntimeError as error:
            failures.append(f'{urlsplit(registry).hostname}: {error}')
    raise RuntimeError('所有安装源均失败：\n' + '\n'.join(failures))
