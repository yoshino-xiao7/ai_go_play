"""Verify media setup against a local package server, without external downloads."""
from hashlib import sha256
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
from threading import Thread
from urllib.error import HTTPError
import zipfile

import pytest


@pytest.fixture
def media_setup(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / 'scripts'))
    import bootstrap_core
    import install_local_ai

    runtime = tmp_path / '.manju/bootstrap'
    (runtime / 'logs').mkdir(parents=True)
    statuses = []

    def run(env):
        bootstrap_core.prepare_media(tmp_path, runtime, env, lambda phase, progress, **data:
                                     statuses.append({'phase': phase, 'progress': progress, **data}))

    return bootstrap_core, install_local_ai, runtime, statuses, run


def test_reuses_verified_system_pair_without_download(tmp_path, monkeypatch, media_setup):
    _, installer, runtime, _, run = media_setup
    stale = tmp_path / 'stale-link'
    stale.mkdir()
    for name in ('ffmpeg', 'ffprobe'):
        (tmp_path / f'{name}.exe').touch()
        (stale / f'{name}.exe').touch()
    monkeypatch.setattr(installer, 'usable_media_binary', lambda path, name, env: path.parent == tmp_path and path.stem == name)
    # No download manifest is present. Reading it would fail this test.
    run({'PATH': os.pathsep.join(map(str, (stale, tmp_path)))})
    saved = json.loads((runtime.parent / 'local-ai-paths.json').read_text())
    assert saved == {name: str(tmp_path / f'{name}.exe') for name in ('ffmpeg', 'ffprobe')}
    assert not (runtime / 'downloads').exists()


def test_runtime_reuses_bootstrap_pair_with_no_path_entry(tmp_path, monkeypatch, media_setup):
    _, installer, _, _, _ = media_setup
    media = tmp_path / 'media'
    media.mkdir()
    paths = {name: media / f'{name}.exe' for name in ('ffmpeg', 'ffprobe')}
    for path in paths.values():
        path.touch()
    monkeypatch.setattr(installer, 'PROJECT', tmp_path)
    monkeypatch.setattr(installer, 'usable_media_binary', lambda path, name, env: path == paths[name])
    installer.write_json(tmp_path / '.manju/local-ai-paths.json', {name: str(path) for name, path in paths.items()})
    runtime = tmp_path / 'local-ai'
    assert installer.prepare_runtime_media(None, runtime, {}, {'PATH': ''}) == tuple(paths.values())
    assert not (runtime / 'downloads').exists()


@pytest.mark.parametrize('denied', [False, True])
def test_missing_probe_download_progress_and_error(tmp_path, monkeypatch, media_setup, denied):
    bootstrap, installer, runtime, statuses, run = media_setup
    archive = tmp_path / 'package.zip'
    with zipfile.ZipFile(archive, 'w') as package:
        for name in ('ffmpeg', 'ffprobe'):
            package.writestr(f'ffmpeg-test/bin/{name}.exe', name)
    content = archive.read_bytes()
    attempts = []

    class Source(BaseHTTPRequestHandler):
        def do_GET(self):
            attempts.append(self.path)
            if denied:
                self.send_error(403)
                return
            self.send_response(200)
            self.send_header('Content-Length', str(len(content)))
            self.end_headers()
            self.wfile.write(content)

    tool = tmp_path / 'ffmpeg.exe'
    tool.touch()
    monkeypatch.setattr(bootstrap, 'usable_media_binary',
                        lambda path, name, env: path == tool or path.is_relative_to(runtime / 'ffmpeg'))
    monkeypatch.setattr(installer, 'usable_media_binary', lambda path, name, env: path == tool)
    with ThreadingHTTPServer(('127.0.0.1', 0), Source) as server:
        thread = Thread(target=server.serve_forever)
        thread.start()
        try:
            spec = tmp_path / 'scripts/local_ai/sources.json'
            spec.parent.mkdir(parents=True)
            spec.write_text(json.dumps({'ffmpeg': {
                'url': f'http://127.0.0.1:{server.server_port}/archive.zip',
                'sha256': sha256(content).hexdigest(),
            }}))
            env = {'PATH': str(tmp_path), 'MANJU_FFMPEG': str(tool)}
            if denied:
                with pytest.raises(HTTPError):
                    run(env)
                assert len(attempts) == 3
                assert statuses[-1]['status'] == 'failed'
                assert '403' in statuses[-1]['error']
                assert '403' in (runtime / 'logs/ffmpeg.log').read_text(encoding='utf-8')
                assert not (runtime.parent / 'local-ai-paths.json').exists()
            else:
                run(env)
                assert len(attempts) == 1
                assert any('100.0%' in row.get('detail', '') for row in statuses)
                assert any('校验' in row['phase'] for row in statuses)
                assert any('解压' in row['phase'] for row in statuses)
                saved = json.loads((runtime.parent / 'local-ai-paths.json').read_text())
                assert Path(saved['ffprobe']).is_file()
        finally:
            server.shutdown()
            thread.join()
