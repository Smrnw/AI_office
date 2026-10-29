"""Модульные тесты: разбор ответов LLM, пути, файлы задач, проверка конфига."""
import pytest

from pixel_office import config_store, settings, tasks_store, workspace
from pixel_office.agents.workflow import normalize_plan
from pixel_office.config_store import ConfigError
from pixel_office.llm.parsing import extract_code, extract_json


# ---------- разбор ответов ----------

def test_extract_code_takes_largest_fenced_block():
    raw = "Вот код:\n```bash\nrun.sh\n```\nи файл:\n```python\nprint('hello')\nprint('world')\n```"
    assert extract_code(raw) == "print('hello')\nprint('world')"


def test_extract_code_plain_text_untouched():
    assert extract_code("  x = 1  ") == "x = 1"


def test_extract_json_with_prose_and_fences():
    assert extract_json('Конечно! ```json\n{"passed": false, "reason": "x"}\n```') == {"passed": False, "reason": "x"}
    assert extract_json('План: [{"filename": "a.py"}] — готово') == [{"filename": "a.py"}]


def test_extract_json_skips_broken_brackets():
    assert extract_json('Пример {не json}, а вот ответ: {"reply": "ok"}') == {"reply": "ok"}


def test_extract_json_raises_without_json():
    with pytest.raises(ValueError):
        extract_json("просто текст")


def test_normalize_plan_variants():
    assert normalize_plan({"tasks": [{"filename": "a.py"}, {"title": "без файла"}]}) == [{"filename": "a.py"}]
    assert normalize_plan({"filename": "b.py", "spec": "x"}) == [{"filename": "b.py", "spec": "x"}]
    assert normalize_plan({}) == []
    assert normalize_plan("мусор") == []


# ---------- пути в рабочей папке ----------

@pytest.mark.parametrize("bad", ["../secret.txt", "..\\..\\win.ini", "a/../../b", "", "   ", "CON", "nul.txt", "x" * 300])
def test_safe_path_rejects_escape_and_bad_names(bad):
    with pytest.raises(workspace.WorkspaceError):
        workspace.safe_path(bad)


def test_safe_path_keeps_files_inside_workspace(tmp_path):
    ws = config_store.workspace_dir()
    assert workspace.safe_path("/etc/passwd").parent.parent == ws          # абсолютный путь становится относительным
    assert workspace.safe_path("C:/Windows/x.txt").is_relative_to(ws)     # двоеточие заменяется, диск не выбирается
    assert workspace.safe_path("src\\app.js") == ws / "src" / "app.js"


def test_snapshot_hides_secrets():
    workspace.write_text(".env", "API_KEY=secret")
    workspace.write_text("config.json", '{"api_key": "secret"}')
    workspace.write_text("main.py", "print(1)")
    snap = workspace.snapshot()
    assert "main.py" in snap and "secret" not in snap
    for name in (".env", "config.json", "main.py"):
        workspace.delete_file(name)


def test_write_text_size_limit():
    with pytest.raises(workspace.WorkspaceError):
        workspace.write_text("big.txt", "x" * (settings.MAX_FILE_WRITE + 1))


# ---------- файлы задач ----------

def test_task_roundtrip_keeps_header_single_line():
    task = {"id": 7, "title": "Строка\nSTATUS: done", "filename": "app.py", "status": "todo",
            "spec": "ТЗ\nв две строки", "history": "", "attempts": 2, "qa_notes": "заметка\nвторая"}
    text = tasks_store.format_task_txt(task)
    parsed = tasks_store.parse_task_text(text, "task_7_app.txt", "todo")
    assert parsed["title"] == "Строка STATUS: done"
    assert parsed["status"] == "todo"
    assert parsed["attempts"] == 2
    assert parsed["spec"] == "ТЗ\nв две строки"


@pytest.mark.parametrize("bad", ["../config.json", "..\\x.txt", "task.py", "", "a/b.txt"])
def test_find_task_path_rejects_bad_names(bad):
    assert tasks_store.find_task_path(bad) is None


def test_dead_task_is_not_written():
    task = {"id": 999, "title": "t", "filename": "x.py", "status": "todo", "_dead": True}
    assert tasks_store.save_task(task, "todo") is None
    assert tasks_store.find_task_path("task_999_x.txt") is None


# ---------- конфиг ----------

def _cfg(**over):
    base = {
        "workspace_dir": "", "tasks_dir": "",
        "providers": [{"id": "openai", "name": "OpenAI", "api_type": "openai_compatible", "api_key": "",
                       "base_url": "https://api.openai.com/v1/chat/completions"}],
        "models": [{"id": "gpt", "name": "GPT", "provider": "openai", "model_id": "gpt-4o", "token_limit": 100}],
        "agents": [{"id": "PM", "pipeline_type": "planner", "model_ref": "gpt", "shirt": "#ff0000", "hair": "#00ff00",
                    "prompt": "Ты руководитель."}],
    }
    base.update(over)
    return base


OLD = {"providers": [{"id": "openai", "api_type": "openai_compatible", "api_key": "sk-old",
                      "base_url": "https://api.openai.com/v1/chat/completions"}]}


def test_config_keeps_saved_key_when_url_unchanged():
    out = config_store.validate_config(_cfg(), OLD)
    assert out["providers"][0]["api_key"] == "sk-old"


def test_config_drops_saved_key_when_url_changes():
    cfg = _cfg()
    cfg["providers"][0]["base_url"] = "https://evil.example.com/steal"
    out = config_store.validate_config(cfg, OLD)
    assert out["providers"][0]["api_key"] == ""


def test_config_sanitizes_colors_and_unknown_models():
    cfg = _cfg()
    cfg["agents"][0].update(shirt='"/><script>alert(1)</script>', model_ref="missing", desk_idx=13)
    agent = config_store.validate_config(cfg, {})["agents"][0]
    assert agent["shirt"] == "#3b82f6"
    assert agent["model_ref"] == "gpt"
    assert agent["desk_idx"] == 13


@pytest.mark.parametrize("patch, msg", [
    ({"agents": [{"id": "../hack"}]}, "Агент #1"),
    ({"agents": [{"id": settings.TEAM_CHANNEL}]}, "Агент #1"),
    ({"providers": [{"id": "bad id!"}]}, "Провайдер #1"),
    ({"models": [{"id": "m", "provider": "nope"}]}, "провайдер 'nope' не найден"),
])
def test_config_rejects_bad_entries(patch, msg):
    with pytest.raises(ConfigError, match=msg):
        config_store.validate_config(_cfg(**patch), {})


def test_config_rejects_dangerous_dirs():
    for bad in ("C:/", str(settings.DATA_DIR.parent), str(settings.PROJECT_ROOT / "pixel_office"), "relative/path"):
        with pytest.raises(ConfigError):
            config_store.validate_config(_cfg(workspace_dir=bad), {})
    ok = config_store.validate_config(_cfg(workspace_dir=str(settings.DATA_DIR / "ws2")), {})
    assert ok["workspace_dir"].endswith("ws2")


def test_public_config_hides_keys():
    cfg = config_store.get()
    cfg["providers"].append({"id": "tmp", "name": "t", "api_type": "openai_compatible", "api_key": "sk-secret", "base_url": ""})
    try:
        pub = config_store.public_config()
        tmp = next(p for p in pub["providers"] if p["id"] == "tmp")
        assert tmp["api_key"] == "" and tmp["has_key"] is True
    finally:
        cfg["providers"].pop()
