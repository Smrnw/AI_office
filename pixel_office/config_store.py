"""Единый файл config.json: провайдеры, модели, агенты и рабочие папки.

Всё, что приходит из браузера, проходит validate_config(): неверные
идентификаторы, цвета и папки отсекаются здесь, а не в коде агентов.
"""
import copy
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import settings
from .defaults import default_config
from .storage import read_json, write_json

API_TYPES = ("gemini", "anthropic", "openai_compatible", "demo")
PIPELINE_TYPES = ("planner", "coder", "qa")
SEAT_COUNT = 64          # верхняя граница номера места; реальное число мест задаёт планировка офиса

# внешность агента: auto - выбрать по имени и роли
HAIR_STYLES = ("auto", "short", "side", "spiky", "long", "bun", "ponytail", "curly", "bald")
OUTFITS = ("auto", "suit", "hoodie", "shirt", "tshirt", "sweater")
ACCESSORIES = ("auto", "none", "glasses", "headphones", "both")
# специализация поверх роли: дизайнер, DevOps и писатель - разработчики своих файлов, безопасник - проверяющий
SPECIALTIES = ("", "designer", "devops", "writer", "security")
SKIN_TONES = 6

ID_RE = re.compile(r"^[A-Za-z0-9_.\-]{1,64}$")
AGENT_ID_RE = re.compile(r"^[A-Za-zА-Яа-яЁё0-9_.\-]{1,40}$")
COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


class ConfigError(ValueError):
    """Проблема в настройках (нет ключа, провайдера, модели). Повторять запрос бессмысленно."""


def _with_defaults(data: Dict[str, Any]) -> Dict[str, Any]:
    for field, empty in (("workspace_dir", ""), ("tasks_dir", ""), ("providers", []), ("models", []), ("agents", [])):
        data.setdefault(field, empty)
    return data


def _load() -> Dict[str, Any]:
    if not settings.CONFIG_PATH.exists():
        cfg = default_config()
        write_json(settings.CONFIG_PATH, cfg)
        return cfg
    data = read_json(settings.CONFIG_PATH, None)
    if not isinstance(data, dict):
        print(f"config.json повреждён, работаю с пустой конфигурацией: {settings.CONFIG_PATH}", flush=True)
        return {"workspace_dir": "", "tasks_dir": "", "providers": [], "models": [], "agents": []}
    return _with_defaults(data)


_config: Dict[str, Any] = _load()


def get() -> Dict[str, Any]:
    return _config


def save(cfg: Optional[Dict[str, Any]] = None) -> None:
    global _config
    if cfg is not None:
        _config = cfg
    write_json(settings.CONFIG_PATH, _config)


DEFAULT_OFFICE_NAME = "AI Office"
OFFICE_NAME_MAX = 60


def office_name() -> str:
    return _config.get("office_name") or DEFAULT_OFFICE_NAME


def set_office_name(raw: Any) -> str:
    """Название в шапке. Пустое возвращает название по умолчанию."""
    name = " ".join("".join(ch for ch in str(raw or "") if ch.isprintable()).split())[:OFFICE_NAME_MAX]
    if name and name != DEFAULT_OFFICE_NAME:
        _config["office_name"] = name
    else:
        _config.pop("office_name", None)
    save()
    return office_name()


LANGUAGES = ("ru", "en")


def language() -> str:
    return _config.get("language") if _config.get("language") in LANGUAGES else "ru"


def set_language(lang: Any) -> str:
    """Язык интерфейса. На нём же агенты отвечают в чате и пишут тексты в коде."""
    if lang not in LANGUAGES:
        raise ConfigError("Неизвестный язык")
    _config["language"] = lang
    save()
    return lang


# -------------------------------------------------------------------------
# Папки
# -------------------------------------------------------------------------

def _dir_from_config(field: str, fallback: str) -> Path:
    raw = (_config.get(field) or "").strip()
    return Path(raw).expanduser().resolve() if raw else (settings.DATA_DIR / fallback).resolve()


def workspace_dir() -> Path:
    path = _dir_from_config("workspace_dir", "workspace")
    path.mkdir(parents=True, exist_ok=True)
    return path


def tasks_dir() -> Path:
    path = _dir_from_config("tasks_dir", "tasks")
    for status in settings.KANBAN_STATUSES:
        (path / status).mkdir(parents=True, exist_ok=True)
    return path


def _is_within(child: Path, parent: Path) -> bool:
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


def _check_dir(raw: str, label: str) -> str:
    """Проверяет папку из настроек. Агенты пишут туда код, поэтому корень диска,
    папка с программой и папка с config.json (там API-ключи) не годятся."""
    raw = (raw or "").strip()
    if not raw:
        return ""
    path = Path(raw).expanduser()
    if not path.is_absolute():
        raise ConfigError(f"{label}: укажите полный путь (например D:/Projects/workspace)")
    path = path.resolve()
    if path.parent == path:
        raise ConfigError(f"{label}: нельзя использовать корень диска")
    for protected in (settings.DATA_DIR, settings.PROJECT_ROOT):
        if _is_within(protected, path):
            raise ConfigError(f"{label}: папка не должна содержать файлы программы или config.json ({protected})")
    if _is_within(path, settings.PROJECT_ROOT) and not _is_within(path, settings.DATA_DIR):
        raise ConfigError(f"{label}: нельзя выбирать папку внутри кода программы (разрешена только {settings.DATA_DIR})")
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise ConfigError(f"{label}: не удалось создать папку ({e})")
    return str(path)


