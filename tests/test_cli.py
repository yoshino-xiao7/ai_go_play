from __future__ import annotations

import json
import os
from pathlib import Path
import socket
import shutil
import subprocess
import sys
import sysconfig
import time
import venv

import httpx
import psutil
import pytest


@pytest.fixture
def live_service(tmp_path):
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    url = f"http://127.0.0.1:{port}"
    environment = dict(os.environ, PYTHONUTF8="1")
    log_path = tmp_path / "server.log"
    with log_path.open("wb") as log:
        process = subprocess.Popen([sys.executable, "-m", "manju", "serve", "--port", str(port), "--data-dir", str(tmp_path / "数据"), "--config-file", str(tmp_path / "配置.json")], stdout=log, stderr=log, env=environment)
        try:
            deadline = time.monotonic() + 15
            with httpx.Client(timeout=0.5, trust_env=False) as client:
                while time.monotonic() < deadline:
                    try:
                        if client.get(url + "/api/health").status_code == 200:
                            break
                    except httpx.HTTPError:
                        pass
                    if process.poll() is not None:
                        pytest.fail(log_path.read_text(encoding="utf-8", errors="replace"))
                    time.sleep(0.1)
                else:
                    pytest.fail("CLI server did not start in 15 seconds")
            yield url
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


def cli(url, *arguments, success=True):
    result = subprocess.run([sys.executable, "-m", "manju", "--url", url, *map(str, arguments), "--json"], capture_output=True, text=True, encoding="utf-8", timeout=30)
    if success:
        assert result.returncode == 0, result.stderr
        assert not result.stderr, result.stderr
        return json.loads(result.stdout)
    assert result.returncode != 0
    assert not result.stdout
    return json.loads(result.stderr)


def test_cli_asset_canvas_archive_and_errors(live_service, tmp_path, png_bytes):
    url = live_service
    image = tmp_path / "角色 图.png"
    image.write_bytes(png_bytes())
    item = cli(url, "project", "create", "末班车", "--aspect", "9:16")
    assert item["name"] == "末班车"
    asset = cli(url, "asset", "import", image, "--project", item["id"], "--request-id", "cli-upload")
    assert cli(url, "asset", "import", image, "--project", item["id"], "--request-id", "cli-upload")["id"] == asset["id"]
    canvas = cli(url, "canvas", "add-asset", item["id"], asset["id"], "--request-id", "cli-card")
    assert canvas["revision"] == 1
    assert cli(url, "canvas", "add-asset", item["id"], asset["id"], "--request-id", "cli-card")["revision"] == 1
    assert len(cli(url, "canvas", "inspect", item["id"])["nodes"]) == 1
    assert cli(url, "asset", "tag", asset["id"], "角色", "主角")["tags"] == ["角色", "主角"]
    image.write_bytes(png_bytes("blue"))
    revised = cli(url, "asset", "version", asset["id"], image, "--request-id", "cli-version")
    assert revised["version_count"] == 2
    assert cli(url, "canvas", "inspect", item["id"])["nodes"][0]["data"]["asset_version_id"] == asset["current_version_id"]
    snapshot = tmp_path / "canvas.json"
    snapshot.write_text(json.dumps(canvas), encoding="utf-8")
    applied = cli(url, "canvas", "apply", item["id"], snapshot, "--request-id", "cli-apply")
    assert applied["revision"] == 2
    assert cli(url, "canvas", "apply", item["id"], snapshot, "--request-id", "cli-apply")["revision"] == 2
    error = cli(url, "canvas", "apply", item["id"], snapshot, "--request-id", "stale", success=False)
    assert error["error"]["code"] == "revision_conflict"
    package = tmp_path / "第一集.manju"
    assert cli(url, "project", "export", item["id"], package)["size"] > 0
    imported = cli(url, "project", "import", package)
    assert imported["id"] != item["id"]
    assert cli(url, "project", "export", item["id"], package, success=False)["error"]["code"] == "file_exists"
    assert cli(url, "doctor")["health"]["ok"] is True
    assert cli(url, "asset", "show", "missing", success=False)["error"]["code"] == "asset_not_found"
    assert cli(url, "asset", "import", tmp_path / "missing.png", success=False)["error"]["code"] == "local_file_error"


