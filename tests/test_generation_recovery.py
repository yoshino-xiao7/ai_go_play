import httpx
import pytest

from conftest import project
from test_generation import generation, submit
from manju.store import DomainError, now


def test_unknown_jobs_do_not_starve_new_submission(client, generation):
    service, peer = generation
    pid = project(client)['id']
    unknown = []
    for i in range(25):
        job = submit(client, pid, request_id=f'unresolved-{i}')
        service._update(job['id'], status='unknown', submission_started_at=now())
        unknown.append(job['id'])
    fresh = submit(client, pid, request_id='new-shot')
    service.tick()
    assert service.get(fresh['id'])['status'] == 'queued'
    assert len(peer.submissions) == 1
    # The rotating window also reaches unresolved jobs beyond the first 20.
    service.tick()
    assert all(service.get(key)['message'] for key in unknown)


def test_unknown_tracking_requires_confirmation_and_works_offline(client, generation):
    service, peer = generation
    job = submit(client, project(client)['id'])
    service._update(job['id'], status='unknown', submission_started_at=now())
    with pytest.raises(DomainError) as caught:
        service.cancel(job['id'])
    assert caught.value.detail['code'] == 'generation_interrupt_confirmation'
    calls = len(peer.calls)
    ended = service.cancel(job['id'], True)
    assert ended['status'] == 'cancelled'
    assert ended['error']['code'] == 'tracking_ended'
    assert len(peer.calls) == calls  # This ends tracking; never globally interrupts the GPU.
    service.tick()
    assert not peer.submissions


def test_active_card_rejects_new_request_but_allows_same_idempotency_key(client, generation):
    service, peer = generation
    pid = project(client)['id']
    canvas = service.store.canvas(pid)
    canvas['nodes'] = [{'id':'image','type':'media','position':{'x':0,'y':0},'data':{'kind':'image'}}]
    service.store.save_canvas(pid, canvas)
    first = submit(client, pid, source_node_id='image', request_id='original')
    assert submit(client, pid, source_node_id='image', request_id='original')['id'] == first['id']
    service._update(first['id'],status='unknown',submission_started_at=now())
    response=client.post('/api/generations',json={'project_id':pid,'source_node_id':'image','workflow_id':'builtin-qwen21-text_to_image','prompt':'new','request_id':'duplicate'})
    assert response.status_code==409
    assert response.json()['detail']['code']=='generation_source_busy'
