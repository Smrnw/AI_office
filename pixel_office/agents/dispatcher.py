"""Диспетчер доски задач.

Один общий цикл: каждый свободный агент берёт следующую работу своей роли (код - разработчики,
проверку - тестировщики), пока всё не окажется в done. Руководитель с доски не берёт.

Задача живёт в двух местах: файл на диске (его видит канбан и человек в проводнике) и словарь
в BOARD (его видит диспетчер). Меняем задачу только через tasks_store.save_task, чтобы они не разъехались.
"""
import asyncio
import time
from typing import Any, Dict, List, Optional, Tuple

from .. import checks, config_store, notify, runtime, tasks_store, workspace
from ..config_store import ConfigError
from ..llm import Cancelled, call_llm, extract_code, extract_json
from ..runtime import STATUS_BUSY, STATUS_FREE, IDLE_ACTION, CHAT_ACTION, state
from . import roles
from .prompts import CODE_PROMPT, REVIEW_PROMPT

MAX_TASK_ATTEMPTS = 6        # после стольких возвратов на доработку задачу принимаем с пометкой
MAX_REVIEW_FAILS = 3         # сколько раз QA может не ответить подряд, прежде чем примем без ревью
MAX_AGENT_STRIKES = 8        # подряд ошибок провайдера у одного агента, после которых работу останавливаем
IDLE_POLL = 0.3
WATCHDOG_PERIOD = 2.0        # как часто сверяем доску с папками задач на диске

BOARD: List[Dict[str, Any]] = []
_dispatcher: Optional[asyncio.Task] = None
_BG: set = set()             # ссылки на фоновые задачи, чтобы их не собрал GC


class TaskBusyError(RuntimeError):
    """Над задачей прямо сейчас работает агент."""


def spawn(coro) -> asyncio.Task:
    task = asyncio.get_running_loop().create_task(coro)
    _BG.add(task)
    task.add_done_callback(_BG.discard)
    return task


# -------------------------------------------------------------------------
# Доска
# -------------------------------------------------------------------------

def open_tasks() -> List[Dict[str, Any]]:
    return [t for t in BOARD if t["status"] != "done" and not t.get("_dead")]


def board_find(task_file: str) -> Optional[Dict[str, Any]]:
    return next((t for t in BOARD if t.get("task_file") == task_file and not t.get("_dead")), None)


def board_add(tasks: List[Dict[str, Any]]) -> None:
    """Кладёт задачи на доску. Если задача с таким файлом уже есть и никем не занята, заменяем её."""
    for t in tasks:
        t.setdefault("_busy", False)
        t.setdefault("worker", "")
        for i, old in enumerate(BOARD):
            if old.get("task_file") == t.get("task_file"):
                if not old.get("_busy"):
                    BOARD[i] = t
                break
        else:
            BOARD.append(t)


def kill_board() -> None:
    """Сброс доски: задачи, над которыми ещё работают, помечаются мёртвыми и на диск больше не пишутся."""
    for t in BOARD:
        t["_dead"] = True
    BOARD.clear()


def _from_disk(t: Dict[str, Any]) -> Dict[str, Any]:
    t.pop("raw_content", None)
    if t["status"] == "in_progress":          # кодера прервали, начинаем с начала
        t["status"] = "todo"
    t["is_revision"] = workspace.is_valid_name(t["filename"]) and workspace.safe_path(t["filename"]).exists()
    t["_busy"] = False
    t["worker"] = ""
    return t


def resume_from_disk() -> int:
    """Подхватывает с диска незавершённые задачи (после перезапуска сервера или после остановки)."""
    known = {t.get("task_file") for t in BOARD}
    added = 0
    for t in tasks_store.scan_all():
        if t["status"] == "done" or t["task_file"] in known:
            continue
        if not workspace.is_valid_name(t["filename"]):
            continue                           # странное имя файла, такую задачу не берём
        BOARD.append(_from_disk(t))
        added += 1
    return added


