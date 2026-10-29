"""Состояние офиса и управление работой: старт, стоп, продолжение, сброс."""
import time

from fastapi import APIRouter, HTTPException, Request

from .. import __version__, config_store, layout_store, runtime, settings, setup_wizard, tasks_store, versions, workspace
from ..agents import autopilot, chat_store, dispatcher, workflow
from ..agents.chat import start_project
from ..llm import usage
from ..runtime import IDLE_ACTION, STATUS_FREE, state
from .schemas import LanguageRequest, OfficeNameRequest, ProjectRequest, ProjectSelectRequest
from .security import PREVIEW_KEY

router = APIRouter(prefix="/api")


@router.get("/health")
async def health():
    # по полю app запускатель отличает наш офис от чужой программы на том же порту
    return {"ok": True, "app": "pixel-office", "version": __version__}


@router.get("/state")
async def get_state(request: Request, since_event: int = 0):
    # открытая видимая вкладка офиса: значит, человечки ходят, и работу стоит начинать за столом
    if request.headers.get("x-office-viewer") == "1":
        state["viewer_seen_at"] = time.time()
    files = workspace.list_files()
    events = [e for e in state["events"] if e["id"] > since_event] if since_event else state["events"][-120:]
    return {
        "is_running": state["is_running"] or state["starting"],
        "paused": state["paused"],
        "dispatch_error": state["dispatch_error"],
        "office_name": config_store.office_name(),
        "version": __version__,
        "needs_setup": setup_wizard.needs_setup(config_store.get()),
        "language": config_store.language(),
        "project_idea": state["project_idea"],
        "project_dir": state["project_dir"],
        "projects": workflow.list_projects(),
        "versions": versions.list_versions(state["project_dir"])[:10],
        "autopilot": autopilot.current(),
        "layout_request": state.get("layout_request"),
        "run_started_at": state["run_started_at"],
        "server_time": time.time(),
        "config_path": str(settings.CONFIG_PATH),
        "workspace_dir": str(config_store.workspace_dir()),
        "tasks_dir": str(config_store.tasks_dir()),
        "agents": state["agents_runtime"],
        "metrics": {**state["metrics"], "files_total": len(files)},
        "tasks": dispatcher.tasks_with_runtime(),
        "open_tasks": len(dispatcher.open_tasks()),
        "events": events,
        "usage": usage.report(),
        "files": files,
        "dirs": workspace.list_dirs(),
        "models": config_store.get().get("models", []),
        "config": config_store.public_config(),
        "preview_key": PREVIEW_KEY,
        "chat_heads": {ch: msgs[-1]["id"] for ch, msgs in chat_store.CHATS.items() if msgs},
        "layout_rev": layout_store.rev(),
    }


@router.post("/office/name")
async def rename_office(req: OfficeNameRequest):
    return {"ok": True, "name": config_store.set_office_name(req.name)}


@router.post("/project/select")
async def select_project(req: ProjectSelectRequest):
    try:
        return {"ok": True, "project": workflow.select_project(req.folder)}
    except ValueError as e:
        raise HTTPException(404, str(e))


@router.post("/office/language")
async def switch_language(req: LanguageRequest):
    try:
        return {"ok": True, "language": config_store.set_language(req.language)}
    except config_store.ConfigError as e:
        raise HTTPException(400, str(e))


@router.post("/start")
async def start(req: ProjectRequest):
    return start_project(req.idea.strip())


@router.post("/stop")
async def stop():
    state["paused"] = True          # чтобы сторож доски не запустил всё заново сам
    if state["is_running"]:
        state["cancel_requested"] = True
        runtime.add_log("🛑 Запрошена остановка: агенты заканчивают текущие запросы...")
    return {"ok": True}


@router.post("/resume")
async def resume():
    """Кнопка «Продолжить»: возвращает в работу всё незавершённое после СТОП или сбоя."""
    state["paused"] = False
    state["cancel_requested"] = False
    state["dispatch_error"] = ""
    dispatcher.resume_from_disk()
    if not dispatcher.open_tasks():
        return {"ok": False, "error": "Незавершённых задач нет."}
    runtime.add_log(f"▶ Продолжаю работу, задач на доске: {len(dispatcher.open_tasks())}")
    dispatcher.ensure_dispatcher()
    return {"ok": True}


@router.post("/reset")
async def reset():
    state["cancel_requested"] = True
    state["paused"] = True
    dispatcher.kill_board()
    tasks_store.clear_all()
    state["logs"].clear()
    state["events"].clear()
    state["metrics"].update({"tokens_in": 0, "tokens_out": 0, "sub_agents": 0, "files_saved": 0})
    for k in state["agents_runtime"]:
        runtime.set_agent(k, STATUS_FREE, IDLE_ACTION)
    runtime.add_log("🧹 Доска задач и журнал очищены.")
    return {"ok": True}


@router.post("/usage/reset")
async def reset_usage():
    usage.reset()
    runtime.add_log("🧮 Счётчики токенов по моделям сброшены.")
    return {"ok": True}
