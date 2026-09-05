from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_tenant_id
from app.domain.invoicing_schemas import InvoiceFromOrderRequest, InvoiceListOut, InvoiceOut
from app.domain.invoicing_services import InvoicingError, InvoicingService

router = APIRouter(prefix="/invoicing", tags=["invoicing"])


@router.get("/invoices", response_model=list[InvoiceListOut])
async def list_invoices(
    limit: int = 50,
    session: AsyncSession = Depends(get_db),
    tenant_id: str = Depends(get_tenant_id),
) -> list[InvoiceListOut]:
    invoices = await InvoicingService(session, tenant_id).list_recent(limit=limit)
    return [
        InvoiceListOut(
            id=invoice.id,
            order_id=invoice.order_id,
            document_type=invoice.document_type,
            serie=invoice.serie,
            numero=invoice.numero,
            fecha_emision=invoice.fecha_emision,
            cliente_denominacion=invoice.cliente_denominacion,
            total=invoice.total,
            sunat_status=invoice.sunat_status,
            created_at=invoice.created_at,
        )
        for invoice in invoices
    ]


@router.get("/invoices/{invoice_id}", response_model=InvoiceOut)
async def get_invoice(
    invoice_id: int,
    session: AsyncSession = Depends(get_db),
    tenant_id: str = Depends(get_tenant_id),
) -> InvoiceOut:
    try:
        return await InvoicingService(session, tenant_id).get(invoice_id)
    except InvoicingError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/invoices/from-order", response_model=InvoiceOut)
async def create_invoice_from_order(
    payload: InvoiceFromOrderRequest,
    session: AsyncSession = Depends(get_db),
    tenant_id: str = Depends(get_tenant_id),
) -> InvoiceOut:
    try:
        return await InvoicingService(session, tenant_id).create_from_order(payload)
    except InvoicingError as exc:
        status = 404 if "no encontrado" in str(exc).lower() else 422
        raise HTTPException(status_code=status, detail=str(exc)) from exc