def tasks_with_runtime() -> List[Dict[str, Any]]:
    """Задачи с диска плюс признак, что над ними прямо сейчас кто-то работает (для спиннеров)."""
    live = {t.get("task_file"): t for t in BOARD}
    out = []
    for t in tasks_store.scan_all():
        t.pop("raw_content", None)
        t.pop("history", None)
        b = live.get(t["task_file"])
        t["busy"] = bool(b and b.get("_busy"))
        t["worker"] = b.get("worker", "") if t["busy"] else ""
        t["spec"] = t["spec"][:300]
        out.append(t)
    return out


def dispatcher_alive() -> bool:
    return _dispatcher is not None and not _dispatcher.done()


def ensure_dispatcher() -> None:
    global _dispatcher
    if not dispatcher_alive():
        _dispatcher = spawn(dispatcher_main())


# -------------------------------------------------------------------------
# Кто что берёт
# -------------------------------------------------------------------------

def _other_idle(agent_id: str) -> bool:
    """Есть ли ещё кто-то свободный, кто возьмёт работу вместо этого агента."""
    busy = {t.get("worker") for t in BOARD if t.get("_busy")}
    return any(a["id"] != agent_id and a["id"] not in busy for a in runtime.agents_list())


def _close_unreviewed() -> None:
    """QA в штате нет (например, его уволили): проверять некому, такие задачи закрываем."""
    for t in BOARD:
        if t["status"] == "testing" and not t.get("_busy") and not t.get("_dead"):
            t["qa_notes"] = "✅ Без QA: код сохранён"
            tasks_store.save_task(t, "done", "QA-агентов нет, задача закрыта без ревью.")


def claim_job(agent_id: str) -> Optional[Tuple[str, Dict[str, Any]]]:
    """Выбирает для агента следующую работу и сразу помечает задачу занятой. None - работы пока нет."""
    agent = runtime.agent(agent_id)
    if not agent:
        return None
    staff = {a["pipeline_type"] for a in runtime.agents_list()}
    qa_exists = "qa" in staff
    if not qa_exists:
        _close_unreviewed()
    # каждый делает свою работу: код пишут разработчики, проверяет QA, руководитель только планирует.
    # Чужую работу берут, лишь когда в штате нет никого с нужной ролью.
    kind_of = agent["pipeline_type"]
    if kind_of == "coder":
        order = ("code",)
    elif kind_of == "qa":
        order = ("review",) if "coder" in staff else ("review", "code")
    else:
        order = () if "coder" in staff else ("code",)
    # специалисты сначала берут файлы своего профиля, остальные - файлы, для которых специалиста нет
    present = {a.get("specialty") for a in runtime.agents_list() if a.get("specialty")}
    candidates = sorted(open_tasks(), key=lambda x: (roles.code_priority(agent, x.get("filename", ""), present), x["id"]))
    for kind in order:
        for t in candidates:
            if t.get("_busy"):
                continue
            if kind == "code" and t["status"] == "todo":
                pass
            elif kind == "review" and t["status"] == "testing" and qa_exists:
                # свой код автор не проверяет, пока есть кому ещё; если все заняты, проверит сам
                if t.get("last_coder") == agent_id and _other_idle(agent_id):
                    continue
            else:
                continue
            t["_busy"] = True
            t["worker"] = agent_id
            return kind, t
    return None


def work_prompt(agent: Dict[str, Any], kind: str) -> str:
    me = f"Тебя зовут {agent['id']}, твоя должность: {agent.get('role') or agent['pipeline_type']}.\n"
    return me + roles.system_prompt(agent, config_store.get())


def free_agent(agent_id: str, note: str = IDLE_ACTION) -> None:
    cur = runtime.agent(agent_id)
    # если агент как раз отвечает в чате, его статус не трогаем
    if cur and cur["action"] != CHAT_ACTION:
        runtime.set_agent(agent_id, STATUS_FREE, note)


def fail_run(message: str) -> None:
    """Останавливает всех работников: дальше повторять бессмысленно (нет ключа, провайдер лежит)."""
    state["dispatch_error"] = message
    state["cancel_requested"] = True
    state["paused"] = True
    runtime.add_log(f"⚠️ [Диспетчер] {message}")
    notify.notify("errors", notify.subject("работа остановилась", "work stopped"), message)


