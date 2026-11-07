import pytest

from manju.generation_progress import JobProgress, GenerationProgress


def test_director_uses_real_sampling_steps_not_six_phase_estimate():
    progress=JobProgress({'id':'job','prompt_id':'owned','backend_url':'http://127.0.0.1:8188','mapped_graph':{'director':{'class_type':'MiniMaxH3Director'}}})
    event={'type':'minimax_director_progress','data':{'node_id':'director','phase':'sample','phase_value':8,'phase_max':20}}
    progress.consume(event);assert 'value' not in progress.snapshot()
    progress.consume({'type':'executing','data':{'prompt_id':'owned','node':'director'}})
    progress.consume(event);assert progress.snapshot()['value']==8 and progress.snapshot()['max']==20
    progress.consume({'type':'progress_state','data':{'prompt_id':'owned','nodes':{'director':{'state':'running','value':2.4,'max':6}}}})
    assert progress.snapshot()['value']==8 and progress.snapshot()['max']==20
    progress.consume({'type':'minimax_director_progress','data':{'node_id':'director','phase':'decode','phase_value':0,'phase_max':1}})
    assert 'value' not in progress.snapshot() and progress.snapshot()['label']=='正在解码音视频'


def tracker():
    return JobProgress({"id": "job", "prompt_id": "owned", "backend_url": "http://127.0.0.1:8188",
                        "mapped_graph": {"sample": {"class_type": "KSampler"}, "decode": {"class_type": "VAEDecodeTiled"}}})


def test_real_steps_are_scoped_to_prompt_and_reset_on_stage_change():
    progress = tracker()
    progress.consume({"type": "progress", "data": {"prompt_id": "someone-else", "node": "sample", "value": 15, "max": 20}})
    assert "value" not in progress.snapshot()
    progress.consume({"type": "progress", "data": {"prompt_id": "owned", "node": "sample", "value": 8, "max": 20}})
    assert progress.snapshot()["value"] == 8
    assert progress.snapshot()["label"] == "正在采样"
    progress.consume({"type": "executing", "data": {"prompt_id": "owned", "node": "decode"}})
    assert progress.snapshot()["label"] == "正在解码画面"
    assert "value" not in progress.snapshot()


def test_progress_state_ignores_finished_nodes_and_reconnect_never_invents_steps():
    progress = tracker()
    progress.consume({"type": "progress_state", "data": {"prompt_id": "owned", "nodes": {
        "load": {"state": "finished", "value": 1, "max": 1},
        "sample": {"state": "running", "value": 3, "max": 20}}}})
    assert progress.snapshot()["value"] == 3
    progress.connection(False)
    assert progress.snapshot()["connected"] is False
    assert "value" not in progress.snapshot()
    progress.consume({"type": "executing", "data": {"node": "sample"}})
    assert progress.snapshot()["connected"] is True
    assert "value" not in progress.snapshot()


@pytest.mark.parametrize("value,maximum", [(3, 0), (-1, 20), (21, 20), (float("nan"), 20), (True, 20), (2, float("inf"))])
def test_invalid_counts_do_not_become_percentages(value, maximum):
    progress = tracker()
    progress.consume({"type": "progress", "data": {"prompt_id": "owned", "node": "sample", "value": value, "max": maximum}})
    assert "value" not in progress.snapshot()


def test_telemetry_is_exposed_on_read_and_removed_after_completion(client, generation):
    from test_generation import submit
    from conftest import project
    service, peer = generation
    job = submit(client, project(client)["id"])
    service.tick()
    observer = tracker()
    service.telemetry.items[job["id"]] = observer
    observer.consume({"type": "progress", "data": {"prompt_id": "owned", "node": "sample", "value": 4, "max": 20}})
    actual = client.get("/api/generations/" + job["id"]).json()
    assert actual["progress"] is None
    assert actual["execution_progress"]["value"] == 4
    assert service.list()[0]["execution_progress"]["max"] == 20
    service._update(job["id"], status="succeeded", progress=1)
    assert service.get(job["id"])["execution_progress"] is None
    service.tick()
    assert observer.stop.is_set()


# Reuse the isolated Comfy peer; these tests never contact the GPU service.
from test_generation import generation
