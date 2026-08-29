"""Vista de lectura sobre las conversaciones (chat web y llamadas
telefonicas comparten la misma tabla: `channel` es lo unico que las
distingue). Pensado para que el frontend pueda mostrar el flujo completo
de una llamada -- turno a turno -- y el pedido que resulto de ella."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_tenant_id
from app.domain.models import Conversation
from app.domain.schemas import ConversationDetailOut, ConversationOut, ConversationTurnOut
from app.domain.services import ConversationService, OrderService

router = APIRouter(prefix="/conversations", tags=["conversations"])


def _parse_transcript(raw: str) -> list[ConversationTurnOut]:
    turns: list[ConversationTurnOut] = []
    for line in (raw or "").split("\n"):
        line = line.strip()
        if not line:
            continue
        if line.startswith("cliente: "):
            turns.append(ConversationTurnOut(role="cliente", text=line[len("cliente: "):]))
        elif line.startswith("agente: "):
            turns.append(ConversationTurnOut(role="agente", text=line[len("agente: "):]))
        else:
            turns.append(ConversationTurnOut(role="sistema", text=line))
    return turns


def _to_summary(convo: Conversation) -> ConversationOut:
    turns = _parse_transcript(convo.transcript)
    return ConversationOut(
        id=convo.external_id,
        channel=convo.channel,
        status=convo.status,
        detail_status=convo.detail_status,
        customer_name=convo.customer.name if convo.customer else None,
        customer_phone=convo.customer.phone if convo.customer else None,
        outcome=convo.outcome,
        turns=len(turns),
        last_message=turns[-1].text if turns else None,
        created_at=convo.created_at,
        updated_at=convo.updated_at,
    )


@router.get("", response_model=list[ConversationOut])
async def list_conversations(
    limit: int = 50,
    session: AsyncSession = Depends(get_db),
    tenant_id: str = Depends(get_tenant_id),
) -> list[ConversationOut]:
    rows = await ConversationService(session, tenant_id).list_recent(limit=limit)
    return [_to_summary(convo) for convo in rows]


@router.get("/{external_id}", response_model=ConversationDetailOut)
async def get_conversation(
    external_id: str,
    session: AsyncSession = Depends(get_db),
    tenant_id: str = Depends(get_tenant_id),
) -> ConversationDetailOut:
    convo = await ConversationService(session, tenant_id).get_by_external_id(external_id)
    if not convo:
        raise HTTPException(status_code=404, detail="Conversacion no encontrada.")

    order = await OrderService(session, tenant_id).get_by_conversation(external_id)
    summary = _to_summary(convo)
    return ConversationDetailOut(
        **summary.model_dump(),
        transcript=_parse_transcript(convo.transcript),
        order=order,
    )
