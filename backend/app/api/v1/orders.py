from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_tenant_id
from app.domain.schemas import OrderCreate, OrderOut, OrderStatusUpdate
from app.domain.services import DomainError, OrderService

router = APIRouter(prefix="/orders", tags=["orders"])


@router.get("", response_model=list[OrderOut])
async def list_orders(
    limit: int = 50,
    session: AsyncSession = Depends(get_db),
    tenant_id: str = Depends(get_tenant_id),
) -> list[OrderOut]:
    return await OrderService(session, tenant_id).list_recent(limit=limit)


@router.post("", response_model=OrderOut)
async def create_order(
    payload: OrderCreate,
    session: AsyncSession = Depends(get_db),
    tenant_id: str = Depends(get_tenant_id),
) -> OrderOut:
    try:
        return await OrderService(session, tenant_id).create_confirmed_order(payload)
    except DomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/{order_id}", response_model=OrderOut)
async def get_order(
    order_id: int,
    session: AsyncSession = Depends(get_db),
    tenant_id: str = Depends(get_tenant_id),
) -> OrderOut:
    try:
        return await OrderService(session, tenant_id).get(order_id)
    except DomainError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.patch("/{order_id}", response_model=OrderOut)
async def update_order_status(
    order_id: int,
    payload: OrderStatusUpdate,
    session: AsyncSession = Depends(get_db),
    tenant_id: str = Depends(get_tenant_id),
) -> OrderOut:
    try:
        return await OrderService(session, tenant_id).update_status(order_id, payload.status)
    except DomainError as exc:
        status = 404 if "no encontrado" in str(exc).lower() else 422
        raise HTTPException(status_code=status, detail=str(exc)) from exc
