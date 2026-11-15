"""Windows PowerShell 5 must serve setup before Python or Node is available."""
import json
import os
from pathlib import Path
import subprocess
import time
import shutil
import socket

import httpx
import pytest


@pytest.mark.skipif(os.name != 'nt', reason='Windows bootstrap HTTP host')
def test_bootstrap_page_status_retry_origin_and_shutdown(tmp_path):
    project = Path(__file__).resolve().parents[1]
    state_dir = tmp_path / '.manju/bootstrap'
    state_dir.mkdir(parents=True)
    status = state_dir / 'status.json'
    status.write_text(json.dumps({'status':'failed','phase':'Download failed','progress':.2,'error':'retry-test'}))
    process = subprocess.Popen(['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',
                                str(project / 'scripts/bootstrap-web.ps1'), '-StateDir', str(state_dir),
                                '-PagePath', str(project / 'scripts/bootstrap.html'), '-Token', 'test-only'],
                               creationflags=subprocess.CREATE_NO_WINDOW)
    try:
        deadline = time.monotonic() + 10
        while not (state_dir / 'web.json').is_file():
            assert time.monotonic() < deadline
            time.sleep(.1)
        web = json.loads((state_dir / 'web.json').read_text(encoding='utf-8-sig'))
        with httpx.Client(base_url=f"http://127.0.0.1:{web['port']}", trust_env=False, timeout=4) as client:
            assert '准备你的创作空间' in client.get('/').text
            assert client.get('/status').json()['error'] == 'retry-test'
            assert client.post('/retry/test-only', headers={'Origin':'https://untrusted.example'}).status_code == 403
            assert client.get('/status', headers={'Host':'untrusted.example'}).status_code == 403
            assert client.post('/retry/wrong').status_code == 404
            assert client.post('/retry/test-only').status_code == 200
            assert (state_dir / 'retry.request').exists()
            # Reopening start.cmd during an active install returns its existing page.
            import ctypes
            from ctypes import wintypes
            kernel = ctypes.WinDLL('kernel32', use_last_error=True)
            kernel.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
            kernel.CreateMutexW.restype = wintypes.HANDLE
            kernel.ReleaseMutex.argtypes = [wintypes.HANDLE]
            kernel.CloseHandle.argtypes = [wintypes.HANDLE]
            with socket.socket() as listener:
                listener.bind(('127.0.0.1', 0))
                app_port = listener.getsockname()[1]
            mutex = kernel.CreateMutexW(None, True, f'Local\\Manju.Start.{app_port}')
            assert mutex
            try:
                shutil.copy2(project / 'start.ps1', tmp_path / 'start.ps1')
                result = subprocess.run(['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass',
                                         '-File', str(tmp_path / 'start.ps1'), '-NoBrowser', '-Port', str(app_port)],
                                        capture_output=True, timeout=8)
                assert result.returncode == 0, result.stderr
                assert f"http://127.0.0.1:{web['port']}/".encode() in result.stdout
                assert not (tmp_path / '.venv').exists()
            finally:
                kernel.ReleaseMutex(mutex)
                kernel.CloseHandle(mutex)
            status.write_text(json.dumps({'status':'ready','url':'http://127.0.0.1:8799','progress':1}))
            assert client.get('/status').json()['status'] == 'ready'
        assert process.wait(timeout=20) == 0
    finally:
        if process.poll() is None: process.terminate(); process.wait(timeout=5)
