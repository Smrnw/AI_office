"""История чатов: личные каналы агентов и общий канал «Проект»."""
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

from .. import runtime, settings
from ..storage import read_json, write_json

CHAT_LIMIT = 200
TEAM = settings.TEAM_CHANNEL

_loaded = read_json(settings.CHAT_PATH, {})
CHATS: Dict[str, List[Dict[str, Any]]] = _loaded if isinstance(_loaded, dict) else {}
PENDING: set = set()          # каналы, где агент прямо сейчас готовит ответ


def save() -> None:
    try:
        write_json(settings.CHAT_PATH, CHATS, indent=1)
    except OSError as e:
        print(f"Не удалось сохранить историю чата: {e}", flush=True)


def task_meta(tasks: Optional[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    return [{"id": t["id"], "filename": t["filename"], "task_file": t.get("task_file", "")} for t in (tasks or [])]


def append(channel: str, role: str, text: str, tasks: Optional[List[Dict[str, Any]]] = None,
           author: Optional[str] = None, to: Optional[List[str]] = None,
           check: Optional[Dict[str, Any]] = None, autopilot: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """role: user | agent | system. author нужен в общем канале, чтобы было видно, кто ответил;
    to - кому заказчик адресовал сообщение по имени; check - отчёт автопроверки (итог и скриншоты);
    autopilot - прогресс автопилота (требования и круг)."""
    msgs = CHATS.setdefault(channel, [])
    msg = {
        "id": (msgs[-1]["id"] + 1) if msgs else 1,
        "role": role,
        "author": author or channel,
        "text": text,
        "t": time.time(),
        "ts": datetime.now().strftime("%H:%M:%S"),
        "tasks": task_meta(tasks),
    }
    if to:
        msg["to"] = list(to)
    if check:
        msg["check"] = check
    if autopilot:
        msg["autopilot"] = autopilot
    msgs.append(msg)
    del msgs[:-CHAT_LIMIT]
    save()
    return msg


def team_say(author: str, text: str, tasks: Optional[List[Dict[str, Any]]] = None) -> None:
    append(TEAM, "agent", text, tasks, author=author)


def office_voice() -> str:
    """От чьего имени офис пишет в общий канал: руководитель, а если его нет — первый агент."""
    agents = runtime.agents_list()
    pm = next((a for a in agents if a["pipeline_type"] == "planner"), agents[0] if agents else None)
    return pm["id"] if pm else "Офис"


def team_note(text: str, tasks: Optional[List[Dict[str, Any]]] = None) -> None:
    """В чате только реплики людей и агентов: служебные сообщения произносит руководитель."""
    append(TEAM, "agent", text, tasks, author=office_voice())


def clear(channel: str) -> None:
    CHATS.pop(channel, None)
    save()


def history(channel: str) -> List[Dict[str, Any]]:
    return CHATS.get(channel, [])
