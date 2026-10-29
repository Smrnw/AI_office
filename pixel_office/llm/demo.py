"""Демо-провайдер: правдоподобные ответы без сети и ключей.

Нужен, чтобы офис можно было попробовать сразу после установки, и для автотестов.
"""
import asyncio
import html
import json
import random
import re
import zlib
from typing import Any, Dict

ACTION_WORDS = re.compile(r"(добав|измени|исправ|сделай|поменя|перепиш|убер|созд|улучш|fix|add|change|make)", re.IGNORECASE)
NAME_QUESTION = re.compile(r"(как тебя зовут|кто ты|твоё имя|твое имя|представься)", re.IGNORECASE)
HIRE_WORD = re.compile(r"(найми|нанять|hire)", re.IGNORECASE)
HIRE_ROLES = [(r"дизайн|design", "designer"), (r"тестир|qa", "qa"), (r"devops|девопс", "devops"),
              (r"писател|документ|writer", "writer"), (r"безопас|security", "security"), (r"разработ|программ|developer", "developer")]
SWITCH_WORDS = re.compile(r"(проект|перейд|переключ|вернись|выбери|project|switch)", re.IGNORECASE)
PY_HINTS = re.compile(r"(python|питон|скрипт|бот|cli|консол|telegram|парсер)", re.IGNORECASE)

DEMO_DELAY = (1.2, 3.0)


async def respond(purpose: str, meta: Dict[str, Any], json_mode: bool) -> str:
    lo, hi = DEMO_DELAY
    if hi > 0:
        await asyncio.sleep(random.uniform(lo, hi))
    if purpose == "plan":
        return json.dumps(_plan(meta.get("idea", "")), ensure_ascii=False)
    if purpose == "review":
        return json.dumps(_review(meta), ensure_ascii=False)
    if purpose == "chat":
        return json.dumps(_chat(meta), ensure_ascii=False)
    if purpose == "code":
        return _code(meta)
    if purpose == "vision":
        return json.dumps({"ok": True, "issues": []})
    if purpose == "requirements":
        return json.dumps(["Главная страница с заголовком и описанием", "Адаптивная вёрстка для телефона",
                           "Кнопка с интерактивом"], ensure_ascii=False)
    if purpose == "autopilot":
        return json.dumps(_autopilot(meta), ensure_ascii=False)
    return json.dumps({"reply": "Демо-режим: подключите настоящую модель в Настройках."}, ensure_ascii=False) if json_mode \
        else "Демо-режим"


def _plan(idea: str):
    if PY_HINTS.search(idea):
        return [
            {"title": "Точка входа и меню", "filename": "main.py",
             "spec": f"Главный скрипт проекта «{idea}». Функция main(), разбор ввода пользователя, вызов логики из logic.py."},
            {"title": "Бизнес-логика", "filename": "logic.py",
             "spec": "Чистые функции без ввода-вывода, которые использует main.py. Докстринги и обработка ошибок."},
        ]
    return [
        {"title": "Разметка страницы", "filename": "index.html",
         "spec": f"Семантическая HTML-страница для «{idea}»: шапка, основной блок, карточки, подвал. Подключает style.css и script.js."},
        {"title": "Оформление", "filename": "style.css",
         "spec": "Современный адаптивный дизайн: тёмная тема, градиенты, карточки с тенями, плавные hover-анимации."},
        {"title": "Интерактив", "filename": "script.js",
         "spec": "Небольшая интерактивность: переключение темы, анимация появления карточек, счётчик кликов."},
    ]


def _autopilot(meta: Dict[str, Any]):
    """Первый круг: одно требование готово, ещё одна задача. Со второго круга цель достигнута."""
    reqs = meta.get("requirements") or []
    finished = int(meta.get("cycle") or 1) >= 2
    marks = [{"id": r["id"], "done": finished or i == 0, "note": "проверено по коду"} for i, r in enumerate(reqs)]
    if finished:
        return {"requirements": marks, "goal_reached": True, "summary": "Все требования выполнены.", "next_tasks": []}
    return {"requirements": marks, "goal_reached": False, "summary": "Страница есть, добавляем адаптивность и интерактив.",
            "next_tasks": [{"title": "Адаптивность и интерактив", "filename": "index.html",
                            "spec": "Добавить адаптивную вёрстку и интерактивную кнопку"}]}


def _review(meta: Dict[str, Any]):
    filename = meta.get("filename", "")
    if int(meta.get("attempts") or 1) <= 1 and zlib.crc32(filename.encode()) % 3 == 0:
        return {"passed": False, "reason": "Не хватает поясняющего комментария в начале файла"}
    return {"passed": True, "reason": "Код соответствует ТЗ, критичных ошибок нет"}


