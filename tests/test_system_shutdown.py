import os
import socket
import subprocess
import sys
import time
import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import httpx
import pytest

from manju.store import DomainError


@pytest.fixture
def owned(client, monkeypatch):
    called = []
    client.app.state.request_shutdown = lambda: called.append(True)
    monkeypatch.setattr(client.app.state.comfy, 'status', lambda: {'managed': False, 'status': 'stopped'})
    return called


def test_shutdown_requires_explicit_confirmation_and_local_origin(client, owned):
    assert client.get('/api/system/shutdown').json()['supported']
    assert not owned
    assert client.post('/api/system/shutdown', json={}).status_code == 422
    assert client.post('/api/system/shutdown', json={'confirm': True}, headers={'origin': 'https://evil.example'}).status_code == 403
    assert not owned


def test_shutdown_does_not_stop_external_comfy_and_gates_new_writes(client, owned, monkeypatch):
    monkeypatch.setattr(client.app.state.comfy, 'status', lambda: {'managed': False, 'status': 'external'})
    monkeypatch.setattr(client.app.state.comfy, 'stop', lambda *_: pytest.fail('External Comfy must not be stopped'))
    response = client.post('/api/system/shutdown', json={'confirm': True})
    assert response.status_code == 202
    assert response.json()['stopped_comfy'] is False
    assert owned == [True]
    assert client.post('/api/projects', json={'name': 'too late'}).status_code == 503
    assert client.post('/api/system/shutdown', json={'confirm': True}).status_code == 409


def test_unmanaged_server_cannot_claim_to_exit(client):
    response = client.post('/api/system/shutdown', json={'confirm': True})
    assert response.status_code == 409
    assert response.json()['detail']['code'] == 'shutdown_unmanaged'
    assert not client.app.state.shutting_down


def test_existing_library_upgrade_does_not_fabricate_first_run_consent(client):
    assert not client.get('/api/setup').json()['existing_library_installation']
    client.post('/api/projects', json={'name': '此前已在使用的资料库'})
    state = client.get('/api/setup').json()
    assert state['existing_library_installation']
    assert state['consent'] is None and not state['completed']
    # Once the user explicitly starts setup, it remains a normal resumable setup.
    client.app.state.setup.save()
    assert not client.get('/api/setup').json()['existing_library_installation']


@pytest.mark.parametrize('kind', ['write', 'migration', 'setup'])
def test_busy_work_prevents_shutdown_and_releases_gate(client, owned, kind):
    state = client.app.state
    if kind == 'write':
        state.active_writes = 1
    elif kind == 'migration':
        state.store.maintenance = True
    else:
        state.setup.jobs.thread = SimpleNamespace(is_alive=lambda: True, join=lambda **_: None)
    try:
        response = client.post('/api/system/shutdown', json={'confirm': True})
        assert response.status_code == 409
        assert response.json()['detail']['code'] == 'shutdown_busy'
        assert not state.shutting_down and not owned
    finally:
        state.active_writes = 0
        state.store.maintenance = False
        if kind == 'setup':
            state.setup.jobs.thread = None


def test_managed_comfy_queue_is_never_force_stopped(client, owned, monkeypatch):
    monkeypatch.setattr(client.app.state.comfy, 'status', lambda: {'managed': True, 'status': 'running'})
    def stop(force):
        assert force is False
        raise DomainError(409, '队列仍有任务', 'comfy_queue_busy')
    monkeypatch.setattr(client.app.state.comfy, 'stop', stop)
    response = client.post('/api/system/shutdown', json={'confirm': True, 'stop_comfy': True})
    assert response.status_code == 409
    assert not client.app.state.shutting_down and not owned


def test_managed_comfy_stops_before_server(client, owned, monkeypatch):
    stopped = []
    monkeypatch.setattr(client.app.state.comfy, 'status', lambda: {'managed': not stopped, 'status': 'running' if not stopped else 'stopped'})
    monkeypatch.setattr(client.app.state.comfy, 'stop', lambda force: stopped.append(force))
    client.app.state.comfy.operation_thread = None
    response = client.post('/api/system/shutdown', json={'confirm': True})
    assert response.status_code == 202 and response.json()['stopped_comfy']
    assert stopped == [False] and owned == [True]


def test_export_in_progress_prevents_shutdown(client, owned, monkeypatch, tmp_path):
    project_id = client.post('/api/projects', json={'name': '导出期间不退出'}).json()['id']
    entered, release = threading.Event(), threading.Event()
    archive = tmp_path / 'export.manju'
    archive.write_bytes(b'isolated export')
    def export(*_):
        entered.set()
        assert release.wait(5)
        return archive
    monkeypatch.setattr('manju.app.export_project', export)
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(client.get, f'/api/projects/{project_id}/export')
        try:
            assert entered.wait(5)
            response = client.post('/api/system/shutdown', json={'confirm': True})
            assert response.status_code == 409 and not owned
            assert response.json()['detail']['code'] == 'shutdown_busy'
        finally:
            release.set()
        assert pending.result().status_code == 200
    assert client.app.state.active_writes == 0


def test_cli_shutdown_releases_listener_and_persists_project(tmp_path):
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        port = listener.getsockname()[1]
    url = f'http://127.0.0.1:{port}'
    command = [sys.executable, '-m', 'manju', 'serve', '--port', str(port), '--data-dir', str(tmp_path / 'data'), '--config-file', str(tmp_path / 'config.json')]
    project_id = None
    for launch in range(2):
        with (tmp_path / f'launch-{launch}.log').open('wb') as log:
            process = subprocess.Popen(command, stdout=log, stderr=log, env=dict(os.environ, PYTHONUTF8='1'))
            try:
                with httpx.Client(base_url=url, timeout=10, trust_env=False) as c:
                    for _ in range(100):
                        try:
                            if c.get('/api/health').status_code == 200:
                                break
                        except httpx.HTTPError:
                            pass
                        time.sleep(.1)
                    else:
                        pytest.fail('Isolated service did not start')
                    assert c.get('/api/system/shutdown').json()['supported']
                    if launch == 0:
                        project_id = c.post('/api/projects', json={'name': '退出后仍保留'}).json()['id']
                    else:
                        assert c.get('/api/projects/' + project_id).json()['name'] == '退出后仍保留'
                    assert c.post('/api/system/shutdown', json={'confirm': True, 'stop_comfy': False}).status_code == 202
                assert process.wait(timeout=15) == 0
                with socket.socket() as probe:
                    assert probe.connect_ex(('127.0.0.1', port)) != 0
            finally:
                if process.poll() is None:
                    process.terminate()
                    process.wait(timeout=10)
