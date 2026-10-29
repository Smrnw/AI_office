"""Тесты HTTP-слоя: защита сервера, файлы, задачи, полный прогон команды на демо-провайдере."""
import pytest

from pixel_office import settings, tasks_store, workspace
from pixel_office.agents import chat_store, dispatcher
from pixel_office.api import security
from pixel_office.runtime import state

from conftest import HEADERS, all_done, wait_for

TEAM = settings.TEAM_CHANNEL


# ---------- защита ----------

def test_foreign_host_rejected(client):
    assert client.get("/api/state", headers={"Host": "evil.example.com"}).status_code == 400


def test_post_without_csrf_header_rejected(client):
    assert client.post("/api/stop").status_code == 403


def test_cross_origin_post_rejected(client):
    r = client.post("/api/stop", headers={**HEADERS, "Origin": "https://evil.example.com"})
    assert r.status_code == 403
    r = client.post("/api/stop", headers={**HEADERS, "Origin": "null"})
    assert r.status_code == 403


def test_same_origin_post_allowed(client):
    assert client.post("/api/stop", headers={**HEADERS, "Origin": "http://localhost"}).status_code == 200
    state["paused"] = False


def test_security_headers(client):
    r = client.get("/")
    assert "script-src 'self'" in r.headers["content-security-policy"]
    assert r.headers["x-frame-options"] == "DENY"
    assert r.headers["x-content-type-options"] == "nosniff"


def test_token_mode(client, monkeypatch):
    monkeypatch.setattr(settings, "ACCESS_TOKEN", "s3cret")
    assert client.get("/api/state").status_code == 401
    assert client.get("/api/state", headers={"Authorization": "Bearer s3cret"}).status_code == 200
    r = client.get("/?token=s3cret", follow_redirects=False)
    assert r.status_code == 303 and "po_token" in r.headers["set-cookie"] and "HttpOnly" in r.headers["set-cookie"]
    client.cookies.clear()


def test_api_keys_never_leave_server(client):
    data = client.get("/api/state").json()
    assert all(p["api_key"] == "" for p in data["config"]["providers"])


# ---------- файлы и предпросмотр ----------

def test_file_crud_and_traversal(office):
    assert office.post("/api/file", json={"filename": "web/index.html", "content": "<h1>hi</h1>"}, headers=HEADERS).status_code == 200
    assert office.get("/api/file", params={"name": "web/index.html"}).json()["content"] == "<h1>hi</h1>"
    assert office.get("/api/file", params={"name": "../config.json"}).status_code == 400
    assert office.post("/api/file", json={"filename": "../../evil.txt", "content": "x"}, headers=HEADERS).status_code == 400
    names = [f["name"] for f in office.get("/api/state").json()["files"]]
    assert "web/index.html" in names
    assert office.post("/api/file/delete", json={"filename": "web/index.html"}, headers=HEADERS).status_code == 200


def test_preview_is_sandboxed_and_keyed(office):
    workspace.write_text("index.html", "<script>fetch('/api/reset')</script>")
    r = office.get(f"/preview/{security.PREVIEW_KEY}/index.html")
    assert r.status_code == 200
    assert r.headers["content-security-policy"].startswith("sandbox")
    assert "allow-same-origin" not in r.headers["content-security-policy"]
    assert office.get("/preview/wrong/index.html").status_code == 404
    assert office.get(f"/preview/{security.PREVIEW_KEY}/../config.json").status_code == 404


def test_zip_download(office):
    workspace.write_text("a.py", "print(1)")
    r = office.get("/api/download-zip")
    assert r.status_code == 200 and r.content[:2] == b"PK"


# ---------- работа команды ----------

def test_full_project_with_demo_team(office):
    r = office.post("/api/chat", json={"agent_id": TEAM, "message": "Сделай красивую html-страничку"}, headers=HEADERS)
    assert r.json() == {"ok": True, "started": True}
    wait_for(all_done, timeout=30)

    data = office.get("/api/state").json()
    folder = data["project_dir"]
    assert folder == "sdelay-krasivuyu-html-stranichku"          # каждый проект - в своей папке
    names = {f["name"] for f in data["files"]}
    assert {f"{folder}/index.html", f"{folder}/style.css", f"{folder}/script.js"} <= names
    assert folder in data["dirs"]
    tasks = tasks_store.scan_all()
    assert all(t["qa_notes"].startswith("✅") for t in tasks)
    authors = {m.get("author") for m in chat_store.history(TEAM) if m["role"] == "agent"}
    assert "PM" in authors
    assert state["is_running"] is False


