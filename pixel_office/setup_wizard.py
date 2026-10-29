"""Мастер первоначальной настройки: собирает config.json из ответов пользователя.

Демо-провайдер остаётся всегда, чтобы офис работал и без ключей. Сотрудники создаются
с пустым промптом и работают по шаблонам ролей.
"""
import random
from typing import Any, Dict, List

from . import config_store, runtime
from .agents import roles, staffing
from .defaults import DEMO_MODEL, DEMO_PROVIDER, PROVIDER_TEMPLATES, SETUP_HINTS

MAX_PER_ROLE = 6
PROVIDER_IDS = ("demo", "gemini", "anthropic", "openai", "openrouter", "ollama", "custom")


def needs_setup(cfg: Dict[str, Any]) -> bool:
    """Офис ещё не настраивали: нет ни штата, ни отметки о пройденной настройке."""
    return not cfg.get("setup_done") and not cfg.get("agents")


def provider_from(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Провайдер из ответа мастера: шаблон + ключ, адрес и модель, которые ввёл человек."""
    kind = raw.get("template") if raw.get("template") in PROVIDER_IDS else "demo"
    if kind == "demo":
        return {"provider": dict(DEMO_PROVIDER), "model": dict(DEMO_MODEL)}
    tpl = next((p for p in PROVIDER_TEMPLATES if p["id"] == kind), None) or \
        {"id": "custom", "name": "Свой провайдер", "api_type": "openai_compatible", "base_url": ""}
    url = str(raw.get("base_url") or tpl.get("base_url") or SETUP_HINTS[kind]["base_url"]).strip()
    model_id = str(raw.get("model_id") or SETUP_HINTS[kind]["model_id"]).strip()
    provider = {**tpl, "id": tpl["id"], "api_key": str(raw.get("api_key") or "").strip(), "base_url": url}
    model = {"id": "main", "name": model_id or "Основная модель", "provider": provider["id"],
             "model_id": model_id, "token_limit": 1_000_000}
    return {"provider": provider, "model": model}


def build_team(team: Dict[str, Any], model_ref: str) -> List[Dict[str, Any]]:
    """Руководитель всегда один, остальных - сколько выбрали (до MAX_PER_ROLE каждой роли)."""
    rnd = random.Random()
    agents: List[Dict[str, Any]] = []
    for kind in roles.ORDER:
        try:
            count = 1 if kind == "planner" else max(0, min(MAX_PER_ROLE, int(team.get(kind) or 0)))
        except (TypeError, ValueError):
            count = 0
        role = roles.ROLES[kind]
        for i in range(count):
            name = "PM" if kind == "planner" else f"{role['prefix']}_{i + 1}"
            agents.append({
                "id": name, "tag": role["tag"], "role": role["title"], "pipeline_type": role["type"],
                "specialty": role["specialty"], "model_ref": model_ref, "desk_idx": 0 if kind == "planner" else len(agents),
                "shirt": rnd.choice(staffing.SHIRTS), "hair": rnd.choice(staffing.HAIRS), "pants": "",
                "skin": rnd.randrange(6), "hair_style": rnd.choice(staffing.HAIR_STYLES), "outfit": role["outfit"],
                "accessory": rnd.choice(["none", "none", "glasses", "headphones"]), "prompt": "", "temp": False,
            })
    return agents


def apply(answers: Dict[str, Any]) -> Dict[str, Any]:
    """Сохраняет конфиг по ответам мастера. ConfigError - если, например, папка указана неверно."""
    old = config_store.get()
    chosen = provider_from(answers.get("provider") if isinstance(answers.get("provider"), dict) else {})
    providers = [dict(DEMO_PROVIDER)] + ([chosen["provider"]] if chosen["provider"]["id"] != "demo" else [])
    models = [dict(DEMO_MODEL)] + ([chosen["model"]] if chosen["model"]["id"] != "demo" else [])
    team = answers.get("team") if isinstance(answers.get("team"), dict) else {}
    prompts = roles.validate_prompts(answers.get("role_prompts"))
    agents = build_team(team, chosen["model"]["id"])
    # готовых промптов нет: каждая роль, на которую кого-то нанимают, должна быть описана пользователем
    missing = [roles.ROLES[k]["title"] for k in roles.ORDER
               if any(roles.kind_of(a) == k for a in agents) and not prompts.get(k)]
    if missing:
        raise config_store.ConfigError("Напишите промпт для ролей: " + ", ".join(missing))
    new = {
        **old,
        "workspace_dir": str(answers.get("workspace_dir") or "").strip(),
        "tasks_dir": str(answers.get("tasks_dir") or "").strip(),
        "providers": providers, "models": models, "agents": agents,
        "role_prompts": prompts,
    }
    opts = answers.get("options") if isinstance(answers.get("options"), dict) else {}
    if isinstance(opts.get("checks"), bool):
        new["checks"] = {**(old.get("checks") or {}), "enabled": opts["checks"]}
    if isinstance(opts.get("auto_hire"), bool):
        new["staffing"] = {**(old.get("staffing") or {}), "auto_hire": opts["auto_hire"]}
    clean = config_store.validate_config(new, old)
    clean["setup_done"] = True
    config_store.save(clean)
    config_store.set_office_name(answers.get("office_name") or "")
    if answers.get("language") in config_store.LANGUAGES:
        config_store.set_language(answers["language"])
    runtime.sync_runtime_agents()
    staffing.ensure_desks()
    runtime.add_log(f"🧭 Офис настроен: {config_store.office_name()}, сотрудников {len(clean['agents'])}, "
                    f"нейросеть {chosen['model']['name']}")
    return {"ok": True, "agents": [a["id"] for a in clean["agents"]]}
