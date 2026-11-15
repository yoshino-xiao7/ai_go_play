from concurrent.futures import ThreadPoolExecutor
import json
import threading

import httpx
import pytest

from manju import __version__
from manju.about import LATEST_API, REPOSITORY, RELEASES_URL, UpdateChecker


def release(tag='v0.2.0', **changes):
    return dict(tag_name=tag, draft=False, prerelease=False, name='New version',
                body='Release notes', published_at='2026-11-14T01:00:00Z', **changes)


def checker(response, version='0.1.0', clock=lambda: 0):
    return UpdateChecker(version, httpx.MockTransport(lambda _: response), clock)


@pytest.mark.parametrize('current,tag,status', [
    ('0.1.0', 'v0.2.0', 'available'), ('0.9.0', 'v0.10.0', 'available'),
    ('1.9.9', 'v2.0.0', 'available'), ('0.1.0', '0.1.0', 'up_to_date'),
    ('1.0.0', 'v0.99.99', 'ahead'), ('0.1.0-dev', 'v0.2.0', 'unavailable'),
])
def test_release_comparison(current, tag, status):
    result = checker(httpx.Response(200, json=release(tag)), current).check()
    assert result['status'] == status
    assert result['latest']['url'] == f'{RELEASES_URL}/tag/{tag}'


@pytest.mark.parametrize('changes', [
    {'draft': True}, {'prerelease': True}, {'tag_name': 'v1.0.0-beta.1'},
    {'tag_name': 'main'}, {'tag_name': 'v01.2.3'}, {'tag_name': 'v1.0.0/evil'},
    {'tag_name': None}, {'draft': 'false'}, {'published_at': None},
    {'body': ['invalid']}, {'published_at': 'invalid'},
])
def test_invalid_or_nonstable_release_is_never_an_update(changes):
    payload = release()
    payload.update(changes)
    result = checker(httpx.Response(200, json=payload)).check()
    assert result['status'] == 'unavailable'
    assert result['latest'] is None


@pytest.mark.parametrize('status,reason', [
    (404, 'not_found'), (403, 'rate_limited'), (429, 'rate_limited'),
    (500, 'upstream_error'), (302, 'upstream_error'),
])
def test_http_failures_do_not_claim_latest(status, reason):
    result = checker(httpx.Response(status)).check()
    assert result['status'] == 'unavailable' and result['reason'] == reason
    assert result['latest'] is None


@pytest.mark.parametrize('error,reason', [
    (httpx.ReadTimeout('timeout'), 'timeout'),
    (httpx.ConnectError('secret proxy path'), 'network'),
])
def test_network_failures_are_sanitized(error, reason):
    def fail(_):
        raise error
    result = UpdateChecker(transport=httpx.MockTransport(fail)).check()
    assert result['reason'] == reason and result['status'] == 'unavailable'
    assert 'secret' not in json.dumps(result)


@pytest.mark.parametrize('content', [b'not json', b'[]', b'x' * (1024 * 1024 + 1)])
def test_bad_response_is_bounded_and_recoverable(content):
    assert checker(httpx.Response(200, content=content)).check()['reason'] == 'invalid_response'


def test_untrusted_urls_are_not_returned_and_notes_are_bounded():
    payload = release(html_url='javascript:alert(1)')
    payload['body'] = '<script>alert(1)</script>' + 'x' * 21000
    result = checker(httpx.Response(200, json=payload)).check()
    assert result['latest']['url'] == f'{RELEASES_URL}/tag/v0.2.0'
    assert len(result['latest']['notes']) == 20000
    assert result['latest']['notes_truncated']


def test_concurrent_checks_coalesce_and_expire():
    calls, now = [], [0]
    entered, finish = threading.Event(), threading.Event()
    def fetch(request):
        calls.append(request)
        entered.set()
        assert finish.wait(5)
        return httpx.Response(200, json=release())
    service = UpdateChecker(transport=httpx.MockTransport(fetch), clock=lambda: now[0])
    assert service.snapshot() is None
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = [pool.submit(service.check) for _ in range(3)]
        assert entered.wait(5)
        finish.set()
        results = [future.result(5) for future in futures]
    assert len(calls) == 1 and sum(r['cached'] for r in results) == 2
    now[0] = 301
    assert service.check()['cached'] is False and len(calls) == 2
    assert str(calls[0].url) == LATEST_API
    assert 'authorization' not in calls[0].headers
    assert calls[0].content == b''


def test_failure_cache_expires_and_can_recover():
    now, responses = [0], [httpx.Response(404), httpx.Response(200, json=release())]
    service = UpdateChecker(transport=httpx.MockTransport(lambda _: responses.pop(0)), clock=lambda: now[0])
    assert service.check()['reason'] == 'not_found'
    assert service.check()['cached'] is True
    now[0] = 61
    assert service.check()['status'] == 'available'


def test_rate_limit_retry_after_respected():
    result = checker(httpx.Response(429, headers={'Retry-After': '900'})).check()
    assert result['retry_after_seconds'] == 900


def test_about_does_not_contact_upstream_and_matches_version(client):
    def unexpected(_):
        pytest.fail('Opening About must not contact GitHub')
    client.app.state.updates = UpdateChecker(transport=httpx.MockTransport(unexpected))
    response = client.get('/api/about')
    assert response.status_code == 200
    body = response.json()
    assert body['version'] == __version__ == client.get('/api/health').json()['version']
    assert body['update'] is None and body['repository'] == REPOSITORY
    assert body['community_qq'] == '455106785'
    assert 'MIT License' in body['license_text']
    assert str(client.app.state.store.root) not in response.text
    assert not any(key in body['runtime'] for key in ('hostname', 'username', 'path'))


def test_check_route_and_local_origin_guard(client):
    client.app.state.updates = checker(httpx.Response(200, json=release()))
    assert client.post('/api/about/updates/check', headers={'Origin': 'https://evil.example'}).status_code == 403
    response = client.post('/api/about/updates/check')
    assert response.status_code == 200 and response.json()['status'] == 'available'
    assert client.get('/api/about').json()['update']['latest']['version'] == '0.2.0'
    assert client.post('/api/about/updates/check').json()['cached'] is True