def send_back(task: Dict[str, Any], who: str, reason: str, note: str) -> None:
    """Возвращает задачу в очередь. Если попыток слишком много, принимаем с пометкой,
    иначе очередь никогда не закончится."""
    task["feedback"] = reason
    if task["attempts"] >= MAX_TASK_ATTEMPTS:
        task["qa_notes"] = f"⚠️ Принято после {task['attempts']} попыток, замечание: {reason[:110]}"
        tasks_store.save_task(task, "done", f"Принято с замечаниями после {task['attempts']} попыток. Последнее замечание: {reason}")
        runtime.add_log(f"☑️ [{task['filename']}] Принято с замечаниями после {task['attempts']} попыток")
    else:
        task["qa_notes"] = f"{note}: {reason[:110]}"
        tasks_store.save_task(task, "todo", f"{who} вернул задачу на доработку: {reason}")
        runtime.add_log(f"↩️ [{who}] Вернул #{task['id']} в очередь: {reason[:100]}")


# -------------------------------------------------------------------------
# Работа над задачей
# -------------------------------------------------------------------------

MAX_CODE_IN_PROMPT = 60000


def clip_code(code: str) -> str:
    """Файл для промпта. Огромный обрезаем, но прямо пишем модели, что это не обрыв файла:
    иначе ревьюер возвращает задачу с замечанием «код обрывается»."""
    if len(code) <= MAX_CODE_IN_PROMPT:
        return code
    return (code[:MAX_CODE_IN_PROMPT] + f"\n\n[Показаны первые {MAX_CODE_IN_PROMPT} из {len(code)} символов. "
            "Файл длиннее и не обрывается - не считай это ошибкой.]")


def _idea() -> str:
    return state["project_idea"] or "Существующий проект в рабочей папке"


# ---- агент сначала доходит до стола, потом работает

WALK_TIMEOUT = 20.0          # дольше не ждём: вкладку могли закрыть или агенту не досталось места
VIEWER_FRESH = 6.0           # офис считается открытым, если вкладка опрашивала сервер недавно
_arrivals: Dict[str, asyncio.Event] = {}


def mark_arrived(agent_id: str) -> None:
    ev = _arrivals.get(agent_id)
    if ev:
        ev.set()


async def walk_to_desk(agent_id: str, purpose: str) -> None:
    """Пока офис открыт в браузере, работа начинается только когда человечек сел за стол:
    иначе он ещё идёт, а задача уже сделана. Если офис никто не смотрит, ждать некого."""
    if time.time() - state["viewer_seen_at"] > VIEWER_FRESH:
        return
    ev = asyncio.Event()
    _arrivals[agent_id] = ev
    runtime.set_agent(agent_id, runtime.STATUS_WALK, f"Идёт к столу: {purpose}")
    try:
        await asyncio.wait_for(ev.wait(), WALK_TIMEOUT)
    except asyncio.TimeoutError:
        pass
    finally:
        if _arrivals.get(agent_id) is ev:
            _arrivals.pop(agent_id, None)


