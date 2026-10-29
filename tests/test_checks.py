"""Автопроверка проекта: синтаксис, безопасность, тесты в песочнице, браузер и цикл доработок."""
import pytest

from pixel_office import checks, config_store, tasks_store, workspace
from pixel_office.agents import chat_store, quality
from pixel_office.checks import sandbox, security
from pixel_office.runtime import state

from conftest import HEADERS, all_done, wait_for

BROKEN_PAGE = """<!DOCTYPE html><html><head><title>Тест</title><script src="missing.js"></script></head>
<body><h1>Калькулятор</h1><p>Страница для проверки автотестов офиса.</p>
<button id="b" onclick="boom()">Посчитать</button>
<script>function boom() { undefinedFunction(); }</script></body></html>"""

GOOD_PAGE = """<!DOCTYPE html><html><head><title>Ок</title><meta name="viewport" content="width=device-width"></head>
<body><h1>Всё хорошо</h1><p>Обычная рабочая страница без ошибок.</p><button onclick="this.textContent='ok'">Жми</button></body></html>"""


@pytest.fixture()
def checks_on(office):
    old = config_store.get().get("checks")
    config_store.get()["checks"] = {"enabled": True, "vision": True, "auto_fix_rounds": 1}
    yield office
    config_store.get()["checks"] = old


def _opts(**kw):
    return {**checks.options({"checks": {"sandbox": "local"}}), **kw}


def test_security_rules():
    found = security.scan_text('const key = "' + "sk-" + "abcdefghijklmnopqrstuvwxyz123456" + '";\nel.innerHTML = input.value;', "app.js")
    levels = {f.message: f.level for f in found}
    assert any("API-ключ" in m and lv == "error" for m, lv in levels.items())
    assert any("innerHTML" in m and lv == "warning" for m, lv in levels.items())
    assert security.scan_text("x = eval(input())", "a.py")[0].level == "error"
    assert security.scan_text("print('hello')", "a.py") == []
    found = security.scan_text("out.innerHTML = document.getElementById('a').value;", "p.html")
    assert found and "innerHTML" in found[0].message
    assert security.scan_text("box.innerHTML = '<b>Готово</b>';", "p.js") == []


def test_sandbox_runs_copy_with_timeout(office):
    workspace.write_text("p/loop.py", "while True: pass\n")
    copy = sandbox.make_copy(workspace.safe_path("p"))
    try:
        assert (copy / "loop.py").is_file() and copy != workspace.safe_path("p")
        r = sandbox.run(["python", "loop.py"], copy, "local", timeout=2)
        assert r.timed_out and r.mode == "local"
        r = sandbox.run(["python", "-c", "import os; print(sorted(k for k in os.environ if 'KEY' in k.upper()))"], copy, "local")
        assert r.output.strip() == "[]"                       # переменных с ключами в песочнице нет
    finally:
        sandbox.drop_copy(copy)
    assert not copy.exists()


def test_tests_are_run(office):
    workspace.write_text("calc/logic.py", "def add(a, b):\n    return a - b\n")
    workspace.write_text("calc/test_logic.py", "from logic import add\n\ndef test_add():\n    assert add(2, 2) == 4\n")
    rep = checks.run_project_checks("calc", _opts(browser=False))
    assert any(f.kind == "tests" and f.level == "error" for f in rep.findings), rep.findings
    workspace.write_text("calc/logic.py", "def add(a, b):\n    return a + b\n")
    rep = checks.run_project_checks("calc", _opts(browser=False))
    assert not rep.errors and "прошло 1" in rep.steps["tests"]


@pytest.mark.skipif(not checks.browser.available(), reason="Playwright не установлен")
def test_browser_finds_js_errors(office):
    workspace.write_text("site/index.html", BROKEN_PAGE)
    rep = checks.run_project_checks("site", _opts(tests=False))
    texts = [f.message for f in rep.findings if f.kind == "browser"]
    assert sum("missing.js" in t for t in texts) == 1, texts             # один файл - одно замечание
    assert any("после клика по «Посчитать»" in t for t in texts), texts
    assert "page1-desktop.png" in rep.shots and (checks.report_dir("site") / "page1-mobile.png").is_file()