def test_cli_rejects_remote_url_and_invalid_arguments():
    result = subprocess.run([sys.executable, "-m", "manju", "--json", "doctor", "--url", "https://example.com"], capture_output=True, text=True, encoding="utf-8", timeout=10)
    assert result.returncode == 1
    assert json.loads(result.stderr)["error"]["code"] == "invalid_url"
    result = subprocess.run([sys.executable, "-m", "manju", "asset", "import", "--json"], capture_output=True, text=True, encoding="utf-8", timeout=10)
    assert result.returncode == 1
    assert json.loads(result.stderr)["error"]["code"] == "invalid_arguments"


def test_cli_planned_named_arguments(live_service, tmp_path, png_bytes):
    url = live_service
    image = tmp_path / "素材.png"
    image.write_bytes(png_bytes())
    project = cli(url, "project", "create", "--name", "命名参数项目")
    asset = cli(url, "asset", "import", "--file", image)
    version_id = asset["imported_version_id"]
    canvas = cli(url, "canvas", "add-asset", "--project", project["id"], "--asset-version", version_id, "--x", "80", "--y", "160")
    assert canvas["nodes"][0]["data"]["asset_version_id"] == version_id
    assert canvas["nodes"][0]["position"] == {"x": 80, "y": 160}
    assert cli(url, "canvas", "inspect", "--project", project["id"])["revision"] == 1
    destination = tmp_path / "命名参数.manju"
    assert cli(url, "project", "export", "--project", project["id"], "--output", destination)["size"] > 0
    assert destination.is_file()


@pytest.mark.skipif(os.name != "nt", reason="Windows double-click launcher")
@pytest.mark.parametrize("entrypoint", ["powershell", "wscript"])
def test_start_script_reuses_running_service(tmp_path, entrypoint):
    workspace = Path(__file__).resolve().parents[1]
    if not (workspace / "frontend" / "dist" / "index.html").is_file():
        pytest.skip("Build frontend before testing the Windows launcher")
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    runtime = Path(os.environ["LOCALAPPDATA"]) / "Manju" / "run"
    record = runtime / f"server-{port}.json"
    if entrypoint == "wscript":
        command = ["wscript.exe", "//nologo", str(workspace / "start.vbs")]
    else:
        command = ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(workspace / "start.ps1")]
    command += ["-Port", str(port), "-DataDir", str(tmp_path / "启动 素材"), "-ConfigFile", str(tmp_path / "启动 配置.json"), "-NoBrowser"]
    initial_windows = visible_terminal_windows()
    pid = None
    try:
        first = subprocess.run(command, capture_output=True, stdin=subprocess.DEVNULL, timeout=300)
        assert first.returncode == 0, (first.stdout + first.stderr).decode(errors="replace")
        pid = json.loads(record.read_text(encoding="utf-8-sig"))["pid"]
        second = subprocess.run(command, capture_output=True, stdin=subprocess.DEVNULL, timeout=15)
        assert second.returncode == 0, (second.stdout + second.stderr).decode(errors="replace")
        assert json.loads(record.read_text(encoding="utf-8-sig"))["pid"] == pid
        with httpx.Client(trust_env=False, timeout=2) as client:
            health = client.get(f"http://127.0.0.1:{port}/api/health").json()
            assert Path(health["root"]) == tmp_path / "启动 素材"
        assert "Application startup complete" in (runtime / f"server-{port}.err.log").read_text(encoding="utf-8")
        service = psutil.Process(pid)
        assert service.name().casefold() == "pythonw.exe"
        for _ in range(3):
            console_children = []
            for child in service.children(recursive=True):
                try:
                    if child.name().casefold() in {"conhost.exe", "openconsole.exe", "windowsterminal.exe"}:
                        console_children.append((child.pid, child.name()))
                except psutil.NoSuchProcess:
                    pass
            assert not console_children, console_children
            new_windows = {handle: details for handle, details in visible_terminal_windows().items() if handle not in initial_windows}
            assert not new_windows, new_windows
            time.sleep(0.2)
    finally:
        if pid is None and record.exists():
            pid = json.loads(record.read_text(encoding="utf-8-sig"))["pid"]
        if pid is not None:
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, timeout=10)
            for path in (record, runtime / f"server-{port}.out.log", runtime / f"server-{port}.err.log"):
                for attempt in range(20):
                    try:
                        path.unlink(missing_ok=True)
                        break
                    except PermissionError:
                        time.sleep(0.1)


