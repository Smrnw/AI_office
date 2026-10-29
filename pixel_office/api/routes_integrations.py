"""Связь с внешним миром: проверочное уведомление и история Git проекта."""
from fastapi import APIRouter, HTTPException

from .. import config_store, gitrepo, notify, workspace
from ..runtime import state
from .schemas import NotifyTestRequest

router = APIRouter(prefix="/api")


@router.post("/notify/test")
async def notify_test(req: NotifyTestRequest):
    o = notify.options(config_store.get())
    ch = o[req.channel]
    if not ch["enabled"]:
        return {"ok": False, "error": "Канал выключен: включите его и сохраните настройки"}
    if req.channel == "telegram" and not (ch["token"] and ch["chat_id"]):
        return {"ok": False, "error": "Укажите токен бота и ID чата и сохраните настройки"}
    if req.channel == "email" and not (ch["host"] and ch["to"]):
        return {"ok": False, "error": "Укажите SMTP-сервер и адрес получателя и сохраните настройки"}
    errors = await notify.deliver(notify.subject("проверка связи", "connection test"),
                                  notify.say("Уведомления настроены. Сюда придут итоги работы и вопросы команды.",
                                             "Notifications are set up. Results and team questions will arrive here."),
                                  only=req.channel)
    return {"ok": not errors, "error": "; ".join(errors)}


@router.get("/git/log")
async def git_log(folder: str = ""):
    folder = folder or state.get("project_dir") or ""
    if not folder or "/" in folder or not workspace.is_valid_name(folder):
        raise HTTPException(400, "Недопустимое имя папки")
    return {"folder": folder, "available": gitrepo.available(), "enabled": gitrepo.enabled(),
            "commits": gitrepo.history(folder)}
