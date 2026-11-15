"""Application identity and an explicit, read-only GitHub Releases check."""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import platform
import re
import threading
import time
from urllib.parse import quote

import httpx
from fastapi import APIRouter, Request

from . import __version__

REPOSITORY = 'yoshino-xiao7/ai_go_play'
REPOSITORY_URL = f'https://github.com/{REPOSITORY}'
RELEASES_URL = f'{REPOSITORY_URL}/releases'
LATEST_API = f'https://api.github.com/repos/{REPOSITORY}/releases/latest'
router = APIRouter(prefix='/api/about', tags=['about'])


def stable_version(value: object) -> tuple[int, int, int] | None:
    # Release governance permits X.Y.Z only. Never compare versions lexically.
    if not isinstance(value, str) or len(value) > 100:
        return None
    match = re.fullmatch(r'v?(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)', value)
    return tuple(int(part) for part in match.groups()) if match else None


class UpdateChecker:
    """Per-server cache and lock keep concurrent tabs from exhausting the API quota."""

    def __init__(self, version: str = __version__, transport=None, clock=time.monotonic):
        self.version = version
        self.transport = transport
        self.clock = clock
        self.lock = threading.Lock()
        self.result: dict | None = None
        self.expires = 0.0

    def snapshot(self):
        # Assignment is atomic; readers need not wait for a network check.
        result = self.result
        return {**result, 'cached': True} if result else None

    def check(self):
        with self.lock:
            if self.result and self.clock() < self.expires:
                return {**self.result, 'cached': True}
            result = {
                'current_version': self.version, 'status': 'unavailable',
                'reason': '', 'message': '', 'latest': None,
                'checked_at': datetime.now(timezone.utc).isoformat(),
                'cached': False, 'retry_after_seconds': 60,
            }
            try:
                self._fetch(result)
            except httpx.TimeoutException:
                result.update(reason='timeout', message='连接 GitHub 超时，请检查网络后重试。')
            except httpx.HTTPError:
                result.update(reason='network', message='暂时无法连接 GitHub，请检查网络或代理设置后重试。')
            except (ValueError, TypeError, KeyError):
                result.update(reason='invalid_response', message='GitHub 返回的版本信息无法识别，请到发布页核实。')
            self.expires = self.clock() + result['retry_after_seconds']
            self.result = result
            return dict(result)

    def _fetch(self, result: dict):
        # No credentials, local paths, project data or configurable destination.
        with httpx.Client(timeout=10.0, follow_redirects=False, transport=self.transport) as client:
            with client.stream('GET', LATEST_API, headers={
                'Accept': 'application/vnd.github+json',
                'X-GitHub-Api-Version': '2026-03-10',
                'User-Agent': 'ai-go-play-update-check',
            }) as response:
                if response.status_code == 404:
                    result.update(reason='not_found', message='暂未找到可公开访问的正式版本。仓库可能尚未发布 Release，或暂未公开。')
                    return
                if response.status_code in (403, 429):
                    result.update(reason='rate_limited', message='GitHub 暂时限制了请求，请稍后重试，或直接访问发布页。')
                    wait = response.headers.get('retry-after', '')
                    reset = response.headers.get('x-ratelimit-reset', '')
                    result['retry_after_seconds'] = min(3600, max(60, int(wait) if wait.isdigit() else (int(reset) - int(time.time()) if reset.isdigit() else 60)))
                    return
                if response.status_code != 200:
                    result.update(reason='upstream_error', message='GitHub 暂时无法提供版本信息，请稍后重试。')
                    return
                payload = bytearray()
                for chunk in response.iter_bytes():
                    payload.extend(chunk)
                    if len(payload) > 1024 * 1024:
                        raise ValueError('Release response too large')
                release = json.loads(payload)
        if not isinstance(release, dict):
            raise ValueError('Expected a release object')
        tag = release.get('tag_name')
        latest = stable_version(tag)
        if release.get('draft') is not False or release.get('prerelease') is not False or latest is None:
            result.update(reason='unsupported_release', message='上游版本不符合正式发布格式，请到发布页核实。')
            return
        body = release.get('body') or ''
        name = release.get('name') or tag
        published = release.get('published_at')
        if not isinstance(body, str) or not isinstance(name, str) or not isinstance(published, str):
            raise ValueError('Invalid release fields')
        datetime.fromisoformat(published.replace('Z', '+00:00'))
        result['latest'] = {
            'version': '.'.join(map(str, latest)), 'tag': tag, 'name': name[:300],
            'published_at': published, 'notes': body[:20000],
            'notes_truncated': len(body) > 20000,
            # Construct the link from our known upstream, not untrusted API URLs.
            'url': f'{RELEASES_URL}/tag/{quote(tag, safe="")}',
        }
        current = stable_version(self.version)
        if current is None:
            result.update(reason='unsupported_current', message='当前为自定义版本，无法自动比较，请对照发布说明。')
            return
        status, message = (
            ('available', '发现新的正式版本。') if latest > current else
            ('up_to_date', '当前版本与最新正式版本一致。') if latest == current else
            ('ahead', '当前版本高于最新正式版本，无需降级。')
        )
        result.update(status=status, message=message, retry_after_seconds=300)


@router.get('')
def about(request: Request):
    license_file = Path(__file__).resolve().parents[2] / 'LICENSE'
    try:
        license_text = license_file.read_text(encoding='utf-8')
    except OSError:
        license_text = ''
    return {
        'name': 'ai-go-play', 'version': __version__, 'channel': 'stable',
        'repository': REPOSITORY, 'repository_url': REPOSITORY_URL,
        'releases_url': RELEASES_URL, 'community_qq': '455106785',
        'runtime': {'system': platform.system(), 'architecture': platform.machine(), 'python': platform.python_version()},
        'license': 'MIT', 'license_text': license_text,
        'update': request.app.state.updates.snapshot(),
    }


@router.post('/updates/check')
def check_updates(request: Request):
    return request.app.state.updates.check()
