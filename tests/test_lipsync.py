"""LatentSync contracts against isolated files and a mocked ComfyUI protocol."""
from copy import deepcopy
from pathlib import Path
import json
import importlib.util

import pytest

from conftest import project, upload
from test_generation import generation
from test_speech import voice_bytes
from manju.generation import GenerationService
from manju.lipsync import ENGINE, NODE, PROFILE_ID
from manju.media import find_binary, run_process
from manju.store import DomainError


@pytest.fixture(scope="module")
def lip_media(tmp_path_factory):
    ffmpeg = find_binary("ffmpeg")
    if not ffmpeg:
        pytest.skip("FFmpeg is needed for real lip-sync video fixtures")
    folder = tmp_path_factory.mktemp("lipsync-media")
    original, result = folder / "original.mp4", folder / "synchronized.mp4"
    run_process([ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "color=red:size=320x240:rate=25", "-t", "4", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(original)], timeout=30)
    run_process([ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "color=blue:size=320x240:rate=25", "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=24000", "-t", "4", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(result)], timeout=30)
    return {"video": original.read_bytes(), "audio": voice_bytes(3), "result": result.read_bytes()}


@pytest.fixture
def lipsync(generation, monkeypatch):
    service, peer = generation
    monkeypatch.setattr(service.workflows, "object_info", lambda: {NODE: {"input": {"required": {"engine": [[ENGINE]]}}}})
    return service, peer


def payload(project_id="project", **values):
    return {"kind": "video", "workflow_id": PROFILE_ID, "project_id": project_id,
            "prompt": "保留原画面，只让角色按配音说话。", "parameters": {"seed": 42},
            "references": [{"id": "voice", "version_id": "audio", "role": "audio"},
                           {"id": "face", "version_id": "video", "role": "video"}], **values}


def real_request(client, service, media, *, source=False):
    item = project(client)
    video = upload(client, media["video"], "original.mp4")
    audio = upload(client, media["audio"], "dialogue.wav")
    body = payload(item["id"], request_id="lipsync-initial", lip_sync_options={"video_start": .25, "audio_offset": .25, "duration": 3.5})
    body["references"][0]["version_id"] = audio["current_version_id"]
    body["references"][1]["version_id"] = video["current_version_id"]
    if source:
        canvas = service.store.canvas(item["id"])
        canvas["nodes"] = [{"id": "lip-card", "type": "media", "position": {"x": 10, "y": 20}, "data": {"kind": "video", "asset_version_id": video["current_version_id"], "title": "口型候选"}},
                           {"id": "note", "type": "text", "position": {"x": 400, "y": 20}, "data": {"text": "保留原始分镜"}}]
        service.store.save_canvas(item["id"], canvas)
        body["source_node_id"] = "lip-card"
    return item, video, audio, body


def complete_video(service, peer, job, content):
    queued = service.get(job["id"])
    peer.image = content
    peer.complete(queued["prompt_id"])
    peer.history[queued["prompt_id"]]["outputs"] = {"sync": {"videos": [{"filename": "synchronized.mp4", "subfolder": "Manju", "type": "output"}]}}
    service.tick()
    return service.get(job["id"])


def test_normalization_keeps_explicit_roles_defaults_and_original_payload():
    body = payload(lip_sync_options={"face_box": [1, 2, 100, 100]})
    original = deepcopy(body)
    request = GenerationService._validate_request(body)
    assert body == original
    assert request["kind"] == "video" and request["workflow_id"] == PROFILE_ID
    assert request["result_policy"] == "review"
    assert request["parameters"] == {"seed": 42, "steps": 20, "cfg": 1.5}
    assert request["lip_sync_options"] == {"video_start": 0, "audio_offset": 0, "duration": None, "face_mode": "auto", "face_box": None}
    assert [(ref["id"], ref["role"], ref["media_type"]) for ref in request["references"]] == [("voice", "audio", "audio"), ("face", "video", "video")]
    for ref in body["references"]:
        ref["media_type"] = ref.pop("role")
    assert {ref["role"] for ref in GenerationService._validate_request(body)["references"]} == {"video", "audio"}


