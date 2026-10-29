"""Проверка готового проекта и цикл «нашёл - вернул на доработку».

Ошибки проверки превращаются в задачи по файлам. Повторяем не больше auto_fix_rounds раз,
иначе слабая модель может гонять один и тот же файл бесконечно.
"""
import asyncio
from collections import OrderedDict
from pathlib import Path
from typing import Any, Dict, List, Optional

from .. import checks, config_store, runtime, tasks_store
from ..checks.report import Finding, Report
from ..llm import Cancelled, call_llm, extract_json
from ..runtime import STATUS_BUSY, state
from ..storage import write_json
from . import chat_store, dispatcher
from .prompts import VISION_PROMPT

MAX_VISION_ISSUES = 3
_busy = {"folder": None}


def pick_checker() -> Optional[Dict[str, Any]]:
    """Проверяет тестировщик; если его нет - руководитель; если и его нет - кто есть."""
    agents = runtime.agents_list()
    for kind in ("qa", "planner"):
        found = next((a for a in agents if a["pipeline_type"] == kind), None)
        if found:
            return found
    return agents[0] if agents else None


def project_folder(tasks: List[Dict[str, Any]]) -> str:
    """Папка, которую проверяем: текущий проект, а если его нет - общая папка файлов задач."""
    if state.get("project_dir"):
        return state["project_dir"]
    heads = {t["filename"].split("/")[0] for t in tasks if "/" in t.get("filename", "")}
    return heads.pop() if len(heads) == 1 else ""


def is_running() -> bool:
    return _busy["folder"] is not None


async def look_at_screens(agent: Dict[str, Any], rep: Report, folder: str) -> None:
    """Нейросеть тестировщика смотрит на скриншоты первой страницы (компьютер и телефон)."""
    shots_dir = checks.report_dir(folder)
    files = ", ".join(p.name for p in checks.project_files(config_store.workspace_dir() / folder)[:30]) if folder else ""
    page = rep.shots[0].split("-")[0] if rep.shots else ""
    looked = 0
    for name in [s for s in rep.shots if s.startswith(page)][:2]:
        image = (shots_dir / name).read_bytes()
        device = "экран компьютера 1280×800" if "desktop" in name else "экран телефона 390×844"
        prompt = VISION_PROMPT.format(page=name, idea=state.get("project_idea") or folder, device=device, files=files)
        try:
            raw = await call_llm(agent["model_ref"], dispatcher.work_prompt(agent, "review"), prompt, json_mode=True,
                                 purpose="vision", meta={"page": name}, image=image)
            verdict = extract_json(raw)
        except (asyncio.CancelledError, Cancelled):
            raise
        except Exception as e:
            # модель не умеет смотреть на картинки или ответила не JSON: это не повод останавливать проверку
            rep.steps["vision"] = "модель не смогла оценить скриншот: " + str(e)[:150]
            return
        looked += 1
        if not isinstance(verdict, dict):
            continue
        issues = verdict.get("issues") if isinstance(verdict.get("issues"), list) else []
        level = "warning" if verdict.get("ok", True) is True else "error"
        for item in issues[:MAX_VISION_ISSUES]:
            if isinstance(item, dict) and str(item.get("problem") or "").strip():
                rep.add([Finding("vision", level, str(item["problem"])[:400], str(item.get("file") or "")[:120])])
    rep.steps["vision"] = f"скриншотов оценено: {looked}"


async def run_check(folder: str, agent: Optional[Dict[str, Any]] = None) -> Report:
    opts = checks.options(config_store.get())
    agent = agent or pick_checker()
    who = agent["id"] if agent else "Офис"
    _busy["folder"] = folder
    try:
        if agent:
            await dispatcher.walk_to_desk(agent["id"], "проверка проекта")
            runtime.set_agent(agent["id"], STATUS_BUSY, "Проверяет проект")
        runtime.add_log(f"🧪 [{who}] Проверяет проект {folder or '(вся рабочая папка)'}: тесты, браузер, безопасность")
        rep = await asyncio.to_thread(checks.run_project_checks, folder, opts, lambda: bool(state["cancel_requested"]))
        if opts["vision"] and rep.shots and agent and not state["cancel_requested"]:
            await look_at_screens(agent, rep, folder)
        write_json(checks.report_dir(folder) / "report.json", rep.to_dict())
        runtime.add_log(f"🧪 [{who}] Проверка {folder or 'проекта'}: ошибок {len(rep.errors)}, предупреждений {len(rep.warnings)}")
        return rep
    finally:
        _busy["folder"] = None
        if agent:
            dispatcher.free_agent(agent["id"])


