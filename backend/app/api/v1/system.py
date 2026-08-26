"""Endpoints de observabilidad minima: auditoria y ejecuciones de workflow,
para poder ver "por dentro" lo que hizo el agente en cada turno."""

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_tenant_id
from app.domain.models import AuditLog, WorkflowRun

router = APIRouter(prefix="/system", tags=["system"])


@router.get("/audit-logs")
async def list_audit_logs(
    limit: int = 50,
    session: AsyncSession = Depends(get_db),
    tenant_id: str = Depends(get_tenant_id),
) -> list[dict]:
    rows = (
        await session.execute(
            select(AuditLog).where(AuditLog.tenant_id == tenant_id).order_by(AuditLog.id.desc()).limit(limit)
        )
    ).scalars().all()
    return [
        {
            "id": row.id, "actor": row.actor, "action": row.action, "entity_type": row.entity_type,
            "entity_id": row.entity_id, "detail": row.detail, "created_at": row.created_at,
        }
        for row in rows
    ]


@router.get("/workflow-runs")
async def list_workflow_runs(
    limit: int = 20,
    session: AsyncSession = Depends(get_db),
    tenant_id: str = Depends(get_tenant_id),
) -> list[dict]:
    rows = (
        await session.execute(
            select(WorkflowRun).where(WorkflowRun.tenant_id == tenant_id).order_by(WorkflowRun.id.desc()).limit(limit)
        )
    ).scalars().all()
    return [
        {
            "id": row.id, "workflow_key": row.workflow_key, "status": row.status,
            "trace": row.trace, "created_at": row.created_at,
        }
        for row in rows
    ]
