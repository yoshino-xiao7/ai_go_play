"""Real local FFmpeg renders; no generation service or user library is used."""
import copy
import hashlib
import json
from pathlib import Path
import zipfile

import pytest

from manju.media import find_binary, probe_media, run_process
from manju.production import ProductionService
from manju.store import DomainError, Store
from manju.transfers import export_project, import_project


@pytest.fixture
def production(tmp_path):
    store = Store(tmp_path / "library", tmp_path / "config.json")
    service = ProductionService(store)
    yield service
    service.close()
    store.close()


@pytest.fixture
def materials(production, tmp_path):
    ffmpeg = find_binary("ffmpeg")
    if not ffmpeg or not find_binary("ffprobe"):
        pytest.skip("FFmpeg and FFprobe required")
    result = {}
    for name, color in (("red", "red"), ("blue", "blue")):
        path = tmp_path / (name + ".mp4")
        run_process([ffmpeg, "-y", "-f", "lavfi", "-i", f"color=c={color}:s=160x96:r=24:d=2", "-f", "lavfi", "-i", "sine=frequency=220:duration=2", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(path)])
        result[name] = production.store.ingest(path, path.name, probe_media(path, path.name), hashlib.sha256(path.read_bytes()).hexdigest())["imported_version_id"]
    path = tmp_path / "voice.wav"
    run_process([ffmpeg, "-y", "-f", "lavfi", "-i", "sine=frequency=880:duration=0.4", str(path)])
    result["audio"] = production.store.ingest(path, path.name, probe_media(path, path.name), hashlib.sha256(path.read_bytes()).hexdigest())["imported_version_id"]
    return result


def save_shots(service, materials):
    project = service.store.create_project("雨夜来信", "16:9")
    canvas = service.store.canvas(project["id"])
    canvas["nodes"].append({"id": "source", "type": "media", "position": {"x": 100, "y": 100}, "data": {"kind": "video", "asset_version_id": materials["red"]}})
    service.store.save_canvas(project["id"], canvas)
    body = {"revision": 1, "request_id": "save-first", "settings": {"width": 160, "height": 96, "fps": 24, "background_audio_version_id": materials["audio"], "background_volume": .1},
            "shots": [{"id": "shot-one", "title": "归来", "duration": 1, "dialogue": "你终于回来了。", "video_version_id": materials["red"], "video_node_id": "source", "audio_version_id": materials["audio"], "audio_offset": .1, "video_volume": .1},
                      {"id": "shot-two", "title": "回应", "duration": 1, "dialogue": "我一直记得。", "video_version_id": materials["blue"]}]}
    return project["id"], service.save(project["id"], body), body


def test_order_fixed_versions_conflict_and_portable_archive(production, materials, tmp_path):
    pid, saved, body = save_shots(production, materials)
    assert saved["total_duration"] == 2
    assert production.save(pid, body)["revision"] == saved["revision"]
    canvas = production.store.canvas(pid)
    source = next(n for n in canvas["nodes"] if n["id"] == "source")
    source["data"]["asset_version_id"] = materials["blue"]
    production.store.save_canvas(pid, canvas)
    current = production.get(pid)
    assert current["shots"][0]["stale"]
    assert current["shots"][0]["video_version_id"] == materials["red"]
    with pytest.raises(DomainError, match="已更新"):
        production.save(pid, {**body, "request_id": "conflicting"})
    duplicate = production.store.duplicate_project(pid)
    assert production.get(duplicate["id"])["shots"][0]["video_version_id"] == materials["red"]
    archive = export_project(production.store, pid)
    target = Store(tmp_path / "imported", tmp_path / "other.json")
    try:
        other = ProductionService(target)
        imported = import_project(target, archive)
        shots = other.get(imported["id"])["shots"]
        assert shots[0]["video_version_id"] != materials["red"]
        assert target.version(shots[0]["video_version_id"])["hash"] == production.store.version(materials["red"])["hash"]
        assert other.get(imported["id"])["settings"]["background_audio_version_id"] != materials["audio"]
    finally:
        target.close()


