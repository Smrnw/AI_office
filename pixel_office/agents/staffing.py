"""Автоматический найм и увольнение под нагрузку.

Сторож доски раз в несколько секунд вызывает tick(). Правила простые: очередь втрое больше
разработчиков - нанимаем разработчика; на проверке втрое больше задач, чем тестировщиков, - тестировщика;
два файла профиля без специалиста - специалиста. Такие сотрудники временные и уходят через
DISMISS_AFTER секунд без работы. Если сотрудников больше, чем столов, просим браузер поставить столы:
место и проходы считает JS-редактор планировки, второй реализации на сервере нет.
"""
import math
import random
import time
from typing import Any, Dict, List, Optional

from .. import config_store, layout_store, runtime
from ..runtime import STATUS_FREE, state
from . import chat_store, dispatcher, roles

DEFAULTS = {"auto_hire": True, "max_agents": 8, "auto_desks": True, "dismiss_temps": True}
CHECK_EVERY = 3.0
HIRE_COOLDOWN = 20.0
DISMISS_AFTER = 30.0
SHIRTS = ["#3b82f6", "#8b5cf6", "#ec4899", "#f59e0b", "#10b981", "#06b6d4", "#ef4444", "#84cc16", "#f97316", "#14b8a6"]
HAIRS = ["#1f1410", "#2b1d14", "#5b3a1e", "#8b5a2b", "#e8c46a", "#c0392b", "#d6d3d1", "#111827"]
HAIR_STYLES = ["short", "side", "spiky", "long", "bun", "ponytail", "curly"]

_clock = {"check": 0.0, "hire": 0.0, "idle_since": None}


def options(cfg: Dict[str, Any]) -> Dict[str, Any]:
    raw = cfg.get("staffing") if isinstance(cfg.get("staffing"), dict) else {}
    out = dict(DEFAULTS)
    for k in ("auto_hire", "auto_desks", "dismiss_temps"):
        if isinstance(raw.get(k), bool):
            out[k] = raw[k]
    try:
        out["max_agents"] = max(1, min(30, int(raw.get("max_agents", out["max_agents"]))))
    except (TypeError, ValueError):
        pass
    return out


def _unique_name(prefix: str, taken: List[str]) -> str:
    n = 1
    while f"{prefix}_{n}" in taken:
        n += 1
    return f"{prefix}_{n}"


def _free_desk(agents: List[Dict[str, Any]]) -> int:
    used = {int(a.get("desk_idx") or 0) for a in agents}
    return next(i for i in range(config_store.SEAT_COUNT + 1) if i not in used) % config_store.SEAT_COUNT


def _model_for(kind: str, agents: List[Dict[str, Any]]) -> str:
    """Та же нейросеть, что у коллег по роли; если таких нет - как у разработчиков; иначе первая модель."""
    want = roles.ROLES[kind]["type"]
    for t in (want, "coder", "qa", "planner"):
        same = next((a for a in agents if a.get("pipeline_type") == t), None)
        if same:
            return same["model_ref"]
    models = config_store.get().get("models") or []
    return models[0]["id"] if models else ""


