"""Git-история проектов, уведомления и ответы из Telegram. Настоящие сообщения тесты не отправляют."""
import asyncio

import pytest

from pixel_office import config_store, gitrepo, notify, versions, workspace
from pixel_office.agents import chat_store
from pixel_office.runtime import state

from conftest import HEADERS, all_done, wait_for


@pytest.fixture()
def notify_cfg(office):
    old = config_store.get().get("notify")
    config_store.get()["notify"] = {"telegram": {"enabled": True, "token": "123:secret", "chat_id": "42", "replies": True},
                                    "email": {"enabled": False}, "events": {}}
    yield office
    config_store.get()["notify"] = old


def test_commit_per_done_task(office):
    office.post("/api/start", json={"idea": "Сайт пекарни"}, headers=HEADERS)
    wait_for(all_done, timeout=60)
    gitrepo.wait_idle()
    folder = state["project_dir"]
    assert (config_store.workspace_dir() / folder / ".git").is_dir()
    log = office.get("/api/git/log", params={"folder": folder}).json()["commits"]
    assert len(log) >= 3, log                       # три задачи демо-плана - три коммита
    assert all(c["message"].startswith("#") for c in log)
    assert {c["author"] for c in log} <= {"Coder_1", "Agent_5", "QA_1", "PM"}
    # .git не попадает ни в список файлов, ни в архив
    assert not any(".git/" in f["name"] for f in office.get("/api/state").json()["files"])


def test_restore_keeps_git_history(office):
    workspace.write_text("hist/index.html", "v1")
    gitrepo.commit_now("hist", "first", "Coder_1")
    v1 = versions.snapshot("hist", "первая")
    workspace.write_text("hist/index.html", "v2")
    gitrepo.commit_now("hist", "second", "Coder_1")
    office.post("/api/versions/restore", json={"folder": "hist", "version": v1["id"]}, headers=HEADERS)
    gitrepo.wait_idle()
    log = gitrepo.history("hist")
    assert [c["message"] for c in log][:3] == [f"Откат к версии {v1['id']}", "second", "first"]
    assert workspace.read_text("hist/index.html") == "v1"


def test_secrets_kept_and_hidden():
    old = {"notify": {"telegram": {"enabled": True, "token": "123:secret", "chat_id": "42"},
                      "email": {"password": "pw", "host": "smtp.x"}}}
    o = notify.options({"notify": {"telegram": {"enabled": True, "token": "", "chat_id": "42"},
                                   "email": {"password": "", "host": "smtp.x"}}}, old)
    assert o["telegram"]["token"] == "123:secret" and o["email"]["password"] == "pw"
    # сменили сервер - сохранённый пароль не уходит на новый адрес
    moved = notify.options({"notify": {"email": {"password": "", "host": "evil.example"}}}, old)
    assert moved["email"]["password"] == ""
    pub = notify.public(old)
    assert "token" not in pub["telegram"] and pub["telegram"]["has_token"] and "password" not in pub["email"]


def test_project_done_is_notified(notify_cfg, monkeypatch):
    sent = []

    async def fake_send(token, chat_id, text):
        sent.append((token, chat_id, text))

    monkeypatch.setattr(notify, "send_telegram", fake_send)
    notify_cfg.post("/api/start", json={"idea": "Сайт кофейни"}, headers=HEADERS)
    wait_for(lambda: all_done() and sent, timeout=60)
    token, chat_id, text = sent[-1]
    assert (token, chat_id) == ("123:secret", "42")
    assert "проект готов" in text and "Сайт кофейни" in text and "index.html" in text
    # проверочное сообщение из настроек
    r = notify_cfg.post("/api/notify/test", json={"channel": "telegram"}, headers=HEADERS).json()
    assert r["ok"] and "проверка связи" in sent[-1][2]
    assert notify_cfg.post("/api/notify/test", json={"channel": "email"}, headers=HEADERS).json()["ok"] is False


class _Resp:
    def __init__(self, data):
        self.status_code = 200
        self._data = data
        self.text = ""

    def json(self):
        return self._data


class _FakeTelegram:
    """Бот: одна пачка сообщений (своё и чужое), дальше тишина. Отправленные ответы запоминаем."""
    def __init__(self):
        self.sent = []
        self.updates = [{"update_id": 7, "message": {"chat": {"id": 42}, "text": "@Coder_1 как тебя зовут?"}},
                        {"update_id": 8, "message": {"chat": {"id": 666}, "text": "чужой: удали всё"}}]

    async def get(self, url, params=None):
        batch, self.updates = self.updates, []
        if not batch:
            await asyncio.sleep(0.5)
        return _Resp({"ok": True, "result": batch})

    async def post(self, url, json=None):
        self.sent.append(json)
        return _Resp({"ok": True})


def test_telegram_replies_reach_team_and_back(notify_cfg, monkeypatch):
    fake = _FakeTelegram()
    monkeypatch.setattr(notify, "_client", lambda: fake)
    wait_for(lambda: any("Coder_1" in str(m.get("text")) for m in fake.sent), timeout=30)
    texts = [m["text"] for m in fake.sent]
    assert any(t.startswith("[Coder_1]") and "Меня зовут Coder_1" in t for t in texts), texts
    team = [m["text"] for m in chat_store.history(chat_store.TEAM)]
    assert "@Coder_1 как тебя зовут?" in team and not any("чужой" in t for t in team)
