"""Сообщения заказчика: запуск проекта, вопросы агентам и просьбы о доработке."""
import asyncio
import re
from typing import Any, Dict, List, Optional

from .. import config_store, layout_store, runtime, tasks_store, workspace
from ..llm import Cancelled, call_llm, extract_json
from ..runtime import CHAT_ACTION, IDLE_ACTION, STATUS_BUSY, STATUS_FREE, state
from . import chat_store, dispatcher, roles, workflow
from .chat_store import TEAM
from .prompts import CHAT_FORMAT_RULES, CHAT_ROLE_HINTS, CHAT_USER_PROMPT, IDENTITY, PROMISE_FIX_PROMPT

MAX_MESSAGE = 4000


def tasks_summary(limit: int = 15) -> str:
    items = tasks_store.scan_all()[-limit:]
    if not items:
        return "(задач на доске нет)"
    return "\n".join(
        f"- #{t['id']} [{t['status']}] {t['filename']} — {t['title']}" + (f" ({t['qa_notes']})" if t.get("qa_notes") else "")
        for t in items)


def identity(ag: Dict[str, Any]) -> str:
    """Кто ты и кто рядом: имя, должность и коллеги - чтобы агент знал себя и откликался на имя."""
    team = ", ".join(f"{a['id']} ({a['role']})" for a in runtime.agents_list() if a["id"] != ag["id"])
    return IDENTITY.format(name=ag["id"], role=ag.get("role") or ag["pipeline_type"], team=team or "пока никого")


def addressed_agents(text: str) -> List[str]:
    """К кому обращаются в общем канале: «@Coder_1 …» где угодно или «Coder_1, …» в начале сообщения.
    Регистр не важен; кроме имени подходит и бейдж агента."""
    found: List[str] = []
    lowered = text.lower()
    agents = sorted(runtime.agents_list(), key=lambda a: -len(a["id"]))     # длинные имена раньше коротких
    for a in agents:
        names = {a["id"].lower()} | ({a["tag"].lower()} if len(a.get("tag") or "") >= 2 else set())
        for name in names:
            esc = re.escape(name)
            if re.search(r"@" + esc + r"(?![\w])", lowered) or re.match(r"\s*" + esc + r"(?=[\s,:!?.]|$)", lowered):
                if a["id"] not in found:
                    found.append(a["id"])
                break
    return found


async def answer_addressed(ids: List[str], text: str) -> None:
    """Каждый, к кому обратились по имени, отвечает в общем канале по очереди."""
    try:
        for agent_id in ids:
            await process_chat_message(agent_id, text, TEAM, release=False)
    finally:
        chat_store.PENDING.discard(TEAM)


# «поручу», «передам», «возьмёт в работу», «сделаю»… - ответ обещает работу
PROMISE = re.compile(r"(поруч|переда[мюё]|возьм[её]т|займ[её]тся|займусь|сделаю|сделаем|внес[уёе]|исправлю|добавлю|"
                     r"приступ|в работу|I will|I'll|will (do|fix|add|take|handle)|assign)", re.IGNORECASE)


def parse_reply(raw: str) -> Dict[str, Any]:
    try:
        data = extract_json(raw)
    except ValueError:
        data = {"reply": raw}
    return data if isinstance(data, dict) else {"reply": str(raw)}


def task_list(tasks: Any) -> List[Dict[str, Any]]:
    """Модели иногда присылают одну задачу объектом, а не списком."""
    if isinstance(tasks, dict):
        tasks = [tasks]
    return [t for t in tasks if isinstance(t, dict)] if isinstance(tasks, list) else []


def switch_project(folder: Any) -> str:
    """Агент решил перейти к другому проекту. Возвращает папку, если переключились."""
    folder = str(folder or "").strip().strip("/")
    if not folder or folder == state.get("project_dir"):
        return ""
    try:
        workflow.select_project(folder)
        return folder
    except ValueError:
        return ""


