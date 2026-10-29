"""Учёт токенов по моделям.

Если провайдер вернул usage, берём его, иначе оцениваем по длине текста (~3 символа на токен).
Лимит в настройках модели - планка пользователя: настоящую квоту провайдера узнать нельзя.
"""
from typing import Any, Dict, List, Optional

from .. import config_store, runtime, settings
from ..storage import read_json, write_json

DEFAULT_TOKEN_LIMIT = 1_000_000

_loaded = read_json(settings.USAGE_PATH, {})
USAGE: Dict[str, Dict[str, int]] = _loaded if isinstance(_loaded, dict) else {}


def estimate(text: str) -> int:
    return max(1, len(text or "") // 3)


def model_limit(model: Dict[str, Any]) -> int:
    try:
        value = int(model.get("token_limit") or 0)
    except (TypeError, ValueError):
        value = 0
    return value if value > 0 else DEFAULT_TOKEN_LIMIT


def track(model_ref: str, tin: int, tout: int, exact: bool = False) -> None:
    model = config_store.model_info(model_ref)
    mid = model["id"]
    u = USAGE.setdefault(mid, {"in": 0, "out": 0, "calls": 0, "warned": 0})
    u["calls"] = u.get("calls", 0) + 1
    u["in"] = u.get("in", 0) + tin
    u["out"] = u.get("out", 0) + tout
    if exact:
        u["exact"] = u.get("exact", 0) + 1
    runtime.state["metrics"]["tokens_in"] += tin
    runtime.state["metrics"]["tokens_out"] += tout

    # предупреждаем в журнале один раз при пересечении 80% и 100%
    pct = (u["in"] + u["out"]) * 100 / model_limit(model)
    level = 100 if pct >= 100 else 80 if pct >= 80 else 0
    if level > u.get("warned", 0):
        icon = "🔴" if level == 100 else "🟡"
        runtime.add_log(f"{icon} Модель «{model.get('name', mid)}»: использовано {pct:.0f}% лимита токенов")
    u["warned"] = level
    write_json(settings.USAGE_PATH, USAGE, indent=1)


def report() -> List[Dict[str, Any]]:
    """Строки для панели лимитов: модели, которыми пользуются агенты, плюс те, где уже есть расход."""
    in_use = {a["model_ref"] for a in runtime.agents_list()}
    rows = []
    for m in config_store.get().get("models", []):
        if m["id"] not in in_use and m["id"] not in USAGE:
            continue
        u = USAGE.get(m["id"], {})
        used = u.get("in", 0) + u.get("out", 0)
        limit = model_limit(m)
        rows.append({
            "id": m["id"], "name": m.get("name", m["id"]), "provider": m.get("provider", ""),
            "model_id": m.get("model_id", ""), "in": u.get("in", 0), "out": u.get("out", 0),
            "calls": u.get("calls", 0), "used": used, "limit": limit,
            "pct": round(used * 100 / limit, 1), "exact": u.get("exact", 0) > 0,
        })
    return rows


def total() -> int:
    """Всего токенов по всем моделям: по разнице автопилот считает свой бюджет."""
    return sum(u.get("in", 0) + u.get("out", 0) for u in USAGE.values())


def reset() -> None:
    USAGE.clear()
    write_json(settings.USAGE_PATH, USAGE, indent=1)
    runtime.state["metrics"]["tokens_in"] = 0
    runtime.state["metrics"]["tokens_out"] = 0


def usage_numbers(data: Any, a: str, b: str) -> Optional[tuple]:
    try:
        tin, tout = int(data[a]), int(data[b])
        return (tin, tout) if tin >= 0 and tout >= 0 else None
    except (TypeError, KeyError, ValueError):
        return None
