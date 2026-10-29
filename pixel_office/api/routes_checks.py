"""Автопроверка проекта: запуск вручную, последний отчёт и скриншоты."""
import re

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from .. import checks, config_store, workspace
from ..agents import dispatcher, quality
from ..runtime import state
from ..storage import read_json

router = APIRouter(prefix="/api/checks")
SHOT_RE = re.compile(r"^page\d+-(desktop|mobile)\.png$")


def _folder(folder: str) -> str:
    if folder and not workspace.is_valid_name(folder):
        raise HTTPException(400, "Недопустимое имя папки")
    return folder


@router.get("")
async def info(folder: str = ""):
    folder = _folder(folder or state.get("project_dir") or "")
    report = read_json(checks.report_dir(folder) / "report.json", None)
    return {"folder": folder, "running": quality.is_running(), "options": checks.options(config_store.get()),
            "browser": checks.browser.available(), "bandit": checks.security.bandit_available(),
            "docker": checks.sandbox.docker_ready(), "report": report}


@router.post("/run")
async def run():
    if quality.is_running():
        return {"ok": False, "error": "Проверка уже идёт"}
    if state["is_running"] or state["starting"]:
        return {"ok": False, "error": "Сейчас идёт работа. Дождитесь завершения или нажмите СТОП."}
    dispatcher.spawn(quality.manual_check())
    return {"ok": True}


@router.get("/shot")
async def shot(name: str, folder: str = ""):
    folder = _folder(folder)
    if not SHOT_RE.match(name):
        raise HTTPException(404)
    path = checks.report_dir(folder) / name
    if not path.is_file():
        raise HTTPException(404, "Файл не найден")
    return FileResponse(path, media_type="image/png", headers={"Cache-Control": "no-store"})