@pytest.mark.parametrize("options", [
    {"audio_offset": -1}, {"audio_offset": 121}, {"audio_offset": True}, {"audio_offset": float("nan")},
    {"video_start": -1}, {"video_start": 86401}, {"video_start": float("inf")},
    {"duration": .1}, {"duration": 121}, {"duration": True}, {"unknown": 1},
    {"face_mode": "random"}, {"face_mode": "manual", "face_box": None},
    {"face_mode": "manual", "face_box": [0, 0, 39, 100]},
    {"face_mode": "manual", "face_box": [-1, 0, 100, 100]},
    {"face_mode": "manual", "face_box": [0, 0, True, 100]},
    {"face_mode": "manual", "face_box": [0, 0, 100, float("nan")]},
])
def test_invalid_timing_and_face_bounds_are_rejected(options):
    with pytest.raises(DomainError) as caught:
        GenerationService._validate_request(payload(lip_sync_options=options))
    assert caught.value.status == 422


@pytest.mark.parametrize("values", [
    {"references": []}, {"references": [{"version_id": "v", "role": "video"}]},
    {"references": [{"version_id": "v", "role": "video"}, {"version_id": "a", "role": "video"}]},
    {"references": [{"version_id": "v", "role": "image"}, {"version_id": "a", "role": "audio"}]},
    {"references": [{"version_id": "v"}, {"version_id": "a", "role": "audio"}]},
    {"parameters": {"steps": 9}}, {"parameters": {"steps": 51}}, {"parameters": {"steps": 20.5}},
    {"parameters": {"cfg": .9}}, {"parameters": {"cfg": 3.1}}, {"parameters": {"cfg": True}},
    {"parameters": {"width": 512}}, {"parameters": {"seed": -2}}, {"provider": "openai"}, {"mask_version_id": "mask"},
])
def test_invalid_input_roles_and_sampling_contract(values):
    with pytest.raises(DomainError):
        GenerationService._validate_request(payload(**values))


def test_missing_engine_rejects_before_any_job_or_upload(client, lipsync, monkeypatch):
    service, peer = lipsync
    monkeypatch.setattr(service.workflows, "object_info", lambda: {})
    assert client.get("/api/lipsync/settings").json()["ready"] is False
    response = client.post("/api/generations", json=payload(project(client)["id"]))
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "lipsync_not_ready"
    assert not service.list() and not peer.uploads and not peer.submissions


@pytest.mark.parametrize(("options", "code"), [
    ({"video_start": 3, "duration": 2}, "lipsync_duration_invalid"),
    ({"video_start": 4}, "lipsync_duration_invalid"),
    ({"duration": 2}, "lipsync_audio_overflow"),
    ({"duration": 4, "audio_offset": 1.1}, "lipsync_audio_overflow"),
    ({"duration": 4, "face_mode": "manual", "face_box": [300, 0, 40, 40]}, "lipsync_face_invalid"),
    ({"duration": 4, "face_mode": "manual", "face_box": [0, 220, 40, 40]}, "lipsync_face_invalid"),
])
def test_real_media_bounds_are_checked_before_queue(client, lipsync, lip_media, options, code):
    service, peer = lipsync
    _, _, _, body = real_request(client, service, lip_media)
    body["lip_sync_options"] = options
    response = client.post("/api/generations", json=body)
    assert response.status_code == 422, response.text
    assert response.json()["detail"]["code"] == code
    assert not service.list() and not peer.uploads


