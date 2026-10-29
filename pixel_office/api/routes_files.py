"""Файлы рабочей папки: просмотр, правка, удаление, архив и безопасный предпросмотр."""
import mimetypes

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, Response

from .. import runtime, workspace
from .schemas import FileDeleteRequest, FileSaveRequest
from .security import check_preview_key

router = APIRouter()


@router.get("/api/file")
async def read_file(name: str):
    try:
        return {"ok": True, "name": name, "content": workspace.read_text(name)}
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Файл ещё не создан")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/api/file/download")
async def download_file(name: str):
    """Скачать один файл проекта (кнопки с именами файлов в чате)."""
    try:
        path = workspace.safe_path(name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Файл не найден")
    return FileResponse(path, filename=path.name, media_type="application/octet-stream")


@router.post("/api/file")
async def save_file(req: FileSaveRequest):
    try:
        workspace.write_text(req.filename, req.content)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    runtime.add_log(f"✏️ Файл {req.filename} сохранён вручную ({len(req.content)} симв.)")
    return {"ok": True}


@router.post("/api/file/delete")
async def delete_file(req: FileDeleteRequest):
    try:
        workspace.delete_file(req.filename)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Файл не найден")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    runtime.add_log(f"🗑 Файл {req.filename} удалён")
    return {"ok": True}


@router.get("/api/download-zip")
async def download_zip():
    return Response(workspace.zip_bytes(), media_type="application/zip",
                    headers={"Content-Disposition": "attachment; filename=workspace_project.zip"})


@router.get("/preview/{key}/{path:path}")
async def preview(key: str, path: str):
    """Сгенерированные страницы открываются в песочнице (заголовок CSP sandbox ставит middleware)."""
    if not check_preview_key(key):
        raise HTTPException(status_code=404)
    try:
        target = workspace.safe_path(path or "index.html")
    except ValueError:
        raise HTTPException(status_code=404)
    if target.is_dir():
        target = target / "index.html"
    if not target.is_file():
        raise HTTPException(status_code=404, detail="Файл не найден")
    media = mimetypes.guess_type(target.name)[0] or "text/plain"
    if media.startswith("text/") or media in ("application/javascript", "application/json"):
        media += "; charset=utf-8"
    return FileResponse(target, media_type=media)
