"""Проверка страниц в браузере (Playwright).

Берём установленный Edge или Chrome, иначе Chromium от Playwright. Страницу отдаёт маленький локальный
сервер над копией проекта. Собираем ошибки консоли и загрузки, жмём кнопки, снимаем экран компьютера и телефона.
"""
import importlib.util
import functools
import ipaddress
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Dict, List
from urllib.parse import urlparse

from .report import Finding

MAX_PAGES = 3
MAX_CLICKS = 12
LOAD_TIMEOUT = 15000


class _QuietHandler(SimpleHTTPRequestHandler):
    # страницы без <meta charset> браузер иначе читает в кодировке системы, и кириллица ломается
    extensions_map = {**SimpleHTTPRequestHandler.extensions_map,
                      ".html": "text/html; charset=utf-8", ".htm": "text/html; charset=utf-8",
                      ".css": "text/css; charset=utf-8", ".js": "text/javascript; charset=utf-8",
                      ".mjs": "text/javascript; charset=utf-8", ".json": "application/json; charset=utf-8",
                      ".txt": "text/plain; charset=utf-8", ".svg": "image/svg+xml"}

    def log_message(self, *args):
        pass


def available() -> bool:
    return importlib.util.find_spec("playwright") is not None


def pick_pages(root: Path) -> List[str]:
    """index.html в корне проекта первым, затем остальные страницы (не больше трёх)."""
    pages = sorted((p for p in root.rglob("*.htm*") if p.suffix.lower() in (".html", ".htm") and p.is_file()),
                   key=lambda p: (p.name.lower() != "index.html", len(p.parts), str(p)))
    return [p.relative_to(root).as_posix() for p in pages[:MAX_PAGES]]


def _private_target(url: str, own_host: str) -> bool:
    """Адрес в локальной сети или на этом компьютере (кроме нашего сервера проверки)."""
    parts = urlparse(url)
    if parts.scheme not in ("http", "https", "ws", "wss"):
        return False                       # data:, blob: и т.п. в сеть не ходят
    if parts.netloc == own_host:
        return False
    name = (parts.hostname or "").lower()
    if name == "localhost" or name.endswith((".localhost", ".local", ".lan", ".internal", ".home")):
        return True
    try:
        ip = ipaddress.ip_address(name)
    except ValueError:
        return False                       # обычное доменное имя
    return ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_unspecified


def _launch(p):
    errors = []
    for channel in ("msedge", "chrome", None):
        try:
            return p.chromium.launch(channel=channel) if channel else p.chromium.launch()
        except Exception as e:           # браузер не установлен - пробуем следующий
            errors.append(str(e).splitlines()[0][:120])
    raise RuntimeError("Не найден браузер для проверки (Edge, Chrome или Chromium): " + "; ".join(errors))


