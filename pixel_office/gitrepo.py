"""История проектов в Git: у папки проекта свой репозиторий, коммит на каждую принятую задачу.

Работаем через dulwich, чтобы не требовать установленный Git. Коммиты пишет отдельный поток.
Хуки из .git/hooks не запускаются никогда: агенты пишут файлы в проект, и это был бы обход песочницы.
"""
import importlib.util
import queue
import re
import threading
from typing import Any, Dict, List, Optional

from . import config_store, runtime, workspace

GITIGNORE = "__pycache__/\n*.pyc\n.pytest_cache/\nnode_modules/\n.venv/\n.env\n"
COMMITTER = b"AI Office <office@ai-office.local>"

_jobs: "queue.Queue[tuple]" = queue.Queue()
_worker: Optional[threading.Thread] = None
_lock = threading.Lock()


def available() -> bool:
    return importlib.util.find_spec("dulwich") is not None


def enabled() -> bool:
    raw = config_store.get().get("git")
    return available() and (raw.get("enabled", True) if isinstance(raw, dict) else True)


def _email(name: str) -> str:
    return (re.sub(r"[^a-z0-9._-]", "", name.lower()) or "agent") + "@ai-office.local"


def project_of(filename: str) -> str:
    """Папка проекта файла: первый сегмент пути. У файлов в корне рабочей папки проекта нет."""
    return filename.split("/")[0] if "/" in filename else ""


def commit_now(folder: str, message: str, author: str, paths: Optional[List[str]] = None) -> Optional[str]:
    """Коммит изменений папки проекта: только paths (пути внутри проекта) или все изменения, если paths нет.
    Возвращает короткий хеш или None, если менять нечего."""
    from dulwich import porcelain
    from dulwich.repo import Repo

    root = workspace.safe_path(folder)
    if not root.is_dir():
        return None
    with _lock:
        if not (root / ".git").exists():
            porcelain.init(str(root))
            if not (root / ".gitignore").exists():
                (root / ".gitignore").write_text(GITIGNORE, encoding="utf-8")
        repo = Repo(str(root))
        repo.hooks.clear()          # хуки из .git/hooks не запускаем никогда: это чужой исполняемый код
        try:
            if paths is None:
                porcelain.add(repo)
            else:
                # задача фиксирует только свой файл: чужие несданные правки ждут своей задачи
                files = [str(root / p) for p in paths + [".gitignore"] if (root / p).exists()]
                gone = [str(root / p) for p in paths if not (root / p).exists()]
                if files:
                    porcelain.add(repo, paths=files)
                if gone and _has_commits(repo):
                    porcelain.remove(repo, paths=gone, cached=True)
            staged = porcelain.status(repo).staged
            if _has_commits(repo) and not any(staged.values()):
                return None
            sha = porcelain.commit(repo, message=message.encode("utf-8"),
                                   author=f"{author} <{_email(author)}>".encode("utf-8"), committer=COMMITTER)
            return sha.decode("ascii")[:7]
        finally:
            repo.close()


def _has_commits(repo) -> bool:
    """В новом репозитории HEAD ещё никуда не указывает."""
    try:
        repo.head()
        return True
    except KeyError:
        return False


def _run_worker() -> None:
    while True:
        folder, message, author, label, paths = _jobs.get()
        try:
            sha = commit_now(folder, message, author, paths)
            if sha:
                runtime.add_log(f"📜 [git] {folder}: коммит {sha} — {label}")
        except Exception as e:                # история не должна ломать работу офиса
            runtime.add_log(f"⚠️ [git] {folder}: не удалось сделать коммит ({str(e)[:150]})")
        finally:
            _jobs.task_done()


def enqueue(folder: str, message: str, author: str, label: str, paths: Optional[List[str]] = None) -> None:
    global _worker
    if not folder or not enabled():
        return
    if _worker is None or not _worker.is_alive():
        _worker = threading.Thread(target=_run_worker, name="git-commits", daemon=True)
        _worker.start()
    _jobs.put((folder, message, author, label, paths))


def adopt_existing() -> int:
    """Проекты, созданные до включения истории: один начальный коммит со всеми их файлами.
    Иначе первый коммит задачи зафиксировал бы только её файл, а остальные остались бы вне истории."""
    if not enabled():
        return 0
    ws = config_store.workspace_dir()
    n = 0
    for d in sorted(ws.iterdir()) if ws.is_dir() else []:
        if d.is_dir() and not d.name.startswith(".") and not (d / ".git").exists() and any(d.iterdir()):
            enqueue(d.name, "Начало истории: файлы проекта на момент включения Git", "AI Office", "начало истории")
            n += 1
    return n


def wait_idle() -> None:
    """Дождаться, пока все коммиты запишутся (нужно тестам)."""
    _jobs.join()


def on_task_done(task: Dict[str, Any]) -> None:
    """Задача принята - фиксируем состояние проекта коммитом от имени автора кода."""
    folder = project_of(task.get("filename", ""))
    title = str(task.get("title") or task.get("filename"))
    note = str(task.get("qa_notes") or "").strip()
    message = f"#{task.get('id')} {title}\n\nФайл: {task.get('filename')}" + (f"\n{note}" if note else "")
    author = task.get("last_coder") or task.get("assigned_to") or "AI Office"
    rel = task.get("filename", "")[len(folder) + 1:]
    enqueue(folder, message, author, f"#{task.get('id')} {title}", [rel])


def history(folder: str, limit: int = 30) -> List[Dict[str, Any]]:
    from dulwich.repo import Repo

    root = workspace.safe_path(folder)
    if not (root / ".git").exists():
        return []
    with _lock:
        repo = Repo(str(root))
        try:
            if not _has_commits(repo):
                return []
            out = []
            for entry in repo.get_walker(max_entries=limit):
                c = entry.commit
                name = c.author.decode("utf-8", "replace").split(" <")[0]
                out.append({"sha": c.id.decode("ascii")[:7], "author": name, "time": c.commit_time,
                            "message": c.message.decode("utf-8", "replace").strip()})
            return out
        finally:
            repo.close()