def test_original_video_and_audio_are_frozen_uploaded_without_h3_conversion_and_collected(client, lipsync, lip_media, monkeypatch):
    service, peer = lipsync
    item, video, audio, body = real_request(client, service, lip_media, source=True)
    body["lip_sync_options"].update(face_mode="manual", face_box=[40, 20, 100, 120])
    response = client.post("/api/generations", json=body)
    assert response.status_code == 202, response.text
    job = response.json()
    assert job["workflow_snapshot"]["id"] == PROFILE_ID and job["workflow_snapshot"]["output_nodes"] == ["sync"]
    assert {ref["snapshot"]["hash"] for ref in job["request"]["references"]} == {service.store.version(asset["current_version_id"])["hash"] for asset in (video, audio)}
    assert service.store.conn.execute("SELECT COUNT(*) FROM generation_inputs WHERE job_id=?", (job["id"],)).fetchone()[0] == 2
    # A new current voice version must not alter the already accepted references.
    upload(client, voice_bytes(3, 2500), "new-dialogue.wav", asset_id=audio["id"])
    def forbidden(*args, **kwargs):
        raise AssertionError("Lip sync must upload original media, not H3 reference conversion")
    monkeypatch.setattr("manju.video_inputs.prepare_reference", forbidden)
    service.tick()
    queued = service.get(job["id"])
    assert queued["status"] == "queued", queued
    assert {entry["content"] for entry in peer.uploads} == {lip_media["video"], lip_media["audio"]}
    assert sorted(Path(entry["filename"]).suffix for entry in peer.uploads) == [".mp4", ".wav"]
    graph = queued["mapped_graph"]
    assert set(graph) == {"sync"} and graph["sync"]["class_type"] == NODE
    inputs = graph["sync"]["inputs"]
    assert inputs["engine"] == ENGINE and inputs["video"].endswith(".mp4") and inputs["audio"].endswith(".wav")
    assert inputs["audio_offset"] == .25 and inputs["video_start"] == .25 and inputs["duration"] == 3.5
    assert json.loads(inputs["face_box"]) == [40, 20, 100, 120]
    assert inputs["steps"] == 20 and inputs["guidance"] == 1.5 and inputs["seed"] == 42
    result = complete_video(service, peer, job, lip_media["result"])
    assert result["status"] == "succeeded", result
    output = result["outputs"][0]
    version = service.store.version(output["version_id"])
    assert version["mime"].startswith("video/") and (version["width"], version["height"]) == (320, 240)
    assert Path(version["path"]).read_bytes() == lip_media["result"]
    assert service.store.asset(output["asset_id"])["source"] == "comfyui"
    assert any(asset["id"] == output["asset_id"] for asset in service.store.assets(project_id=item["id"])["items"])
    saved = service.store.canvas(item["id"])
    assert len(saved["nodes"]) == 2 and saved["nodes"][1]["data"]["text"] == "保留原始分镜"
    card = saved["nodes"][0]["data"]
    assert card["asset_version_id"] == video["current_version_id"]  # Review policy preserves adopted video.
    assert any(entry["version_id"] == output["version_id"] and entry.get("candidate") for entry in card["image_history"])
    service._collect(result, peer.history[queued["prompt_id"]])
    assert service.store.canvas(item["id"])["revision"] == saved["revision"]


