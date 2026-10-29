"""Автопилот: команда сама доводит проект до цели.

Цель -> список проверяемых требований -> круги: версия проекта, оценка руководителем, задачи,
работа и автопроверка. Стоп - цель достигнута, кончились круги, токены или время, либо нажали СТОП.
"""
import asyncio
import time
from typing import Any, Dict, List, Optional

from .. import checks, config_store, notify, runtime, settings, tasks_store, versions, workspace
from ..llm import Cancelled, call_llm, extract_json, usage
from ..runtime import STATUS_BUSY, state
from ..storage import read_json, write_json
from . import chat_store, dispatcher, quality, roles, workflow
from .prompts import AUTOPILOT_REVIEW_PROMPT, REQUIREMENTS_PROMPT

DEFAULTS = {"max_cycles": 5, "max_tokens": 500_000, "max_minutes": 90, "max_tasks": 4}
LIMITS = {"max_cycles": (1, 20), "max_tokens": (10_000, 50_000_000), "max_minutes": (5, 24 * 60), "max_tasks": (1, 8)}
STATE_PATH = settings.DATA_DIR / "autopilot.json"
ACTIVE = ("planning", "review", "working")


def options(cfg: Dict[str, Any]) -> Dict[str, int]:
    raw = cfg.get("autopilot") if isinstance(cfg.get("autopilot"), dict) else {}
    out = dict(DEFAULTS)
    for k, (lo, hi) in LIMITS.items():
        try:
            out[k] = max(lo, min(hi, int(raw.get(k, out[k]))))
        except (TypeError, ValueError):
            pass
    return out


def current() -> Dict[str, Any]:
    """Последний запуск автопилота (идущий или завершённый) - для шапки и чата."""
    if not state.get("autopilot"):
        saved = read_json(STATE_PATH, {})
        if isinstance(saved, dict) and saved:
            if saved.get("status") in ACTIVE:              # сервер перезапускали посреди работы
                saved["status"] = "stopped"
                saved["reason"] = "Офис перезапускали — запустите автопилот снова"
            state["autopilot"] = saved
    return state.get("autopilot") or {}


def is_active() -> bool:
    return current().get("status") in ACTIVE


def _save(ap: Dict[str, Any]) -> None:
    state["autopilot"] = ap
    write_json(STATE_PATH, ap)


def _say(ap: Dict[str, Any], author: str, text: str, tasks: Optional[List[Dict[str, Any]]] = None) -> None:
    progress = {"goal": ap["goal"], "cycle": ap["cycle"], "max_cycles": ap["max_cycles"], "status": ap["status"],
                "requirements": [{"text": r["text"], "done": r["done"], "note": r.get("note", "")} for r in ap["requirements"]]}
    chat_store.append(chat_store.TEAM, "agent", text, tasks, author=author, autopilot=progress)


def _limit_reason(ap: Dict[str, Any], opts: Dict[str, int]) -> str:
    spent = usage.total() - ap["tokens_start"]
    ap["tokens_spent"] = spent
    if spent >= opts["max_tokens"]:
        return f"Потрачен бюджет токенов: {spent} из {opts['max_tokens']}"
    minutes = (time.time() - ap["started_at"]) / 60
    if minutes >= opts["max_minutes"]:
        return f"Вышло время: {minutes:.0f} мин из {opts['max_minutes']}"
    return ""


def _pm_system(pm: Dict[str, Any]) -> str:
    me = f"Тебя зовут {pm['id']}, твоя должность: {pm.get('role') or 'руководитель'}.\n"
    return me + roles.system_prompt(pm, config_store.get())


def _check_errors(folder: str) -> int:
    """Ошибки последней автопроверки. Проверки не было (выключена) - ошибок нет."""
    rep = read_json(checks.report_dir(folder) / "report.json", None)
    return int(rep.get("errors") or 0) if isinstance(rep, dict) else 0


async def make_requirements(pm: Dict[str, Any], goal: str) -> List[Dict[str, Any]]:
    raw = await call_llm(pm["model_ref"], _pm_system(pm), REQUIREMENTS_PROMPT.format(goal=goal),
                         json_mode=True, purpose="requirements", meta={"goal": goal})
    data = extract_json(raw)
    if isinstance(data, dict):
        data = next((v for v in data.values() if isinstance(v, list)), [])
    items = [str(x.get("text") if isinstance(x, dict) else x).strip() for x in (data or [])]
    items = [x for x in items if x][:10]
    if not items:
        raise ValueError("Руководитель не смог составить требования к цели")
    return [{"id": f"R{i + 1}", "text": t[:300], "done": False, "note": ""} for i, t in enumerate(items)]


