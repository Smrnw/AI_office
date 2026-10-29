from fastapi import APIRouter

from ..agents import chat, chat_store
from .schemas import ChatClearRequest, ChatRequest

router = APIRouter(prefix="/api/chat")


@router.get("")
async def chat_get(agent_id: str):
    return {
        "ok": True,
        "agent_id": agent_id,
        "messages": chat_store.history(agent_id),
        "pending": agent_id in chat_store.PENDING,
        "pending_all": sorted(chat_store.PENDING),
    }


@router.post("")
async def chat_send(req: ChatRequest):
    return chat.send(req.agent_id, req.message)


@router.post("/clear")
async def chat_clear(req: ChatClearRequest):
    chat_store.clear(req.agent_id)
    return {"ok": True}