def hire_requested(ag: Dict[str, Any], hires: Any) -> List[str]:
    """Нанимать может только руководитель; по просьбе заказчика сотрудник постоянный, не временный."""
    if ag["pipeline_type"] != "planner" or not isinstance(hires, list):
        return []
    from . import staffing
    names = []
    for h in hires[:3]:
        if not isinstance(h, dict):
            continue
        kind = str(h.get("role") or "")
        new = staffing.hire(kind, str(h.get("reason") or "по просьбе заказчика")[:200], temp=False, by=ag["id"])
        if new:
            names.append(new["id"])
        elif kind in roles.ROLES and not roles.prompt_for(kind, config_store.get()):
            chat_store.team_note(f"⚠️ Не могу нанять: для роли «{roles.ROLES[kind]['title']}» не написан промпт. "
                                 "Добавьте его в Настройки → Роли и промпты.")
    return names


async def process_chat_message(agent_id: str, text: str, channel: Optional[str] = None, release: bool = True) -> None:
    """Ответ агента и (если нужно) задачи на доработку. channel - личный канал агента или общий TEAM.
    release=False - флаг «печатает…» снимет тот, кто вызвал (несколько агентов отвечают подряд)."""
    channel = channel or agent_id
    ag = runtime.agent(agent_id)
    if not ag:
        if release:
            chat_store.PENDING.discard(channel)
        return

    took_desk = ag["status"] != STATUS_BUSY
    if took_desk:
        runtime.set_agent(agent_id, STATUS_BUSY, CHAT_ACTION)
    runtime.add_log(f"💬 [{agent_id}] Сообщение от заказчика: {text[:80]}")

    try:
        past = chat_store.history(channel)[:-1][-10:]
        def who(m):
            if m["role"] != "user":
                return m.get("author", agent_id)
            return "Заказчик" + (" → " + ", ".join(m["to"]) if m.get("to") else "")
        history_text = "\n".join(f"{who(m)}: {m['text'][:600]}" for m in past if m["role"] in ("user", "agent")) \
            or "(это начало диалога)"
        system_prompt = identity(ag) + "\n" + roles.system_prompt(ag, config_store.get()) + "\n" + \
            CHAT_ROLE_HINTS.get(ag["pipeline_type"], "") + CHAT_FORMAT_RULES
        projects = "\n".join(f"- {p['folder']} — {p['idea'][:120]}" + (" (текущий)" if p["current"] else "")
                             for p in workflow.list_projects()) or "(проектов пока нет)"
        user_prompt = CHAT_USER_PROMPT.format(
            idea=state["project_idea"] or "не задан (работа с существующими файлами)",
            folder=(state["project_dir"] or "не выбрана") + "/", projects=projects,
            office=layout_store.office_brief(),
            snapshot=workspace.snapshot(folder=state["project_dir"]), tasks=tasks_summary(), history=history_text, message=text)
        files = [f["name"] for f in workspace.list_files()]
        meta = {"message": text, "files": files, "role": ag["pipeline_type"], "name": ag["id"], "title": ag.get("role", ""),
                "projects": [p["folder"] for p in workflow.list_projects()]}
        data = parse_reply(await call_llm(ag["model_ref"], system_prompt, user_prompt, json_mode=True, purpose="chat", meta=meta))

        # пообещал работу, но задач не завёл: такое обещание никто бы не выполнил - переспрашиваем один раз
        if not task_list(data.get("tasks")) and PROMISE.search(str(data.get("reply") or "")):
            fix = PROMISE_FIX_PROMPT.format(reply=str(data.get("reply"))[:800])
            data = parse_reply(await call_llm(ag["model_ref"], system_prompt, user_prompt + "\n\n" + fix, json_mode=True,
                                              purpose="chat", meta={**meta, "promise_fix": True})) or data

        switched = switch_project(data.get("project"))
        hired = hire_requested(ag, data.get("hire"))
        reply = str(data.get("reply") or "").strip() or "Принято."
        if switched:
            reply = f"📁 Перешёл к проекту {switched}/. " + reply
        if hired:
            reply += " 👋 В команде новые сотрудники: " + ", ".join(hired) + "."
        created = workflow.create_revision_tasks(ag, task_list(data.get("tasks")), text)
        chat_store.append(channel, "agent", reply, created, author=agent_id)
        runtime.add_log(f"💬 [{agent_id}] Ответил в чате" + (f", создано задач: {len(created)}" if created else ""))
        if created:
            dispatcher.spawn(workflow.run_revision_tasks(created, agent_id, channel))
    except (asyncio.CancelledError, Cancelled):
        runtime.add_log(f"🛑 [{agent_id}] Ответ в чате прерван")
    except Exception as e:
        chat_store.append(channel, "agent", f"⚠️ Не получилось ответить: {e}", author=agent_id)
        runtime.add_log(f"⚠️ [{agent_id}] Ошибка чата: {e}")
    finally:
        if release:
            chat_store.PENDING.discard(channel)
        cur = runtime.agent(agent_id)
        if took_desk and cur and cur["action"] == CHAT_ACTION:
            runtime.set_agent(agent_id, STATUS_FREE, IDLE_ACTION)


