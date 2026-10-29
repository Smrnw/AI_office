"""Задачи канбана хранятся текстовыми файлами в подпапках todo/, in_progress/, testing/, done/.

Файл задачи читается человеком: шапка с полями, затем ТЗ и история.
"""
import re
import shutil
import zlib
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from . import config_store
from .settings import KANBAN_STATUSES

SPEC_MARK = "=== ТЕХНИЧЕСКОЕ ЗАДАНИЕ (SPEC) ==="
HISTORY_MARK = "=== ИСТОРИЯ ВЫПОЛНЕНИЯ (HISTORY) ==="
TASK_FILE_RE = re.compile(r"^[A-Za-z0-9_.\-]{1,120}\.txt$")


def format_task_txt(task: Dict[str, Any]) -> str:
    lines = [
        f"ID: {task['id']}",
        f"TITLE: {_one_line(task['title'])}",
        f"CODE_FILE: {_one_line(task['filename'])}",
        f"ASSIGNED_TO: {_one_line(task.get('assigned_to', ''))}",
        f"STATUS: {task['status']}",
        f"ATTEMPTS: {task.get('attempts', 0)}",
        f"QA_NOTES: {_one_line(task.get('qa_notes', ''))}",
        f"UPDATED_AT: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        SPEC_MARK,
        str(task.get("spec", "")).strip(),
        "",
        HISTORY_MARK,
        str(task.get("history", "")).strip(),
    ]
    return "\n".join(lines).strip() + "\n"


def _one_line(value: Any) -> str:
    """Поле шапки должно оставаться одной строкой, иначе разбор файла поедет."""
    return " ".join(str(value or "").split())


def parse_task_text(raw: str, task_file: str, status_folder: str) -> Dict[str, Any]:
    meta: Dict[str, str] = {}
    spec_part = history_part = ""
    if SPEC_MARK in raw:
        header, rest = raw.split(SPEC_MARK, 1)
        if HISTORY_MARK in rest:
            spec_part, history_part = rest.split(HISTORY_MARK, 1)
        else:
            spec_part = rest
    else:
        header, spec_part = "", raw

    for line in header.strip().splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            meta[k.strip().upper()] = v.strip()

    stem = Path(task_file).stem
    m = re.search(r"(\d+)", stem)
    default_id = int(m.group(1)) if m else zlib.crc32(task_file.encode()) % 100000
    try:
        t_id = int(meta.get("ID", default_id))
    except ValueError:
        t_id = default_id
    try:
        attempts = int(meta.get("ATTEMPTS", 0))
    except ValueError:
        attempts = 0

    return {
        "id": t_id,
        "task_file": task_file,
        "title": meta.get("TITLE", stem),
        "filename": meta.get("CODE_FILE", "module.py"),
        "assigned_to": meta.get("ASSIGNED_TO", ""),
        "status": status_folder,
        "attempts": attempts,
        "qa_notes": meta.get("QA_NOTES", ""),
        "updated_at": meta.get("UPDATED_AT", ""),
        "spec": spec_part.strip(),
        "history": history_part.strip(),
        "raw_content": raw,
    }


def parse_task_file(path: Path, status_folder: str) -> Dict[str, Any]:
    return parse_task_text(path.read_text(encoding="utf-8", errors="replace"), path.name, status_folder)


def task_file_name(task: Dict[str, Any]) -> str:
    stem = re.sub(r"[^a-zA-Z0-9_\-]", "_", Path(task["filename"]).stem)[:60] or "task"
    return f"task_{task['id']}_{stem}.txt"


# кого позвать, когда задача впервые попала в done (коммит в Git и т.п.)
ON_DONE: List[Callable[[Dict[str, Any]], None]] = []


def save_task(task: Dict[str, Any], new_status: str, log_entry: str = "") -> Optional[Path]:
    """Создаёт файл задачи или переносит его в подпапку нового статуса.
    Задачи, удалённые сбросом доски (_dead), на диск больше не пишутся."""
    if task.get("_dead"):
        return None
    if new_status not in KANBAN_STATUSES:
        new_status = "todo"
    root = config_store.tasks_dir()
    became_done = new_status == "done" and task.get("status") != "done"
    task["status"] = new_status
    if log_entry:
        ts = datetime.now().strftime("%H:%M:%S")
        prev = str(task.get("history", "")).strip()
        task["history"] = f"{prev}\n[{ts}] [{new_status.upper()}] {log_entry}".strip()

    name = task.get("task_file") or task_file_name(task)
    task["task_file"] = name
    target = root / new_status / name
    for st in KANBAN_STATUSES:
        old = root / st / name
        if old != target and old.exists():
            shutil.move(str(old), str(target))
    target.write_text(format_task_txt(task), encoding="utf-8")
    if became_done:
        for hook in ON_DONE:
            try:
                hook(task)
            except Exception as e:                 # подписчик не должен ломать сохранение задачи
                print(f"Обработчик готовой задачи упал: {e}", flush=True)
    return target


def find_task_path(task_file: str, hint_status: str = "") -> Optional[Path]:
    """Путь к файлу задачи. Имя проверяем строго: никаких ../ и чужих расширений."""
    name = Path(task_file or "").name
    if not TASK_FILE_RE.match(name):
        return None
    root = config_store.tasks_dir()
    order = ([hint_status] if hint_status in KANBAN_STATUSES else []) + list(KANBAN_STATUSES)
    for st in order:
        path = root / st / name
        if path.is_file():
            return path
    return None


def scan_all() -> List[Dict[str, Any]]:
    root = config_store.tasks_dir()
    tasks: List[Dict[str, Any]] = []
    for st in KANBAN_STATUSES:
        for f in sorted((root / st).glob("*.txt")):
            try:
                tasks.append(parse_task_file(f, st))
            except OSError:
                continue
    tasks.sort(key=lambda x: x["id"])
    return tasks


def delete_task_file(task_file: str) -> bool:
    path = find_task_path(task_file)
    if not path:
        return False
    path.unlink()
    return True


def clear_all() -> None:
    root = config_store.tasks_dir()
    for st in KANBAN_STATUSES:
        for f in (root / st).glob("*.txt"):
            try:
                f.unlink()
            except OSError:
                pass


def next_task_id() -> int:
    ids = [t["id"] for t in scan_all()]
    return max(ids + [400]) + 1
