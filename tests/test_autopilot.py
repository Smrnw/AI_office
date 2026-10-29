"""Автопилот: цель -> требования -> круги до достижения цели; ограничители; версии и откат."""
from pixel_office import config_store, versions, workspace
from pixel_office.agents import autopilot, chat_store
from pixel_office.runtime import state

from conftest import HEADERS, all_done, wait_for


def _finished():
    return autopilot.current().get("status") not in autopilot.ACTIVE and state["jobs"] == 0


def test_autopilot_reaches_goal(office):
    r = office.post("/api/chat", json={"agent_id": "__team__", "message": "/auto Лендинг для кофейни"}, headers=HEADERS)
    assert r.json()["ok"]
    wait_for(_finished, timeout=120)
    ap = office.get("/api/autopilot").json()
    assert ap["status"] == "done", ap
    assert ap["cycle"] == 2 and len(ap["requirements"]) == 3 and all(r["done"] for r in ap["requirements"])
    folder = ap["folder"]
    # перед каждым кругом сохранялась версия проекта
    assert len(versions.list_versions(folder)) == 2
    msgs = [m for m in chat_store.history(chat_store.TEAM) if m.get("autopilot")]
    assert msgs and "Цель достигнута" in msgs[-1]["text"]
    assert office.get("/api/state").json()["autopilot"]["status"] == "done"


def test_autopilot_stops_at_cycle_limit(office):
    old = config_store.get().get("autopilot")
    config_store.get()["autopilot"] = {"max_cycles": 1}
    try:
        workspace.write_text("cafe/index.html", "<!DOCTYPE html><title>x</title><p>Кафе</p>")
        office.post("/api/project/select", json={"folder": "cafe"}, headers=HEADERS)
        r = office.post("/api/autopilot/start", json={"goal": "Сайт кафе", "current_project": True}, headers=HEADERS)
        assert r.json()["ok"]
        assert office.post("/api/autopilot/start", json={"goal": "ещё", "current_project": True}, headers=HEADERS).json()["ok"] is False
        wait_for(_finished, timeout=120)
        ap = autopilot.current()
        assert ap["status"] == "limit" and "круги" in ap["reason"].lower(), ap
        assert ap["folder"] == "cafe"
    finally:
        config_store.get()["autopilot"] = old
    wait_for(all_done, timeout=30)


def test_versions_restore(office):
    workspace.write_text("site/index.html", "v1")
    v1 = versions.snapshot("site", "первая")
    workspace.write_text("site/index.html", "v2")
    workspace.write_text("site/extra.js", "x")
    r = office.post("/api/versions/restore", json={"folder": "site", "version": v1["id"]}, headers=HEADERS)
    assert r.json()["ok"]
    assert workspace.read_text("site/index.html") == "v1" and not workspace.safe_path("site/extra.js").exists()
    # состояние перед откатом тоже сохранено - откат можно отменить
    notes = [v["note"] for v in versions.list_versions("site")]
    assert any("перед откатом" in n for n in notes)
    bad = office.post("/api/versions/restore", json={"folder": "../x", "version": v1["id"]}, headers=HEADERS)
    assert bad.status_code == 404
    assert office.post("/api/versions/restore", json={"folder": "site", "version": "../../etc"}, headers=HEADERS).status_code == 404


def test_autopilot_options_validated():
    o = autopilot.options({"autopilot": {"max_cycles": 999, "max_tokens": "abc", "max_minutes": 1}})
    assert o["max_cycles"] == 20 and o["max_tokens"] == autopilot.DEFAULTS["max_tokens"] and o["max_minutes"] == 5
