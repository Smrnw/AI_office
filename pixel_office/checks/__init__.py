"""Автопроверка проекта: синтаксис, безопасность, тесты в песочнице, браузер.

run_project_checks долгая и синхронная - запускать в потоке. Оценку скриншота моделью
делает agents/quality.py, потому что ей нужен вызов нейросети.
"""
import asyncio
from pathlib import Path
from typing import Callable, Dict, List

from .. import config_store, settings, workspace
from . import browser, runner, sandbox, security
from .report import Finding, Report

DEFAULTS = {
    "enabled": True,          # проверять проект после выполнения всех задач
    "browser": True,          # открывать страницы в браузере
    "tests": True,            # запускать автотесты
    "security": True,         # искать уязвимости
    "vision": True,           # показывать скриншот нейросети тестировщика
    "write_tests": True,      # просить разработчиков писать автотесты
    "auto_fix_rounds": 2,     # сколько раз подряд возвращать найденное на доработку
    "sandbox": "auto",        # auto | docker | local
}
CHECKS_DIR = settings.DATA_DIR / "checks"


def options(cfg: Dict) -> Dict:
    raw = cfg.get("checks") if isinstance(cfg.get("checks"), dict) else {}
    out = dict(DEFAULTS)
    for k, v in raw.items():
        if k in DEFAULTS and type(v) is type(DEFAULTS[k]):
            out[k] = v
    out["auto_fix_rounds"] = max(0, min(5, out["auto_fix_rounds"]))
    if out["sandbox"] not in ("auto", "docker", "local"):
        out["sandbox"] = "auto"
    return out


def report_dir(folder: str) -> Path:
    return CHECKS_DIR / (folder or "_root")


def project_files(root: Path) -> List[Path]:
    return [p for p, _ in workspace._iter_files(root)]


def run_project_checks(folder: str, opts: Dict, should_stop: Callable[[], bool] = lambda: False) -> Report:
    """folder - папка проекта внутри рабочей директории ("" - вся рабочая директория)."""
    root = workspace.safe_path(folder) if folder else config_store.workspace_dir()
    rep = Report(folder)
    if not root.is_dir():
        rep.add([Finding("syntax", "error", "Папка проекта не найдена", folder)])
        return rep
    files = project_files(root)
    out_dir = report_dir(folder)
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("*.png"):
        old.unlink(missing_ok=True)

    # 1. синтаксис всех файлов: ловит то, что сломали правки соседних задач
    bad = 0
    for f in files:
        err = asyncio.run(workspace.check_syntax(f))
        if err:
            bad += 1
            rep.add([Finding("syntax", "error", "Синтаксическая ошибка: " + err[:400], f.relative_to(root).as_posix())])
    rep.steps["syntax"] = f"файлов: {len(files)}, с ошибками: {bad}"

    # 2. безопасность: только чтение файлов, код не выполняется
    if opts["security"] and not should_stop():
        found = security.scan_files(files, root) + security.run_bandit(files, root)
        rep.add(found)
        rep.steps["security"] = ("bandit + правила" if security.bandit_available() else "правила") + f", замечаний: {len(found)}"

    # 3. автотесты - только в песочнице
    if opts["tests"] and not should_stop():
        mode = sandbox.pick_mode(opts["sandbox"])
        if mode is None:
            rep.steps["tests"] = "пропущено: выбран запуск только в Docker, а Docker не запущен"
            rep.add([Finding("tests", "warning", "Автотесты не запускались: Docker не запущен")])
        else:
            rep.sandbox = mode
            copy = sandbox.make_copy(root)
            try:
                res = runner.run_tests(copy, mode)
            finally:
                sandbox.drop_copy(copy)
            rep.add(res["findings"])
            rep.steps["tests"] = res["summary"] + (" (Docker, без сети)" if mode == "docker" else " (без Docker)")

    # 4. браузер: страницы открываются с локального сервера над копией проекта
    if opts["browser"] and not should_stop():
        if not browser.available():
            rep.steps["browser"] = "пропущено: не установлен Playwright"
        elif not browser.pick_pages(root):
            rep.steps["browser"] = "HTML-страниц нет"
        else:
            copy = sandbox.make_copy(root)
            try:
                res = browser.check_pages(copy, out_dir, should_stop)
                rep.add(res["findings"])
                rep.shots = res["shots"]
                rep.steps["browser"] = res["summary"]
            except Exception as e:
                rep.steps["browser"] = "не удалось: " + str(e).splitlines()[0][:200]
                rep.add([Finding("browser", "warning", "Проверка в браузере не удалась: " + str(e).splitlines()[0][:200])])
            finally:
                sandbox.drop_copy(copy)
    return rep


def quick_file_check(path: Path, rel: str) -> List[Finding]:
    """Быстро и без запуска кода: правила безопасности для одного файла (для ревью задачи)."""
    if not path.is_file() or path.suffix.lower() not in security.CODE_EXT:
        return []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    return security.scan_text(text, rel)