# -------------------------------------------------------------------------
# Модели, провайдеры, ключи
# -------------------------------------------------------------------------

def model_info(model_ref: str) -> Dict[str, Any]:
    models = _config.get("models", [])
    for m in models:
        if m["id"] == model_ref:
            return m
    if models:
        return models[0]
    raise ConfigError("Не настроено ни одной модели. Откройте Настройки → Нейросети и модели.")


def provider_info(provider_id: str) -> Dict[str, Any]:
    for p in _config.get("providers", []):
        if p["id"] == provider_id:
            return p
    raise ConfigError(f"Провайдер '{provider_id}' не найден. Проверьте Настройки → Провайдеры.")


def real_key(key: Any) -> str:
    """Ключ или пустая строка, если это пусто либо заглушка вроде 'ВАШ_КЛЮЧ_OPENAI'."""
    key = (key or "").strip() if isinstance(key, str) else ""
    if not key or "ВАШ_КЛЮЧ" in key.upper() or key.upper().startswith("YOUR_"):
        return ""
    return key


def provider_key(provider: Dict[str, Any]) -> str:
    return real_key(provider.get("api_key")) or os.getenv(f"{provider['id'].upper()}_API_KEY", "").strip()


def public_config() -> Dict[str, Any]:
    """Копия конфига для браузера: сами API-ключи наружу не отдаются."""
    cfg = copy.deepcopy(_config)
    for p in cfg.get("providers", []):
        p["has_key"] = bool(provider_key(p))
        p["api_key"] = ""
    from .checks import options as check_options
    cfg["checks"] = check_options(cfg)
    from .agents.autopilot import options as autopilot_options
    cfg["autopilot"] = autopilot_options(cfg)
    from .agents.staffing import options as staffing_options
    cfg["staffing"] = staffing_options(cfg)
    from .notify import public as notify_public
    cfg["notify"] = notify_public(cfg)
    cfg["git"] = {"enabled": bool((cfg.get("git") or {}).get("enabled", True))}
    from .agents.roles import public_roles, validate_prompts
    cfg["role_prompts"] = validate_prompts(cfg.get("role_prompts"))
    cfg["role_defaults"] = public_roles()
    return cfg


# -------------------------------------------------------------------------
# Проверка конфига из браузера
# -------------------------------------------------------------------------

def _text(value: Any, limit: int) -> str:
    return str(value if value is not None else "").strip()[:limit]


def _url(value: Any, label: str) -> str:
    url = _text(value, 500)
    if url and not re.match(r"^https?://[^\s/]+", url, re.IGNORECASE):
        raise ConfigError(f"{label}: адрес должен начинаться с http:// или https://")
    return url