def _check_summary(folder: str) -> str:
    rep = read_json(checks.report_dir(folder) / "report.json", None)
    if not isinstance(rep, dict):
        return "(проверки ещё не было)"
    lines = [f"ошибок {rep.get('errors', 0)}, предупреждений {rep.get('warnings', 0)}"]
    lines += [f"- [{f.get('level')}] {f.get('file', '')} {f.get('message', '')[:300]}" for f in rep.get("findings", [])[:12]]
    return "\n".join(lines)


async def review(pm: Dict[str, Any], ap: Dict[str, Any], opts: Dict[str, int]) -> Dict[str, Any]:
    reqs = "\n".join(f"{r['id']} [{'выполнено' if r['done'] else 'нет'}] {r['text']}" for r in ap["requirements"])
    prompt = AUTOPILOT_REVIEW_PROMPT.format(
        goal=ap["goal"], folder=ap["folder"], cycle=ap["cycle"], max_cycles=ap["max_cycles"], requirements=reqs,
        check=_check_summary(ap["folder"]), snapshot=workspace.snapshot(folder=ap["folder"], max_total=40000, max_each=8000),
        max_tasks=opts["max_tasks"])
    raw = await call_llm(pm["model_ref"], _pm_system(pm), prompt, json_mode=True,
                         purpose="autopilot", meta={"cycle": ap["cycle"], "requirements": ap["requirements"],
                                                    "folder": ap["folder"]})
    data = extract_json(raw)
    if not isinstance(data, dict):
        raise ValueError("Руководитель ответил не JSON-объектом")
    marks = {str(r.get("id")): r for r in data.get("requirements") or [] if isinstance(r, dict)}
    for r in ap["requirements"]:
        m = marks.get(r["id"])
        if m is not None:
            r["done"] = m.get("done") is True or str(m.get("done")).lower() in ("true", "1", "yes", "да")
            r["note"] = str(m.get("note") or "")[:300]
    return data


async def run(goal: str, folder: Optional[str] = None) -> None:
    """folder=None - новый проект (команда сначала делает его по цели), иначе - доводим существующий."""
    opts = options(config_store.get())
    ap = {"goal": goal[:1000], "folder": folder or "", "cycle": 0, "max_cycles": opts["max_cycles"],
          "requirements": [], "status": "planning", "reason": "", "summary": "",
          "started_at": time.time(), "tokens_start": usage.total(), "tokens_spent": 0}
    _save(ap)
    runtime.add_log(f"🤖 Автопилот запущен: '{goal[:120]}'")
    runtime.begin_job()
    pm = None
    try:
        if folder is None:
            await workflow.run_company_workflow(goal)
            if state["cancel_requested"] or state["dispatch_error"] or not state.get("project_dir"):
                raise Cancelled()
            folder = state["project_dir"]
        else:
            workflow.select_project(folder)
        ap["folder"] = folder
        pm = workflow.pick_pm()
        if not pm:
            raise ValueError("В офисе нет агентов: наймите сотрудников в Настройках")

        await dispatcher.walk_to_desk(pm["id"], "требования к цели")
        runtime.set_agent(pm["id"], STATUS_BUSY, "Составляет требования")
        ap["requirements"] = await make_requirements(pm, goal)
        dispatcher.free_agent(pm["id"])
        _save(ap)
        _say(ap, pm["id"], f"🤖 Автопилот ведёт проект {folder}/. Требования к цели: {len(ap['requirements'])}. "
                           f"Кругов не больше {ap['max_cycles']}.")

        while True:
            if state["cancel_requested"]:
                raise Cancelled()
            if ap["cycle"] >= ap["max_cycles"]:
                ap.update(status="limit", reason=f"Закончились круги: {ap['max_cycles']}")
                break
            reason = _limit_reason(ap, opts)
            if reason:
                ap.update(status="limit", reason=reason)
                break
            ap["cycle"] += 1
            ap["status"] = "review"
            _save(ap)
            versions.snapshot(folder, f"Автопилот, перед кругом {ap['cycle']}")

            await dispatcher.walk_to_desk(pm["id"], "оценка проекта")
            runtime.set_agent(pm["id"], STATUS_BUSY, "Оценивает проект")
            runtime.add_log(f"🤖 [{pm['id']}] Автопилот, круг {ap['cycle']}: оценивает проект {folder}")
            verdict = await review(pm, ap, opts)
            dispatcher.free_agent(pm["id"])
            ap["summary"] = str(verdict.get("summary") or "")[:600]
            ask_client(ap, pm, verdict.get("questions"))
            done = sum(r["done"] for r in ap["requirements"])
            clean = _check_errors(folder) == 0
            if (verdict.get("goal_reached") is True or done == len(ap["requirements"])) and clean:
                ap.update(status="done", reason="Цель достигнута")
                _say(ap, pm["id"], f"🎯 Цель достигнута: выполнено требований {done} из {len(ap['requirements'])}. {ap['summary']}")
                break

            items = [t for t in (verdict.get("next_tasks") or []) if isinstance(t, dict)][:opts["max_tasks"]]
            items = [{**t, "filename": f"{folder}/{str(t.get('filename') or '').lstrip('/')}"
                      if not str(t.get("filename") or "").startswith(folder + "/") else t["filename"]} for t in items]
            tasks = workflow.build_tasks(items, pm, tasks_store.next_task_id(),
                                         f"Задача автопилота, круг {ap['cycle']}", revision=True)
            if not tasks:
                ap.update(status="stopped", reason="Руководитель не предложил следующих задач")
                _say(ap, pm["id"], f"⏸ Автопилот остановился: руководитель не предложил следующих задач. {ap['summary']}")
                break
            ap["status"] = "working"
            _save(ap)
            _say(ap, pm["id"], f"🤖 Круг {ap['cycle']} из {ap['max_cycles']}: выполнено требований {done} из "
                               f"{len(ap['requirements'])}. {ap['summary']}", tasks)
            if not await dispatcher.drive_tasks(tasks):
                raise Cancelled()
            await quality.check_and_fix(tasks)
            if state["dispatch_error"]:
                raise RuntimeError(state["dispatch_error"])

        if ap["status"] == "limit":
            _say(ap, pm["id"], f"⏹ Автопилот остановлен: {ap['reason']}. Выполнено требований "
                               f"{sum(r['done'] for r in ap['requirements'])} из {len(ap['requirements'])}.")
    except (asyncio.CancelledError, Cancelled):
        ap.update(status="stopped", reason="Остановлено заказчиком")
        if pm:
            _say(ap, pm["id"], "🛑 Автопилот остановлен. Версии проекта сохранены — можно откатиться в меню проекта.")
    except Exception as e:
        ap.update(status="error", reason=str(e)[:300])
        runtime.add_log(f"⚠️ [Автопилот] {e}")
        chat_store.team_note(f"⚠️ Автопилот остановился с ошибкой: {e}")
    finally:
        ap["finished_at"] = time.time()
        ap["tokens_spent"] = usage.total() - ap["tokens_start"]
        _save(ap)
        runtime.add_log(f"🤖 Автопилот завершён: {ap['reason'] or ap['status']}")
        done = sum(r["done"] for r in ap["requirements"])
        reqs = "\n".join(("✅ " if r["done"] else "⬜ ") + r["text"] for r in ap["requirements"])
        notify.notify("autopilot", notify.subject("автопилот завершён", "autopilot finished"), notify.say(
            f"Цель: {ap['goal']}\nИтог: {ap['reason'] or ap['status']}\nКругов: {ap['cycle']}, "
            f"требований выполнено: {done} из {len(ap['requirements'])}\n\n{reqs}",
            f"Goal: {ap['goal']}\nResult: {ap['reason'] or ap['status']}\nRounds: {ap['cycle']}, "
            f"requirements met: {done} of {len(ap['requirements'])}\n\n{reqs}"))
        if pm:
            dispatcher.free_agent(pm["id"])
        runtime.finish_job()


