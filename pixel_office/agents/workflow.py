"""Сценарии работы команды: новый проект от идеи и доработки по запросу из чата."""
import asyncio
import re
import time
from typing import Any, Dict, List, Optional

from .. import checks, config_store, notify, runtime, settings, tasks_store, workspace
from ..llm import Cancelled, call_llm, extract_json
from ..runtime import STATUS_BUSY, STATUS_ERROR, STATUS_FREE, state
from ..storage import read_json, write_json
from . import chat_store, dispatcher, quality, roles
from .prompts import PLAN_PROMPT, TESTS_HINT

PROJECT_PATH = settings.DATA_DIR / "project.json"
PROJECTS_PATH = settings.DATA_DIR / "projects.json"      # идеи всех проектов: папка -> описание
MAX_PLAN_TASKS = 8

_TRANSLIT = dict(zip("абвгдеёжзийклмнопрстуфхцчшщъыьэюя",
                     ["a", "b", "v", "g", "d", "e", "e", "zh", "z", "i", "y", "k", "l", "m", "n", "o", "p", "r", "s", "t",
                      "u", "f", "h", "ts", "ch", "sh", "sch", "", "y", "", "e", "yu", "ya"]))


def load_project_idea() -> None:
    data = read_json(PROJECT_PATH, {})
    if isinstance(data, dict):
        state["project_idea"] = str(data.get("idea") or "")
        folder = str(data.get("dir") or "")
        state["project_dir"] = folder if folder and workspace.is_valid_name(folder) else ""


def save_project_idea(idea: str, folder: str) -> None:
    state["project_idea"] = idea
    state["project_dir"] = folder
    write_json(PROJECT_PATH, {"idea": idea, "dir": folder})
    if folder:
        known = _registry()
        known[folder] = {"idea": idea, "updated": time.time()}
        write_json(PROJECTS_PATH, known)


def _registry() -> Dict[str, Dict[str, Any]]:
    data = read_json(PROJECTS_PATH, {})
    return data if isinstance(data, dict) else {}


def list_projects() -> List[Dict[str, Any]]:
    """Проекты - папки верхнего уровня рабочей директории. Идея берётся из реестра, если проект
    создавала команда; для папок, положенных вручную, вместо идеи - имя папки."""
    ws = config_store.workspace_dir()
    known = _registry()
    out = []
    for d in sorted(p for p in ws.iterdir() if p.is_dir() and p.name not in settings.SKIP_DIRS and not p.name.startswith(".")):
        info = known.get(d.name) if isinstance(known.get(d.name), dict) else {}
        out.append({"folder": d.name, "idea": str(info.get("idea") or d.name), "updated": info.get("updated") or d.stat().st_mtime,
                    "current": d.name == state.get("project_dir")})
    return out


def select_project(folder: str) -> Dict[str, Any]:
    """Сделать папку текущим проектом: доработки, чат и проверка дальше работают с ней."""
    folder = str(folder or "").strip().strip("/")
    match = next((p for p in list_projects() if p["folder"] == folder), None)
    if not match:
        raise ValueError(f"Проект «{folder}» не найден")
    if folder != state.get("project_dir"):
        save_project_idea(match["idea"], folder)
        runtime.add_log(f"📁 Текущий проект: {folder}/")
    return match


def project_folder_name(idea: str) -> str:
    """Каждый проект живёт в своей папке рабочей директории: «Сайт пекарни» -> sayt-pekarni.
    Если такая папка уже есть, добавляем номер, чтобы не перезаписать прошлый проект."""
    text = "".join(_TRANSLIT.get(ch, ch) for ch in idea.lower())
    slug = re.sub(r"[^a-z0-9]+", "-", text).strip("-")[:40].strip("-") or "project"
    ws = workspace.safe_path(slug).parent
    name, n = slug, 2
    while (ws / name).exists():
        name, n = f"{slug}-{n}", n + 1
    return name


