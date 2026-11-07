import json
from time import monotonic
from types import SimpleNamespace
import httpx
import pytest
from manju.cli import CliError, build_parser, production_command, run_command


def test_production_cli_keeps_revision_and_batch_intent(tmp_path):
    captured=[]
    def handler(request):
        captured.append((request.method,request.url.path,json.loads(request.content)))
        return httpx.Response(200,json={'ok':True})
    doc=tmp_path/'shots.json'
    doc.write_text(json.dumps({'revision':7,'settings':{},'shots':[]}),encoding='utf-8')
    with httpx.Client(base_url='http://127.0.0.1',transport=httpx.MockTransport(handler)) as client:
        args=build_parser().parse_args(['production','apply','--project','p','--file',str(doc),'--request-id','save-1'])
        production_command(client,args)
        args=build_parser().parse_args(['production','generate','--project','p','--shot','s1','--kind','video','--redo','--request-id','batch-1'])
        production_command(client,args)
        args=build_parser().parse_args(['production','render','--project','p','--revision','8','--name','成片','--request-id','render-1'])
        production_command(client,args)
    assert captured[0][2]['revision']==7
    assert captured[1][2]=={'request_id':'batch-1','only_missing':False,'kinds':['video'],'shot_ids':['s1']}
    assert captured[2][2]=={'request_id':'render-1','burn_subtitles':True,'name':'成片','revision':8}


@pytest.mark.parametrize(("command", "method", "path", "body"), [
    (["timeline", "inspect", "--project", "p"], "GET", "/api/projects/p/timeline", None),
    (["timeline", "import-production", "--project", "p", "--revision", "12", "--request-id", "import-one"], "POST", "/api/projects/p/timeline/import-production", {"revision": 12, "request_id": "import-one"}),
    (["timeline", "render", "--project", "p", "--revision", "13", "--name", "多轨成片", "--request-id", "timeline-render"], "POST", "/api/projects/p/timeline/render", {"revision": 13, "request_id": "timeline-render", "name": "多轨成片"}),
    (["timeline", "show", "render-id"], "GET", "/api/production/renders/render-id", None),
    (["timeline", "retry", "render-id"], "POST", "/api/production/renders/render-id/retry", None),
    (["canvas-run", "plan", "--project", "p", "--scope", "downstream", "--node", "voice", "--node", "video", "--force", "--revision", "19"], "POST", "/api/projects/p/canvas-runs/plan", {"scope": "downstream", "force": True, "revision": 19, "node_ids": ["voice", "video"]}),
    (["canvas-run", "start", "--project", "p", "--revision", "20", "--request-id", "run-once"], "POST", "/api/projects/p/canvas-runs", {"scope": "all", "force": False, "revision": 20, "request_id": "run-once"}),
    (["canvas-run", "list", "--project", "p"], "GET", "/api/projects/p/canvas-runs", None),
    (["canvas-run", "show", "run-id"], "GET", "/api/canvas-runs/run-id", None),
    (["canvas-run", "retry", "run-id"], "POST", "/api/canvas-runs/run-id/retry", None),
    (["canvas-run", "cancel", "run-id"], "POST", "/api/canvas-runs/run-id/cancel", None),
    (["lipsync", "settings"], "GET", "/api/lipsync/settings", None),
])
def test_new_commands_route_to_correct_service_with_exact_intent(command, method, path, body):
    captured = []
    def handler(request):
        captured.append((request.method, request.url.path, json.loads(request.content) if request.content else None))
        return httpx.Response(200, json={"accepted": True})
    with httpx.Client(base_url="http://127.0.0.1", transport=httpx.MockTransport(handler)) as client:
        assert run_command(client, build_parser().parse_args(command)) == {"accepted": True}
    assert captured == [(method, path, body)]


def test_timeline_apply_preserves_full_document_and_overrides_only_request_id(tmp_path):
    body = {"revision": 27, "request_id": "from-file", "settings": {"width": 1280, "height": 720, "fps": 24},
            "tracks": [{"id": "dialogue", "type": "audio", "order": 1, "locked": False, "muted": False}],
            "clips": [{"id": "mother", "track_id": "dialogue", "asset_version_id": "immutable-version", "start": 4.5, "duration": 3, "trim_start": .2, "audio_preset": "phone", "volume": 1.2, "fade_out": .15}]}
    file = tmp_path / "时间线.json"
    file.write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8-sig")
    captured = []
    def handler(request):
        captured.append((request.method, request.url.path, json.loads(request.content)))
        return httpx.Response(200, json={"revision": 28})
    with httpx.Client(base_url="http://127.0.0.1", transport=httpx.MockTransport(handler)) as client:
        args = build_parser().parse_args(["timeline", "apply", "--project", "p", "--file", str(file), "--request-id", "explicit"])
        assert run_command(client, args)["revision"] == 28
    assert captured == [("PUT", "/api/projects/p/timeline", {**body, "request_id": "explicit"})]
    assert json.loads(file.read_text(encoding="utf-8-sig")) == body