def visible_terminal_windows():
    """Capture both modern Windows Terminal and classic console windows."""
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
    user32.EnumWindows.restype = wintypes.BOOL
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsWindowVisible.restype = wintypes.BOOL
    user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    windows = {}

    @callback_type
    def visit(handle, parameter):
        if user32.IsWindowVisible(handle):
            class_name = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(handle, class_name, len(class_name))
            if class_name.value in {"CASCADIA_HOSTING_WINDOW_CLASS", "ConsoleWindowClass"}:
                title = ctypes.create_unicode_buffer(2048)
                user32.GetWindowTextW(handle, title, len(title))
                windows[handle] = {"class": class_name.value, "title": title.value}
        return True

    assert user32.EnumWindows(visit, 0)
    return windows


@pytest.mark.skipif(os.name != "nt", reason="Windows launcher errors")
@pytest.mark.parametrize("missing", ["environment", "dependency"])
def test_startup_failure_records_setup_instructions(tmp_path, missing, isolated_launcher):
    workspace = Path(__file__).resolve().parents[1]
    environment = dict(os.environ)
    if missing == "environment":
        script = tmp_path / "start.ps1"
        script.write_bytes((workspace / "start.ps1").read_bytes())
    else:
        script = isolated_launcher / "start.ps1"
        shadow = isolated_launcher / '.venv/Lib/site-packages'
        (shadow / "psutil.py").write_text("raise ImportError('missing test dependency')", encoding="utf-8")
    error_log = tmp_path / "启动失败.log"
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    result = subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script), "-Port", str(port), "-NoBrowser", "-ErrorLogPath", str(error_log)], capture_output=True, timeout=10, env=environment)
    assert result.returncode == 1
    message = error_log.read_text(encoding="utf-16")
    assert "missing" in message
    assert ("complete ai-go-play project" if missing == "environment" else "pip install -c requirements.lock") in message


def test_comfy_cli_routes_and_json(monkeypatch, capsys, tmp_path):
    from manju import cli as cli_module

    seen = []
    def respond(request):
        seen.append((request.method, request.url.path, dict(request.url.params), json.loads(request.content) if request.content else None))
        return httpx.Response(200, json={"status": "stopped"})

    original_client = httpx.Client
    monkeypatch.setattr(cli_module.httpx, "Client", lambda **kwargs: original_client(transport=httpx.MockTransport(respond), **kwargs))
    installation = tmp_path / "中文 ComfyUI"
    cases = [
        (["status"], ("GET", "/api/comfy", {}, None)),
        (["scan", "--path", str(installation)], ("POST", "/api/comfy/scan", {}, {"path": str(installation)})),
        (["configure", "--installation-path", str(installation), "--port", "8199"], ("PUT", "/api/comfy/settings", {}, {"installation_path": str(installation), "port": 8199})),
        (["start"], ("POST", "/api/comfy/start", {}, {})),
        (["stop"], ("POST", "/api/comfy/stop", {}, {"force": False})),
        (["stop", "--force"], ("POST", "/api/comfy/stop", {}, {"force": True})),
        (["logs", "--limit", "50"], ("GET", "/api/comfy/logs", {"limit": "50"}, None)),
    ]
    for arguments, expected in cases:
        assert cli_module.main(["comfy", *arguments, "--json"]) == 0
        captured = capsys.readouterr()
        assert json.loads(captured.out) == {"status": "stopped"}
        assert captured.err == ""
        assert seen[-1] == expected


