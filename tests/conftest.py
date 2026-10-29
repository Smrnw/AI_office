"""Тесты работают в отдельной временной папке данных и с демо-провайдером без сети."""
import os
import shutil
import stat
import sys
import tempfile
import time
from pathlib import Path

import pytest

_DATA = Path(tempfile.mkdtemp(prefix="pixel_office_tests_"))
os.environ["PIXEL_OFFICE_DIR"] = str(_DATA)
os.environ.pop("PIXEL_OFFICE_TOKEN", None)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient  # noqa: E402

from pixel_office import config_store, gitrepo, settings, tasks_store  # noqa: E402
from pixel_office.agents import chat_store, dispatcher  # noqa: E402
from pixel_office.llm import demo  # noqa: E402
from pixel_office.main import app  # noqa: E402
from pixel_office.runtime import state  # noqa: E402

demo.DEMO_DELAY = (0.02, 0.05)
# новый офис пустой: штат, промпты и планировку пользователь создаёт сам. Тестам нужна готовая команда
TEST_AGENTS = [
    {"id": "PM", "tag": "PM", "role": "Руководитель проекта", "pipeline_type": "planner", "model_ref": "demo",
     "desk_idx": 0, "shirt": "#c0392b", "hair": "#2b1d14", "skin": 1, "hair_style": "side", "outfit": "suit", "prompt": ""},
    {"id": "Coder_1", "tag": "coder", "role": "Senior-разработчик", "pipeline_type": "coder", "model_ref": "demo",
     "desk_idx": 1, "shirt": "#16a34a", "hair": "#1f1410", "skin": 4, "hair_style": "short", "outfit": "hoodie", "prompt": ""},
    {"id": "QA_1", "tag": "qa", "role": "Тестировщик", "pipeline_type": "qa", "model_ref": "demo",
     "desk_idx": 2, "shirt": "#9333ea", "hair": "#e8c46a", "skin": 0, "hair_style": "long", "outfit": "sweater", "prompt": ""},
    {"id": "Agent_5", "tag": "dev", "role": "Разработчик", "pipeline_type": "coder", "model_ref": "demo",
     "desk_idx": 4, "shirt": "#22a35a", "hair": "#1f1410", "skin": 5, "hair_style": "curly", "outfit": "tshirt", "prompt": ""},
]
TEST_PROMPTS = {k: f"Тестовый промпт роли {k}." for k in
                ("planner", "developer", "qa", "designer", "devops", "writer", "security")}
config_store.get().update(agents=TEST_AGENTS, role_prompts=TEST_PROMPTS, setup_done=True)
# полная автопроверка открывает браузер и запускает тесты: включаем её только в тестах проверки
config_store.get()["checks"] = {"enabled": False}
# автонайм менял бы штат посреди чужих тестов: включаем его только в тестах самоуправления
config_store.get()["staffing"] = {"auto_hire": False, "dismiss_temps": False, "auto_desks": False}
HEADERS = {"X-Requested-With": "pixel-office"}


@pytest.fixture(scope="session")
def data_dir():
    yield _DATA
    shutil.rmtree(_DATA, ignore_errors=True)


@pytest.fixture(scope="session")
def client(data_dir):
    with TestClient(app, base_url="http://localhost") as c:
        yield c


@pytest.fixture()
def office(client):
    """Чистый офис перед тестом: пустая доска, рабочая папка и чаты."""
    client.post("/api/reset", headers=HEADERS)
    wait_for(lambda: not dispatcher.dispatcher_alive() and state["jobs"] == 0, timeout=10)
    gitrepo.wait_idle()                     # коммиты пишет фоновый поток - пусть допишет до уборки
    ws = config_store.workspace_dir()
    for p in ws.iterdir():
        shutil.rmtree(p, onexc=_force_remove) if p.is_dir() else p.unlink()
    chat_store.CHATS.clear()
    chat_store.PENDING.clear()
    state["paused"] = False
    state["cancel_requested"] = False
    state["dispatch_error"] = ""
    yield client


def _force_remove(func, path, _exc):
    """Git хранит объекты только для чтения: снимаем флаг и удаляем ещё раз."""
    os.chmod(path, stat.S_IWRITE)
    func(path)


def wait_for(cond, timeout=15.0, step=0.05):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(step)
    raise AssertionError("Условие не выполнилось за отведённое время")


def all_done():
    tasks = tasks_store.scan_all()
    return bool(tasks) and all(t["status"] == "done" for t in tasks) and state["jobs"] == 0


__all__ = ["HEADERS", "wait_for", "all_done", "settings"]
