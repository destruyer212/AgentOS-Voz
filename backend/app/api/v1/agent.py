import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.runtime import AgentRuntime
from app.agents.state import get_lock
from app.api.deps import get_db, get_tenant_id
from app.domain.schemas import AgentMessageIn, AgentTurnOut

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/agent", tags=["agent"])


@router.post("/turn", response_model=AgentTurnOut)
async def agent_turn(
    payload: AgentMessageIn,
    session: AsyncSession = Depends(get_db),
    tenant_id: str = Depends(get_tenant_id),
) -> AgentTurnOut:
    lock = get_lock(payload.conversation_id) if payload.conversation_id else None
    try:
        if lock:
            async with lock:
                runtime = AgentRuntime(session, tenant_id)
                return await runtime.handle_turn(payload)
        runtime = AgentRuntime(session, tenant_id)
        return await runtime.handle_turn(payload)
    except Exception:
        logger.exception("Fallo procesando /agent/turn (conversation_id=%s)", payload.conversation_id)
        raise HTTPException(
            status_code=500,
            detail="Hubo un problema procesando tu mensaje. Intenta de nuevo en un momento.",
        ) from None