def ask_client(ap: Dict[str, Any], pm: Dict[str, Any], questions: Any) -> None:
    """Вопросы, без ответа на которые работа может пойти не туда: в чат и заказчику в уведомления.
    Автопилот не ждёт ответа - продолжает с допущением, а ответ заказчика придёт в чат как доработка."""
    qs = [str(q).strip()[:300] for q in (questions or []) if str(q).strip()] if isinstance(questions, list) else []
    fresh = [q for q in qs[:3] if q not in ap.setdefault("asked", [])]
    if not fresh:
        return
    ap["asked"] += fresh
    text = "\n".join(f"❓ {q}" for q in fresh)
    chat_store.team_say(pm["id"], "Вопросы к вам — ответьте здесь, когда будет время:\n" + text)
    notify.notify("questions", notify.subject("у команды вопрос", "the team has a question"), notify.say(
        f"Проект: {ap['folder']}/\n{text}\n\nОтветьте в чате офиса или боту в Telegram.",
        f"Project: {ap['folder']}/\n{text}\n\nReply in the office chat or to the Telegram bot."))


def start(goal: str, current_project: bool) -> Dict[str, Any]:
    goal = (goal or "").strip()
    if not goal:
        return {"ok": False, "error": "Опишите цель для автопилота"}
    if is_active():
        return {"ok": False, "error": "Автопилот уже работает"}
    if state["is_running"] or state["starting"]:
        return {"ok": False, "error": "Сейчас идёт работа. Дождитесь завершения или нажмите СТОП."}
    if not runtime.agents_list():
        return {"ok": False, "error": "В офисе нет агентов. Наймите сотрудников в Настройках."}
    folder = None
    if current_project:
        folder = state.get("project_dir") or ""
        if not folder:
            return {"ok": False, "error": "Сначала выберите проект"}
    state["cancel_requested"] = False
    state["paused"] = False
    state["dispatch_error"] = ""
    dispatcher.spawn(run(goal, folder))
    return {"ok": True}