def test_comfy_cli_preserves_busy_error(monkeypatch, capsys):
    from manju import cli as cli_module

    original_client = httpx.Client
    transport = httpx.MockTransport(lambda request: httpx.Response(409, json={"detail": {"code": "comfy_queue_busy", "message": "ComfyUI 正在执行任务。"}}))
    monkeypatch.setattr(cli_module.httpx, "Client", lambda **kwargs: original_client(transport=transport, **kwargs))
    assert cli_module.main(["comfy", "stop", "--json"]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert json.loads(captured.err)["error"]["code"] == "comfy_queue_busy"


def test_comfy_cli_reads_local_service(live_service, tmp_path):
    status = cli(live_service, "comfy", "status")
    assert status["status"] in {"not_configured", "external"}
    assert status["managed"] is False
    empty_directory = tmp_path / "空扫描目录"
    empty_directory.mkdir()
    scan = cli(live_service, "comfy", "scan", "--path", empty_directory)
    assert scan["installations"] == []
    assert isinstance(scan["scanned_roots"], list)
    logs = cli(live_service, "comfy", "logs", "--limit", "20")
    assert logs["lines"] == []
    assert logs["path"] is None


def test_workflow_generation_cli_routes(monkeypatch, capsys, tmp_path):
    from manju import cli as cli_module

    seen = []
    def respond(request):
        seen.append((request.method, request.url.path, dict(request.url.params), json.loads(request.content) if request.content else None))
        return httpx.Response(200, json={"id": "job-1", "status": "succeeded", "outputs": []})

    original_client = httpx.Client
    monkeypatch.setattr(cli_module.httpx, "Client", lambda **kwargs: original_client(transport=httpx.MockTransport(respond), **kwargs))
    graph_file = tmp_path / "工作流.json"
    graph = {"11": {"class_type": "SaveImage", "inputs": {}}}
    graph_file.write_text(json.dumps(graph), encoding="utf-8")
    spec_file = tmp_path / "工作流配置.json"
    spec = {"name": "角色参考", "revision": 2, "api_graph": graph}
    spec_file.write_text(json.dumps(spec), encoding="utf-8")
    cases = [
        (["workflow", "list", "--mode", "reference"], ("GET", "/api/workflows", {"mode": "reference", "include_video":"true", "include_audio":"true"}, None)),
        (["workflow", "list", "--mode", "audio"], ("GET", "/api/workflows", {"mode": "audio", "include_video":"true", "include_audio":"true"}, None)),
        (["generate", "--kind", "audio", "--project", "p", "--subject-node", "speaker", "--source-node", "output", "--prompt", "出发吧。", "--speed", "1.25", "--emotion", "happy"], ("POST", "/api/generations", {}, {"kind":"audio", "project_id":"p", "workflow_id":"builtin-indextts25-local", "subject_node_id":"speaker", "source_node_id":"output", "prompt":"出发吧。", "references":[], "parameters":{}, "speech_options":{"speed":1.25,"emotion":"happy"}})),
        (["workflow", "get", "wf"], ("GET", "/api/workflows/wf", {}, None)),
        (["workflow", "import", "--file", str(graph_file), "--name", "新工作流", "--mode", "edit"], ("POST", "/api/workflows/import", {}, {"name": "新工作流", "mode": "edit", "api_graph": graph})),
        (["workflow", "create", "--file", str(spec_file)], ("POST", "/api/workflows", {}, spec)),
        (["workflow", "update", "wf", "--file", str(spec_file)], ("PUT", "/api/workflows/wf", {}, spec)),
        (["workflow", "duplicate", "wf"], ("POST", "/api/workflows/wf/duplicate", {}, None)),
        (["workflow", "validate", "wf"], ("POST", "/api/workflows/wf/validate", {}, None)),
        (["workflow", "delete", "wf"], ("DELETE", "/api/workflows/wf", {}, None)),
        (["generate", "--project", "project", "--workflow", "wf", "--prompt", "保持角色", "--negative-prompt", "糊", "--reference", "v1", "--reference", "v2", "--mask", "m1", "--source-node", "card", "--seed", "-1", "--width", "512", "--x", "10", "--y", "20", "--request-id", "once"], ("POST", "/api/generations", {}, {"project_id": "project", "workflow_id": "wf", "prompt": "保持角色", "negative_prompt": "糊", "references": [{"version_id": "v1"}, {"version_id": "v2"}], "parameters": {"seed": -1, "width": 512}, "mask_version_id": "m1", "source_node_id": "card", "placement": {"x": 10.0, "y": 20.0}, "request_id": "once"})),
        (["generate", "--project", "project", "--workflow", "wf", "--prompt", "沿用默认"], ("POST", "/api/generations", {}, {"project_id": "project", "workflow_id": "wf", "prompt": "沿用默认", "references": [], "parameters": {}})),
        (["generate", "--project", "project", "--workflow", "wf", "--prompt", "清空负面", "--negative-prompt", ""], ("POST", "/api/generations", {}, {"project_id": "project", "workflow_id": "wf", "prompt": "清空负面", "negative_prompt": "", "references": [], "parameters": {}})),
        (["job", "list", "--project", "project", "--limit", "10"], ("GET", "/api/generations", {"project_id": "project", "limit": "10"}, None)),
        (["job", "show", "job-1"], ("GET", "/api/generations/job-1", {}, None)),
        (["job", "cancel", "job-1"], ("POST", "/api/generations/job-1/cancel", {}, {"interrupt_running": False})),
        (["job", "cancel", "job-1", "--interrupt-running"], ("POST", "/api/generations/job-1/cancel", {}, {"interrupt_running": True})),
        (["job", "retry", "job-1", "--request-id", "again"], ("POST", "/api/generations/job-1/retry", {}, {"request_id": "again"})),
        (["job", "wait", "job-1", "--interval", "0.01"], ("GET", "/api/generations/job-1", {}, None)),
    ]
    for arguments, expected in cases:
        assert cli_module.main([*arguments, "--json"]) == 0
        captured = capsys.readouterr()
        assert json.loads(captured.out)["status"] == "succeeded"
        assert captured.err == ""
        assert seen[-1] == expected
    request_file = tmp_path / "生成请求.json"
    payload = {"project_id": "project", "workflow_id": "wf", "prompt": "中文引用", "references": [{"version_id": "v1", "node_id": "card"}]}
    request_file.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    assert cli_module.main(["generate", "--file", str(request_file), "--json"]) == 0
    capsys.readouterr()
    assert seen[-1][-1] == payload
    assert cli_module.main(["generate", "--file", str(request_file), "--seed", "42", "--json"]) == 1
    assert json.loads(capsys.readouterr().err)["error"]["code"] == "invalid_arguments"


def test_job_wait_failure_is_nonzero_json(monkeypatch, capsys):
    from manju import cli as cli_module

    original_client = httpx.Client
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"id": "job", "status": "failed", "message": "模型不可用"}))
    monkeypatch.setattr(cli_module.httpx, "Client", lambda **kwargs: original_client(transport=transport, **kwargs))
    assert cli_module.main(["job", "wait", "job", "--json"]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert json.loads(captured.err)["error"]["code"] == "generation_failed"


def test_workflow_and_job_cli_subprocess(live_service):
    items = cli(live_service, "workflow", "list")["items"]
    assert {item["id"] for item in items if item.get("provider") != "openai"} == {
        "builtin-qwen21-text_to_image", "builtin-qwen21-reference", "builtin-qwen21-edit",
        "builtin-minimax-h3-image-text_to_image", "builtin-minimax-h3-image-reference", "builtin-minimax-h3-image-edit",
        "builtin-h3-local", "builtin-indextts25-local", "builtin-video-interpolate-local",
        "builtin-video-upscale-local", "builtin-video-watermark-local",
    }
    assert len([item for item in items if item.get("provider") == "openai"]) == 3
    original = cli(live_service, "workflow", "get", items[0]["id"])
    duplicate = cli(live_service, "workflow", "duplicate", original["id"])
    assert duplicate["api_graph"] == original["api_graph"]
    assert duplicate["read_only"] is False
    cli(live_service, "workflow", "delete", duplicate["id"])
    assert cli(live_service, "job", "list")["items"] == []
    error = cli(live_service, "generate", "--project", "missing", "--workflow", original["id"], "--prompt", "不会提交到GPU", success=False)
    assert error["error"]["code"] == "project_not_found"


def test_subject_cli_routes_and_explicit_empty_description(monkeypatch, capsys):
    from manju import cli as cli_module

    seen = []
    def respond(request):
        seen.append((request.method, request.url.path, dict(request.url.params), json.loads(request.content) if request.content else None, request.headers.get("X-Request-ID")))
        return httpx.Response(200, json={"id": "subject-1"})
    original_client = httpx.Client
    monkeypatch.setattr(cli_module.httpx, "Client", lambda **kwargs: original_client(transport=httpx.MockTransport(respond), **kwargs))
    cases = [
        (["list", "--search", "女主", "--offset", "5", "--limit", "10"], ("GET", "/api/subjects", {"search": "女主", "offset": "5", "limit": "10"}, None, None)),
        (["list", "--kind", "prop"], ("GET", "/api/subjects", {"search": "", "offset": "0", "limit": "60", "kind": "prop"}, None, None)),
        (["show", "subject-1"], ("GET", "/api/subjects/subject-1", {}, None, None)),
        (["create", "--name", "女主正面", "--asset-version", "v1", "--description", "蓝色衣服", "--request-id", "one-subject"], ("POST", "/api/subjects", {}, {"name": "女主正面", "version_id": "v1", "description": "蓝色衣服"}, "one-subject")),
        (["update", "subject-1", "--name", "角色"], ("PATCH", "/api/subjects/subject-1", {}, {"name": "角色"}, None)),
        (["update", "subject-1", "--description", ""], ("PATCH", "/api/subjects/subject-1", {}, {"description": ""}, None)),
        (["create", "--name", "人物", "--kind", "character", "--image", "v1", "--image", "v2", "--voice-version", "audio-v1", "--voice-name", "少女", "--voice-transcript", "你好", "--request-id", "multi"], ("POST", "/api/subjects", {}, {"name": "人物", "description": "", "kind": "character", "image_version_ids": ["v1", "v2"], "voice_version_id": "audio-v1", "voice_name": "少女", "voice_transcript": "你好"}, "multi")),
        (["update", "subject-1", "--kind", "scene", "--image", "v2", "--clear-voice"], ("PATCH", "/api/subjects/subject-1", {}, {"kind": "scene", "image_version_ids": ["v2"], "voice_version_id": None, "voice_name": "", "voice_transcript": ""}, None)),
        (["delete", "subject-1"], ("DELETE", "/api/subjects/subject-1", {}, None, None)),
    ]
    for arguments, expected in cases:
        assert cli_module.main(["subject", *arguments, "--json"]) == 0
        captured = capsys.readouterr()
        assert json.loads(captured.out) == {"id": "subject-1"}
        assert captured.err == ""
        assert seen[-1] == expected
    for invalid in (["create", "--name", "缺版本"], ["update", "subject-1"], ["create", "--name", "冲突", "--version", "v1", "--image", "v2"], ["update", "subject-1", "--clear-voice", "--voice-name", "不能同时设置"]):
        assert cli_module.main(["subject", *invalid, "--json"]) == 1
        captured = capsys.readouterr()
        assert captured.out == ""
        assert json.loads(captured.err)["error"]["code"] == "invalid_arguments"


def test_subject_cli_subprocess_lifecycle(live_service, tmp_path, png_bytes):
    image = tmp_path / "角色.png"
    image.write_bytes(png_bytes())
    asset = cli(live_service, "asset", "import", image)
    subject = cli(live_service, "subject", "create", "--name", "主角", "--version", asset["current_version_id"], "--request-id", "cli-subject")
    replay = cli(live_service, "subject", "create", "--name", "主角", "--version", asset["current_version_id"], "--request-id", "cli-subject")
    assert replay["id"] == subject["id"]
    assert cli(live_service, "subject", "list", "--search", "主角")["total"] == 1
    assert cli(live_service, "subject", "show", subject["id"])["version_id"] == asset["current_version_id"]
    assert cli(live_service, "subject", "update", subject["id"], "--description", "可复用正面图")["description"] == "可复用正面图"
    assert cli(live_service, "asset", "trash", asset["id"], success=False)["error"]["code"] == "subject_referenced"
    assert cli(live_service, "subject", "delete", subject["id"])["deleted"] is True
    assert cli(live_service, "asset", "show", asset["id"])["subject_references"] == []


def test_subject_cli_multi_image_voice_and_blank_canvas_snapshot(live_service, tmp_path, png_bytes):
    from test_subject_snapshots import audio_bytes, snapshot, subject_node

    images = []
    for color in ("red", "blue"):
        path = tmp_path / f"{color}.png"
        path.write_bytes(png_bytes(color))
        images.append(cli(live_service, "asset", "import", path))
    sound = tmp_path / "音色.wav"
    sound.write_bytes(audio_bytes())
    voice = cli(live_service, "asset", "import", sound)
    subject = cli(live_service, "subject", "create", "--name", "女主", "--kind", "character", "--image", images[0]["current_version_id"], "--image", images[1]["current_version_id"], "--voice-version", voice["current_version_id"], "--voice-name", "清亮", "--voice-transcript", "你好")
    assert subject["image_version_ids"] == [image["current_version_id"] for image in images]
    assert subject["voice"]["id"] == voice["current_version_id"]
    changed = cli(live_service, "subject", "update", subject["id"], "--image", images[1]["current_version_id"], "--kind", "prop", "--clear-voice")
    assert changed["version_id"] == images[1]["current_version_id"]
    assert changed["voice"] is None and changed["voice_name"] == changed["voice_transcript"] == ""
    assert cli(live_service, "subject", "list", "--kind", "prop")["total"] == 1
    item = cli(live_service, "project", "create", "空白主体")
    canvas = {"revision": 0, "nodes": [subject_node(snapshot())], "edges": [], "viewport": {"x": 0, "y": 0, "zoom": 1}}
    document = tmp_path / "画布.json"
    document.write_text(json.dumps(canvas, ensure_ascii=False), encoding="utf-8")
    saved = cli(live_service, "canvas", "apply", item["id"], document)
    assert saved["nodes"][0]["type"] == "subject"
    assert saved["nodes"][0]["data"]["subject"]["image_version_ids"] == []


@pytest.fixture
def isolated_launcher(tmp_path):
    workspace = Path(__file__).resolve().parents[1]
    isolated = tmp_path / "独立工作台 空格"
    isolated.mkdir()
    shutil.copyfile(workspace / "start.ps1", isolated / "start.ps1")
    # These tests isolate launcher/configuration behavior. The real bootstrap is
    # exercised separately with a source-only checkout and pinned downloads.
    scripts = isolated / 'scripts'
    scripts.mkdir()
    (scripts / 'bootstrap.ps1').write_text(
        "param([string]$Workspace, [switch]$NoBrowser)\n"
        "$state = Join-Path $Workspace '.manju'\n"
        "New-Item -ItemType Directory -Force -Path (Join-Path $state 'bootstrap') | Out-Null\n"
        "$paths = @{ ffmpeg = (Get-Command ffmpeg -CommandType Application).Source; "
        "ffprobe = (Get-Command ffprobe -CommandType Application).Source } | ConvertTo-Json\n"
        "[IO.File]::WriteAllText((Join-Path $state 'local-ai-paths.json'), $paths)\n",
        encoding='utf-8',
    )
    environment = isolated / ".venv"
    venv.EnvBuilder(with_pip=False).create(environment)
    packages = environment / "Lib" / "site-packages"
    packages.mkdir(parents=True, exist_ok=True)
    # Reuse installed dependencies while keeping launcher state fully isolated.
    (packages / "test-dependencies.pth").write_text(f"import site; site.addsitedir({sysconfig.get_path('purelib')!r})\n", encoding="utf-8")
    frontend = isolated / "frontend" / "dist"
    frontend.mkdir(parents=True)
    (frontend / "index.html").write_text("<!doctype html><title>Launcher fixture</title>", encoding="utf-8")
    return isolated


@pytest.mark.skipif(os.name != "nt", reason="Windows configuration bootstrap")
def test_default_launcher_keeps_configuration_across_appdata(isolated_launcher, tmp_path):
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    environment = dict(os.environ)
    environment.pop("MANJU_DATA_DIR", None)
    environment.pop("MANJU_CONFIG_FILE", None)
    environment["LOCALAPPDATA"] = str(tmp_path / "local")
    command = ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(isolated_launcher / "start.ps1"), "-Port", str(port), "-NoBrowser"]
    anchor = isolated_launcher / ".manju" / "launcher.json"
    record = Path(environment["LOCALAPPDATA"]) / "Manju" / "run" / f"server-{port}.json"
    original_root = tmp_path / "第一资料库"
    original_config = tmp_path / "桌面APPDATA" / "Manju" / "config.json"
    original_config.parent.mkdir(parents=True)
    original_config.write_text(json.dumps({"root": str(original_root)}), encoding="utf-8")
    alternate_config = tmp_path / "资源管理器APPDATA" / "Manju" / "config.json"
    alternate_config.parent.mkdir(parents=True)
    alternate_config.write_text(json.dumps({"root": str(tmp_path / "其他资料库")}), encoding="utf-8")
    pid = None
    try:
        for config in (original_config, alternate_config):
            environment["APPDATA"] = str(config.parent.parent)
            started = subprocess.run(command, capture_output=True, stdin=subprocess.DEVNULL, timeout=15, env=environment)
            assert started.returncode == 0, (started.stdout + started.stderr).decode(errors="replace")
            pid = json.loads(record.read_text(encoding="utf-8-sig"))["pid"]
            assert Path(json.loads(anchor.read_text(encoding="utf-8"))["config_file"]) == original_config.resolve()
            with httpx.Client(base_url=f"http://127.0.0.1:{port}", trust_env=False, timeout=2) as client:
                assert Path(client.get("/api/health").json()["root"]) == original_root
                if config == original_config:
                    assert client.post("/api/projects", json={"name": "跨上下文项目"}).status_code == 201
                else:
                    assert client.get("/api/projects").json()[0]["name"] == "跨上下文项目"
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, timeout=10, check=True)
            pid = None
        assert not (tmp_path / "其他资料库").exists()
    finally:
        if pid is not None:
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, timeout=10)


