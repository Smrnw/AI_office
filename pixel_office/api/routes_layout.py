"""Планировка офиса и сигнал «агент дошёл до своего стола»."""
from typing import Any, Dict

from fastapi import APIRouter, Body, HTTPException

from .. import layout_store, runtime
from ..agents import dispatcher, staffing
from .schemas import AgentArrived

router = APIRouter(prefix="/api")


@router.get("/layout")
async def get_layout():
    return {"ok": True, "layout": layout_store.get(), "rev": layout_store.rev()}


@router.post("/layout")
async def save_layout(data: Dict[str, Any] = Body(...)):
    try:
        clean = layout_store.save(data.get("layout"))
    except layout_store.LayoutError as e:
        raise HTTPException(status_code=400, detail=str(e))
    desks = sum(1 for it in clean["items"] if it["type"] == "desk_pod")
    runtime.add_log(f"🏢 Планировка офиса сохранена: зон {len(clean['zones'])}, предметов {len(clean['items'])}, блоков столов {desks}")
    staffing.ensure_desks()                 # столов стало хватать - просьба расшириться снимается
    return {"ok": True, "rev": layout_store.rev()}


@router.post("/agent/arrived")
async def agent_arrived(req: AgentArrived):
    dispatcher.mark_arrived(req.agent_id)
    return {"ok": True}
