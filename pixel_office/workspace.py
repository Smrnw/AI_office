"""Рабочая папка с кодом: безопасные пути, список файлов, срез для LLM, проверки синтаксиса."""
import asyncio
import io
import json
import re
import shutil
import sys
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import config_store
from .settings import MAX_FILE_READ, MAX_FILE_WRITE, MAX_LISTED_FILES, SKIP_DIRS

# зарезервированные имена Windows: файл с таким именем не создать
_RESERVED = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}
# такие файлы не отправляем нейросети в контексте
_SECRET_NAMES = re.compile(r"(^\.env(\..*)?$|\.pem$|\.key$|^id_rsa|^config\.json$|^credentials)", re.IGNORECASE)


class WorkspaceError(ValueError):
    pass


def safe_path(filename: str) -> Path:
    """Путь внутри рабочей папки. Всё, что пытается выйти наружу, отклоняется."""
    ws = config_store.workspace_dir()
    name = str(filename or "").strip().replace("\\", "/").lstrip("/")
    name = re.sub(r'[<>:"|?*\x00-\x1f]', "_", name)
    parts = [p for p in name.split("/") if p not in ("", ".")]
    if not parts:
        raise WorkspaceError("Пустое имя файла")
    if any(p == ".." for p in parts):
        raise WorkspaceError(f"Попытка выйти за пределы рабочей папки: {filename}")
    if any(p.split(".")[0].lower() in _RESERVED for p in parts):
        raise WorkspaceError(f"Недопустимое имя файла: {filename}")
    if len(name) > 200:
        raise WorkspaceError("Слишком длинный путь к файлу")
    target = (ws / "/".join(parts)).resolve()
    try:
        rel = target.relative_to(ws)
    except ValueError:
        raise WorkspaceError(f"Попытка выйти за пределы рабочей папки: {filename}")
    # .git закрыт: файл в .git/hooks выполнился бы при следующем коммите, то есть агент (или текст,
    # подсунутый ему в задачу) получил бы запуск кода в обход песочницы. Проверяем уже разрешённый путь:
    # Windows понимает и «.git.», и короткое имя GIT~1
    if any(p.rstrip(". ").lower() == ".git" for p in rel.parts):
        raise WorkspaceError(f"Служебная папка Git недоступна: {filename}")
    return target


def is_valid_name(filename: str) -> bool:
    try:
        safe_path(filename)
        return True
    except WorkspaceError:
        return False


def _iter_files(ws: Path):
    for p in sorted(ws.rglob("*")):
        rel = p.relative_to(ws)
        if any(part in SKIP_DIRS for part in rel.parts):
            continue
        if p.is_symlink() or not p.is_file():
            continue
        yield p, rel


def list_files() -> List[Dict[str, Any]]:
    ws = config_store.workspace_dir()
    files = []
    for p, rel in _iter_files(ws):
        st = p.stat()
        files.append({
            "name": rel.as_posix(),
            "size": st.st_size,
            "mtime": datetime.fromtimestamp(st.st_mtime).strftime("%H:%M:%S"),
            "mtime_ts": st.st_mtime,
        })
        if len(files) >= MAX_LISTED_FILES:
            break
    return files


def list_dirs() -> List[str]:
    """Все папки рабочей директории (и пустые тоже): нужны дереву файлов в интерфейсе."""
    ws = config_store.workspace_dir()
    out = []
    for p in sorted(ws.rglob("*")):
        rel = p.relative_to(ws)
        if p.is_dir() and not p.is_symlink() and not any(part in SKIP_DIRS for part in rel.parts):
            out.append(rel.as_posix())
            if len(out) >= MAX_LISTED_FILES:
                break
    return out


def read_text(filename: str) -> str:
    path = safe_path(filename)
    if not path.is_file():
        raise FileNotFoundError(filename)
    if path.stat().st_size > MAX_FILE_READ:
        raise WorkspaceError("Файл слишком большой для просмотра (больше 2 МБ)")
    return path.read_text(encoding="utf-8", errors="replace")


def write_text(filename: str, content: str) -> Path:
    if len(content.encode("utf-8")) > MAX_FILE_WRITE:
        raise WorkspaceError("Файл слишком большой (больше 2 МБ)")
    path = safe_path(filename)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def delete_file(filename: str) -> None:
    path = safe_path(filename)
    if not path.is_file():
        raise FileNotFoundError(filename)
    path.unlink()


def snapshot(with_content: bool = True, max_total: int = 20000, max_each: int = 4000, folder: str = "") -> str:
    """Текстовый срез рабочей папки для контекста LLM: список файлов и (по желанию) их код.
    folder - папка текущего проекта: тогда в срез попадает только она (пути остаются от корня)."""
    ws = config_store.workspace_dir()
    parts: List[str] = []
    total = 0
    for p, rel in _iter_files(ws):
        if folder and not rel.as_posix().startswith(folder.rstrip("/") + "/"):
            continue
        if _SECRET_NAMES.search(p.name):
            continue
        try:
            if p.stat().st_size > 200_000:
                parts.append(f"- {rel.as_posix()} (большой файл, пропущен)")
                continue
            content = p.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue  # бинарный файл
        if not with_content:
            parts.append(f"- {rel.as_posix()} ({len(content)} симв.)")
            continue
        chunk = content[:max_each] + ("\n...[файл обрезан]" if len(content) > max_each else "")
        if total + len(chunk) > max_total:
            parts.append(f"### {rel.as_posix()} (не поместился в контекст)")
            continue
        total += len(chunk)
        parts.append(f"### Файл: {rel.as_posix()}\n{chunk}")
    return "\n\n".join(parts) if parts else "(рабочая папка пуста)"


def zip_bytes() -> bytes:
    ws = config_store.workspace_dir()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for p, rel in _iter_files(ws):
            zf.write(p, arcname=rel.as_posix())
    return buf.getvalue()


# -------------------------------------------------------------------------
# Проверка синтаксиса сгенерированного кода (сам код не запускается)
# -------------------------------------------------------------------------

async def _run(*args: str, timeout: float = 20) -> Optional[str]:
    proc = await asyncio.create_subprocess_exec(*args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    try:
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout)
    except asyncio.TimeoutError:
        proc.kill()
        return None
    if proc.returncode != 0:
        return stderr.decode("utf-8", errors="replace").strip()[-1500:] or "ошибка проверки"
    return None


async def check_syntax(path: Path) -> Optional[str]:
    """Текст ошибки или None. Python компилируется (py_compile не выполняет код),
    JSON разбирается, JS проверяется через node --check, если Node.js установлен."""
    suffix = path.suffix.lower()
    if suffix == ".py":
        return await _run(sys.executable, "-m", "py_compile", str(path))
    if suffix == ".json":
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, OSError) as e:
            return f"Некорректный JSON: {e}"
        return None
    if suffix in (".js", ".mjs", ".cjs") and shutil.which("node"):
        err = await _run("node", "--check", str(path))
        # старые Node.js считают import/export ошибкой в .js-файле - это не вина кода
        if err and re.search(r"import statement|Unexpected token 'export'", err):
            return None
        return err
    return None
