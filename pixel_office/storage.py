"""Чтение и атомарная запись JSON-файлов с данными приложения."""
import json
from pathlib import Path
from typing import Any


def read_json(path: Path, default: Any) -> Any:
    try:
        if path.exists():
            # utf-8-sig: Блокнот Windows сохраняет файл с BOM, обычный utf-8 на нём падает
            return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception as e:
        print(f"Не удалось прочитать {path}: {e}", flush=True)
    return default


def write_json(path: Path, data: Any, indent: int = 2) -> None:
    """Пишем во временный файл и подменяем: при сбое не останется полфайла."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=indent), encoding="utf-8")
    tmp.replace(path)
