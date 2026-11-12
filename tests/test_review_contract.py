from copy import deepcopy
import pytest
from conftest import project, upload
from test_generation import generation, submit
from test_generation_history import image_card, finish
from manju.reference_contract import normalize_references, compile_prompt
from manju.store import DomainError

def test_review_delivery_preserves_adopted_and_pins_candidate(client,generation,png_bytes):
    service,peer=generation
    item=project(client)
    original=upload(client,png_bytes("red"))["current_version_id"]
    card=image_card(client,item["id"],original)
    job=submit(client,item["id"],source_node_id=card["id"],result_policy="review")
    result=finish(service,peer,job,png_bytes,["blue","green"])
    canvas=service.store.canvas(item["id"])
    assert len(canvas["nodes"])==1
    data=canvas["nodes"][0]["data"]
    assert data["asset_version_id"]==original
    assert "previous_image_version_id" not in data
    assert all(entry["candidate"] for entry in data["image_history"][1:])
    assert result["outputs"][0]["version_id"] in service.store.node_version_ids(canvas["nodes"][0])
    service._append_results(service.get(job["id"]),result["outputs"])
    assert service.store.canvas(item["id"])==canvas

def test_review_first_result_auto_adopts(client,generation,png_bytes):
    service,peer=generation
    item=project(client);card=image_card(client,item["id"])
    job=submit(client,item["id"],source_node_id=card["id"],result_policy="review")
    result=finish(service,peer,job,png_bytes,["green","blue"])
    assert service.store.canvas(item["id"])["nodes"][0]["data"]["asset_version_id"]==result["outputs"][0]["version_id"]
    history=service.store.canvas(item["id"])["nodes"][0]["data"]["image_history"]
    assert not history[0]["candidate"] and history[1]["candidate"]

def test_legacy_reference_normalization_keeps_idempotency_shape():
    request={"references":[{"version_id":"one","node_id":"source"}]}
    before=deepcopy(request)
    normalize_references({"references":[{"version_id":"one","node_id":"source"}]},request)
    assert request==before

def test_candidate_and_edit_base_survive_archive(client,generation,png_bytes):
    service,peer=generation
    item=project(client)
    current=upload(client,png_bytes("red"))["current_version_id"]
    candidate=upload(client,png_bytes("blue"))["current_version_id"]
    base=upload(client,png_bytes("green"))["current_version_id"]
    previous=upload(client,png_bytes("yellow"))["current_version_id"]
    image_card(client,item["id"],current)
    canvas=service.store.canvas(item["id"])
    data=canvas["nodes"][0]["data"]
    data["image_history"]=[{"version_id":current},{"version_id":candidate,"candidate":True}]
    data["previous_image_version_id"]=previous
    data["generation"]={"mode":"edit","prompt":"修改","references":[],"edit_base_version_id":base}
    service.store.save_canvas(item["id"],canvas)
    assert base in service.store.node_version_ids(canvas["nodes"][0])
    archive=client.get(f"/api/projects/{item['id']}/export").content
    imported=client.post("/api/projects/import",files={"file":("review.manju",archive)})
    assert imported.status_code==201,imported.text
    restored=service.store.canvas(imported.json()["id"])["nodes"][0]["data"]
    assert restored["image_history"][1]["candidate"]
    assert client.get('/api/media/'+restored['generation']['edit_base_version_id']).content==png_bytes("green")
    assert client.get('/api/media/'+restored['previous_image_version_id']).content==png_bytes("yellow")

def test_reference_survives_deleted_source_and_compiles_aliases(client,generation,png_bytes):
    service,peer=generation
    item=project(client);card=image_card(client,item["id"])
    one=upload(client,png_bytes("red"))["current_version_id"]
    two=upload(client,png_bytes("blue"))["current_version_id"]
    job=submit(client,item["id"],source_node_id=card["id"],workflow_id="builtin-qwen21-reference",
       prompt="让 @甲 站在 @乙 左边",references=[{"id":"b","version_id":two,"node_id":"deleted","title":"乙"},{"id":"a","version_id":one,"title":"甲","description":"黄色围巾"}],
       prompt_parts=[{"type":"text","text":"让 "},{"type":"reference","reference_id":"a"},{"type":"text","text":" 站在 "},{"type":"reference","reference_id":"b"},{"type":"text","text":" 左边"}])
    assert job["request"]["compiled_prompt"]=="让 参考图2中的主体 站在 参考图1中的主体 左边\n参考图2的主体设定：黄色围巾"
    service.tick()
    graph=peer.submissions[-1]["prompt"]
    assert graph["8"]["inputs"]["prompt"]==job["request"]["compiled_prompt"]

@pytest.mark.parametrize("parts",[[{"type":"reference","reference_id":"missing"}],[{"type":"text","text":4}],{}])
def test_prompt_contract_rejects_invalid_parts(parts):
    request={"references":[{"version_id":"one"}]}
    with pytest.raises(DomainError):
        normalize_references({"references":[{"version_id":"one","id":"a"}],"prompt_parts":parts},request)

def test_unknown_workflow_must_declare_mapping():
    request={"prompt":"@甲","references":[{"id":"a","version_id":"one"}],"prompt_parts":[{"type":"reference","reference_id":"a"}]}
    with pytest.raises(DomainError) as error:
        compile_prompt(request,{"id":"custom","capabilities":{}})
    assert error.value.detail["code"]=="reference_mapping_unsupported"

def test_locked_edges_cannot_be_reconnected_or_removed(client,generation,png_bytes):
    store=client.app.state.store;item=project(client)
    canvas=store.canvas(item["id"])
    canvas["nodes"]=[{"id":i,"type":"text","position":{"x":index*100,"y":0},"data":{"locked":i=="locked"}} for index,i in enumerate(["locked","other","target"])]
    canvas["edges"]=[{"id":"line","source":"locked","target":"target","data":{"role":"relation"}}]
    store.save_canvas(item["id"],canvas)
    for mutation in ("remove","reconnect","role"):
        doc=deepcopy(store.canvas(item["id"]))
        if mutation=="remove":doc["edges"]=[]
        elif mutation=="reconnect":doc["edges"][0]["source"]="other"
        else:doc["edges"][0]["data"]["role"]="pending"
        with pytest.raises(DomainError) as error:store.save_canvas(item["id"],doc)
        assert error.value.detail["code"]=="edge_locked"
    doc=store.canvas(item["id"]);doc["nodes"][0]["data"]["locked"]=False;doc["edges"]=[]
    assert store.save_canvas(item["id"],doc)["edges"]==[]
