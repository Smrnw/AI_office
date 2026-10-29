"""Промпты ролей пишет пользователь, мастер настройки собирает офис без готовых команды и планировки."""
import copy

import pytest

from pixel_office import config_store, defaults, layout_store, runtime, setup_wizard
from pixel_office.agents import dispatcher, roles

from conftest import HEADERS


@pytest.fixture()
def restore_config(office):
    before = copy.deepcopy(config_store.get())
    yield office
    config_store.save(before)
    runtime.sync_runtime_agents()


def test_no_builtin_prompts():
    assert all("prompt" not in r for r in roles.ROLES.values())
    assert roles.prompt_for("qa", {}) == ""
    assert defaults.default_config()["agents"] == []


def test_empty_prompt_uses_role_prompt(restore_config):
    cfg = config_store.get()
    qa = {"id": "QA_1", "role": "Тестировщик", "pipeline_type": "qa", "prompt": ""}
    cfg["role_prompts"] = {"qa": "Ты строгий QA, проверяешь всё дважды."}
    assert "проверяешь всё дважды" in dispatcher.work_prompt(qa, "review")
    assert roles.system_prompt({**qa, "prompt": "Мой промпт"}, cfg) == "Мой промпт"     # свой важнее ролевого
    designer = {"id": "D", "pipeline_type": "coder", "specialty": "designer", "prompt": ""}
    assert roles.system_prompt(designer, cfg) == ""


def test_agent_without_any_prompt_cannot_be_saved(restore_config):
    cfg = copy.deepcopy(config_store.get())
    cfg["role_prompts"] = {}
    r = restore_config.post("/api/config", json=cfg, headers=HEADERS)
    assert r.status_code == 400 and "Без системного промпта" in r.json()["detail"]
    cfg["agents"] = [{**a, "prompt": f"Я {a['id']}."} for a in cfg["agents"]]
    assert restore_config.post("/api/config", json=cfg, headers=HEADERS).status_code == 200


def test_role_prompts_validated_and_public(restore_config):
    assert roles.validate_prompts({"qa": "  новый  ", "hacker": "x", "writer": ""}) == {"qa": "новый"}
    pub = restore_config.get("/api/state").json()["config"]
    assert set(pub["role_defaults"]) == set(roles.ORDER) and "prompt" not in pub["role_defaults"]["planner"]


def test_fresh_office_needs_setup():
    assert setup_wizard.needs_setup(defaults.default_config())
    assert not setup_wizard.needs_setup({"agents": [{"id": "PM"}]})
    assert not setup_wizard.needs_setup({"agents": [], "setup_done": True})


ANSWERS = {
    "office_name": "Студия Альфа", "language": "ru",
    "provider": {"template": "openai", "api_key": "sk-test", "model_id": "gpt-test"},
    "team": {"developer": 2, "qa": 1, "designer": 1, "devops": 0, "writer": 0, "security": 0},
    "role_prompts": {"planner": "Ты руководитель.", "developer": "Пиши на TypeScript.", "qa": "Проверяй всё.",
                     "designer": "Делай красиво.", "writer": "этот промпт есть, но писателей не нанимают"},
    "options": {"checks": False, "auto_hire": False},
}


def test_wizard_requires_prompts_for_hired_roles(restore_config):
    answers = copy.deepcopy(ANSWERS)
    del answers["role_prompts"]["designer"]
    del answers["role_prompts"]["planner"]
    r = restore_config.post("/api/setup", json=answers, headers=HEADERS)
    assert r.status_code == 400
    assert "Руководитель проекта" in r.json()["detail"] and "Дизайнер интерфейсов" in r.json()["detail"]
    assert config_store.get().get("office_name") != "Студия Альфа"          # ничего не сохранилось


def test_wizard_builds_office_without_layout(restore_config):
    layout_store.reset()
    r = restore_config.post("/api/setup", json=ANSWERS, headers=HEADERS).json()
    assert r["ok"]
    cfg = config_store.get()
    ids = [a["id"] for a in cfg["agents"]]
    assert ids == ["PM", "Coder_1", "Coder_2", "QA_1", "Designer_1"]
    assert cfg["setup_done"] and cfg["office_name"] == "Студия Альфа"
    assert [p["id"] for p in cfg["providers"]] == ["demo", "openai"] and cfg["providers"][1]["api_key"] == "sk-test"
    assert all(a["model_ref"] == "main" and a["prompt"] == "" for a in cfg["agents"])
    assert cfg["role_prompts"]["developer"] == "Пиши на TypeScript."
    assert "TypeScript" in dispatcher.work_prompt(runtime.agent("Coder_1"), "code")
    # планировку пользователь делает сам: офис пустой, столы сами не ставятся
    assert layout_store.get() is None and restore_config.get("/api/state").json()["layout_request"] is None
    assert "sk-test" not in str(restore_config.get("/api/state").json())


def test_wizard_rejects_bad_folder(restore_config):
    r = restore_config.post("/api/setup", json={**ANSWERS, "workspace_dir": "relative/path"}, headers=HEADERS)
    assert r.status_code == 400


def test_wizard_ping(restore_config):
    assert restore_config.post("/api/setup/test", json={"template": "demo"}, headers=HEADERS).json() == {"ok": True, "reply": "OK"}
    bad = restore_config.post("/api/setup/test", json={"template": "gemini", "api_key": ""}, headers=HEADERS).json()
    assert bad["ok"] is False and "ключ" in bad["error"]
