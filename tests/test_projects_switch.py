"""Возврат к любому проекту и обещания агентов, которые обязаны превращаться в задачи."""
import json

from pixel_office import tasks_store, workspace
from pixel_office.agents import chat, chat_store, workflow
from pixel_office.runtime import state

from conftest import HEADERS, all_done, wait_for


def _two_projects():
    workflow.save_project_idea("Сайт банка", "bank")
    workspace.write_text("bank/index.html", "<p>bank</p>")
    workflow.save_project_idea("Рекламная страница", "reklama")
    workspace.write_text("reklama/promo.html", "<p>promo</p>")
    workspace.write_text("manual/notes.txt", "положили руками")


def test_projects_listed_and_selected(office):
    _two_projects()
    projects = {p["folder"]: p for p in office.get("/api/state").json()["projects"]}
    assert projects["bank"]["idea"] == "Сайт банка" and projects["reklama"]["current"]
    assert projects["manual"]["idea"] == "manual"            # папка без истории - называется по имени
    r = office.post("/api/project/select", json={"folder": "bank"}, headers=HEADERS)
    assert r.status_code == 200 and state["project_dir"] == "bank" and state["project_idea"] == "Сайт банка"
    assert office.post("/api/project/select", json={"folder": "../etc"}, headers=HEADERS).status_code == 404
    # новые файлы доработок идут в выбранный проект
    created = workflow.create_revision_tasks(state["agents_runtime"]["Coder_1"], [{"filename": "about.html", "spec": "о банке"}], "добавь")
    assert created[0]["filename"] == "bank/about.html"
    wait_for(all_done, timeout=30)


def test_agent_switches_project_from_chat(office):
    _two_projects()
    office.post("/api/chat", json={"agent_id": "Coder_1", "message": "Перейди к проекту bank"}, headers=HEADERS)
    wait_for(lambda: "Coder_1" not in chat_store.PENDING, timeout=15)
    assert state["project_dir"] == "bank"
    assert "bank" in chat_store.history("Coder_1")[-1]["text"]


def test_promise_without_task_is_asked_again(office, monkeypatch):
    calls = []

    async def fake_llm(model_ref, system, user, json_mode=False, purpose="", meta=None, image=None):
        calls.append(meta or {})
        if not (meta or {}).get("promise_fix"):
            return json.dumps({"reply": "Поручу это Coder_1, он возьмёт в работу.", "tasks": []}, ensure_ascii=False)
        return json.dumps({"reply": "Завёл задачу.", "tasks": {"title": "Кнопка", "filename": "index.html",
                                                               "spec": "Сделать кнопку синей"}}, ensure_ascii=False)

    monkeypatch.setattr(chat, "call_llm", fake_llm)
    state["project_dir"] = ""
    office.post("/api/chat", json={"agent_id": "PM", "message": "Поручи"}, headers=HEADERS)
    wait_for(lambda: "PM" not in chat_store.PENDING, timeout=15)
    assert len(calls) == 2 and calls[1]["promise_fix"]
    assert chat_store.history("PM")[-1]["tasks"], "обещанная задача должна появиться"
    assert any(t["title"] == "Кнопка" for t in tasks_store.scan_all())
    wait_for(all_done, timeout=30)


def test_honest_reply_is_not_asked_again(office, monkeypatch):
    calls = []

    async def fake_llm(*args, **kwargs):
        calls.append(1)
        return json.dumps({"reply": "Уточните, пожалуйста, что именно поменять?", "tasks": []}, ensure_ascii=False)

    monkeypatch.setattr(chat, "call_llm", fake_llm)
    office.post("/api/chat", json={"agent_id": "PM", "message": "Поручи"}, headers=HEADERS)
    wait_for(lambda: "PM" not in chat_store.PENDING, timeout=15)
    assert len(calls) == 1