async def code_step(agent: Dict[str, Any], task: Dict[str, Any]) -> None:
    await walk_to_desk(agent["id"], task["filename"])
    if task.get("_dead"):
        return
    attempt = int(task.get("attempts") or 0) + 1
    task["attempts"] = attempt
    task["last_coder"] = agent["id"]
    task["assigned_to"] = agent["id"]

    label = f"Пишет {task['filename']}" if attempt == 1 else f"Фиксит {task['filename']} (#{attempt})"
    tasks_store.save_task(task, "in_progress", f"Агент {agent['id']} ({agent.get('model_name', '')}) взял задачу, попытка {attempt}")
    runtime.set_agent(agent["id"], STATUS_BUSY, label)
    runtime.add_log(f"💻 [{agent['id']}] Берёт #{task['id']} → in_progress ({task['filename']}, попытка {attempt})")

    feedback = task.get("feedback") or ""
    fix_block = f"\n\nВНИМАНИЕ! Исправь замечания:\n{feedback}" if feedback else ""

    # при доработке и повторных попытках кодер видит текущий код файла
    existing_block = ""
    path = workspace.safe_path(task["filename"])
    if (task.get("is_revision") or attempt > 1) and path.is_file():
        code_now = path.read_text(encoding="utf-8", errors="replace")
        existing_block = "\n\nТекущий код файла (внеси нужные изменения и верни файл ЦЕЛИКОМ):\n" + clip_code(code_now)

    architecture = "\n".join(
        f"- {t['filename']}: {t['title']} ({str(t.get('spec', ''))[:200]})" for t in BOARD if not t.get("_dead"))
    prompt = CODE_PROMPT.format(idea=_idea(), architecture=architecture, filename=task["filename"],
                                title=task["title"], spec=task["spec"], fix_block=fix_block,
                                existing_block=existing_block)
    raw = await call_llm(agent["model_ref"], work_prompt(agent, "code"), prompt, purpose="code",
                         meta={"filename": task["filename"], "title": task["title"], "spec": task["spec"],
                               "idea": _idea(), "feedback": feedback, "attempts": attempt})
    code = extract_code(raw)
    if not code.strip():
        raise RuntimeError("Модель вернула пустой ответ")
    if task.get("_dead"):
        return                                   # доску сбросили, пока агент думал

    workspace.write_text(task["filename"], code)
    state["metrics"]["files_saved"] += 1
    runtime.add_log(f"💾 [{agent['id']}] Сохранил {task['filename']} ({len(code)} симв.)")

    # синтаксис проверяем сразу: гонять QA по файлу, который не компилируется, нет смысла
    syntax_err = await workspace.check_syntax(path)
    if syntax_err:
        send_back(task, agent["id"], f"Синтаксическая ошибка:\n{syntax_err}", "❌ Ошибка компиляции")
        return

    if any(a["pipeline_type"] == "qa" for a in runtime.agents_list()):
        tasks_store.save_task(task, "testing", f"Код готов, ждёт проверки QA (автор {agent['id']})")
        runtime.add_log(f"🔍 Задача #{task['id']} передана на проверку")
    else:
        task["qa_notes"] = "✅ Без QA: код сохранён"
        tasks_store.save_task(task, "done", f"Разработка завершена без QA. Код сохранён в {task['filename']}.")
        runtime.add_log(f"✅ Задача #{task['id']} готова")


async def review_step(agent: Dict[str, Any], task: Dict[str, Any]) -> None:
    await walk_to_desk(agent["id"], "ревью " + task["filename"])
    if task.get("_dead"):
        return
    runtime.set_agent(agent["id"], STATUS_BUSY, f"Ревью {task['filename']}")
    runtime.add_log(f"🔍 [{agent['id']}] Проверяет #{task['id']} ({task['filename']})")
    try:
        code = workspace.read_text(task["filename"])
    except (OSError, ValueError):
        code = ""
    if not code.strip():
        send_back(task, agent["id"], "Файл не найден или пуст", "❌ Нет файла")
        return

    # правила безопасности по тексту файла: явные ошибки (ключи в коде, eval(input())) возвращаем сразу,
    # предупреждения показываем QA, чтобы он решил, критично ли это для задачи
    found = checks.quick_file_check(workspace.safe_path(task["filename"]), task["filename"])
    errors = [f for f in found if f.level == "error"]
    if errors:
        send_back(task, agent["id"], "Проверка безопасности: " + "; ".join(f.text() for f in errors), "❌ Небезопасный код")
        return
    prompt = REVIEW_PROMPT.format(filename=task["filename"], idea=_idea(), spec=task["spec"], code=clip_code(code))
    if found:
        prompt += "\nАвтоматическая проверка безопасности предупреждает:\n" + "\n".join("- " + f.text() for f in found)
    try:
        raw = await call_llm(agent["model_ref"], work_prompt(agent, "review"), prompt, json_mode=True,
                             purpose="review", meta={"filename": task["filename"], "attempts": task.get("attempts", 1)})
        verdict = extract_json(raw)
        if not isinstance(verdict, dict):
            raise ValueError("QA вернул не JSON-объект")
    except (asyncio.CancelledError, Cancelled, ConfigError):
        raise
    except Exception as e:
        # QA не ответил или ответил мусором. Пробуем ещё раз, но не бесконечно.
        task["review_fails"] = int(task.get("review_fails") or 0) + 1
        if task["review_fails"] >= MAX_REVIEW_FAILS:
            task["qa_notes"] = f"⚠️ Принято без ревью: QA не ответил ({str(e)[:70]})"
            tasks_store.save_task(task, "done", f"QA-ревью не удалось {task['review_fails']} раза: {e}. Синтаксис корректен.")
            runtime.add_log(f"⚠️ [{agent['id']}] Ревью #{task['id']} не удалось, задача принята без него: {e}")
        else:
            runtime.add_log(f"⚠️ [{agent['id']}] Ревью #{task['id']} не удалось ({e}), попробуем ещё раз")
        return
    if task.get("_dead"):
        return

    passed = verdict.get("passed", True)
    passed = passed if isinstance(passed, bool) else str(passed).strip().lower() in ("true", "1", "yes", "да")
    reason = str(verdict.get("reason") or "Код проверен")[:600]
    if passed:
        task["qa_notes"] = f"✅ QA OK: {reason}"
        task["feedback"] = ""
        tasks_store.save_task(task, "done", f"QA {agent['id']} одобрил задачу: {reason}")
        runtime.add_log(f"✅ [{agent['id']}] Одобрил #{task['id']} ({task['filename']})")
    else:
        send_back(task, agent["id"], reason, "⚠️ Замечание QA")