def start_project(idea: str) -> Dict[str, Any]:
    """Запуск нового проекта. Флаг starting ставим сразу, чтобы двойной клик не запустил два проекта."""
    if state["is_running"] or state["starting"]:
        return {"ok": False, "error": "Сейчас идёт работа. Дождитесь завершения или нажмите СТОП."}
    if not runtime.agents_list():
        return {"ok": False, "error": "В офисе нет агентов. Наймите сотрудников в Настройках."}
    state["starting"] = True
    runtime.add_log(f"🚀 Запуск нового проекта: '{idea[:120]}'")
    task = dispatcher.spawn(workflow.run_company_workflow(idea))
    task.add_done_callback(lambda _t: state.__setitem__("starting", False))
    return {"ok": True, "started": True}


def send(channel: str, message: str) -> Dict[str, Any]:
    text = (message or "").strip()[:MAX_MESSAGE]
    if not text:
        return {"ok": False, "error": "Пустое сообщение"}

    if channel == TEAM:
        if TEAM in chat_store.PENDING:
            return {"ok": False, "error": "Команда ещё отвечает, подождите немного."}
        pm = workflow.pick_pm()
        if not pm:
            return {"ok": False, "error": "В офисе нет агентов. Добавьте их в Настройках."}

        # "/auto цель" - автопилот: команда сама доводит новый проект до цели
        if text.lower().startswith("/auto"):
            goal = text[5:].strip()
            if not goal:
                return {"ok": False, "error": "После /auto опишите цель, например: /auto Интернет-магазин с корзиной"}
            from . import autopilot
            result = autopilot.start(goal, current_project=False)
            if result["ok"]:
                chat_store.append(TEAM, "user", text)
            return result

        # "/new описание" - явно начать новый проект с чистой доской
        force_new = text.lower().startswith("/new")
        idea = text[4:].strip() if force_new else text
        if force_new and not idea:
            return {"ok": False, "error": "После /new опишите проект, например: /new Консольная игра на Python"}

        # обратились по имени: отвечают именно эти агенты (а не PM), прямо в общем канале
        named = [] if force_new else addressed_agents(text)
        if named:
            chat_store.append(TEAM, "user", text, to=named)
            chat_store.PENDING.add(TEAM)
            dispatcher.spawn(answer_addressed(named, text))
            return {"ok": True, "to": named}

        # новый проект - по /new или когда работать не с чем: ни задач, ни выбранного проекта.
        # Если проект выбран, а доска пустая (например, после сброса), это просьба о доработке
        folder = state.get("project_dir") or ""
        has_project = bool(folder) and (config_store.workspace_dir() / folder).is_dir()
        if force_new or (not tasks_store.scan_all() and not has_project):
            result = start_project(idea)
            if result["ok"]:
                chat_store.append(TEAM, "user", text)
                chat_store.team_note("Принял! Составляю план проекта и раздам задачи команде.")
            return result

        # проект уже есть - считаем сообщение просьбой о доработке и отдаём PM
        chat_store.append(TEAM, "user", text)
        chat_store.PENDING.add(TEAM)
        dispatcher.spawn(process_chat_message(pm["id"], text, TEAM))
        return {"ok": True}

    if not runtime.agent(channel):
        return {"ok": False, "error": "Агент не найден"}
    if channel in chat_store.PENDING:
        return {"ok": False, "error": "Агент ещё отвечает, подождите немного."}
    chat_store.append(channel, "user", text)
    chat_store.PENDING.add(channel)
    dispatcher.spawn(process_chat_message(channel, text))
    return {"ok": True}
