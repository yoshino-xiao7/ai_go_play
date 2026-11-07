from __future__ import annotations

import json
import base64
import os
from pathlib import Path
import socket
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import venv

import psutil
import pytest

from manju.comfy import ComfyManager, detect_installation, identity_process, process_identity, scan_installations
from manju import comfy
from manju.store import DomainError


FAKE_MAIN = '''
import argparse, json, os, pathlib, subprocess, sys, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
parser = argparse.ArgumentParser()
parser.add_argument('--listen', default='127.0.0.1')
parser.add_argument('--port', type=int)
args, _ = parser.parse_known_args()
root = pathlib.Path(__file__).parent
print('测试服务启动', flush=True)
print('测试错误流', file=sys.stderr, flush=True)
if (root / 'exit.flag').exists():
    print('requested test exit', flush=True)
    sys.exit(7)
child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(600)'], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
(root / 'child.pid').write_text(str(child.pid))
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/system_stats':
            value = {'system': {'comfyui_version': 'test'}, 'devices': []}
        elif self.path == '/queue':
            file = root / 'queue.json'
            value = json.loads(file.read_text()) if file.exists() else {'queue_running': [], 'queue_pending': []}
        else:
            self.send_error(404)
            return
        body = json.dumps(value).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    def log_message(self, *args):
        pass
ThreadingHTTPServer((args.listen, args.port), Handler).serve_forever()
'''


def free_port():
    with socket.socket() as connection:
        connection.bind(("127.0.0.1", 0))
        return connection.getsockname()[1]


def wait_status(manager, expected, timeout=12):
    deadline = time.monotonic() + timeout
    result = None
    while time.monotonic() < deadline:
        result = manager.status()
        if result["status"] == expected:
            return result
        time.sleep(0.05)
    pytest.fail(f"Expected {expected}, got {result}; logs={manager.logs()}")


@pytest.fixture
def installation(tmp_path):
    root = tmp_path / "二次元 工作流" / "ComfyUI"
    root.mkdir(parents=True)
    (root / "main.py").write_text(FAKE_MAIN, encoding="utf-8")
    (root / "server.py").write_text("# installation marker", encoding="utf-8")
    (root / "comfy").mkdir()
    venv.EnvBuilder(with_pip=False).create(root / ".venv")
    return root


@pytest.fixture
def manager(tmp_path, installation):
    controller = ComfyManager(tmp_path / "preferences" / "config.json")
    controller.configure(str(installation), free_port())
    yield controller
    if controller._owned_processes():
        controller._stop_worker()
    controller.close()


def test_scan_portable_and_venv_in_unicode_paths(tmp_path, installation):
    portable = tmp_path / "便携 服务" / "ComfyUI_windows_portable"
    comfy = portable / "ComfyUI"
    comfy.mkdir(parents=True)
    (comfy / "main.py").touch()
    (comfy / "server.py").touch()
    (comfy / "comfy").mkdir()
    (portable / "python_embeded").mkdir()
    (portable / "python_embeded" / "python.exe").touch()
    result = scan_installations(str(tmp_path))
    assert {item["kind"] for item in result["installations"]} == {"portable", "venv"}
    assert len(result["installations"]) == 2
    assert detect_installation(comfy)["path"] == str(portable)
    assert detect_installation(installation)["comfy_path"] == str(installation)
    with pytest.raises(DomainError, match="不存在"):
        scan_installations(str(tmp_path / "missing"))


