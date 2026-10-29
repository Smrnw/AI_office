"""Роли команды: должность и профиль файлов. Промпты ролей пишет пользователь.

Готовых инструкций нет: в мастере и во вкладке «Роли и промпты» пользователь сам описывает каждую
роль (config.json -> role_prompts). Агент с пустым своим промптом работает по промпту роли;
сотрудника без промпта - ни своего, ни ролевого - сохранить или нанять нельзя.
"""
from pathlib import PurePosixPath
from typing import Any, Dict, Iterable, List

ROLES: Dict[str, Dict[str, str]] = {
    "planner": {"type": "planner", "specialty": "", "title": "Руководитель проекта", "tag": "PM", "prefix": "PM",
                "outfit": "suit"},
    "developer": {"type": "coder", "specialty": "", "title": "Разработчик", "tag": "dev", "prefix": "Coder",
                  "outfit": "hoodie"},
    "qa": {"type": "qa", "specialty": "", "title": "Тестировщик", "tag": "qa", "prefix": "QA", "outfit": "sweater"},
    "designer": {"type": "coder", "specialty": "designer", "title": "Дизайнер интерфейсов", "tag": "design",
                 "prefix": "Designer", "outfit": "tshirt"},
    "devops": {"type": "coder", "specialty": "devops", "title": "DevOps-инженер", "tag": "ops", "prefix": "DevOps",
               "outfit": "shirt"},
    "writer": {"type": "coder", "specialty": "writer", "title": "Технический писатель", "tag": "docs", "prefix": "Writer",
               "outfit": "sweater"},
    "security": {"type": "qa", "specialty": "security", "title": "Специалист по безопасности", "tag": "sec",
                 "prefix": "Security", "outfit": "suit"},
}

_EXT = {
    "designer": {".css", ".scss", ".sass", ".less", ".html", ".htm", ".svg"},
    "writer": {".md", ".rst", ".txt", ".adoc"},
    "devops": {".yml", ".yaml", ".sh", ".ps1", ".bat", ".cmd", ".toml", ".ini", ".cfg", ".env.example"},
}
_NAMES = {
    "devops": {"dockerfile", "docker-compose.yml", "makefile", "requirements.txt", "package.json", "procfile",
               ".dockerignore", ".gitignore", "nginx.conf"},
    "writer": {"readme", "license", "changelog"},
}


ORDER = ["planner", "developer", "qa", "designer", "devops", "writer", "security"]
TYPE_KIND = {"planner": "planner", "coder": "developer", "qa": "qa"}


def kind_of(agent: Dict[str, Any]) -> str:
    """Роль агента для шаблона промпта: специализация, а без неё - роль в конвейере."""
    spec = agent.get("specialty") or ""
    return spec if spec in ROLES else TYPE_KIND.get(agent.get("pipeline_type", ""), "developer")


def prompt_for(kind: str, cfg: Dict[str, Any]) -> str:
    """Промпт роли из настроек ("" - пользователь его ещё не написал)."""
    raw = cfg.get("role_prompts") if isinstance(cfg.get("role_prompts"), dict) else {}
    return str(raw.get(kind) or "").strip()


def system_prompt(agent: Dict[str, Any], cfg: Dict[str, Any]) -> str:
    """Свой промпт агента, а если он пустой - промпт его роли."""
    return str(agent.get("prompt") or "").strip() or prompt_for(kind_of(agent), cfg)


def validate_prompts(raw: Any) -> Dict[str, str]:
    """Промпты ролей из настроек: только известные роли, пустые не храним."""
    out: Dict[str, str] = {}
    if isinstance(raw, dict):
        for kind, text in raw.items():
            text = str(text or "").strip()[:20000]
            if kind in ROLES and text:
                out[kind] = text
    return out


def agents_without_prompt(agents: List[Dict[str, Any]], cfg: Dict[str, Any]) -> List[str]:
    """Сотрудники, которым нечем работать: ни своего промпта, ни промпта роли."""
    return [a["id"] for a in agents if not system_prompt(a, cfg)]


def public_roles() -> Dict[str, Dict[str, str]]:
    return {k: {"title": ROLES[k]["title"], "type": ROLES[k]["type"], "specialty": ROLES[k]["specialty"]} for k in ORDER}


def specialty_of(filename: str) -> str:
    """Чей профиль файл: designer / devops / writer или "" - обычный код."""
    p = PurePosixPath(filename.lower())
    for spec, names in _NAMES.items():
        if p.name in names or p.stem in names:
            return spec
    if any(part in (".github", "deploy", "ci") for part in p.parts[:-1]):
        return "devops"
    for spec, exts in _EXT.items():
        if p.suffix in exts:
            return spec
    return ""


def code_priority(agent: Dict, filename: str, present: Iterable[str]) -> int:
    """Чем меньше, тем охотнее агент берёт файл. Специалист - сначала свои файлы. Обычный разработчик -
    сначала то, для чего специалиста в штате нет, а файлы специалистов оставляет им."""
    spec = specialty_of(filename)
    mine = agent.get("specialty") or ""
    if mine:
        return 0 if spec == mine else 1
    return 1 if spec and spec in set(present) else 0
