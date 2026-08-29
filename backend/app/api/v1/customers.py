from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_tenant_id
from app.domain.schemas import CustomerCreate, CustomerOut, CustomerUpdate
from app.domain.services import CustomerService, DomainError

router = APIRouter(prefix="/customers", tags=["customers"])


@router.get("", response_model=list[CustomerOut])
async def list_customers(
    q: str | None = Query(default=None, description="Busca por nombre o telefono"),
    limit: int = 100,
    session: AsyncSession = Depends(get_db),
    tenant_id: str = Depends(get_tenant_id),
) -> list[CustomerOut]:
    customers = await CustomerService(session, tenant_id).list_all(q, limit=limit)
    return [
        CustomerOut(id=c.id, name=c.name, phone=c.phone, address=c.address, notes=c.notes)
        for c in customers
    ]


@router.post("", response_model=CustomerOut)
async def create_customer(
    payload: CustomerCreate,
    session: AsyncSession = Depends(get_db),
    tenant_id: str = Depends(get_tenant_id),
) -> CustomerOut:
    customer = await CustomerService(session, tenant_id).get_or_create(payload)
    await session.commit()
    return CustomerOut(
        id=customer.id, name=customer.name, phone=customer.phone,
        address=customer.address, notes=customer.notes,
    )


@router.patch("/{customer_id}", response_model=CustomerOut)
async def update_customer(
    customer_id: int,
    payload: CustomerUpdate,
    session: AsyncSession = Depends(get_db),
    tenant_id: str = Depends(get_tenant_id),
) -> CustomerOut:
    try:
        customer = await CustomerService(session, tenant_id).update(customer_id, payload)
    except DomainError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return CustomerOut(
        id=customer.id, name=customer.name, phone=customer.phone,
        address=customer.address, notes=customer.notes,
    )


@router.delete("/{customer_id}", status_code=204)
async def delete_customer(
    customer_id: int,
    session: AsyncSession = Depends(get_db),
    tenant_id: str = Depends(get_tenant_id),
) -> None:
    try:
        await CustomerService(session, tenant_id).delete(customer_id)
    except DomainError as exc:
        status = 404 if "no encontrado" in str(exc).lower() else 409
        raise HTTPException(status_code=status, detail=str(exc)) from exc