def test_real_render_mix_subtitles_duration_and_idempotent_delivery(production, materials):
    pid, saved, _ = save_shots(production, materials)
    payload = {"request_id": "render-first", "revision": saved["revision"], "burn_subtitles": True, "name": "雨夜来信 · 完整测试"}
    job = production.render(pid, payload)
    assert production.render(pid, payload)["id"] == job["id"]
    # Later canvas edits must survive result delivery.
    canvas = production.store.canvas(pid)
    canvas["nodes"][0]["position"]["x"] = 999
    production.store.save_canvas(pid, canvas)
    production.tick()
    result = production.get_render(job["id"])
    assert result["status"] == "succeeded", result["error"]
    version = production.store.version(result["output_version_id"])
    assert abs(version["duration"] - 2) < .1
    streams = json.loads(run_process([find_binary("ffprobe"), "-v", "error", "-show_streams", "-of", "json", version["path"]]).stdout)["streams"]
    assert {s["codec_type"] for s in streams} == {"audio", "video"}
    canvas = production.store.canvas(pid)
    assert next(n for n in canvas["nodes"] if n["id"] == "source")["position"]["x"] == 999
    assert sum(n["id"] == result["output_node_id"] for n in canvas["nodes"]) == 1
    assert "00:00:00,100 --> 00:00:00,500" in production.subtitle(pid)
    with zipfile.ZipFile(production.handoff(pid)) as handoff:
        manifest = json.loads(handoff.read("production.json"))
        assert len(manifest["shots"]) == 2
        assert manifest["shots"][0]["video_file"] in handoff.namelist()
        assert "subtitles.srt" in handoff.namelist()
    production.tick()
    assert len(production.list_renders(pid)) == 1


def test_render_rejects_truncated_video_and_dialogue(production, materials):
    pid, saved, body = save_shots(production, materials)
    body = copy.deepcopy(body)
    body.update(revision=saved["revision"], request_id="short-voice")
    body["shots"][0]["audio_offset"] = .8
    production.save(pid, body)
    with pytest.raises(DomainError) as error:
        production.render(pid, {})
    assert error.value.detail["code"] == "production_audio_overflow"
    body.update(revision=production.get(pid)["revision"], request_id="short-video")
    body["shots"][0].update(audio_offset=0, duration=3)
    production.save(pid, body)
    with pytest.raises(DomainError) as error:
        production.render(pid, {})
    assert error.value.detail["code"] == "production_video_too_short"


def test_active_render_guards_inputs_and_restart_retry(production, materials):
    pid, saved, _ = save_shots(production, materials)
    job = production.render(pid, {"request_id": "durable"})
    with pytest.raises(DomainError) as error:
        production.store.trash_project(pid)
    assert error.value.detail["code"] == "production_in_progress"
    with pytest.raises(DomainError):
        production.store._guard_generations(asset_id=production.store.version(materials["red"])["asset_id"])
    production._update(job["id"], status="running")
    recovered = ProductionService(production.store)
    assert recovered.get_render(job["id"])["status"] == "pending"
    recovered._update(job["id"], status="failed", error="interrupted")
    assert recovered.retry_render(job["id"])["status"] == "pending"
    assert recovered.get_render(job["id"])["snapshot"]["shots"][0]["video_version_id"] == materials["red"]


def test_finished_render_recovers_delivery_without_reencoding(production, materials, monkeypatch):
    pid, _, _ = save_shots(production, materials)
    job = production.render(pid, {"request_id": "recover-delivery"})
    deliver = production._deliver
    def unavailable(*args):
        raise OSError("temporary disk delivery failure")
    monkeypatch.setattr(production, "_deliver", unavailable)
    production.tick()
    assert production.get_render(job["id"])["status"] == "failed"
    assert (production.store.root / "exports" / ("production-" + job["id"]) / "receipt.json").exists()
    monkeypatch.setattr(production, "_deliver", deliver)
    import manju.production as module
    monkeypatch.setattr(module, "run_process", lambda *a, **k: pytest.fail("already-rendered movie must not be encoded again"))
    production.retry_render(job["id"])
    production.tick()
    assert production.get_render(job["id"])["status"] == "succeeded"


@pytest.mark.parametrize("fps,expected", [(24, 3 / 24), (25, 3 / 25), (30, .1)])
def test_minimum_shot_duration_remains_readable_and_portable(production, tmp_path, fps, expected):
    project = production.store.create_project("最短镜头", "16:9")
    payload = {"revision": 0, "request_id": "minimum-duration", "settings": {"fps": fps},
               "shots": [{"id": "short-shot", "duration": .1, "dialogue": "稍等"}]}
    saved = production.save(project["id"], payload)
    assert saved["shots"][0]["duration"] == pytest.approx(expected)
    assert production.get(project["id"])["shots"] == saved["shots"]
    archive = export_project(production.store, project["id"])
    target = Store(tmp_path / "minimum-import", tmp_path / "minimum-config.json")
    try:
        restored = ProductionService(target)
        imported = import_project(target, archive)
        assert restored.get(imported["id"])["shots"][0]["duration"] == pytest.approx(expected)
    finally:
        target.close()