def validate_config(new_cfg: Any, old_cfg: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(new_cfg, dict):
        raise ConfigError("Ожидался объект с настройками")

    out: Dict[str, Any] = {
        "workspace_dir": _check_dir(new_cfg.get("workspace_dir", ""), "Рабочая папка"),
        "tasks_dir": _check_dir(new_cfg.get("tasks_dir", ""), "Папка задач"),
    }
    # необязательные поля, которые мы не редактируем в окне, сохраняем как есть
    for k, v in old_cfg.items():
        if k not in ("workspace_dir", "tasks_dir", "providers", "models", "agents", "checks", "autopilot", "staffing", "notify", "git",
                     "role_prompts"):
            out.setdefault(k, v)
    # настройки автопроверки: неизвестные ключи и значения не того типа отбрасываются
    from .checks import options as check_options
    raw_checks = new_cfg.get("checks") if isinstance(new_cfg.get("checks"), dict) else old_cfg.get("checks")
    out["checks"] = check_options({"checks": raw_checks or {}})
    from .agents.autopilot import options as autopilot_options
    raw_auto = new_cfg.get("autopilot") if isinstance(new_cfg.get("autopilot"), dict) else old_cfg.get("autopilot")
    out["autopilot"] = autopilot_options({"autopilot": raw_auto or {}})
    from .agents.staffing import options as staffing_options
    raw_staff = new_cfg.get("staffing") if isinstance(new_cfg.get("staffing"), dict) else old_cfg.get("staffing")
    out["staffing"] = staffing_options({"staffing": raw_staff or {}})
    from .notify import options as notify_options
    out["notify"] = notify_options(new_cfg if isinstance(new_cfg.get("notify"), dict) else old_cfg, old_cfg)
    raw_git = new_cfg.get("git") if isinstance(new_cfg.get("git"), dict) else old_cfg.get("git")
    out["git"] = {"enabled": bool((raw_git or {}).get("enabled", True))}
    from .agents.roles import validate_prompts
    out["role_prompts"] = validate_prompts(new_cfg["role_prompts"] if isinstance(new_cfg.get("role_prompts"), dict)
                                           else old_cfg.get("role_prompts"))

    # ---- провайдеры. Сохранённый ключ оставляем, только если адрес не поменялся:
    # иначе подменой base_url можно было бы отправить старый ключ на чужой сервер.
    old_providers = {p.get("id"): p for p in old_cfg.get("providers", [])}
    providers: List[Dict[str, Any]] = []
    for i, p in enumerate(new_cfg.get("providers") or []):
        if not isinstance(p, dict):
            continue
        pid = _text(p.get("id"), 64)
        if not ID_RE.match(pid):
            raise ConfigError(f"Провайдер #{i + 1}: ID может содержать только латиницу, цифры, _ . -")
        if any(x["id"] == pid for x in providers):
            raise ConfigError(f"Провайдер '{pid}' указан дважды")
        api_type = p.get("api_type") if p.get("api_type") in API_TYPES else "openai_compatible"
        base_url = _url(p.get("base_url"), f"Провайдер '{pid}'")
        key = _text(p.get("api_key"), 400)
        old = old_providers.get(pid)
        if not key and old and (old.get("base_url") or "").strip() == base_url and old.get("api_type") == api_type:
            key = old.get("api_key", "")
        providers.append({"id": pid, "name": _text(p.get("name"), 80) or pid, "api_type": api_type,
                          "api_key": key, "base_url": base_url})
    out["providers"] = providers
    provider_ids = {p["id"] for p in providers}

    models: List[Dict[str, Any]] = []
    for i, m in enumerate(new_cfg.get("models") or []):
        if not isinstance(m, dict):
            continue
        mid = _text(m.get("id"), 64)
        if not ID_RE.match(mid):
            raise ConfigError(f"Модель #{i + 1}: ID может содержать только латиницу, цифры, _ . -")
        if any(x["id"] == mid for x in models):
            raise ConfigError(f"Модель '{mid}' указана дважды")
        provider = _text(m.get("provider"), 64)
        if provider not in provider_ids:
            raise ConfigError(f"Модель '{mid}': провайдер '{provider}' не найден")
        try:
            limit = max(0, int(m.get("token_limit") or 0))
        except (TypeError, ValueError):
            limit = 0
        models.append({"id": mid, "name": _text(m.get("name"), 80) or mid, "provider": provider,
                       "model_id": _text(m.get("model_id"), 120), "token_limit": limit})
    out["models"] = models
    model_ids = [m["id"] for m in models]

    agents: List[Dict[str, Any]] = []
    for i, a in enumerate(new_cfg.get("agents") or []):
        if not isinstance(a, dict):
            continue
        aid = _text(a.get("id"), 40)
        if not AGENT_ID_RE.match(aid) or aid == settings.TEAM_CHANNEL:
            raise ConfigError(f"Агент #{i + 1}: имя может содержать буквы, цифры, _ . - (до 40 символов)")
        if any(x["id"] == aid for x in agents):
            raise ConfigError(f"Агент '{aid}' указан дважды")
        model_ref = _text(a.get("model_ref"), 64)
        if model_ref not in model_ids:
            model_ref = model_ids[0] if model_ids else ""
        try:
            desk = int(a.get("desk_idx") or 0) % SEAT_COUNT
        except (TypeError, ValueError):
            desk = i % SEAT_COUNT
        shirt = a.get("shirt") if COLOR_RE.match(str(a.get("shirt") or "")) else "#3b82f6"
        hair = a.get("hair") if COLOR_RE.match(str(a.get("hair") or "")) else "#f1f5f9"
        pants = a.get("pants") if COLOR_RE.match(str(a.get("pants") or "")) else ""
        try:
            skin = int(a.get("skin", -1))
        except (TypeError, ValueError):
            skin = -1
        skin = skin if 0 <= skin < SKIN_TONES else -1
        agents.append({
            "id": aid,
            "tag": _text(a.get("tag"), 40) or aid,
            "role": _text(a.get("role"), 60) or "Agent",
            "pipeline_type": a.get("pipeline_type") if a.get("pipeline_type") in PIPELINE_TYPES else "coder",
            "model_ref": model_ref,
            "desk_idx": desk,
            "shirt": shirt,
            "hair": hair,
            "pants": pants,
            "skin": skin,
            "hair_style": a.get("hair_style") if a.get("hair_style") in HAIR_STYLES else "auto",
            "outfit": a.get("outfit") if a.get("outfit") in OUTFITS else "auto",
            "accessory": a.get("accessory") if a.get("accessory") in ACCESSORIES else "auto",
            "prompt": _text(a.get("prompt"), 20000),
            "specialty": a.get("specialty") if a.get("specialty") in SPECIALTIES else "",
            "temp": bool(a.get("temp")),
        })
    out["agents"] = agents
    from .agents.roles import agents_without_prompt
    silent = agents_without_prompt(agents, out)
    if silent:
        raise ConfigError("Без системного промпта: " + ", ".join(silent) + ". Напишите промпт агенту "
                          "или его роли во вкладке «Роли и промпты»")
    return out