def _return_to_queue(task: Dict[str, Any], why: str) -> None:
    """Код не дописан: возвращаем задачу в очередь, попытку не засчитываем."""
    if task["status"] == "in_progress" and not task.get("_dead"):
        task["attempts"] = max(0, int(task.get("attempts") or 1) - 1)
        tasks_store.save_task(task, "todo", why)


async def worker_loop(agent_id: str, session: Dict[str, bool]) -> None:
    """Работа одного агента: берёт задачу, делает, берёт следующую.
    Выходит по команде диспетчера, при остановке или если агента уволили."""
    strikes = 0
    while not session["stop"] and not state["cancel_requested"]:
        agent = runtime.agent(agent_id)
        if agent is None:
            return
        job = claim_job(agent_id)
        if job is None:
            if agent["status"] != STATUS_FREE and agent["action"] != CHAT_ACTION:
                free_agent(agent_id)
            await asyncio.sleep(IDLE_POLL)
            continue

        kind, task = job
        state["metrics"]["sub_agents"] += 1
        try:
            if kind == "code":
                await code_step(agent, task)
            else:
                await review_step(agent, task)
            strikes = 0
            cur = runtime.agent(agent_id)
            if cur:
                cur["done"] = cur.get("done", 0) + 1
        except (asyncio.CancelledError, Cancelled):
            _return_to_queue(task, "Работа была остановлена, задача вернулась в очередь")
            return
        except ConfigError as e:
            _return_to_queue(task, f"Ошибка настроек: {e}")
            fail_run(str(e))
            return
        except workspace.WorkspaceError as e:
            # имя файла не годится: повторять бессмысленно, закрываем задачу с пометкой
            task["qa_notes"] = f"❌ {e}"
            tasks_store.save_task(task, "done", f"Задача закрыта: {e}")
            runtime.add_log(f"❌ [{agent_id}] #{task['id']}: {e}")
        except Exception as e:
            # ошибка провайдера или сети: задача возвращается в очередь, агент немного ждёт и идёт дальше
            strikes += 1
            runtime.add_log(f"⚠️ [{agent_id}] Ошибка при работе над #{task['id']}: {str(e)[:200]}")
            if kind == "code":
                task["qa_notes"] = f"⚠️ Ошибка: {str(e)[:100]}"
                _return_to_queue(task, f"Ошибка при выполнении: {e}")
            if strikes >= MAX_AGENT_STRIKES:
                fail_run(f"Провайдер не отвечает: {MAX_AGENT_STRIKES} ошибок подряд у {agent_id} ({str(e)[:120]})")
                return
            await asyncio.sleep(min(20, 2 * strikes))
        finally:
            state["metrics"]["sub_agents"] = max(0, state["metrics"]["sub_agents"] - 1)
            task["_busy"] = False
            task["worker"] = ""
            free_agent(agent_id)


