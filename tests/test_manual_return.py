"""Задача, которую человек вернул на доске (кнопкой, перетаскиванием или прямо в папке), снова берётся в работу."""
import shutil

from pixel_office import config_store, tasks_store
from pixel_office.runtime import state

from conftest import HEADERS, all_done, wait_for


def _finished_project(office):
    office.post("/api/start", json={"idea": "Страница"}, headers=HEADERS)
    wait_for(all_done, timeout=30)
    return tasks_store.scan_all()[0]


def _picked_again(task_file, attempts_before):
    def check():
        t = next(t for t in tasks_store.scan_all() if t["task_file"] == task_file)
        return t["status"] == "done" and "попытка" in t["history"].split("Перемещено вручную")[-1] and state["jobs"] == 0
    return check


def test_returned_task_is_picked_after_stop(office):
    task = _finished_project(office)
    office.post("/api/stop", headers=HEADERS)            # возврат задачи должен снимать паузу
    assert state["paused"] is True
    r = office.post("/api/task/move", json={"task_file": task["task_file"], "new_status": "todo"}, headers=HEADERS)
    assert r.status_code == 200
    wait_for(_picked_again(task["task_file"], task["attempts"]), timeout=30)
    assert state["paused"] is False


def test_return_with_comment_reaches_coder(office):
    task = _finished_project(office)
    r = office.post("/api/task/move", json={"task_file": task["task_file"], "new_status": "todo",
                                            "comment": "Сделай кнопку красной"}, headers=HEADERS)
    assert r.status_code == 200
    wait_for(_picked_again(task["task_file"], task["attempts"]), timeout=30)
    t = next(t for t in tasks_store.scan_all() if t["task_file"] == task["task_file"])
    assert "Сделай кнопку красной" in t["history"]


def test_exhausted_attempts_are_reset_on_manual_return(office):
    task = _finished_project(office)
    path = tasks_store.find_task_path(task["task_file"])
    path.write_text(path.read_text(encoding="utf-8").replace(f"ATTEMPTS: {task['attempts']}", "ATTEMPTS: 6"), encoding="utf-8")
    office.post("/api/task/move", json={"task_file": task["task_file"], "new_status": "todo"}, headers=HEADERS)
    wait_for(_picked_again(task["task_file"], 0), timeout=30)
    t = next(t for t in tasks_store.scan_all() if t["task_file"] == task["task_file"])
    assert t["attempts"] <= 2


def test_task_moved_between_folders_on_disk_is_picked(office):
    task = _finished_project(office)
    root = config_store.tasks_dir()
    shutil.move(str(root / "done" / task["task_file"]), str(root / "todo" / task["task_file"]))
    wait_for(lambda: any(t["task_file"] == task["task_file"] and t["status"] != "todo" for t in tasks_store.scan_all()), timeout=15)
    wait_for(all_done, timeout=30)


def test_task_file_added_on_disk_is_picked(office):
    _finished_project(office)
    new = {"id": 777, "title": "Ручная задача", "filename": "extra.js", "status": "todo", "spec": "Скрипт",
           "attempts": 0, "qa_notes": "", "history": ""}
    path = config_store.tasks_dir() / "todo" / tasks_store.task_file_name(new)
    path.write_text(tasks_store.format_task_txt(new), encoding="utf-8")
    wait_for(lambda: (config_store.workspace_dir() / "extra.js").exists(), timeout=15)
    wait_for(all_done, timeout=30)


def test_each_agent_does_own_job(office):
    """Возвращённую задачу пишет разработчик, а проверяет только QA - не руководитель и не кодер."""
    from pixel_office.agents import dispatcher
    task = _finished_project(office)
    r = office.post("/api/task/move", json={"task_file": task["task_file"], "new_status": "todo"}, headers=HEADERS)
    assert r.status_code == 200
    wait_for(_picked_again(task["task_file"], task["attempts"]), timeout=30)
    t = next(t for t in tasks_store.scan_all() if t["task_file"] == task["task_file"])
    tail = t["history"].split("Перемещено вручную")[-1]
    assert "Агент PM" not in tail and "Агент QA_1" not in tail
    # прямая проверка выбора работы
    office.post("/api/stop", headers=HEADERS)
    wait_for(lambda: state["jobs"] == 0, timeout=10)
    probe = [{"id": 9001, "status": "todo", "task_file": "x1"}, {"id": 9002, "status": "testing", "task_file": "x2"}]
    dispatcher.BOARD.extend(probe)
    try:
        assert dispatcher.claim_job("PM") is None
        kind, got = dispatcher.claim_job("Coder_1")
        assert (kind, got["id"]) == ("code", 9001)
        assert dispatcher.claim_job("Agent_5") is None      # проверка - не работа разработчика
        kind, got = dispatcher.claim_job("QA_1")
        assert (kind, got["id"]) == ("review", 9002)
    finally:
        for p in probe:
            dispatcher.BOARD.remove(p)
