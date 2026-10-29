"""Состояние офиса в памяти: кто чем занят, журнал событий, счётчики."""
import time
from datetime import datetime
from typing import Any, Dict

from . import config_store, settings

STATUS_FREE = "Свободен"
STATUS_BUSY = "Работает"
STATUS_ERROR = "Ошибка"
STATUS_WALK = "Идёт"          # получил задачу и идёт к своему столу
IDLE_ACTION = "Ожидает задачу"
CHAT_ACTION = "Отвечает в чате..."

state: Dict[str, Any] = {
    "is_running": False,
    "starting": False,        # проект запрошен, но фоновая задача ещё не стартовала
    "jobs": 0,
    "paused": False,          # СТОП: сторож доски сам задачи не возобновляет
    "dispatch_error": "",
    "cancel_requested": False,
    "project_idea": "",
    "project_dir": "",        # папка текущего проекта внутри рабочей директории
    "run_started_at": 0.0,
    "agents_runtime": {},
    "metrics": {"tokens_in": 0, "tokens_out": 0, "sub_agents": 0, "files_saved": 0},
    "viewer_seen_at": 0.0,    # когда офис последний раз смотрели в открытой вкладке
    "logs": [],
    "events": [],             # то же, что logs, но с временем в секундах - для общей ленты чата
}

_event_seq = 0


def _write_log_file(ts: str, msg: str) -> None:
    """Журнал дублируется в data/logs/ГГГГ-ММ-ДД.log, чтобы история не пропадала после перезапуска."""
    try:
        settings.LOGS_DIR.mkdir(parents=True, exist_ok=True)
        with open(settings.LOGS_DIR / f"{datetime.now():%Y-%m-%d}.log", "a", encoding="utf-8") as f:
            f.write(f"[{ts}] {msg}\n")
    except OSError:
        pass


def add_log(msg: str) -> None:
    global _event_seq
    ts = datetime.now().strftime("%H:%M:%S")
    try:
        print(f"[{ts}] {msg}", flush=True)
    except (UnicodeEncodeError, ValueError, OSError):
        pass  # консоль Windows в cp1251 не умеет эмодзи, а журнал в интерфейсе важнее
    _write_log_file(ts, msg)
    state["logs"].insert(0, f"[{ts}] {msg}")
    del state["logs"][150:]
    _event_seq += 1
    state["events"].append({"id": _event_seq, "t": time.time(), "ts": ts, "text": msg})
    del state["events"][:-200]


def set_agent(ag_id: str, status: str, action: str) -> None:
    ag = state["agents_runtime"].get(ag_id)
    if ag:
        ag["status"] = status
        ag["action"] = action
        ag["since"] = time.time()


def agent(ag_id: str):
    return state["agents_runtime"].get(ag_id)


def agents_list():
    return list(state["agents_runtime"].values())


def sync_runtime_agents() -> None:
    """Пересобирает список агентов из конфига, сохраняя их текущие статусы."""
    cfg = config_store.get()
    models = cfg.get("models", [])
    fallback = models[0]["id"] if models else ""
    valid = {m["id"] for m in models}
    runtime = {}
    for idx, ag in enumerate(cfg.get("agents", [])):
        prev = state["agents_runtime"].get(ag["id"], {})
        model_ref = ag.get("model_ref", fallback)
        if valid and model_ref not in valid:
            model_ref = fallback
        model = next((m for m in models if m["id"] == model_ref), {})
        runtime[ag["id"]] = {
            "id": ag["id"],
            "tag": ag.get("tag", ag["id"]),
            "role": ag.get("role", "Agent"),
            "pipeline_type": ag.get("pipeline_type", "coder"),
            "model_ref": model_ref,
            "model_name": model.get("name", model_ref),
            "desk_idx": int(ag.get("desk_idx", idx)) % config_store.SEAT_COUNT,
            "shirt": ag.get("shirt", "#3b82f6"),
            "hair": ag.get("hair", "#f1f5f9"),
            "pants": ag.get("pants", ""),
            "skin": ag.get("skin", -1),
            "hair_style": ag.get("hair_style", "auto"),
            "outfit": ag.get("outfit", "auto"),
            "accessory": ag.get("accessory", "auto"),
            "prompt": ag.get("prompt", ""),
            "specialty": ag.get("specialty", ""),
            "temp": bool(ag.get("temp")),
            "status": prev.get("status", STATUS_FREE),
            "action": prev.get("action", IDLE_ACTION),
            "since": prev.get("since", time.time()),
            "done": prev.get("done", 0),
        }
    state["agents_runtime"] = runtime


def finish_job() -> None:
    """Общий хвост для всех фоновых работ: когда последняя закончилась, офис свободен."""
    state["jobs"] = max(0, state["jobs"] - 1)
    if state["jobs"] == 0:
        state["is_running"] = False
        state["run_started_at"] = 0.0
        state["metrics"]["sub_agents"] = 0
        for k, ag in state["agents_runtime"].items():
            if ag["status"] in (STATUS_BUSY, STATUS_WALK) and ag["action"] != CHAT_ACTION:
                set_agent(k, STATUS_FREE, IDLE_ACTION)


def begin_job() -> None:
    state["jobs"] += 1
    state["is_running"] = True
    state["starting"] = False
    if not state["run_started_at"]:
        state["run_started_at"] = time.time()