async def dispatcher_main() -> None:
    runtime.begin_job()
    try:
        # хвосты прерванной работы: незавершённый кодинг возвращаем в очередь
        for t in BOARD:
            t["_busy"] = False
            t["worker"] = ""
            if t["status"] == "in_progress" and not t.get("_dead"):
                tasks_store.save_task(t, "todo", "Работа была прервана, задача вернулась в очередь")

        # Сессия живёт, пока на доске есть что делать. Когда всё в done, ждём секунду (вдруг
        # прилетит новая доработка) и закрываемся. Если за это время задачи появились, начинаем заново.
        while not state["cancel_requested"] and open_tasks():
            if not runtime.agents_list():
                fail_run("В офисе нет агентов: наймите сотрудников в Настройках")
                return
            session = {"stop": False}
            crew: Dict[str, asyncio.Task] = {}

            def staff():
                # новые сотрудники подключаются к работе на ходу
                for a in runtime.agents_list():
                    if a["id"] not in crew or crew[a["id"]].done():
                        crew[a["id"]] = spawn(worker_loop(a["id"], session))

            staff()
            quiet_since = None
            while not state["cancel_requested"]:
                await asyncio.sleep(IDLE_POLL)
                staff()
                if open_tasks():
                    quiet_since = None
                elif quiet_since is None:
                    quiet_since = time.monotonic()
                elif time.monotonic() - quiet_since > 1.0:
                    break
            session["stop"] = True
            if state["cancel_requested"]:
                for c in crew.values():
                    c.cancel()
            await asyncio.gather(*crew.values(), return_exceptions=True)
    finally:
        runtime.finish_job()


async def drive_tasks(tasks: List[Dict[str, Any]]) -> bool:
    """Отдаёт задачи диспетчеру и ждёт, пока все они дойдут до done. False - если работу остановили."""
    board_add(tasks)
    ensure_dispatcher()
    while any(t["status"] != "done" and not t.get("_dead") for t in tasks):
        if state["cancel_requested"]:
            return False
        ensure_dispatcher()     # на случай, если диспетчер успел завершиться между проверками
        await asyncio.sleep(0.5)
    return not any(t.get("_dead") for t in tasks)


async def board_watchdog() -> None:
    """Сторож доски. После запуска сервера подхватывает задачи, оставшиеся на диске,
    а дальше следит: если на доске есть незавершённое, а диспетчер молчит (и пользователь
    не нажимал СТОП), запускает его снова."""
    await asyncio.sleep(2)
    found = resume_from_disk()
    if found and not state["paused"]:
        runtime.add_log(f"▶ После запуска сервера нашёл незавершённых задач: {found}. Продолжаю работу.")
        ensure_dispatcher()
    from . import staffing                  # staffing сам опирается на доску диспетчера
    staffing.ensure_desks()
    while True:
        try:
            staffing.tick()
            if sync_from_disk():
                wake_for_manual_return()
            elif not state["paused"] and not state["cancel_requested"] and not dispatcher_alive() and open_tasks():
                runtime.add_log(f"▶ Диспетчер был остановлен, а задач в работе: {len(open_tasks())}. Запускаю снова.")
                ensure_dispatcher()
        except Exception as e:
            print(f"Сбой сторожа доски: {e}", flush=True)
        await asyncio.sleep(WATCHDOG_PERIOD)


# -------------------------------------------------------------------------
# Ручное управление задачами из интерфейса
# -------------------------------------------------------------------------

def wake_for_manual_return() -> None:
    """Человек сам вернул задачу в работу - это явная команда, поэтому снимаем паузу и будим диспетчер.
    Если диспетчер как раз останавливается, он увидит снятый флаг и продолжит с новыми задачами."""
    if state["paused"] or state["cancel_requested"]:
        runtime.add_log("▶ Задачу вернули в работу вручную — снимаю паузу")
    state["paused"] = False
    state["cancel_requested"] = False
    state["dispatch_error"] = ""
    ensure_dispatcher()


def _prepare_manual_return(task: Dict[str, Any], status: str, comment: str) -> str:
    """Возвращённая задача начинает с чистого листа: счётчик попыток обнуляется, иначе после
    первого же замечания QA её сразу «приняли бы с замечаниями». Комментарий получит кодер."""
    task["review_fails"] = 0
    task["is_revision"] = workspace.is_valid_name(task["filename"]) and workspace.safe_path(task["filename"]).exists()
    note = "↩ Возвращено вручную" + (f": {comment}" if comment else "")
    if status == "todo":
        task["attempts"] = 0
        task["feedback"] = comment
        task["qa_notes"] = note
    elif status == "testing":
        task["qa_notes"] = note
    return "Перемещено вручную" + (f". Комментарий заказчика: {comment}" if comment else "")


