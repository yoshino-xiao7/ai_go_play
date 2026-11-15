"""Installer contracts: corrupt/incomplete inputs must never publish a bridge."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import zipfile

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('local_ai_install_test', ROOT / 'scripts/install_local_ai.py')
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


def test_sources_extract_once_and_detect_user_modification(tmp_path):
    package = tmp_path / 'source.zip'
    with zipfile.ZipFile(package, 'w') as stream:
        stream.writestr('repo/', '')
        stream.writestr('repo/package/code.py', 'original')
    destination = tmp_path / 'source'
    sha = installer.digest(package)
    installer.unpack(package, destination, sha)
    installer.unpack(package, destination, sha)
    (destination / 'package/code.py').write_text('user edit')
    with pytest.raises(ValueError, match='edited'):
        installer.unpack(package, destination, sha)
    assert (destination / 'package/code.py').read_text() == 'user edit'


@pytest.mark.parametrize('name', ['repo/../escape', '/outside', 'repo/C:/escape', 'other/escape', 'repo/..\\escape'])
def test_archive_cannot_leave_destination(tmp_path, name):
    package = tmp_path / 'bad.zip'
    with zipfile.ZipFile(package, 'w') as stream:
        stream.writestr('repo/', '')
        stream.writestr(name, 'bad')
    with pytest.raises(ValueError, match='Unsafe'):
        installer.unpack(package, tmp_path / 'source', installer.digest(package))
    assert not (tmp_path / 'source').exists()
    assert not (tmp_path / 'escape').exists()


def test_corrupt_model_is_reported_before_installation(tmp_path, monkeypatch):
    project = tmp_path / 'project'
    release = project / 'release'
    release.mkdir(parents=True)
    models = tmp_path / 'models'
    models.mkdir()
    model = models / 'model.bin'
    model.write_bytes(b'good')
    (release / 'models.json').write_text(json.dumps({'files': [{'path': 'model.bin', 'packs': ['05-indextts']}]}))
    (release / 'model-checksums.sha256').write_text(installer.digest(model) + '  model.bin\n')
    monkeypatch.setattr(installer, 'PROJECT', project)
    assert installer.validate_models(models, ['speech'], False)['verified_files'] == 1
    model.write_bytes(b'evil')  # Same size is not sufficient.
    with pytest.raises(ValueError, match='SHA256 mismatch: model.bin'):
        installer.validate_models(models, ['speech'], False)
    model.unlink()
    with pytest.raises(ValueError, match='Missing model files'):
        installer.validate_models(models, ['speech'], False)


def test_bridge_backup_and_complete_runtime_helpers(tmp_path):
    destination = tmp_path / 'nodes'
    bridge = destination / 'comfyui_manju_speech'
    bridge.mkdir(parents=True)
    (bridge / 'runtime.json').write_text('{"old": true}')
    (bridge / 'worker.py').write_text('previous worker')
    config = {'kind': 'speech', 'python': 'new-python', 'repo': 'new-source'}
    root = tmp_path / 'install'
    installer.install_bridge(config, destination, root)
    assert json.loads((bridge / 'runtime.json').read_text()) == config
    assert (bridge / 'runtime_env.py').is_file()
    backup = list((root / 'backups').iterdir())[0]
    assert (backup / 'worker.py').read_text() == 'previous worker'
    assert json.loads((backup / 'runtime.json').read_text()) == {'old': True}


def test_worker_environment_uses_private_caches(tmp_path, monkeypatch):
    module_spec = importlib.util.spec_from_file_location('worker_env_test', ROOT / 'integrations/comfyui_manju_speech/runtime_env.py')
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    monkeypatch.setenv('PYTHONPATH', 'old-comfy-site-packages')
    monkeypatch.setenv('HF_HOME', 'global-hf-cache')
    config = {'cache_dir': str(tmp_path), 'python': 'python.exe', 'ffmpeg': str(tmp_path / 'bin/ffmpeg.exe')}
    env = module.worker_environment(config)
    assert 'PYTHONPATH' not in env
    assert env['HF_HOME'] == str(tmp_path / 'huggingface')
    assert env['HF_HUB_OFFLINE'] == '1'
    assert env['PATH'].split(__import__('os').pathsep)[0] == str(tmp_path / 'bin')


def test_runtime_helpers_stay_identical():
    speech = ROOT / 'integrations/comfyui_manju_speech/runtime_env.py'
    lipsync = ROOT / 'integrations/comfyui_manju_lipsync/runtime_env.py'
    assert speech.read_bytes() == lipsync.read_bytes()


def test_worker_launch_handles_unicode_paths_and_output(tmp_path, monkeypatch):
    module_spec = importlib.util.spec_from_file_location('worker_command_test', ROOT / 'integrations/comfyui_manju_speech/runtime_env.py')
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    folder = tmp_path / '中文路径 with spaces'
    folder.mkdir()
    payload = folder / '请求.json'
    payload.write_text(json.dumps({'text': '你好，こんにちは 🎬'}, ensure_ascii=False), encoding='utf-8')
    script = folder / '工作进程.py'
    script.write_text("import json, pathlib, sys\nassert sys.flags.isolated\nprint(json.loads(pathlib.Path(sys.argv[1]).read_text(encoding='utf-8'))['text'])\n", encoding='utf-8')
    monkeypatch.setenv('PYTHONIOENCODING', 'ascii')
    result = subprocess.run(module.worker_command({'python': sys.executable}, script, payload), capture_output=True, check=True, timeout=20)
    assert result.stdout.decode('utf-8').strip() == '你好，こんにちは 🎬'


def test_media_finds_installer_ffmpeg_without_system_path(tmp_path, monkeypatch):
    from manju import media
    monkeypatch.setattr(media, '__file__', str(tmp_path / 'backend/manju/media.py'))
    monkeypatch.setattr(media.shutil, 'which', lambda name: None)
    monkeypatch.delenv('MANJU_FFMPEG', raising=False)
    monkeypatch.delenv('MANJU_FFPROBE', raising=False)
    binary = tmp_path / 'private/bin/ffmpeg.exe'
    installer.write_json(tmp_path / '.manju/local-ai-paths.json', {'ffmpeg': str(binary)})
    calls = []
    monkeypatch.setattr(media, 'run_process', lambda command, **kwargs: calls.append(command))
    media.find_binary.cache_clear()
    try:
        assert media.find_binary('ffmpeg') == str(binary.resolve())
        assert calls == [[str(binary), '-version']]
    finally:
        media.find_binary.cache_clear()
