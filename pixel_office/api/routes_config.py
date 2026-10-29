from typing import Any, Dict

from fastapi import APIRouter, Body, HTTPException

from .. import config_store, runtime
from ..agents import staffing
from ..config_store import ConfigError
from .schemas import AgentModelSwitch

router = APIRouter(prefix="/api")


@router.post("/agent/model")
async def switch_agent_model(req: AgentModelSwitch):
    cfg = config_store.get()
    if not any(m["id"] == req.model_ref for m in cfg.get("models", [])):
        raise HTTPException(status_code=400, detail="Модель не найдена")
    agent = next((a for a in cfg.get("agents", []) if a["id"] == req.agent_id), None)
    if not agent:
        raise HTTPException(status_code=404, detail="Агент не найден")
    agent["model_ref"] = req.model_ref
    config_store.save()
    runtime.sync_runtime_agents()
    runtime.add_log(f"🔄 Модель агента [{req.agent_id}] изменена на: {config_store.model_info(req.model_ref)['name']}")
    return {"ok": True}


@router.post("/config")
async def update_config(new_cfg: Dict[str, Any] = Body(...)):
    try:
        clean = config_store.validate_config(new_cfg, config_store.get())
    except ConfigError as e:
        raise HTTPException(status_code=400, detail=str(e))
    config_store.save(clean)
    runtime.sync_runtime_agents()
    runtime.add_log(f"⚙️ Конфиг сохранён: провайдеров {len(clean['providers'])}, "
                    f"моделей {len(clean['models'])}, агентов {len(clean['agents'])}")
    staffing.ensure_desks()
    return {"ok": True}