def hire(kind: str, reason: str, temp: bool, by: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Добавляет агента в штат (config.json) и сразу выводит на работу. None - нанять нельзя (лимит штата)."""
    if kind not in roles.ROLES or kind == "planner":       # руководитель в офисе один
        return None
    cfg = config_store.get()
    if not roles.prompt_for(kind, cfg):                     # роль без промпта пользователя - работать нечем
        return None
    agents = list(cfg.get("agents") or [])
    if len(agents) >= options(cfg)["max_agents"]:
        return None
    role = roles.ROLES[kind]
    rnd = random.Random()
    new = {
        "id": _unique_name(role["prefix"], [a["id"] for a in agents]),
        "tag": role["tag"], "role": role["title"], "pipeline_type": role["type"], "specialty": role["specialty"],
        "model_ref": _model_for(kind, agents), "desk_idx": _free_desk(agents),
        "shirt": rnd.choice(SHIRTS), "hair": rnd.choice(HAIRS), "pants": "", "skin": rnd.randrange(6),
        "hair_style": rnd.choice(HAIR_STYLES), "outfit": role["outfit"],
        "accessory": rnd.choice(["none", "none", "glasses", "headphones"]),
        "prompt": "", "temp": temp,               # пустой промпт - работает по шаблону роли из настроек
    }
    clean = config_store.validate_config({**cfg, "agents": agents + [new]}, cfg)
    config_store.save(clean)
    runtime.sync_runtime_agents()
    who = by or chat_store.office_voice()
    runtime.add_log(f"👋 [{who}] Нанял {new['id']} ({role['title']}): {reason}")
    chat_store.team_say(who, f"👋 Нанял в команду {new['id']} — {role['title'].lower()}"
                             + (" (временно, на эту работу)" if temp else "") + f". Причина: {reason}.")
    _clock["hire"] = time.time()
    ensure_desks()
    return new


def dismiss_temps() -> List[str]:
    """Временные сотрудники, у которых нет работы, уходят."""
    cfg = config_store.get()
    gone = [a["id"] for a in cfg.get("agents") or []
            if a.get("temp") and (runtime.agent(a["id"]) or {}).get("status", STATUS_FREE) == STATUS_FREE]
    if not gone:
        return []
    clean = config_store.validate_config({**cfg, "agents": [a for a in cfg["agents"] if a["id"] not in gone]}, cfg)
    config_store.save(clean)
    runtime.sync_runtime_agents()
    runtime.add_log(f"👋 Временные сотрудники закончили работу и ушли: {', '.join(gone)}")
    chat_store.team_note(f"👋 Работа закончена, временные сотрудники ушли: {', '.join(gone)}.")
    ensure_desks()
    return gone


def ensure_desks() -> None:
    """Работников (кроме руководителя - он в кабинете) больше, чем столов: просим браузер поставить столы."""
    # офис обставляет пользователь: пока он не сохранил свою планировку, столы сами не появляются
    if not options(config_store.get())["auto_desks"] or layout_store.get() is None:
        state["layout_request"] = None
        return
    workers = sum(1 for a in runtime.agents_list() if a["pipeline_type"] != "planner")
    seats = layout_store.seat_count()
    if workers > seats:
        prev = state.get("layout_request") or {}
        desks = math.ceil((workers - seats) / 2)
        if prev.get("desks") != desks:
            state["layout_request"] = {"id": int(time.time() * 1000), "desks": desks}
    else:
        state["layout_request"] = None


def _decide() -> Optional[tuple]:
    """Кого нанять сейчас. Только роли, для которых пользователь написал промпт."""
    ready = {k for k in roles.ROLES if roles.prompt_for(k, config_store.get())}
    decision = _need()
    return decision if decision and decision[0] in ready else None


def _need() -> Optional[tuple]:
    agents = runtime.agents_list()
    todo = [t for t in dispatcher.open_tasks() if t["status"] == "todo" and not t.get("_busy")]
    review = [t for t in dispatcher.open_tasks() if t["status"] == "testing" and not t.get("_busy")]
    present = {a.get("specialty") for a in agents if a.get("specialty")}
    for spec in ("designer", "devops", "writer"):
        n = sum(1 for t in todo if roles.specialty_of(t["filename"]) == spec)
        if n >= 2 and spec not in present:
            return spec, f"в очереди {n} задач по профилю, а такого специалиста нет"
    coders = [a for a in agents if a["pipeline_type"] == "coder"]
    if todo and (not coders or len(todo) >= 3 * len(coders)):
        return "developer", f"в очереди {len(todo)} задач на {len(coders)} разработчиков"
    qas = [a for a in agents if a["pipeline_type"] == "qa"]
    if review and (not qas or len(review) >= 3 * len(qas)):
        return "qa", f"на проверке {len(review)} задач на {len(qas)} тестировщиков"
    return None


def tick() -> None:
    """Вызывается сторожем доски. Нанимает под нагрузку и отпускает временных, когда работы нет."""
    now = time.time()
    if now - _clock["check"] < CHECK_EVERY:
        return
    _clock["check"] = now
    opts = options(config_store.get())
    busy = state["jobs"] > 0 or bool(dispatcher.open_tasks())
    if busy:
        _clock["idle_since"] = None
        if opts["auto_hire"] and not state["paused"] and now - _clock["hire"] >= HIRE_COOLDOWN:
            decision = _decide()
            if decision:
                hire(decision[0], decision[1], temp=True)
        return
    if _clock["idle_since"] is None:
        _clock["idle_since"] = now
    elif opts["dismiss_temps"] and now - _clock["idle_since"] >= DISMISS_AFTER:
        if any(a.get("temp") for a in config_store.get().get("agents") or []):
            dismiss_temps()
