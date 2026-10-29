"""Версии проектов: копия папки перед каждым кругом автопилота и откат к ней.

data/versions/<проект>/<время>/files + meta.json. Храним последние KEEP версий.
"""
import re
import shutil
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from . import config_store, gitrepo, settings
from .storage import read_json, write_json

VERSIONS_DIR = settings.DATA_DIR / "versions"
KEEP = 15
ID_RE = re.compile(r"^\d{8}-\d{6}(-\d+)?$")


class VersionError(ValueError):
    pass


def _project_dir(folder: str) -> Path:
    ws = config_store.workspace_dir()
    path = (ws / folder).resolve()
    if not folder or "/" in folder or "\\" in folder or path.parent != ws.resolve():
        raise VersionError(f"Проект «{folder}» не найден")
    return path


def _ignore(_dir, names):
    return [n for n in names if n in settings.SKIP_DIRS]


def snapshot(folder: str, note: str, protect: str = "") -> Dict[str, Any]:
    """protect - версия, которую нельзя удалить при чистке старых (к ней сейчас откатываемся)."""
    src = _project_dir(folder)
    if not src.is_dir():
        raise VersionError(f"Проект «{folder}» не найден")
    base = VERSIONS_DIR / folder
    vid = datetime.now().strftime("%Y%m%d-%H%M%S")
    n = 2
    while (base / vid).exists():
        vid = datetime.now().strftime("%Y%m%d-%H%M%S") + f"-{n}"
        n += 1
    dst = base / vid
    shutil.copytree(src, dst / "files", ignore=_ignore)
    files = sum(1 for p in (dst / "files").rglob("*") if p.is_file())
    meta = {"id": vid, "note": note[:200], "created": time.time(), "files": files}
    write_json(dst / "meta.json", meta)
    for old in [v for v in list_versions(folder) if v["id"] != protect][KEEP:]:
        shutil.rmtree(base / old["id"], ignore_errors=True)
    return meta


def list_versions(folder: str) -> List[Dict[str, Any]]:
    base = VERSIONS_DIR / folder
    if not folder or not base.is_dir():
        return []
    out = []
    for d in base.iterdir():
        if d.is_dir() and ID_RE.match(d.name):
            meta = read_json(d / "meta.json", {})
            out.append({"id": d.name, "note": str(meta.get("note") or ""), "created": meta.get("created") or d.stat().st_mtime,
                        "files": meta.get("files", 0)})
    return sorted(out, key=lambda v: v["id"], reverse=True)


def restore(folder: str, vid: str) -> Dict[str, Any]:
    """Откат: текущее состояние тоже сохраняется версией, так что откат можно отменить."""
    target = _project_dir(folder)                    # заодно проверяет имя папки
    if not ID_RE.match(vid or ""):
        raise VersionError("Версия не найдена")
    saved = VERSIONS_DIR / folder / vid / "files"
    if not saved.is_dir():
        raise VersionError("Версия не найдена")
    if target.is_dir():
        snapshot(folder, f"перед откатом к версии {vid}", protect=vid)
        # история Git (.git) остаётся: откат станет в ней обычным коммитом
        for child in target.iterdir():
            if child.name == ".git":
                continue
            shutil.rmtree(child) if child.is_dir() and not child.is_symlink() else child.unlink()
    shutil.copytree(saved, target, dirs_exist_ok=True)
    gitrepo.enqueue(folder, f"Откат к версии {vid}", "AI Office", f"откат к версии {vid}")
    return {"id": vid, "folder": folder}
