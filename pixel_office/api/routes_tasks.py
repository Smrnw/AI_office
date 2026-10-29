"""Карточки канбана: просмотр, правка, перенос между колонками, удаление."""
from fastapi import APIRouter, HTTPException

from .. import tasks_store, workspace
from ..agents import dispatcher
from ..settings import KANBAN_STATUSES
from .schemas import TaskDeleteRequest, TaskMoveRequest, TaskUpdateRequest

router = APIRouter(prefix="/api")


def _move(task_file: str, new_status: str, raw_content=None, comment: str = ""):
    try:
        return {"ok": True, **dispatcher.manual_update(task_file, new_status, raw_content, comment)}
    except dispatcher.TaskBusyError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Файл задачи не найден")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/task-file")
async def read_task(task_file: str, status: str = ""):
    """Файл задачи из подпапки статуса плюс сгенерированный код (если есть)."""
    path = tasks_store.find_task_path(task_file, status)
    if not path:
        raise HTTPException(status_code=404, detail="Файл задачи не найден")
    task = tasks_store.parse_task_file(path, path.parent.name)
    code, code_exists = "", False
    try:
        code = workspace.read_text(task["filename"])
        code_exists = True
    except (OSError, ValueError):
        pass
    live = dispatcher.board_find(task["task_file"])
    return {"ok": True, "task": task, "task_path": str(path), "code_exists": code_exists,
            "code_content": code, "busy": bool(live and live.get("_busy"))}


@router.post("/task-file")
async def update_task(req: TaskUpdateRequest):
    if req.new_status not in KANBAN_STATUSES:
        raise HTTPException(status_code=400, detail="Недопустимый статус задачи")
    return _move(req.task_file, req.new_status, req.raw_content)


@router.post("/task/move")
async def move_task(req: TaskMoveRequest):
    return _move(req.task_file, req.new_status, comment=req.comment)


@router.post("/task/delete")
async def delete_task(req: TaskDeleteRequest):
    try:
        dispatcher.manual_delete(req.task_file)
    except dispatcher.TaskBusyError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Файл задачи не найден")
    return {"ok": True}