def test_second_project_blocked_while_running(office):
    office.post("/api/start", json={"idea": "Проект один"}, headers=HEADERS)
    r = office.post("/api/start", json={"idea": "Проект два"}, headers=HEADERS).json()
    assert r["ok"] is False
    wait_for(all_done, timeout=30)


def test_revision_from_private_chat(office):
    office.post("/api/start", json={"idea": "Страница"}, headers=HEADERS)
    wait_for(all_done, timeout=30)
    before = len(tasks_store.scan_all())
    r = office.post("/api/chat", json={"agent_id": "Coder_1", "message": "Исправь index.html: добавь подвал"}, headers=HEADERS)
    assert r.json()["ok"] is True
    wait_for(lambda: len(tasks_store.scan_all()) > before and all_done(), timeout=30)
    reply = [m for m in chat_store.history("Coder_1") if m["role"] == "agent"]
    assert reply and reply[0]["tasks"]


def test_stop_and_resume(office, monkeypatch):
    from pixel_office.llm import demo
    monkeypatch.setattr(demo, "DEMO_DELAY", (0.4, 0.5))
    office.post("/api/start", json={"idea": "Медленный проект"}, headers=HEADERS)
    wait_for(lambda: any(t["status"] != "todo" for t in tasks_store.scan_all()), timeout=10)
    office.post("/api/stop", headers=HEADERS)
    wait_for(lambda: state["jobs"] == 0, timeout=10)
    assert state["paused"] is True
    assert not any(t["status"] == "in_progress" for t in tasks_store.scan_all())   # прерванное вернулось в очередь
    assert office.post("/api/resume", headers=HEADERS).json()["ok"] is True
    wait_for(all_done, timeout=30)


def test_manual_move_and_delete(office):
    office.post("/api/start", json={"idea": "Страница"}, headers=HEADERS)
    wait_for(all_done, timeout=30)
    task = tasks_store.scan_all()[0]
    r = office.post("/api/task/move", json={"task_file": task["task_file"], "new_status": "in_progress"}, headers=HEADERS)
    assert r.status_code == 400
    r = office.post("/api/task/move", json={"task_file": "../x.txt", "new_status": "todo"}, headers=HEADERS)
    assert r.status_code == 404
    # вернули в очередь вручную - диспетчер должен снова её сделать
    r = office.post("/api/task/move", json={"task_file": task["task_file"], "new_status": "todo"}, headers=HEADERS)
    assert r.status_code == 200
    wait_for(all_done, timeout=30)
    assert office.post("/api/task/delete", json={"task_file": task["task_file"]}, headers=HEADERS).status_code == 200
    assert tasks_store.find_task_path(task["task_file"]) is None


def test_busy_task_cannot_be_moved(office):
    office.post("/api/file", json={"filename": "x.py", "content": "x=1"}, headers=HEADERS)
    task = {"id": 950, "title": "t", "filename": "x.py", "status": "todo", "spec": "", "attempts": 0, "qa_notes": "", "history": ""}
    tasks_store.save_task(task, "testing")
    task["_busy"], task["worker"] = True, "QA_1"
    dispatcher.BOARD.append(task)
    try:
        r = office.post("/api/task/move", json={"task_file": task["task_file"], "new_status": "todo"}, headers=HEADERS)
        assert r.status_code == 409
    finally:
        task["_busy"] = False
        dispatcher.kill_board()


def test_raw_edit_with_bad_code_path_rejected(office):
    task = {"id": 960, "title": "t", "filename": "ok.py", "status": "todo", "spec": "", "attempts": 0, "qa_notes": "", "history": ""}
    tasks_store.save_task(task, "done")
    raw = tasks_store.format_task_txt({**task, "filename": "../../evil.py"})
    r = office.post("/api/task-file", json={"task_file": task["task_file"], 
                                            "new_status": "done", "raw_content": raw}, headers=HEADERS)
    assert r.status_code == 400


@pytest.mark.parametrize("cfg_patch", [{"workspace_dir": "C:/"}, {"agents": [{"id": "<img>"}]}])
def test_bad_config_rejected_via_api(office, cfg_patch):
    cfg = office.get("/api/state").json()["config"]
    cfg.update(cfg_patch)
    assert office.post("/api/config", json=cfg, headers=HEADERS).status_code == 400


def test_config_roundtrip_keeps_agents(office):
    cfg = office.get("/api/state").json()["config"]
    assert office.post("/api/config", json=cfg, headers=HEADERS).status_code == 200
    assert set(office.get("/api/state").json()["agents"]) == {a["id"] for a in cfg["agents"]}
