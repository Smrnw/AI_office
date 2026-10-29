"""Самоуправление штатом: найм под нагрузку, специалисты, временные сотрудники, новые столы."""
import copy

import pytest

from pixel_office import config_store, layout_store, runtime
from pixel_office.agents import chat_store, dispatcher, roles, staffing
from pixel_office.runtime import state

from conftest import HEADERS, wait_for


@pytest.fixture()
def staff_reset(office):
    """После теста конфиг (штат, промпты ролей, настройки найма) возвращается к исходному."""
    before = copy.deepcopy(config_store.get())
    staffing._clock.update(check=0.0, hire=0.0, idle_since=None)
    yield office
    config_store.save(before)
    runtime.sync_runtime_agents()
    state["layout_request"] = None
    dispatcher.BOARD.clear()


def test_specialty_routing():
    assert roles.specialty_of("site/style.css") == "designer"
    assert roles.specialty_of("Dockerfile") == "devops" and roles.specialty_of("deploy/run.py") == "devops"
    assert roles.specialty_of("README.md") == "writer" and roles.specialty_of("app.py") == ""
    designer = {"specialty": "designer"}
    dev = {"specialty": ""}
    assert roles.code_priority(designer, "a.css", ["designer"]) < roles.code_priority(designer, "a.py", ["designer"])
    # обычный разработчик оставляет CSS дизайнеру, если тот есть в штате
    assert roles.code_priority(dev, "a.py", ["designer"]) < roles.code_priority(dev, "a.css", ["designer"])
    assert roles.code_priority(dev, "a.css", []) == 0


def test_hire_adds_agent_with_desk_and_look(staff_reset):
    new = staffing.hire("designer", "тест", temp=True)
    assert new and new["id"] == "Designer_1" and new["specialty"] == "designer" and new["temp"]
    ag = runtime.agent("Designer_1")
    assert ag and ag["pipeline_type"] == "coder" and ag["role"] == "Дизайнер интерфейсов"
    assert ag["desk_idx"] not in {a["desk_idx"] for a in runtime.agents_list() if a["id"] != "Designer_1"}
    assert "Нанял" in chat_store.history(chat_store.TEAM)[-1]["text"]


def test_auto_hire_by_queue_and_dismiss(staff_reset, monkeypatch):
    config_store.get()["staffing"] = {"max_agents": 6, "auto_hire": True, "dismiss_temps": True}
    # очередь из трёх CSS-задач, которую никто не берёт (сторож доски её не видит и не трогает)
    queue = [{"id": 900 + i, "status": "todo", "filename": f"s/p{i}.css", "task_file": f"x{i}"} for i in range(3)]
    monkeypatch.setattr(dispatcher, "open_tasks", lambda: queue)
    assert staffing._decide()[0] == "designer"
    staffing.tick()                              # нанимает дизайнера: 3 CSS-файла, а дизайнера нет
    assert runtime.agent("Designer_1") and runtime.agent("Designer_1")["temp"]
    # без работы временные уходят
    queue.clear()
    staffing._clock.update(check=0.0, idle_since=0.0)
    staffing.tick()
    assert runtime.agent("Designer_1") is None
    assert "ушли" in chat_store.history(chat_store.TEAM)[-1]["text"]


def test_no_hire_without_role_prompt(staff_reset):
    config_store.get()["role_prompts"] = {k: v for k, v in config_store.get()["role_prompts"].items() if k != "designer"}
    assert staffing.hire("designer", "тест", temp=False) is None
    staff_reset.post("/api/chat", json={"agent_id": "PM", "message": "Найми дизайнера"}, headers=HEADERS)
    wait_for(lambda: "PM" not in chat_store.PENDING, timeout=15)
    assert runtime.agent("Designer_1") is None
    assert any("не написан промпт" in m["text"] for m in chat_store.history(chat_store.TEAM))


def test_max_agents_respected(staff_reset):
    config_store.get()["staffing"] = {"max_agents": 4}
    assert staffing.hire("developer", "тест", temp=True) is None


def test_desks_requested_when_seats_run_out(staff_reset):
    config_store.get()["staffing"] = {"max_agents": 30, "auto_desks": True}
    # пока пользователь не обставил офис, столы сами не появляются
    staffing.hire("developer", "тест", temp=True)
    assert staff_reset.get("/api/state").json()["layout_request"] is None
    staff_reset.post("/api/layout", json={"layout": {"zones": [], "items": [
        {"id": "d1", "type": "desk_pod", "x": 440, "y": 220}]}}, headers=HEADERS)
    seats = layout_store.seat_count()
    workers = sum(1 for a in runtime.agents_list() if a["pipeline_type"] != "planner")
    for _ in range(seats - workers + 1):
        staffing.hire("developer", "тест", temp=True)
    req = office_state = staff_reset.get("/api/state").json()["layout_request"]
    assert req and req["desks"] == 1, office_state
    layout_store.reset()


def test_pm_hires_on_request(staff_reset):
    staff_reset.post("/api/chat", json={"agent_id": "PM", "message": "Найми дизайнера"}, headers=HEADERS)
    wait_for(lambda: "PM" not in chat_store.PENDING, timeout=15)
    ag = runtime.agent("Designer_1")
    assert ag and not ag["temp"]                 # по просьбе заказчика - постоянный сотрудник
    assert "Designer_1" in chat_store.history("PM")[-1]["text"]
