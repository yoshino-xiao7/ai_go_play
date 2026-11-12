from conftest import project


def document():
    return {
        "title": "我的名字，你记住了吗",
        "audience": "轻百合爱好者",
        "hooks": "校园群像",
        "genre": "校园轻喜",
        "logline": "有人先记住了她的名字。",
        "synopsis": "第一段。\n\n第二段。",
        "characters": [{"name": "DeepSeek", "bio": "新生。\n蓝发。"}],
        "episodes": [
            {"id": f"ep-{number}", "title": f"第 {number} 集", "outline": f"大纲 {number}\n分场待定。",
             "script": f"### 场 {number}-1\n\n△ 她回到座位。\nDeepSeek：到。\n"}
            for number in range(1, 25)
        ],
    }


def test_screenplay_revision_is_independent_and_conflicts_leave_text_intact(client):
    project_path = f"/api/projects/{project(client)['id']}"
    path = project_path + "/screenplay"
    canvas = client.get(project_path + "/canvas").json()
    assert client.get(path).json() == {"revision": 0, "document": None}

    draft = document()
    saved = client.put(path, json={"revision": 0, "document": draft})
    assert saved.status_code == 200, saved.text
    assert saved.json() == {"revision": 1, "document": draft}
    assert client.get(project_path + "/canvas").json() == canvas

    updated = {**draft, "title": "新标题"}
    stale = client.put(path, json={"revision": 0, "document": updated})
    assert stale.status_code == 409
    assert stale.json()["detail"]["revision"] == 1
    assert client.get(path).json() == saved.json()

    invalid = {**draft, "episodes": [draft["episodes"][0]] * 2}
    assert client.put(path, json={"revision": 1, "document": invalid}).status_code == 422
    saved = client.put(path, json={"revision": 1, "document": updated})
    assert saved.json() == {"revision": 2, "document": updated}


def test_screenplay_round_trips_with_project_and_is_retained_in_trash(client):
    project_path = f"/api/projects/{project(client)['id']}"
    path = project_path + "/screenplay"
    draft = document()
    assert client.put(path, json={"revision": 0, "document": draft}).status_code == 200

    duplicate = client.post(project_path + "/duplicate")
    assert duplicate.status_code == 201
    duplicate_path = f"/api/projects/{duplicate.json()['id']}/screenplay"
    assert client.get(duplicate_path).json() == {"revision": 1, "document": draft}

    archive = client.get(project_path + "/export")
    assert archive.status_code == 200
    imported = client.post("/api/projects/import", files={"file": ("剧本项目.manju", archive.content)})
    assert imported.status_code == 201, imported.text
    imported_path = f"/api/projects/{imported.json()['id']}/screenplay"
    assert client.get(imported_path).json() == {"revision": 1, "document": draft}

    assert client.delete(project_path).status_code == 200
    assert client.get(path).status_code == 404
    assert client.put(path, json={"revision": 1, "document": draft}).status_code == 404
    assert client.post(project_path + "/restore").status_code == 200
    assert client.get(path).json() == {"revision": 1, "document": draft}
    assert client.delete(project_path).status_code == 200
    assert client.delete(project_path + "/permanent").status_code == 200
    assert client.app.state.store.conn.execute("SELECT COUNT(*) FROM screenplays").fetchone()[0] == 2