def in_project(filename: str, revision: bool) -> str:
    """Путь файла внутри папки текущего проекта. Уже существующие файлы (в том числе старые,
    лежащие в корне рабочей папки) правим там, где они лежат."""
    folder = state.get("project_dir") or ""
    if not folder or filename == folder or filename.startswith(folder + "/"):
        return filename
    if revision and workspace.is_valid_name(filename) and workspace.safe_path(filename).exists():
        return filename
    return f"{folder}/{filename}"


def _tests_hint() -> str:
    opts = checks.options(config_store.get())
    return TESTS_HINT if opts["enabled"] and opts["tests"] and opts["write_tests"] else ""


def pick_pm() -> Optional[Dict[str, Any]]:
    """Руководитель: первый planner, а если его нет, то первый агент."""
    agents = runtime.agents_list()
    return next((a for a in agents if a["pipeline_type"] == "planner"), agents[0] if agents else None)


def normalize_plan(parsed: Any) -> List[Dict[str, Any]]:
    """Нейросети возвращают план по-разному: массив, {"tasks": [...]}, один объект. Приводим к списку."""
    if isinstance(parsed, dict):
        for key in ("tasks", "tickets", "files", "items", "plan"):
            if isinstance(parsed.get(key), list):
                parsed = parsed[key]
                break
        else:
            lists = [v for v in parsed.values() if isinstance(v, list)]
            parsed = lists[0] if lists else ([parsed] if "filename" in parsed else [])
    if not isinstance(parsed, list):
        return []
    return [t for t in parsed if isinstance(t, dict) and str(t.get("filename") or "").strip()][:MAX_PLAN_TASKS]