def test_managed_lifecycle_idempotence_logs_and_restart(manager, installation):
    started = manager.start()
    assert started["status"] == "starting"
    assert started["can_stop"] is True
    assert manager.start()["pid"] == started["pid"]
    running = wait_status(manager, "running")
    assert running["managed"] and running["queue"] == {"running": 0, "pending": 0}
    command = manager.record["identity"]["cmdline"]
    assert "--disable-auto-launch" in command
    assert command[command.index("--listen") + 1] == "127.0.0.1"
    if os.name == "nt":
        assert Path(command[0]).name.casefold() == "pythonw.exe"
    assert any("测试服务启动" in line for line in manager.logs()["lines"])
    owned = [process_identity(process) for process in manager._owned_processes()]
    assert len(owned) >= 2
    bootstrap = manager.directory.parent / "config.json"
    manager.close()
    reconnected = ComfyManager(bootstrap)
    try:
        state = reconnected.status()
        assert state["status"] == "running" and state["managed"]
        assert reconnected.stop()["status"] == "stopping"
        wait_status(reconnected, "stopped")
        assert all(identity_process(identity) is None for identity in owned)
        assert not reconnected._port_open(state["port"])
    finally:
        reconnected.close()


@pytest.mark.skipif(os.name != "nt", reason="Windows venv console regression")
def test_windows_venv_keeps_process_tree_windowless_and_logs_both_streams(manager):
    manager.start()
    names = set()
    deadline = time.monotonic() + 12
    state = None
    while time.monotonic() < deadline:
        for process in manager._owned_processes():
            try:
                names.add(process.name().casefold())
            except psutil.NoSuchProcess:
                continue
        state = manager.status()
        if state["status"] == "running":
            break
        time.sleep(0.01)
    assert state["status"] == "running", manager.logs()
    assert "pythonw.exe" in names
    assert not names.intersection({"conhost.exe", "windowsterminal.exe", "openconsole.exe"})
    assert all(process.name().casefold() == "pythonw.exe" for process in manager._owned_processes())
    lines = manager.logs()["lines"]
    assert "测试服务启动" in lines
    assert "测试错误流" in lines
    manager.stop()
    wait_status(manager, "stopped")


def test_busy_queue_requires_force(manager, installation):
    manager.start()
    wait_status(manager, "running")
    (installation / "queue.json").write_text(json.dumps({"queue_running": [[1]], "queue_pending": [[2]]}))
    with pytest.raises(DomainError) as failed:
        manager.stop()
    assert failed.value.detail["code"] == "comfy_queue_busy"
    assert manager.status()["status"] == "running"
    manager.stop(force=True)
    wait_status(manager, "stopped")


def test_reused_pid_identity_is_never_stopped(manager):
    manager.start()
    wait_status(manager, "running")
    original = json.loads(json.dumps(manager.record))
    manager.record["identity"]["created"] -= 100
    manager.record["descendants"] = []
    try:
        with pytest.raises(DomainError) as failed:
            manager.stop(force=True)
        assert failed.value.detail["code"] == "comfy_external"
        assert identity_process(original["identity"], original["token"]) is not None
    finally:
        manager.record = original


def test_unrelated_process_record_is_rejected(manager):
    current = psutil.Process()
    manager.record = {"status": "running", "identity": process_identity(current), "token": "not-the-process-token", "descendants": [], "started_epoch": time.time()}
    with pytest.raises(DomainError) as failed:
        manager.stop(force=True)
    assert failed.value.detail["code"] == "comfy_ownership_lost"
    assert current.is_running()
    manager.record = {}