@pytest.mark.skipif(not checks.browser.available(), reason="Playwright не установлен")
def test_project_check_returns_errors_to_coders(checks_on):
    state["project_dir"] = "shop"
    workspace.write_text("shop/index.html", BROKEN_PAGE)
    r = checks_on.post("/api/checks/run", headers=HEADERS).json()
    assert r["ok"]
    wait_for(lambda: not quality.is_running() and state["jobs"] == 0, timeout=60)
    info = checks_on.get("/api/checks").json()
    assert info["report"]["errors"] > 0 and info["folder"] == "shop"
    msg = chat_store.history(chat_store.TEAM)[-1]
    assert msg["check"]["errors"] > 0 and msg["check"]["shots"]
    assert checks_on.get("/api/checks/shot", params={"folder": "shop", "name": "page1-desktop.png"}).status_code == 200
    assert checks_on.get("/api/checks/shot", params={"folder": "shop", "name": "../report.json"}).status_code == 404
    # из ошибок получаются задачи на исправление по файлам
    items = quality.fix_items(quality.Report("shop", findings=[
        checks.Finding("browser", "error", "Ошибка JavaScript", "index.html"),
        checks.Finding("tests", "error", "тесты упали")]), "shop", ["shop/index.html"])
    assert [i["filename"] for i in items] == ["shop/index.html"] and "тесты упали" in items[0]["spec"]


@pytest.mark.skipif(not checks.browser.available(), reason="Playwright не установлен")
def test_full_project_is_checked_after_work(checks_on):
    checks_on.post("/api/start", json={"idea": "Страница кофейни"}, headers=HEADERS)
    wait_for(lambda: all_done() and not quality.is_running(), timeout=90)
    msgs = chat_store.history(chat_store.TEAM)
    reports = [m for m in msgs if m.get("check")]
    assert reports, [m["text"] for m in msgs]
    assert reports[-1]["author"] == "QA_1"
    assert "Проект готов" in msgs[-1]["text"]
    assert (checks.report_dir(state["project_dir"]) / "report.json").is_file()


@pytest.mark.skipif(not checks.browser.available(), reason="Playwright не установлен")
def test_found_errors_go_back_to_coders_and_get_rechecked(checks_on):
    # доработка из чата касается index.html, а сломан соседний other.html: его найдёт проверка
    state["project_dir"] = "flowers"
    workspace.write_text("flowers/index.html", GOOD_PAGE)
    workspace.write_text("flowers/other.html", BROKEN_PAGE)
    # демо-разработчик пишет страницы со ссылками на style.css и script.js - они должны существовать
    workspace.write_text("flowers/style.css", "body { font-family: sans-serif; }\n")
    workspace.write_text("flowers/script.js", "console.log('ok');\n")
    r = checks_on.post("/api/chat", json={"agent_id": "Coder_1", "message": "Исправь index.html, сделай кнопку синей"},
                       headers=HEADERS)
    assert r.status_code == 200

    def reports():
        return [m for m in chat_store.history("Coder_1") if m.get("check")]
    wait_for(lambda: len(reports()) >= 2 and all_done() and not quality.is_running(), timeout=120)
    first, second = reports()[0]["check"], reports()[-1]["check"]
    assert first["errors"] > 0 and second["errors"] == 0, (first["items"], second["items"])
    fix = [t for t in tasks_store.scan_all() if t["filename"] == "flowers/other.html"]
    assert fix and fix[0]["status"] == "done" and fix[0]["title"] == "Исправить замечания автопроверки"


def test_unsafe_code_is_sent_back_on_review(office):
    from pixel_office.agents import dispatcher
    workspace.write_text("leak/app.js", 'const token = "ghp_' + "a" * 36 + '";\n')
    task = {"id": 77, "title": "t", "filename": "leak/app.js", "spec": "", "status": "testing", "attempts": 1,
            "qa_notes": "", "history": ""}
    tasks_store.save_task(task, "testing")
    import asyncio
    asyncio.run(dispatcher.review_step(state["agents_runtime"]["QA_1"] | {"model_ref": "demo", "pipeline_type": "qa", "id": "QA_1", "prompt": ""}, task))
    assert task["status"] == "todo" and "Небезопасный код" in task["qa_notes"]


def test_check_options_are_validated():
    opts = checks.options({"checks": {"auto_fix_rounds": 99, "sandbox": "rm -rf", "browser": "yes", "junk": 1}})
    assert opts["auto_fix_rounds"] == 5 and opts["sandbox"] == "auto" and opts["browser"] is True and "junk" not in opts