@pytest.mark.skipif(os.name != "nt", reason="Windows configuration bootstrap")
@pytest.mark.parametrize("override", ["-DataDir", "-ConfigFile", "MANJU_DATA_DIR", "MANJU_CONFIG_FILE"])
def test_explicit_configuration_bypasses_default_anchor(isolated_launcher, tmp_path, override):
    anchor = isolated_launcher / ".manju" / "launcher.json"
    anchor.parent.mkdir()
    anchor.write_text('{"config_file": "invalid-default-anchor"}', encoding="utf-8")
    anchor_before = anchor.read_bytes()
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    environment = dict(os.environ)
    environment.pop("MANJU_DATA_DIR", None)
    environment.pop("MANJU_CONFIG_FILE", None)
    environment["LOCALAPPDATA"] = str(tmp_path / "local")
    root = tmp_path / "指定资料库"
    config = tmp_path / "指定配置.json"
    config.write_text(json.dumps({"root": str(root)}), encoding="utf-8")
    value = str(config if "CONFIG" in override.upper() else root)
    command = ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(isolated_launcher / "start.ps1"), "-Port", str(port), "-NoBrowser"]
    if override.startswith("-"):
        command += [override, value]
    else:
        environment[override] = value
    record = Path(environment["LOCALAPPDATA"]) / "Manju" / "run" / f"server-{port}.json"
    pid = None
    try:
        started = subprocess.run(command, capture_output=True, stdin=subprocess.DEVNULL, timeout=15, env=environment)
        assert started.returncode == 0, (started.stdout + started.stderr).decode(errors="replace")
        pid = json.loads(record.read_text(encoding="utf-8-sig"))["pid"]
        with httpx.Client(trust_env=False, timeout=2) as client:
            assert Path(client.get(f"http://127.0.0.1:{port}/api/health").json()["root"]) == root
        assert anchor.read_bytes() == anchor_before
    finally:
        if pid is not None:
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, timeout=10)
