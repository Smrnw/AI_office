"""Сборка приложения FastAPI и запуск сервера."""
import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import __version__, config_store, gitrepo, notify, runtime, settings, tasks_store
from .agents import dispatcher, workflow
from .api import (routes_autopilot, routes_chat, routes_checks, routes_config, routes_files, routes_integrations,
                  routes_layout, routes_office, routes_setup, routes_tasks)
from .api.security import LOOPBACK, SecurityMiddleware
from .llm import client


@asynccontextmanager
async def lifespan(_app: FastAPI):
    runtime.sync_runtime_agents()
    workflow.load_project_idea()
    if gitrepo.on_task_done not in tasks_store.ON_DONE:
        tasks_store.ON_DONE.append(gitrepo.on_task_done)
    gitrepo.adopt_existing()
    runtime.add_log(f"🟢 Офис открыт. Конфиг: {settings.CONFIG_PATH} | Код: {config_store.workspace_dir()}")
    watchdog = dispatcher.spawn(dispatcher.board_watchdog())
    dispatcher.spawn(notify.telegram_loop())          # ответы заказчика из Telegram (если бот настроен)
    try:
        yield
    finally:
        watchdog.cancel()
        for task in list(dispatcher._BG):
            task.cancel()
        await asyncio.gather(*dispatcher._BG, return_exceptions=True)
        await client.close()
        await notify.close()


def create_app() -> FastAPI:
    app = FastAPI(title="AI Office", version=__version__, lifespan=lifespan,
                  docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(SecurityMiddleware)
    for module in (routes_office, routes_chat, routes_tasks, routes_files, routes_config, routes_layout, routes_checks, routes_autopilot, routes_integrations, routes_setup):
        app.include_router(module.router)
    app.mount("/static", StaticFiles(directory=settings.STATIC_DIR), name="static")

    @app.get("/", include_in_schema=False)
    async def index():
        return FileResponse(settings.STATIC_DIR / "index.html", headers={"Cache-Control": "no-cache"})

    return app


app = create_app()


def main() -> None:
    import sys

    import uvicorn

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    if settings.HOST not in LOOPBACK and not settings.ACCESS_TOKEN:
        raise SystemExit(
            f"Сервер слушает {settings.HOST}, то есть доступен из сети. Задайте PIXEL_OFFICE_TOKEN, "
            "иначе любой в сети сможет управлять агентами и читать код.")
    print(f"AI Office {__version__}: http://{'localhost' if settings.HOST in LOOPBACK else settings.HOST}:{settings.PORT}")
    uvicorn.run(app, host=settings.HOST, port=settings.PORT, log_level="warning")


if __name__ == "__main__":
    main()
