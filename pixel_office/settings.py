"""Настройки запуска: пути к данным, адрес сервера, токен доступа.

Всё берётся из переменных окружения (или из файла .env в корне проекта),
поэтому одну и ту же копию кода можно запускать с разными папками данных.
"""
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = PROJECT_ROOT / "static"


def _load_dotenv(path: Path) -> None:
    """Минимальный разбор .env: KEY=VALUE, комментарии через #. Уже заданные переменные не трогаем."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key.strip(), value)


_load_dotenv(PROJECT_ROOT / ".env")


def _data_dir() -> Path:
    raw = os.getenv("PIXEL_OFFICE_DIR", "").strip()
    path = Path(raw).expanduser() if raw else PROJECT_ROOT / "data"
    path.mkdir(parents=True, exist_ok=True)
    return path.resolve()


DATA_DIR = _data_dir()
CONFIG_PATH = DATA_DIR / "config.json"
USAGE_PATH = DATA_DIR / "usage.json"
CHAT_PATH = DATA_DIR / "chat_history.json"
LOGS_DIR = DATA_DIR / "logs"

# всё хранится обычными файлами в одной папке; эта памятка лежит рядом с ними
DATA_README = """Данные AI Office. Базы данных нет: всё хранится обычными файлами в этой папке.

config.json        настройки: провайдеры нейросетей и API-ключи, модели, агенты и их внешность
layout.json        планировка офиса: зоны с описаниями, столы и мебель (появится после сохранения)
project.json       текущий проект: идея и папка, в которой он лежит
projects.json      описания всех проектов (для списка проектов в шапке)
autopilot.json     последний запуск автопилота: цель, требования, итог
chat_history.json  переписка с агентами по каналам
usage.json         расход токенов по моделям
tasks/             задачи канбана: по текстовому файлу на задачу в папках todo, in_progress, testing, done
workspace/         код, который пишут агенты; каждый новый проект - в своей папке
logs/              журнал событий офиса, по файлу на день
checks/            отчёты автопроверки и скриншоты страниц, по папке на проект
versions/          копии проектов перед кругами автопилота (для отката)

Чтобы перенести офис на другой компьютер, достаточно скопировать эту папку.
Резервная копия - тоже просто копия папки. Не публикуйте config.json: в нём API-ключи.
"""


def _write_data_readme() -> None:
    path = DATA_DIR / "README.txt"
    try:
        if not path.exists():
            path.write_text(DATA_README, encoding="utf-8")
    except OSError:
        pass


_write_data_readme()

HOST = os.getenv("PIXEL_OFFICE_HOST", "127.0.0.1").strip() or "127.0.0.1"
PORT = int(os.getenv("PIXEL_OFFICE_PORT") or os.getenv("PORT") or "8080")

# Если задан, все запросы к API требуют этот токен (нужно при запуске не на localhost)
ACCESS_TOKEN = os.getenv("PIXEL_OFFICE_TOKEN", "").strip()

# Дополнительные имена хоста, под которыми сервер доступен (через запятую), например office.lan
EXTRA_HOSTS = [h.strip().lower() for h in os.getenv("PIXEL_OFFICE_ALLOWED_HOSTS", "").split(",") if h.strip()]

# Сколько запросов к нейросетям может идти одновременно
LLM_PARALLEL = max(1, int(os.getenv("PIXEL_OFFICE_LLM_PARALLEL", "3")))
LLM_TIMEOUT = float(os.getenv("PIXEL_OFFICE_LLM_TIMEOUT", "120"))

KANBAN_STATUSES = ("todo", "in_progress", "testing", "done")
TEAM_CHANNEL = "__team__"           # общий канал «Проект»

# Ограничения, чтобы один огромный файл не повесил сервер или браузер
MAX_FILE_READ = 2 * 1024 * 1024
MAX_FILE_WRITE = 2 * 1024 * 1024
MAX_LISTED_FILES = 500
SKIP_DIRS = {"__pycache__", ".git", "node_modules", ".venv", "venv", ".idea", ".vscode", ".mypy_cache", ".pytest_cache"}
