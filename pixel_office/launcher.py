"""Запуск по ярлыку: если офис уже работает, просто открываем браузер; иначе стартуем сервер
(на свободном порту, если 8080 занят чужой программой) и открываем браузер, когда он ответит.
"""
import json
import socket
import sys
import threading
import time
import urllib.request
import webbrowser

from . import __version__, settings

LOCAL = "127.0.0.1"


def _health(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://{LOCAL}:{port}/api/health", timeout=1.5) as r:
            return json.loads(r.read().decode("utf-8")).get("app") == "pixel-office"
    except Exception:
        return False


def _port_busy(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex((LOCAL, port)) == 0


def _url(port: int) -> str:
    return f"http://localhost:{port}/"


def _open_when_ready(port: int) -> None:
    for _ in range(120):
        if _health(port):
            webbrowser.open(_url(port))
            return
        time.sleep(0.5)
    print("Офис не ответил за минуту - посмотрите сообщения выше.", flush=True)


def main() -> None:
    open_browser = "--no-browser" not in sys.argv
    port = settings.PORT
    if _health(port):
        print(f"Офис уже запущен: {_url(port)}", flush=True)
        if open_browser:
            webbrowser.open(_url(port))
        return
    if _port_busy(port):
        free = next((p for p in range(port + 1, port + 50) if not _port_busy(p)), None)
        if free is None:
            raise SystemExit(f"Порт {port} и следующие заняты. Укажите другой в .env: PIXEL_OFFICE_PORT=...")
        print(f"Порт {port} занят другой программой, запускаю офис на {free}", flush=True)
        port = settings.PORT = free
    print("=" * 60, flush=True)
    print(f"  AI Office {__version__}: {_url(port)}", flush=True)
    print(f"  Данные: {settings.DATA_DIR}", flush=True)
    print("  Чтобы остановить офис, закройте это окно.", flush=True)
    print("=" * 60, flush=True)
    if open_browser:
        threading.Thread(target=_open_when_ready, args=(port,), daemon=True).start()
    from .main import main as run_server
    run_server()


if __name__ == "__main__":
    main()
