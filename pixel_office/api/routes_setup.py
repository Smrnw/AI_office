"""Мастер первоначальной настройки и проверка связи с нейросетью до сохранения."""
from typing import Any, Dict

from fastapi import APIRouter, Body, HTTPException

from .. import config_store, settings, setup_wizard
from ..agents import roles
from ..defaults import PROVIDER_TEMPLATES, SETUP_HINTS
from ..llm import client

router = APIRouter(prefix="/api/setup")


@router.get("")
async def info():
    return {
        "needs_setup": setup_wizard.needs_setup(config_store.get()),
        "providers": [{"id": "demo", "name": "Демо (без ключа и сети)", "api_type": "demo"}]
        + [{"id": p["id"], "name": p["name"], "api_type": p["api_type"]} for p in PROVIDER_TEMPLATES]
        + [{"id": "custom", "name": "Свой (OpenAI-совместимый)", "api_type": "openai_compatible"}],
        "hints": SETUP_HINTS,
        "roles": roles.public_roles(),
        "role_prompts": config_store.get().get("role_prompts") or {},
        "default_dirs": {"workspace": str(settings.DATA_DIR / "workspace"), "tasks": str(settings.DATA_DIR / "tasks")},
        "office_name": config_store.office_name(),
        "language": config_store.language(),
    }


@router.post("")
async def run(answers: Dict[str, Any] = Body(...)):
    try:
        return setup_wizard.apply(answers)
    except config_store.ConfigError as e:
        raise HTTPException(400, str(e))


@router.post("/test")
async def test(raw: Dict[str, Any] = Body(...)):
    chosen = setup_wizard.provider_from(raw)
    p, m = chosen["provider"], chosen["model"]
    try:
        reply = await client.ping(p["api_type"], p.get("base_url") or "", p.get("api_key") or "", m["model_id"])
    except Exception as e:
        return {"ok": False, "error": str(e)[:300]}
    return {"ok": True, "reply": reply}
