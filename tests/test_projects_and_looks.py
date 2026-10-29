"""Проекты в отдельных папках, журнал в файлах, настройки внешности агентов."""
from pixel_office import config_store, settings, tasks_store, workspace
from pixel_office.agents import workflow
from pixel_office.runtime import state

from conftest import HEADERS, all_done, wait_for


def test_each_project_gets_own_folder(office):
    office.post("/api/start", json={"idea": "Сайт пекарни"}, headers=HEADERS)
    wait_for(all_done, timeout=30)
    first = state["project_dir"]
    office.post("/api/start", json={"idea": "Сайт пекарни"}, headers=HEADERS)
    wait_for(lambda: state["project_dir"] != first and all_done(), timeout=30)
    assert first == "sayt-pekarni" and state["project_dir"] == "sayt-pekarni-2"
    names = {f["name"] for f in workspace.list_files()}
    assert "sayt-pekarni/index.html" in names and "sayt-pekarni-2/index.html" in names


def test_revision_stays_in_project_folder(office):
    office.post("/api/start", json={"idea": "Лендинг"}, headers=HEADERS)
    wait_for(all_done, timeout=30)
    folder = state["project_dir"]
    agent = state["agents_runtime"]["Coder_1"]
    created = workflow.create_revision_tasks(agent, [{"filename": "about.html", "spec": "Страница о нас"}], "добавь about")
    assert created[0]["filename"] == f"{folder}/about.html"
    # уже существующий файл в корне (старые проекты) правится там, где лежит
    workspace.write_text("legacy.html", "<p>old</p>")
    created = workflow.create_revision_tasks(agent, [{"filename": "legacy.html", "spec": "поправь"}], "поправь")
    assert created[0]["filename"] == "legacy.html"
    wait_for(all_done, timeout=30)


def test_request_without_current_project_gets_own_folder(office):
    # как после переноса из старой версии: проекта нет, старые файлы лежат в корне
    state["project_dir"] = ""
    workspace.write_text("index.html", "<p>старый магазин</p>")
    tasks_store.save_task({"id": 404, "title": "Старое", "filename": "index.html", "status": "done", "spec": ""}, "done")
    agent = state["agents_runtime"]["PM"]
    created = workflow.create_revision_tasks(
        agent, [{"filename": "promo.html", "spec": "реклама"}, {"filename": "index.html", "spec": "поправь"}],
        "создай страницу html с рекламой")
    names = {t["filename"] for t in created}
    assert state["project_dir"].startswith("sozday-stranitsu-html")
    assert f"{state['project_dir']}/promo.html" in names       # новый файл - в новой папке
    assert "index.html" in names                                # существующий правится на месте
    wait_for(all_done, timeout=30)


def test_long_files_reach_qa_whole():
    from pixel_office.agents import dispatcher
    long_code = "<div>" + "x" * 20000 + "</div>"
    assert dispatcher.clip_code(long_code) == long_code
    huge = "y" * (dispatcher.MAX_CODE_IN_PROMPT + 10)
    assert "не обрывается" in dispatcher.clip_code(huge)


def test_folder_names_are_safe():
    assert workflow.project_folder_name("Калькулятор на HTML, CSS и JS!!!").startswith("kalkulyator-na-html-css-i-js")
    assert workflow.project_folder_name("???") == "project" or workflow.project_folder_name("???").startswith("project")
    assert workspace.is_valid_name(workflow.project_folder_name("../../etc/passwd"))


def test_journal_written_to_files(office):
    office.post("/api/usage/reset", headers=HEADERS)
    logs = list(settings.LOGS_DIR.glob("*.log"))
    assert logs and "Счётчики токенов" in logs[0].read_text(encoding="utf-8")
    assert (settings.DATA_DIR / "README.txt").exists()


def test_appearance_fields_validated():
    base = {"providers": [{"id": "p", "api_type": "demo"}], "models": [{"id": "m", "provider": "p"}],
            "role_prompts": {"developer": "Ты разработчик."}}
    good = config_store.validate_config({**base, "agents": [{
        "id": "A", "model_ref": "m", "skin": 3, "hair_style": "curly", "outfit": "hoodie", "accessory": "both", "pants": "#112233"}]}, {})
    a = good["agents"][0]
    assert (a["skin"], a["hair_style"], a["outfit"], a["accessory"], a["pants"]) == (3, "curly", "hoodie", "both", "#112233")
    bad = config_store.validate_config({**base, "agents": [{
        "id": "A", "model_ref": "m", "skin": 99, "hair_style": "<b>", "outfit": "robe", "accessory": "x", "pants": "red"}]}, {})
    a = bad["agents"][0]
    assert (a["skin"], a["hair_style"], a["outfit"], a["accessory"], a["pants"]) == (-1, "auto", "auto", "auto", "")


def test_office_name(office):
    assert office.get("/api/state").json()["office_name"] == "AI Office"
    r = office.post("/api/office/name", json={"name": "  Моя\n  студия  "}, headers=HEADERS).json()
    assert r["name"] == "Моя студия" and config_store.get()["office_name"] == "Моя студия"
    assert office.get("/api/state").json()["office_name"] == "Моя студия"
    assert office.post("/api/office/name", json={"name": ""}, headers=HEADERS).json()["name"] == "AI Office"
    assert "office_name" not in config_store.get()


def test_language_switch(office):
    from pixel_office.llm import client
    assert office.get("/api/state").json()["language"] == "ru"
    assert client.with_language("Ты агент.") == "Ты агент."
    assert office.post("/api/office/language", json={"language": "xx"}, headers=HEADERS).status_code == 400
    assert office.post("/api/office/language", json={"language": "en"}, headers=HEADERS).json()["language"] == "en"
    assert office.get("/api/state").json()["language"] == "en" and config_store.get()["language"] == "en"
    # на английском агенты получают указание писать по-английски
    assert client.with_language("Ты агент.").endswith(client.ENGLISH_NOTE)
    office.post("/api/office/language", json={"language": "ru"}, headers=HEADERS)


def test_task_ids_in_state(office):
    office.post("/api/start", json={"idea": "Страница"}, headers=HEADERS)
    wait_for(all_done, timeout=30)
    ids = [t["id"] for t in office.get("/api/state").json()["tasks"]]
    assert ids == sorted(ids) and all(isinstance(i, int) for i in ids)
    assert ids == [t["id"] for t in tasks_store.scan_all()]
