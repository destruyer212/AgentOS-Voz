"""Endpoints de observabilidad minima: auditoria y ejecuciones de workflow,
para poder ver "por dentro" lo que hizo el agente en cada turno."""

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_tenant_id
from app.domain.models import AuditLog, VoiceTurnMetric, WorkflowRun

router = APIRouter(prefix="/system", tags=["system"])


def _percentile(sorted_values: list[int], pct: float) -> int:
    if not sorted_values:
        return 0
    index = min(int(len(sorted_values) * pct), len(sorted_values) - 1)
    return sorted_values[index]


@router.get("/voice-metrics")
async def voice_metrics(
    limit: int = 500,
    session: AsyncSession = Depends(get_db),
    tenant_id: str = Depends(get_tenant_id),
) -> dict:
    """Cuanto tarda AgentRuntime en 'pensar' cada turno (chat web o
    telefono), sobre los ultimos `limit` turnos. No mide STT/TTS -- eso
    corre en Deepgram, fuera de este proceso. Percentiles calculados en
    Python (no en SQL) porque SQLite no trae una funcion de percentil
    nativa y la muestra reciente ya alcanza para ser util sin eso."""
    rows = (
        await session.execute(
            select(VoiceTurnMetric)
            .where(VoiceTurnMetric.tenant_id == tenant_id)
            .order_by(VoiceTurnMetric.id.desc())
            .limit(limit)
        )
    ).scalars().all()

    if not rows:
        return {"count": 0, "p50_ms": 0, "p95_ms": 0, "avg_ms": 0, "fallback_rate": 0.0, "by_channel": {}, "by_intent": {}}

    think_times = sorted(row.think_ms for row in rows)
    fallback_count = sum(1 for row in rows if row.used_fallback)

    by_channel: dict[str, dict] = {}
    by_intent: dict[str, dict] = {}
    for row in rows:
        for bucket, key in ((by_channel, row.channel), (by_intent, row.intent)):
            entry = bucket.setdefault(key, {"count": 0, "total_ms": 0})
            entry["count"] += 1
            entry["total_ms"] += row.think_ms
    for bucket in (by_channel, by_intent):
        for entry in bucket.values():
            entry["avg_ms"] = round(entry["total_ms"] / entry["count"])
            del entry["total_ms"]

    return {
        "count": len(rows),
        "p50_ms": _percentile(think_times, 0.50),
        "p95_ms": _percentile(think_times, 0.95),
        "avg_ms": round(sum(think_times) / len(think_times)),
        "fallback_rate": round(fallback_count / len(rows), 4),
        "by_channel": by_channel,
        "by_intent": by_intent,
    }


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