def report_text(rep: Report, fixing: bool) -> str:
    if not rep.errors:
        head = "✅ Проверка пройдена" + (f", предупреждений: {len(rep.warnings)}" if rep.warnings else "")
    else:
        head = f"❌ Проверка нашла ошибок: {len(rep.errors)}" + (f", предупреждений: {len(rep.warnings)}" if rep.warnings else "")
        head += ". Вернул на доработку разработчикам" if fixing else ". Исправьте вручную или попросите команду в чате"
    return head


def post_report(rep: Report, author: str, channel: Optional[str], fixing: bool) -> None:
    chat_store.append(channel or chat_store.TEAM, "agent", report_text(rep, fixing), author=author,
                      check=rep.summary_for_chat())


def fix_items(rep: Report, folder: str, fallback: List[str]) -> List[Dict[str, Any]]:
    """Ошибки по файлам -> по одной задаче на файл. Ошибки без файла (упавшие тесты) - главному файлу."""
    prefix = folder + "/" if folder else ""
    main = next((f for f in fallback if f.endswith("index.html")), None) or \
        next((f for f in fallback if not Path(f).name.startswith("test_")), None) or (fallback[0] if fallback else "")
    by_file: "OrderedDict[str, List[str]]" = OrderedDict()
    for f in rep.errors:
        target = prefix + f.file if f.file and not f.file.startswith(prefix) else (f.file or main)
        if not target:
            continue
        by_file.setdefault(target, []).append(f"- [{f.kind}] " + (f"строка {f.line}: " if f.line else "") + f.message)
    return [{"filename": name, "title": "Исправить замечания автопроверки",
             "spec": "Автоматическая проверка проекта нашла проблемы. Исправь их, не ломая остальное:\n" + "\n".join(lines[:12])}
            for name, lines in by_file.items()]


async def check_and_fix(tasks: List[Dict[str, Any]], channel: Optional[str] = None) -> Optional[Report]:
    """Полная проверка после работы команды. None - проверка выключена в настройках."""
    from .workflow import build_tasks           # workflow сам вызывает этот модуль

    opts = checks.options(config_store.get())
    if not opts["enabled"] or not tasks:
        return None
    folder = project_folder(tasks)
    rounds = opts["auto_fix_rounds"]
    rep: Optional[Report] = None
    for rnd in range(rounds + 1):
        if state["cancel_requested"]:
            return rep
        checker = pick_checker()
        if not checker:
            return None
        rep = await run_check(folder, checker)
        fixing = bool(rep.errors) and rnd < rounds
        post_report(rep, checker["id"], channel, fixing)
        if not fixing:
            return rep
        items = fix_items(rep, folder, [t["filename"] for t in tasks])
        created = build_tasks(items, checker, tasks_store.next_task_id(),
                              f"Задача создана по итогам автопроверки ({checker['id']})", revision=True)
        if not created:
            return rep
        runtime.add_log(f"↩️ [{checker['id']}] Автопроверка: заведено задач на исправление: {len(created)} (круг {rnd + 1} из {rounds})")
        if not await dispatcher.drive_tasks(created):
            return rep
    return rep


async def manual_check() -> Dict[str, Any]:
    """Кнопка «Проверить проект»: только проверка и отчёт, без автоматических доработок."""
    if is_running():
        raise RuntimeError("Проверка уже идёт")
    checker = pick_checker()
    if not checker:
        raise RuntimeError("В офисе нет агентов: наймите сотрудников в Настройках")
    folder = state.get("project_dir") or ""
    runtime.begin_job()
    try:
        rep = await run_check(folder, checker)
        post_report(rep, checker["id"], None, False)
        return rep.to_dict()
    finally:
        runtime.finish_job()