def _serve(root: Path):
    server = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(_QuietHandler, directory=str(root)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def check_pages(root: Path, shots_dir: Path, should_stop=lambda: False) -> Dict:
    """Синхронная: вызывать из отдельного потока. Возвращает замечания, скриншоты и короткий итог."""
    from playwright.sync_api import sync_playwright

    pages = pick_pages(root)
    if not pages:
        return {"findings": [], "shots": [], "summary": "HTML-страниц нет", "pages": []}
    shots_dir.mkdir(parents=True, exist_ok=True)
    server = _serve(root)
    base = f"http://127.0.0.1:{server.server_address[1]}/"
    findings: List[Finding] = []
    shots: List[str] = []
    clicked_total = 0
    try:
        with sync_playwright() as p:
            browser = _launch(p)
            try:
                for i, rel in enumerate(pages):
                    if should_stop():
                        break
                    f, s, c = _check_one(browser, base, rel, shots_dir, i)
                    findings += f
                    shots += s
                    clicked_total += c
            finally:
                browser.close()
    finally:
        server.shutdown()
    errors = sum(1 for f in findings if f.level == "error")
    summary = f"страниц: {len(pages)}, нажато кнопок: {clicked_total}, ошибок: {errors}"
    return {"findings": findings, "shots": shots, "summary": summary, "pages": pages}


def _check_one(browser, base: str, rel: str, shots_dir: Path, idx: int):
    findings: List[Finding] = []
    shots: List[str] = []
    stage = {"name": ""}                 # что происходило, когда случилась ошибка
    seen = set()
    host = urlparse(base).netloc

    def add(level: str, message: str):
        key = (level, message[:200])
        if key in seen or len(seen) > 40:
            return
        seen.add(key)
        findings.append(Finding("browser", level, message + (f" (после клика по «{stage['name']}»)" if stage["name"] else ""), rel))

    ctx = browser.new_context(viewport={"width": 1280, "height": 800})
    page = ctx.new_page()
    # «Failed to load resource» дублирует сообщение о файле, который не загрузился: его ловят обработчики ниже
    page.on("console", lambda m: m.type == "error" and not m.text.startswith("Failed to load resource")
            and add("error", "Ошибка в консоли: " + m.text[:300]))
    page.on("pageerror", lambda e: add("error", "Ошибка JavaScript: " + str(e)[:300]))
    page.on("dialog", lambda d: d.dismiss())

    missing = set()                      # про один и тот же файл сообщаем один раз

    def not_found(resp):
        if resp.status >= 400 and urlparse(resp.url).netloc == host and resp.url not in missing:
            missing.add(resp.url)
            add("error", f"Файл проекта не найден ({resp.status}): " + resp.url.replace(base, "")[:200])

    def failed(req):
        if req.url in missing:
            return
        missing.add(req.url)
        local = urlparse(req.url).netloc == host
        add("error" if local else "warning", ("Не загрузился файл проекта: " if local else "Не загрузился внешний ресурс: ")
            + req.url.replace(base, "")[:200])
    page.on("response", not_found)
    page.on("requestfailed", failed)
    # страница написана нейросетью: интернет (шрифты, CDN) ей можно, а локальную сеть, роутер и сам офис - нельзя
    page.route("**/*", lambda route: route.abort("blockedbyclient")
               if _private_target(route.request.url, host) else route.continue_())

    url = base + rel
    try:
        page.goto(url, wait_until="load", timeout=LOAD_TIMEOUT)
    except Exception as e:
        add("error", "Страница не открылась: " + str(e).splitlines()[0][:200])
        ctx.close()
        return findings, shots, 0
    page.wait_for_timeout(700)

    stem = f"page{idx + 1}"
    page.screenshot(path=str(shots_dir / f"{stem}-desktop.png"))
    shots.append(f"{stem}-desktop.png")

    info = page.evaluate("""() => ({
        text: (document.body && document.body.innerText || '').trim().length,
        media: document.querySelectorAll('img, canvas, svg, video').length,
        title: document.title || ''
    })""")
    if info["text"] < 15 and info["media"] == 0:
        add("error", "Страница выглядит пустой: на ней почти нет текста и картинок")
    if not info["title"].strip():
        add("warning", "У страницы нет заголовка <title>")

    clicked = 0
    buttons = page.locator("button:visible, [role=button]:visible, input[type=button]:visible, input[type=submit]:visible")
    for k in range(min(buttons.count(), MAX_CLICKS)):
        btn = buttons.nth(k)
        try:
            label = (btn.inner_text(timeout=500) or btn.get_attribute("value") or btn.get_attribute("aria-label") or f"кнопка {k + 1}").strip()[:40]
            stage["name"] = label
            btn.click(timeout=1500, no_wait_after=True)
            clicked += 1
            page.wait_for_timeout(250)
            if page.url.split("#")[0] != url:            # кнопка увела на другую страницу - возвращаемся
                page.goto(url, wait_until="load", timeout=LOAD_TIMEOUT)
        except Exception:
            continue                                     # кнопку перекрыли или она исчезла - не ошибка страницы
    stage["name"] = ""

    # телефон: заметная горизонтальная прокрутка почти всегда значит, что вёрстка не адаптивная
    page.set_viewport_size({"width": 390, "height": 844})
    page.wait_for_timeout(300)
    page.screenshot(path=str(shots_dir / f"{stem}-mobile.png"))
    shots.append(f"{stem}-mobile.png")
    overflow = page.evaluate("() => document.documentElement.scrollWidth - window.innerWidth")
    if overflow > 24:
        add("warning", f"На телефоне страница шире экрана на {overflow}px — появляется горизонтальная прокрутка")
    ctx.close()
    return findings, shots, clicked

