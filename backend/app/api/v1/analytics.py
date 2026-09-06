"""Contabilidad / reportes del negocio (panel admin: /contabilidad). Ver
app/domain/analytics_services.py -- toda la logica de agregacion vive ahi,
esto solo valida el query param `range` y expone un endpoint por reporte."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_tenant_id
from app.domain.analytics_services import RANGE_KEYS, AnalyticsError, AnalyticsService

router = APIRouter(prefix="/analytics", tags=["analytics"])


def _validate_range(range: str) -> str:
    if range not in RANGE_KEYS:
        raise HTTPException(status_code=422, detail=f"range debe ser uno de {RANGE_KEYS}.")
    return range


@router.get("/summary")
async def summary(
    range: str = "30d",
    session: AsyncSession = Depends(get_db),
    tenant_id: str = Depends(get_tenant_id),
) -> dict:
    _validate_range(range)
    try:
        return await AnalyticsService(session, tenant_id).summary(range)
    except AnalyticsError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/top-products")
async def top_products(
    range: str = "30d",
    limit: int = 10,
    session: AsyncSession = Depends(get_db),
    tenant_id: str = Depends(get_tenant_id),
) -> dict:
    _validate_range(range)
    return await AnalyticsService(session, tenant_id).top_products(range, limit)


@router.get("/top-customers")
async def top_customers(
    range: str = "30d",
    limit: int = 10,
    session: AsyncSession = Depends(get_db),
    tenant_id: str = Depends(get_tenant_id),
) -> dict:
    _validate_range(range)
    return await AnalyticsService(session, tenant_id).top_customers(range, limit)


@router.get("/sales-by-channel")
async def sales_by_channel(
    range: str = "30d",
    session: AsyncSession = Depends(get_db),
    tenant_id: str = Depends(get_tenant_id),
) -> dict:
    _validate_range(range)
    return await AnalyticsService(session, tenant_id).sales_by_channel(range)


@router.get("/sales-by-time")
async def sales_by_time(
    range: str = "30d",
    session: AsyncSession = Depends(get_db),
    tenant_id: str = Depends(get_tenant_id),
) -> dict:
    _validate_range(range)
    return await AnalyticsService(session, tenant_id).sales_by_time(range)


@router.get("/invoices")
async def invoices_summary(
    range: str = "30d",
    list_limit: int = 200,
    session: AsyncSession = Depends(get_db),
    tenant_id: str = Depends(get_tenant_id),
) -> dict:
    _validate_range(range)
    return await AnalyticsService(session, tenant_id).invoices_summary(range, list_limit=list_limit)