def _coders(fallback: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [a for a in runtime.agents_list() if a["pipeline_type"] == "coder"] or [fallback]


def ensure_project_folder(items: List[Dict[str, Any]], request_text: str) -> None:
    """Проект не выбран, а просят новые файлы: заводим под них папку по тексту просьбы.
    Уже существующие файлы правим на месте."""
    if state.get("project_dir"):
        return
    new_files = [str(i.get("filename") or "") for i in items
                 if workspace.is_valid_name(str(i.get("filename") or "")) and not workspace.safe_path(str(i["filename"])).exists()]
    if not new_files:
        return
    idea = " ".join(request_text.split()[:6]) or "проект"
    save_project_idea(request_text.strip()[:300] or idea, project_folder_name(idea))
    runtime.add_log(f"📁 Новые файлы пойдут в папку проекта: {state['project_dir']}/")


def build_tasks(items: List[Dict[str, Any]], author: Dict[str, Any], first_id: int, note: str,
                request_text: str = "", revision: bool = False) -> List[Dict[str, Any]]:
    """Создаёт файлы задач в todo/. Плохие пути отбрасываются, задачи на один файл склеиваются."""
    if revision:
        ensure_project_folder(items, request_text)
    coders = _coders(author)
    by_file: Dict[str, Dict[str, Any]] = {}
    created: List[Dict[str, Any]] = []
    for item in items:
        filename = str(item.get("filename") or "").strip().replace("\\", "/").lstrip("/")
        if workspace.is_valid_name(filename):
            filename = in_project(filename, revision)
        if not workspace.is_valid_name(filename):
            runtime.add_log(f"⚠️ {author['id']} предложил недопустимый путь '{filename[:80]}' — задача пропущена")
            continue
        spec = str(item.get("spec") or "").strip()
        if request_text:
            spec = (spec + f"\n\nЗапрос заказчика в чате: {request_text}").strip()
        if filename in by_file:                       # два пункта про один файл - одна задача
            by_file[filename]["spec"] += "\n\n" + spec
            continue
        assigned = author["id"] if (revision and author["pipeline_type"] == "coder") else coders[len(created) % len(coders)]["id"]
        task = {
            "id": first_id + len(created),
            "title": str(item.get("title") or f"Файл {filename}")[:120],
            "filename": filename,
            "spec": spec,
            "status": "todo",
            "assigned_to": assigned,
            "attempts": 0,
            "qa_notes": "",
            "history": "",
            "is_revision": revision or workspace.safe_path(filename).exists(),
        }
        by_file[filename] = task
        created.append(task)
    for task in created:
        path = tasks_store.save_task(task, "todo", f"{note}, исполнитель: {task['assigned_to']}")
        runtime.add_log(f"📌 Создана задача #{task['id']} {task['filename']} → {task['assigned_to']}"
                        + (f" ({path.name})" if path else ""))
    # на доску кладём сразу, без await между записью файла и этим местом: иначе сторож,
    # сверяющий доску с диском, успел бы завести свою копию задачи
    dispatcher.board_add(created)
    return created


# -------------------------------------------------------------------------
# Новый проект
# -------------------------------------------------------------------------

async def run_company_workflow(idea: str) -> None:
    runtime.begin_job()
    state["cancel_requested"] = False
    state["paused"] = False
    state["dispatch_error"] = ""
    save_project_idea(idea, project_folder_name(idea))
    runtime.add_log(f"📁 Папка проекта: {state['project_dir']}/")
    pm = None
    try:
        pm = pick_pm()
        if not pm:
            runtime.add_log("⚠️ В офисе нет агентов! Откройте Настройки → Агенты и наймите сотрудников.")
            chat_store.team_note("⚠️ В офисе нет агентов. Наймите сотрудников в Настройках.")
            return

        await dispatcher.walk_to_desk(pm["id"], "план проекта")
        runtime.set_agent(pm["id"], STATUS_BUSY, "Декомпозирует проект...")
        runtime.add_log(f"📋 [{pm['id']}] ({pm.get('model_name', '')}) Планирует задачи для: '{idea[:120]}'")
        me = f"Тебя зовут {pm['id']}, твоя должность: {pm.get('role') or 'руководитель'}.\n"
        raw = await call_llm(pm["model_ref"], me + roles.system_prompt(pm, config_store.get()),
                             PLAN_PROMPT.format(idea=idea, tests_hint=_tests_hint()), json_mode=True, purpose="plan", meta={"idea": idea})
        items = normalize_plan(extract_json(raw))
        if not items:
            raise ValueError("PM не вернул список задач. Попробуйте переформулировать идею или сменить модель.")

        dispatcher.kill_board()
        tasks_store.clear_all()
        created = build_tasks(items, pm, 401, f"Задача создана руководителем {pm['id']}")
        if not created:
            raise ValueError("Ни одна задача из плана не прошла проверку имён файлов")

        runtime.set_agent(pm["id"], STATUS_FREE, f"Создал задач: {len(created)}")
        files = ", ".join(t["filename"] for t in created)
        chat_store.team_say(pm["id"], f"План готов, задач: {len(created)} ({files}). Раздаю команде.", created)
        await asyncio.sleep(0.6)

        finished = await dispatcher.drive_tasks(created)
        if state["dispatch_error"]:
            raise RuntimeError(state["dispatch_error"])
        if not finished:
            runtime.add_log("🛑 Выполнение проекта остановлено пользователем.")
            chat_store.team_note("🛑 Проект на паузе. Кнопка «Продолжить» вернёт задачи в работу.")
        else:
            runtime.add_log("🎉 Все задачи выполнены!")
            rep = await quality.check_and_fix(created)
            if state["cancel_requested"]:
                chat_store.team_note("🛑 Проект на паузе. Кнопка «Продолжить» вернёт задачи в работу.")
                return
            chat_store.team_say(pm["id"], "🎉 Проект готов! Нажмите на файл, чтобы скачать его, "
                                          "или напишите здесь, что доработать.", created)
            notify.notify("project_done", notify.subject("проект готов", "project is ready"), work_summary(idea, created, rep))
    except (asyncio.CancelledError, Cancelled):
        runtime.add_log("🛑 Выполнение остановлено.")
    except Exception as e:
        runtime.add_log(f"⚠️ [Ошибка]: {e}")
        chat_store.team_note(f"⚠️ Проект остановился с ошибкой: {e}")
        notify.notify("errors", notify.subject("проект остановился", "project stopped"),
                      notify.say(f"Проект «{idea}» остановился с ошибкой:\n{e}", f"Project \"{idea}\" stopped with an error:\n{e}"))
        if pm:
            runtime.set_agent(pm["id"], STATUS_ERROR, str(e)[:60])
    finally:
        runtime.finish_job()


# -------------------------------------------------------------------------
# Доработки из чата
# -------------------------------------------------------------------------

def create_revision_tasks(agent: Dict[str, Any], tasks_raw: Any, request_text: str) -> List[Dict[str, Any]]:
    if not isinstance(tasks_raw, list):
        return []
    items = [t for t in tasks_raw[:5] if isinstance(t, dict)]
    return build_tasks(items, agent, tasks_store.next_task_id(),
                       f"Задача создана по запросу из чата (агент {agent['id']})", request_text, revision=True)


def work_summary(idea: str, tasks: List[Dict[str, Any]], rep: Any) -> str:
    """Текст уведомления о готовой работе: что сделано и чем кончилась автопроверка."""
    folder = state.get("project_dir") or ""
    files = "\n".join(f"{_task_icon(t)} {t['filename']}" for t in tasks)
    if rep is None:
        check = notify.say("автопроверка выключена", "automatic check is off")
    elif rep.errors:
        check = notify.say(f"❌ ошибок: {len(rep.errors)}", f"❌ errors: {len(rep.errors)}")
    else:
        check = notify.say("✅ без ошибок", "✅ no errors") + (f", ⚠️ {len(rep.warnings)}" if rep.warnings else "")
    return notify.say(f"Проект: {idea}\nПапка: {folder}/\nЗадач: {len(tasks)}\nПроверка: {check}\n\n{files}",
                      f"Project: {idea}\nFolder: {folder}/\nTasks: {len(tasks)}\nCheck: {check}\n\n{files}")


def _task_icon(task: Dict[str, Any]) -> str:
    q = task.get("qa_notes") or ""
    if task.get("status") == "done":
        return "✅" if q.startswith("✅") or not q else "☑️"
    return "❌" if q.startswith("❌") else "⏸"


async def run_revision_tasks(tasks: List[Dict[str, Any]], origin_id: str, channel: Optional[str] = None) -> None:
    """Отдаёт доработки общему диспетчеру, ждёт, пока они дойдут до done, и пишет отчёт в чат."""
    channel = channel or origin_id
    runtime.begin_job()
    state["paused"] = False
    if not dispatcher.dispatcher_alive():
        # остатки прошлой остановки не должны мешать новой работе
        state["cancel_requested"] = False
        state["dispatch_error"] = ""
    try:
        finished = await dispatcher.drive_tasks(tasks)
        if state["dispatch_error"]:
            chat_store.append(channel, "agent", f"⚠️ Доработка остановилась: {state['dispatch_error']}", author=origin_id)
        elif not finished:
            chat_store.append(channel, "agent", "⏸ Доработка на паузе. Кнопка «Продолжить» вернёт задачи в работу.", author=origin_id)
        else:
            lines = [f"{_task_icon(t)} {t['filename']} — {t.get('qa_notes') or t.get('status')}" for t in tasks]
            chat_store.append(channel, "agent", "Готово! Нажмите на файл, чтобы скачать:\n" + "\n".join(lines), tasks, author=origin_id)
            runtime.add_log(f"🎉 Доработка по запросу из чата завершена ({len(tasks)} задач)")
            rep = await quality.check_and_fix(tasks, channel)
            notify.notify("project_done", notify.subject("доработка готова", "revision is ready"),
                          work_summary(state.get("project_idea") or "", tasks, rep))
    except Exception as e:
        runtime.add_log(f"⚠️ [Доработка]: {e}")
        chat_store.append(channel, "agent", f"⚠️ Ошибка при выполнении доработки: {e}", author=origin_id)
        notify.notify("errors", notify.subject("доработка остановилась", "revision stopped"), str(e))
    finally:
        runtime.finish_job()