@pytest.mark.parametrize("revision", [None, True, "3", 3.5])
def test_timeline_apply_requires_integer_revision_before_network(tmp_path, revision):
    file = tmp_path / "invalid.json"
    file.write_text(json.dumps({"revision": revision, "tracks": [], "clips": []}), encoding="utf-8")
    def forbidden(request):
        pytest.fail("An invalid timeline revision must not be submitted")
    with httpx.Client(base_url="http://127.0.0.1", transport=httpx.MockTransport(forbidden)) as client:
        with pytest.raises(CliError) as caught:
            run_command(client, build_parser().parse_args(["timeline", "apply", "--project", "p", "--file", str(file)]))
    assert caught.value.detail["code"] == "missing_revision"


def test_canvas_run_file_keeps_frozen_configuration_and_explicit_overrides(tmp_path):
    body = {"revision": 4, "scope": "downstream", "force": True, "node_ids": ["old-selection"], "request_id": "file-key", "targets": [{"node_id": "actor", "job_request": {"speech_options": {"quality": "studio"}}}]}
    file = tmp_path / "run.json"
    file.write_text(json.dumps(body), encoding="utf-8-sig")
    captured = []
    def handler(request):
        captured.append(json.loads(request.content))
        return httpx.Response(200, json={"id": "new-run"})
    with httpx.Client(base_url="http://127.0.0.1", transport=httpx.MockTransport(handler)) as client:
        args = build_parser().parse_args(["canvas-run", "start", "--project", "p", "--file", str(file), "--node", "new-selection", "--revision", "5", "--request-id", "explicit-key"])
        run_command(client, args)
    assert captured == [{**body, "node_ids": ["new-selection"], "revision": 5, "request_id": "explicit-key"}]


@pytest.mark.parametrize("explicit", [False, True])
def test_lipsync_create_freezes_media_roles_and_options_from_file(tmp_path, explicit):
    body = {"project_id": "p", "source_node_id": "lip-node", "kind": "audio", "workflow_id": "unrelated", "request_id": "file-id", "prompt": "请同步这段台词", "references": [{"id": "v", "role": "video", "version_id": "video-v1"}, {"id": "a", "role": "audio", "version_id": "voice-v2"}], "lip_sync_options": {"video_start": .5, "audio_offset": .25, "duration": 5, "face_mode": "manual", "face_box": [120, 40, 180, 200]}, "parameters": {"seed": 21, "steps": 24, "cfg": 1.5}, "result_policy": "review"}
    file = tmp_path / "口型.json"
    file.write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8-sig")
    captured = []
    def handler(request):
        captured.append((request.method, request.url.path, json.loads(request.content)))
        return httpx.Response(202, json={"id": "lip-job"})
    command = ["lipsync", "create", "--file", str(file)] + (["--request-id", "override"] if explicit else [])
    with httpx.Client(base_url="http://127.0.0.1", transport=httpx.MockTransport(handler)) as client:
        assert run_command(client, build_parser().parse_args(command))["id"] == "lip-job"
    expected = {**body, "kind": "video", "workflow_id": "builtin-latentsync15-local", "request_id": "override" if explicit else "file-id"}
    assert captured == [("POST", "/api/generations", expected)]
    assert json.loads(file.read_text(encoding="utf-8-sig")) == body


@pytest.mark.parametrize(("command", "path"), [("timeline", "/api/production/renders/job"), ("canvas-run", "/api/canvas-runs/job")])
def test_new_wait_commands_poll_until_success_without_mutation(command, path, monkeypatch):
    states = iter(["pending", "running", "succeeded"])
    calls, sleeps = [], []
    monkeypatch.setattr("manju.cli.time", SimpleNamespace(monotonic=monotonic, sleep=sleeps.append))
    def handler(request):
        calls.append((request.method, request.url.path))
        return httpx.Response(200, json={"id": "job", "status": next(states)})
    with httpx.Client(base_url="http://127.0.0.1", transport=httpx.MockTransport(handler)) as client:
        result = run_command(client, build_parser().parse_args([command, "wait", "job", "--interval", ".01", "--max-wait", "5"]))
    assert result["status"] == "succeeded" and calls == [("GET", path)] * 3 and sleeps == [.01, .01]


@pytest.mark.parametrize(("command", "code"), [("timeline", "production_render_failed"), ("canvas-run", "canvas_run_failed")])
def test_wait_surfaces_terminal_failure(command, code):
    with httpx.Client(base_url="http://127.0.0.1", transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"id": "job", "status": "failed", "error": "fixture failure"}))) as client:
        with pytest.raises(CliError) as caught:
            run_command(client, build_parser().parse_args([command, "wait", "job"]))
    assert caught.value.detail["code"] == code


@pytest.mark.parametrize(("command", "code"), [("timeline", "production_wait_timeout"), ("canvas-run", "canvas_run_timeout")])
def test_wait_timeout_keeps_backend_task_running(command, code, monkeypatch):
    clock = iter([0, 2])
    monkeypatch.setattr("manju.cli.time", SimpleNamespace(monotonic=lambda: next(clock), sleep=lambda seconds: pytest.fail("An expired CLI wait must return immediately")))
    calls = []
    def handler(request):
        calls.append(request.method)
        return httpx.Response(200, json={"id": "job", "status": "running"})
    with httpx.Client(base_url="http://127.0.0.1", transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(CliError) as caught:
            run_command(client, build_parser().parse_args([command, "wait", "job", "--max-wait", "1"]))
    assert caught.value.detail["code"] == code and calls == ["GET"]
