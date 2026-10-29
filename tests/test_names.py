"""Агенты знают своё имя и откликаются, когда к ним обращаются в общем канале."""
from pixel_office import settings
from pixel_office.agents import chat as chat_mod
from pixel_office.agents import chat_store

from conftest import HEADERS, all_done, wait_for

TEAM = settings.TEAM_CHANNEL


def test_addressed_agents_parsing(client):
    f = chat_mod.addressed_agents
    assert f("@Coder_1 почини кнопку") == ["Coder_1"]
    assert f("coder_1, как дела?") == ["Coder_1"]                    # регистр не важен
    assert f("QA_1: проверь форму") == ["QA_1"]
    assert sorted(f("@PM и @QA_1, посмотрите")) == ["PM", "QA_1"]
    assert f("Сделай кнопку как у Coder_1") == []                      # имя в середине без @ - не обращение
    assert f("email@Coder_1x.ru") == []                                # часть другого слова не считается


def test_named_agent_answers_in_team_channel(office):
    office.post("/api/start", json={"idea": "Страница"}, headers=HEADERS)
    wait_for(all_done, timeout=30)
    r = office.post("/api/chat", json={"agent_id": TEAM, "message": "@QA_1 как тебя зовут?"}, headers=HEADERS).json()
    assert r == {"ok": True, "to": ["QA_1"]}
    wait_for(lambda: TEAM not in chat_store.PENDING, timeout=10)
    msgs = chat_store.history(TEAM)
    assert msgs[-2]["role"] == "user" and msgs[-2]["to"] == ["QA_1"]
    assert msgs[-1]["author"] == "QA_1" and "Меня зовут QA_1" in msgs[-1]["text"]


def test_named_agents_answer_without_starting_project(office):
    r = office.post("/api/chat", json={"agent_id": TEAM, "message": "Coder_1, привет! @Agent_5 ты тут?"}, headers=HEADERS).json()
    assert r["to"] == ["Coder_1", "Agent_5"] or sorted(r["to"]) == ["Agent_5", "Coder_1"]
    wait_for(lambda: TEAM not in chat_store.PENDING, timeout=10)
    authors = [m["author"] for m in chat_store.history(TEAM) if m["role"] == "agent"]
    assert set(authors) == {"Coder_1", "Agent_5"}
    assert all(t != "PM" for t in authors)


def test_agent_knows_its_name_and_team(office, monkeypatch):
    seen = {}

    async def fake_llm(model_ref, system, user, **kw):
        seen["system"] = system
        return '{"reply": "ok", "tasks": []}'
    monkeypatch.setattr(chat_mod, "call_llm", fake_llm)
    office.post("/api/chat", json={"agent_id": "Agent_5", "message": "привет"}, headers=HEADERS)
    wait_for(lambda: "system" in seen, timeout=5)
    assert "Тебя зовут Agent_5" in seen["system"]
    assert "Coder_1" in seen["system"] and "QA_1" in seen["system"]    # знает коллег
