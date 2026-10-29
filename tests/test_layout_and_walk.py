"""Планировка офиса, «агент сначала садится за стол», скачивание файлов из чата, чат без системных сообщений."""
import threading
import time

import pytest

from pixel_office import layout_store, settings, tasks_store, workspace
from pixel_office.agents import chat_store, dispatcher
from pixel_office.runtime import state

from conftest import HEADERS, all_done, wait_for

TEAM = settings.TEAM_CHANNEL
VIEWER = {"X-Office-Viewer": "1"}


def _layout(**over):
    base = {"zones": [{"id": "z1", "label": "Кабинет", "x": 20, "y": 152, "w": 300, "h": 200, "style": "rug_red",
                       "walls": True, "door": "east"}],
            "items": [{"id": "d1", "type": "desk_pod", "x": 404, "y": 210}, {"id": "b1", "type": "boss_desk", "x": 100, "y": 260}]}
    base.update(over)
    return base


# ---------- планировка ----------

def test_layout_roundtrip(client):
    assert client.post("/api/layout", json={"layout": _layout()}, headers=HEADERS).status_code == 200
    got = client.get("/api/layout").json()
    assert [i["type"] for i in got["layout"]["items"]] == ["desk_pod", "boss_desk"]
    assert got["rev"] == client.get("/api/state").json()["layout_rev"]
    layout_store.reset()


@pytest.mark.parametrize("bad", [
    _layout(items=[{"id": "x", "type": "rocket", "x": 1, "y": 200}]),
    _layout(items=[{"id": "x", "type": "plant", "x": 1e9, "y": 200}]),
    _layout(items=[{"id": "../x", "type": "plant", "x": 1, "y": 200}]),
    _layout(items=[{"id": f"d{i}", "type": "plant", "x": 10, "y": 200} for i in range(201)]),
    _layout(zones=[{"id": "z", "x": 0, "y": 160, "w": 5, "h": 100}]),
    {"items": "нет"},
])
def test_layout_validation(client, bad):
    assert client.post("/api/layout", json={"layout": bad}, headers=HEADERS).status_code == 400


def test_any_number_of_desks_allowed(client):
    many = _layout(items=[{"id": f"d{i}", "type": "desk_pod", "x": 10 + i, "y": 200} for i in range(40)])
    assert client.post("/api/layout", json={"layout": many}, headers=HEADERS).status_code == 200
    layout_store.reset()


def test_zone_description_reaches_agents(office, monkeypatch):
    lay = _layout()
    lay["zones"][0].update(description="Здесь руководитель проводит планёрки", activity="meeting",
                           roles=["planner", "hacker"])
    assert office.post("/api/layout", json={"layout": lay}, headers=HEADERS).status_code == 200
    z = layout_store.get()["zones"][0]
    assert z["roles"] == ["planner"] and z["activity"] == "meeting"
    brief = layout_store.office_brief()
    assert "Кабинет (обсуждения; доступ: руководитель): Здесь руководитель проводит планёрки" in brief

    from pixel_office.agents import chat as chat_mod
    seen = {}

    async def fake_llm(model_ref, system, user, **kw):
        seen["prompt"] = user
        return '{"reply": "ok", "tasks": []}'
    monkeypatch.setattr(chat_mod, "call_llm", fake_llm)
    office.post("/api/chat", json={"agent_id": "Coder_1", "message": "Где у нас проходят планёрки?"}, headers=HEADERS)
    wait_for(lambda: "prompt" in seen, timeout=5)
    assert "Здесь руководитель проводит планёрки" in seen["prompt"]
    layout_store.reset()


def test_new_office_is_empty():
    layout_store.reset()
    assert layout_store.get() is None and layout_store.seat_count() == 0
    assert "не обставлен" in layout_store.office_brief()


def test_layout_sanitizes_strings(client):
    lay = _layout()
    lay["zones"][0].update(label="<script>alert(1)</script>" * 3, style="evil", door="up")
    client.post("/api/layout", json={"layout": lay}, headers=HEADERS)
    z = layout_store.get()["zones"][0]
    assert len(z["label"]) <= 24 and z["style"] == "none" and z["door"] == "east"
    layout_store.reset()


# ---------- агент работает только за столом ----------

def test_work_waits_until_agent_is_at_desk(office, monkeypatch):
    monkeypatch.setattr(dispatcher, "WALK_TIMEOUT", 30.0)
    office.get("/api/state", headers=VIEWER)          # офис открыт во вкладке
    stop = threading.Event()

    def keep_viewing():
        while not stop.is_set():
            office.get("/api/state", headers=VIEWER)
            time.sleep(0.5)
    threading.Thread(target=keep_viewing, daemon=True).start()
    try:
        office.post("/api/start", json={"idea": "Страница"}, headers=HEADERS)
        wait_for(lambda: state["agents_runtime"]["PM"]["status"] == "Идёт", timeout=5)
        time.sleep(1.0)
        assert not tasks_store.scan_all(), "PM начал планировать, не дойдя до стола"
        office.post("/api/agent/arrived", json={"agent_id": "PM"}, headers=HEADERS)
        wait_for(lambda: tasks_store.scan_all(), timeout=10)
        # кодеры тоже ждут: задача не уходит в работу, пока агент не сел
        wait_for(lambda: any(a["status"] == "Идёт" for n, a in state["agents_runtime"].items() if n != "PM"), timeout=5)
        time.sleep(0.8)
        assert not any(t["status"] == "in_progress" for t in tasks_store.scan_all())

        def arrive_all():
            for name, a in state["agents_runtime"].items():
                if a["status"] == "Идёт":
                    office.post("/api/agent/arrived", json={"agent_id": name}, headers=HEADERS)
            return all_done()
        wait_for(arrive_all, timeout=40, step=0.2)
    finally:
        stop.set()
        state["viewer_seen_at"] = 0.0


def test_without_viewer_agents_do_not_wait(office):
    state["viewer_seen_at"] = 0.0
    office.post("/api/start", json={"idea": "Страница"}, headers=HEADERS)
    wait_for(all_done, timeout=30)


# ---------- чат и файлы ----------

def test_chat_has_only_people_and_agents(office):
    office.post("/api/chat", json={"agent_id": TEAM, "message": "Сделай страницу"}, headers=HEADERS)
    wait_for(all_done, timeout=30)
    msgs = chat_store.history(TEAM)
    assert msgs and {m["role"] for m in msgs} <= {"user", "agent"}
    final = msgs[-1]
    assert final["author"] == "PM" and len(final["tasks"]) == 3     # итог проекта со списком файлов


def test_file_download(office):
    workspace.write_text("site/index.html", "<h1>ok</h1>")
    r = office.get("/api/file/download", params={"name": "site/index.html"})
    assert r.status_code == 200 and r.content == b"<h1>ok</h1>"
    assert "attachment" in r.headers["content-disposition"]
    assert office.get("/api/file/download", params={"name": "../config.json"}).status_code == 400
    assert office.get("/api/file/download", params={"name": "nope.txt"}).status_code == 404