def test_request_id_retry_and_lost_response_do_not_duplicate_submissions(client, lipsync, lip_media, monkeypatch):
    service, peer = lipsync
    _, _, _, body = real_request(client, service, lip_media, source=True)
    body["parameters"] = {"seed": -1, "steps": 24, "cfg": 1.8}
    first = client.post("/api/generations", json=body).json()
    duplicate = client.post("/api/generations", json=body).json()
    assert first["id"] == duplicate["id"] and first["request"]["parameters"]["seed"] == duplicate["request"]["parameters"]["seed"] >= 0
    conflict = client.post("/api/generations", json={**body, "prompt": "different"})
    assert conflict.status_code == 409 and conflict.json()["detail"]["code"] == "idempotency_conflict"
    peer.timeout_after_accept = True
    service.tick()
    assert len(peer.submissions) == 1 and service.get(first["id"])["status"] == "unknown"
    with pytest.raises(DomainError) as caught:
        service.retry(first["id"], "unsafe-retry")
    assert caught.value.detail["code"] == "generation_retry_unavailable"
    service.tick()
    recovered = service.get(first["id"])
    assert recovered["status"] == "queued" and len(peer.submissions) == 1
    peer.complete(recovered["prompt_id"], error=True); service.tick()
    assert service.get(first["id"])["status"] == "failed"
    # Retry is pinned to the original validated engine snapshot, even if discovery goes away.
    monkeypatch.setattr(service.workflows, "object_info", lambda: {})
    retry = service.retry(first["id"], "retry-once")
    assert service.retry(first["id"], "retry-once")["id"] == retry["id"]
    assert retry["parent_job_id"] == first["id"]
    assert retry["request"]["references"] == first["request"]["references"]
    assert retry["request"]["parameters"] == first["request"]["parameters"]
    assert retry["workflow_snapshot"] == first["workflow_snapshot"]
    peer.timeout_after_accept = False; service.tick()
    assert service.get(retry["id"])["status"] == "queued" and len(peer.submissions) == 2


def test_wrong_type_or_missing_original_is_rejected_before_upload(client, lipsync, lip_media, png_bytes):
    service, peer = lipsync
    _, video, _, body = real_request(client, service, lip_media)
    image = upload(client, png_bytes(), "not-video.png")
    body["references"][1]["version_id"] = image["current_version_id"]
    response = client.post("/api/generations", json=body)
    assert response.status_code == 422 and response.json()["detail"]["code"] == "lipsync_inputs_invalid"
    body["references"][1]["version_id"] = video["current_version_id"]
    Path(service.store.version(video["current_version_id"])["path"]).unlink()
    response = client.post("/api/generations", json=body)
    assert response.status_code == 422 and response.json()["detail"]["code"] == "lipsync_inputs_invalid"
    assert not peer.uploads and not service.list()


def test_worker_mux_trims_whisper_padding_to_exact_requested_video_frames(tmp_path):
    ffmpeg, ffprobe = find_binary("ffmpeg"), find_binary("ffprobe")
    if not ffmpeg or not ffprobe:
        pytest.skip("FFmpeg and FFprobe are needed for the real lip-sync mux boundary test")
    # Import only the worker helper; the Comfy plugin package imports runtime modules.
    worker_path = Path(__file__).resolve().parents[1] / "integrations/comfyui_manju_lipsync/worker.py"
    spec = importlib.util.spec_from_file_location("lipsync_mux_test_worker", worker_path)
    worker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(worker)
    folder = tmp_path / "render"
    folder.mkdir()
    run_process([ffmpeg, "-v", "error", "-y", "-f", "lavfi", "-i", "color=red:size=320x240:rate=25", "-frames:v", "127", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(folder / "video.mp4")], timeout=30)
    run_process([ffmpeg, "-v", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=16000", "-t", "5.08", str(folder / "audio.wav")], timeout=30)
    result = tmp_path / "synchronized.mp4"
    run_process(worker.mux_command(ffmpeg, folder, result, 125), timeout=30)
    probe = json.loads(run_process([ffprobe, "-v", "error", "-count_frames", "-show_streams", "-show_format", "-of", "json", str(result)], timeout=30).stdout)
    video = next(stream for stream in probe["streams"] if stream["codec_type"] == "video")
    audio = next(stream for stream in probe["streams"] if stream["codec_type"] == "audio")
    assert video["avg_frame_rate"] == "25/1"
    assert int(video["nb_read_frames"]) == 125
    assert float(video["duration"]) == pytest.approx(5, abs=1e-6)
    assert 5 <= float(audio["duration"]) <= 5.05
    assert 5 <= float(probe["format"]["duration"]) <= 5.05
