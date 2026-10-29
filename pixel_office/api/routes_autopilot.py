"""Автопилот (запуск и состояние) и версии проектов (список и откат)."""
from fastapi import APIRouter, HTTPException

from .. import runtime, versions
from ..agents import autopilot
from ..runtime import state
from .schemas import AutopilotRequest, VersionRestoreRequest

router = APIRouter(prefix="/api")


@router.get("/autopilot")
async def autopilot_state():
    return autopilot.current()


@router.post("/autopilot/start")
async def autopilot_start(req: AutopilotRequest):
    return autopilot.start(req.goal, req.current_project)


@router.get("/versions")
async def list_versions(folder: str = ""):
    return {"folder": folder, "versions": versions.list_versions(folder) if folder and "/" not in folder else []}


@router.post("/versions/restore")
async def restore(req: VersionRestoreRequest):
    if state["is_running"] or state["starting"]:
        return {"ok": False, "error": "Сейчас идёт работа. Дождитесь завершения или нажмите СТОП."}
    try:
        versions.restore(req.folder, req.version)
    except versions.VersionError as e:
        raise HTTPException(404, str(e))
    runtime.add_log(f"↩ Проект {req.folder} откатан к версии {req.version}")
    return {"ok": True}