@pytest.mark.parametrize("external_comfy", [False, True])
def test_foreign_service_port_is_not_started_or_stopped(manager, external_comfy):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            value = {"system": {}, "devices": []} if external_comfy else {"different": "service"}
            if self.path == "/queue":
                value = {"queue_running": [], "queue_pending": []}
            payload = json.dumps(value).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(("127.0.0.1", manager.port), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        state = manager.status()
        assert state["status"] == ("external" if external_comfy else "port_conflict")
        assert not state["managed"] and not state["can_stop"]
        with pytest.raises(DomainError):
            manager.start()
        with pytest.raises(DomainError) as failed:
            manager.stop(force=True)
        assert failed.value.detail["code"] == "comfy_external"
        assert thread.is_alive()
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_stop_resumes_after_controller_restart(manager):
    manager.start()
    wait_status(manager, "running")
    manager.record["status"] = "stopping"
    manager._save_record()
    bootstrap = manager.directory.parent / "config.json"
    manager.close()
    restarted = ComfyManager(bootstrap)
    try:
        restarted.start_monitor()
        wait_status(restarted, "stopped")
        assert restarted.record["identity"] is None
    finally:
        restarted.close()


def test_failed_start_keeps_logs_and_can_retry(manager, installation):
    (installation / "exit.flag").touch()
    manager.start()
    failed = wait_status(manager, "error")
    assert failed["can_start"] and not failed["managed"]
    assert any("requested test exit" in line for line in manager.logs()["lines"])
    (installation / "exit.flag").unlink()
    manager.start()
    wait_status(manager, "running")


def test_settings_reject_invalid_port_and_active_change(manager, installation):
    with pytest.raises(DomainError):
        manager.configure(str(installation), 80)
    manager.start()
    wait_status(manager, "running")
    with pytest.raises(DomainError) as failed:
        manager.configure(str(installation), free_port())
    assert failed.value.detail["code"] == "comfy_running"


def test_log_tail_strips_ansi_without_changing_disk(manager):
    path = manager.directory / "logs" / "test.log"
    path.parent.mkdir(parents=True)
    original = "first\n\x1b[32m[INFO]\x1b[0m 中文日志\nlast\n"
    path.write_text(original, encoding="utf-8")
    manager.record["log_path"] = str(path)
    result = manager.logs(limit=2)
    assert result["lines"] == ["[INFO] 中文日志", "last"]
    assert result["truncated"]
    assert path.read_text(encoding="utf-8") == original


@pytest.mark.parametrize("redirect", ["parent", "runtime"])
def test_configuration_resolves_redirected_directories(tmp_path, redirect):
    physical = tmp_path / "物理配置目录"
    physical.mkdir()
    logical = tmp_path / "逻辑配置目录"
    if redirect == "parent":
        link, target = logical, physical
        expected = physical / "config.comfy"
    else:
        logical.mkdir()
        link, target = logical / "config.comfy", physical
        expected = physical
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError as error:
        if os.name != "nt":
            pytest.skip(f"Directory symbolic links are unavailable: {error}")
        quoted_link = "'" + str(link).replace("'", "''") + "'"
        quoted_target = "'" + str(target).replace("'", "''") + "'"
        command = f"New-Item -ItemType Junction -Path {quoted_link} -Target {quoted_target} -ErrorAction Stop | Out-Null"
        encoded = base64.b64encode(command.encode("utf-16le")).decode("ascii")
        result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded], capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
        if result.returncode:
            pytest.skip("Directory symbolic links and junctions are unavailable")
    bootstrap = logical / "config.json"
    assert not bootstrap.exists()
    controller = ComfyManager(bootstrap)
    try:
        assert controller.directory == expected.resolve()
        assert controller.settings_path.parent == expected.resolve()
        comfy._write_json(controller.settings_path, {"port": 8199})
        assert json.loads((expected / "settings.json").read_text(encoding="utf-8")) == {"port": 8199}
        assert not (expected / "settings.json.tmp").exists()
        assert not bootstrap.exists()
    finally:
        controller.close()


def test_failed_settings_write_preserves_in_memory_configuration(manager, installation, monkeypatch):
    original = dict(manager.settings)
    write = comfy._write_json
    def fail_settings(path, value):
        if path == manager.settings_path:
            raise OSError("simulated atomic replace failure")
        write(path, value)
    monkeypatch.setattr(comfy, "_write_json", fail_settings)
    with pytest.raises(OSError, match="atomic replace"):
        manager.configure(str(installation), free_port())
    assert manager.settings == original
    assert json.loads(manager.settings_path.read_text(encoding="utf-8")) == original