def sync_from_disk() -> int:
    """Сверяет доску с папками задач. Ловит то, что человек сделал руками в проводнике:
    перенёс файл задачи в другую папку, положил новый или удалил. Возвращает, сколько задач
    стало открытыми (их надо брать в работу)."""
    disk = {t["task_file"]: t for t in tasks_store.scan_all()}
    reopened = 0
    for t in list(BOARD):
        if t.get("_busy") or t.get("_dead"):
            continue
        d = disk.get(t["task_file"])
        if d is None:                                   # файл удалили руками
            t["_dead"] = True
            BOARD.remove(t)
            continue
        status = "todo" if d["status"] == "in_progress" else d["status"]
        if status == t["status"]:
            continue
        was_open = t["status"] != "done"
        for k in ("title", "filename", "spec", "history", "assigned_to"):
            t[k] = d[k]
        if not workspace.is_valid_name(t["filename"]):
            continue
        t["status"] = status
        if status != "done" and not was_open:
            log = _prepare_manual_return(t, status, "")
            tasks_store.save_task(t, status, log + " (файл перенесён в папке)")
            runtime.add_log(f"📂 Задача #{t['id']} вручную возвращена в {status}")
            reopened += 1
    known = {t.get("task_file") for t in BOARD}
    for name, d in disk.items():
        if name in known or d["status"] == "done" or not workspace.is_valid_name(d["filename"]):
            continue
        BOARD.append(_from_disk(d))
        runtime.add_log(f"📂 Найдена новая задача #{d['id']} ({d['filename']}) в папке {d['status']}")
        reopened += 1
    return reopened


def manual_update(task_file: str, new_status: str, raw_content: Optional[str] = None,
                  comment: str = "") -> Dict[str, Any]:
    """Перенос задачи в другую колонку (и, по желанию, правка её текста) с синхронизацией доски."""
    if new_status not in tasks_store.KANBAN_STATUSES:
        raise ValueError("Недопустимый статус задачи")
    if new_status == "in_progress":
        raise ValueError("В работу задачи берут сами агенты: переместите задачу в очередь")
    live = board_find(task_file)
    if live and live.get("_busy"):
        raise TaskBusyError(f"Над задачей сейчас работает {live.get('worker')}, подождите")
    path = tasks_store.find_task_path(task_file)
    if not path:
        raise FileNotFoundError(task_file)

    raw = raw_content if raw_content is not None else path.read_text(encoding="utf-8", errors="replace")
    parsed = tasks_store.parse_task_text(raw, path.name, path.parent.name)
    if not workspace.is_valid_name(parsed["filename"]):
        raise workspace.WorkspaceError(f"Недопустимое имя файла кода: {parsed['filename']}")
    parsed.pop("raw_content", None)

    task = live if live else parsed
    if live:
        for k in ("title", "filename", "spec", "history", "qa_notes", "attempts", "assigned_to"):
            live[k] = parsed[k]
    comment = (comment or "").strip()[:4000]
    reopen = new_status in ("todo", "testing")
    log = _prepare_manual_return(task, new_status, comment) if reopen else "Перемещено вручную"
    target = tasks_store.save_task(task, new_status, log)
    if not live and new_status != "done":
        BOARD.append(_from_disk(task))
    runtime.add_log(f"📂 Задача #{task['id']} перемещена в {new_status}" + (f": {comment[:80]}" if comment else ""))
    if reopen:
        wake_for_manual_return()
    return {"new_status": new_status, "task_path": str(target)}


def manual_delete(task_file: str) -> None:
    live = board_find(task_file)
    if live and live.get("_busy"):
        raise TaskBusyError(f"Над задачей сейчас работает {live.get('worker')}, подождите")
    if live:
        live["_dead"] = True
        BOARD.remove(live)
    if not tasks_store.delete_task_file(task_file):
        raise FileNotFoundError(task_file)
    runtime.add_log(f"🗑 Задача {task_file} удалена")
