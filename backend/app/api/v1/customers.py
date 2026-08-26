from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_tenant_id
from app.domain.schemas import CustomerCreate, CustomerOut
from app.domain.services import CustomerService

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
