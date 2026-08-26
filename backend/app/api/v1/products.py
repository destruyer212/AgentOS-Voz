from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_tenant_id
from app.domain.schemas import ProductOut
from app.domain.services import ProductService

router = APIRouter(prefix="/products", tags=["products"])


@router.get("", response_model=list[ProductOut])
async def list_products(
    q: str | None = Query(default=None, description="Texto de busqueda difusa"),
    session: AsyncSession = Depends(get_db),
    tenant_id: str = Depends(get_tenant_id),
) -> list[ProductOut]:
    service = ProductService(session, tenant_id)
    if q:
        return await service.search(q, limit=20)
    return await service.list_all()