def _chat(meta: Dict[str, Any]):
    text = str(meta.get("message", ""))
    files = meta.get("files") or []
    name, title = meta.get("name") or "агент", meta.get("title") or ""
    target_project = next((p for p in meta.get("projects") or [] if p.lower() in text.lower()), None)
    if target_project and SWITCH_WORDS.search(text):
        return {"reply": f"Хорошо, работаем с проектом {target_project}.", "project": target_project, "tasks": []}
    if HIRE_WORD.search(text):
        role = next((r for rx, r in HIRE_ROLES if re.search(rx, text, re.IGNORECASE)), "developer")
        return {"reply": "Хорошо, нанимаю.", "hire": [{"role": role, "reason": "по просьбе заказчика"}], "tasks": []}
    if NAME_QUESTION.search(text):
        return {"reply": f"Меня зовут {name}" + (f", я {title.lower()}" if title else "") + ". Чем помочь?", "tasks": []}
    if not ACTION_WORDS.search(text):
        return {"reply": f"{name} на связи. Я в демо-режиме, поэтому отвечаю заготовкой. Попросите что-нибудь "
                         "изменить, и я заведу задачу для команды.", "tasks": []}
    target = next((f for f in files if f.lower() in text.lower()), None) \
        or next((f for f in files if f.endswith((".html", ".py"))), None) or "index.html"
    return {"reply": f"{name}: понял задачу. Заведу доработку файла {target}, команда возьмёт её в работу.",
            "tasks": [{"title": f"Доработка {target}", "filename": target, "spec": text}]}


def _code(meta: Dict[str, Any]) -> str:
    filename = str(meta.get("filename", "file.txt"))
    idea = str(meta.get("idea", "Проект"))
    note = "Исправлено по замечаниям QA. " if meta.get("feedback") else ""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext == "html":
        title = html.escape(idea[:80])
        return f"""<!DOCTYPE html>
<!-- {note}Главная страница проекта -->
<html lang="ru">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <link rel="stylesheet" href="style.css">
</head>
<body>
  <header class="hero">
    <h1>{title}</h1>
    <p>Собрано командой пиксельного офиса</p>
    <button id="themeBtn">Сменить тему</button>
  </header>
  <main class="grid">
    <article class="card"><h2>Быстро</h2><p>Агенты разбили идею на задачи и написали код.</p></article>
    <article class="card"><h2>Красиво</h2><p>Тёмная тема, градиенты и мягкие тени.</p></article>
    <article class="card"><h2>Проверено</h2><p>QA посмотрел каждый файл перед сдачей.</p></article>
  </main>
  <footer>Кликов: <span id="clicks">0</span></footer>
  <script src="script.js"></script>
</body>
</html>
"""
    if ext == "css":
        return f"""/* {note}Оформление страницы */
:root {{ --bg: #0f172a; --card: #1e293b; --text: #e2e8f0; --accent: #38bdf8; }}
body.light {{ --bg: #f1f5f9; --card: #ffffff; --text: #0f172a; }}
* {{ box-sizing: border-box; }}
body {{ margin: 0; font-family: system-ui, sans-serif; background: var(--bg); color: var(--text); transition: background .3s; }}
.hero {{ padding: 64px 24px; text-align: center; background: linear-gradient(135deg, #6366f1, #06b6d4); color: #fff; }}
.hero button {{ margin-top: 16px; padding: 10px 18px; border: 0; border-radius: 10px; cursor: pointer; font-weight: 600; }}
.grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 20px; padding: 32px; max-width: 1000px; margin: 0 auto; }}
.card {{ background: var(--card); border-radius: 16px; padding: 22px; box-shadow: 0 10px 30px rgba(0,0,0,.25); opacity: 0; transform: translateY(12px); transition: .5s; }}
.card.shown {{ opacity: 1; transform: none; }}
.card:hover {{ transform: translateY(-4px); }}
footer {{ text-align: center; padding: 24px; opacity: .7; }}
"""
    if ext == "js":
        return f"""// {note}Интерактив страницы
document.addEventListener('DOMContentLoaded', () => {{
  document.querySelectorAll('.card').forEach((card, i) => setTimeout(() => card.classList.add('shown'), 150 * i));
  let clicks = 0;
  const counter = document.getElementById('clicks');
  document.addEventListener('click', () => {{ clicks += 1; if (counter) counter.textContent = clicks; }});
  const btn = document.getElementById('themeBtn');
  if (btn) btn.addEventListener('click', () => document.body.classList.toggle('light'));
}});
"""
    if ext == "py":
        return f'''"""{note}{filename}: часть проекта {idea[:60]!r}."""


def greet(name: str) -> str:
    return f"Привет, {{name}}! Это проект пиксельного офиса."


def main() -> None:
    print(greet("мир"))


if __name__ == "__main__":
    main()
'''
    return f"{note}Файл {filename} для проекта: {idea}\n"
