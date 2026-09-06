"""Contabilidad / reportes del negocio (panel admin: /contabilidad).

Todo se calcula a partir de datos reales de `orders`/`order_items`/
`invoices` -- nada mockeado. Igual que `system.py` (voice_metrics), los
endpoints devuelven `dict` en vez de un schema Pydantic formal: son
reportes de solo lectura, no contratos que otra parte del sistema
consuma, y el codebase ya sigue ese mismo patron ahi.

Agrupar "por dia"/"por hora"/"por dia de la semana" se hace en PYTHON, no
en SQL -- mismo motivo que los percentiles de voice_metrics: SQLite (dev
local) no tiene las funciones de fecha/timezone de Postgres (prod), y el
volumen real de pedidos de un restaurante (decenas a un par de cientos por
consulta) hace que traer las filas y agregar en memoria sea simple y
suficientemente rapido, sin duplicar logica de fechas en dos dialectos SQL
distintos.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.domain.invoicing_models import Invoice
from app.domain.models import Conversation, Order, OrderItem
from app.infrastructure.config import settings

# Pedidos que de verdad representan una venta -- excluye lo que nunca llego
# a confirmarse (draft/pending_confirmation, todavia no es un compromiso
# real del cliente) y lo que se cayo (cancelled/failed). Mismo criterio en
# TODAS las pantallas de /contabilidad para que ninguna cuente distinto.
_EXCLUDED_STATUSES = {"draft", "pending_confirmation", "cancelled", "failed"}
_CANCELLED_STATUSES = {"cancelled", "failed"}

RANGE_KEYS = ("today", "7d", "30d", "90d", "all")

_LIMA = ZoneInfo(settings.business_timezone)
_WEEKDAY_NAMES_ES = ("Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo")


class AnalyticsError(Exception):
    pass


def _range_start_utc(range_key: str) -> datetime | None:
    """Limite de inicio del rango, en UTC naive (asi se guarda created_at --
    ver TimestampMixin). Se calcula sobre la hora de Peru para que "hoy" y
    "ultimos 7 dias" respeten el dia calendario real del negocio, no el de
    UTC."""
    if range_key not in RANGE_KEYS:
        raise AnalyticsError(f"Rango invalido: '{range_key}'.")
    if range_key == "all":
        return None
    now_lima = datetime.now(_LIMA)
    days = {"today": 0, "7d": 7, "30d": 30, "90d": 90}[range_key]
    start_lima = (now_lima - timedelta(days=days)).replace(hour=0, minute=0, second=0, microsecond=0)
    return start_lima.astimezone(UTC).replace(tzinfo=None)


def _to_lima(naive_utc: datetime) -> datetime:
    return naive_utc.replace(tzinfo=UTC).astimezone(_LIMA)


class AnalyticsService:
    def __init__(self, session: AsyncSession, tenant_id: str):
        self.session = session
        self.tenant_id = tenant_id

    async def _load_orders(self, range_key: str) -> list[Order]:
        query = (
            select(Order)
            .where(Order.tenant_id == self.tenant_id, Order.status.notin_(_EXCLUDED_STATUSES))
            .options(selectinload(Order.items).selectinload(OrderItem.product), selectinload(Order.customer))
            .order_by(Order.created_at.asc())
        )
        start = _range_start_utc(range_key)
        if start is not None:
            query = query.where(Order.created_at >= start)
        return list((await self.session.execute(query)).scalars().all())

    async def _count_cancelled(self, range_key: str) -> int:
        query = select(Order).where(Order.tenant_id == self.tenant_id, Order.status.in_(_CANCELLED_STATUSES))
        start = _range_start_utc(range_key)
        if start is not None:
            query = query.where(Order.created_at >= start)
        rows = (await self.session.execute(query)).scalars().all()
        return len(rows)

    # ------------------------------------------------------------------
    # Resumen: cuanto se vendio, tendencia diaria, por entrega y por pago.
    # ------------------------------------------------------------------
    async def summary(self, range_key: str) -> dict:
        orders = await self._load_orders(range_key)
        cancelled_count = await self._count_cancelled(range_key)

        revenue_total = sum(o.total for o in orders)
        orders_count = len(orders)
        average_ticket = revenue_total / orders_count if orders_count else 0.0
        total_attempts = orders_count + cancelled_count
        cancelled_rate = cancelled_count / total_attempts if total_attempts else 0.0

        by_day: dict[date, dict] = {}
        by_fulfillment: dict[str, dict] = defaultdict(lambda: {"revenue": 0.0, "orders": 0})
        by_payment: dict[str, dict] = defaultdict(lambda: {"revenue": 0.0, "orders": 0})

        for order in orders:
            day = _to_lima(order.created_at).date()
            bucket = by_day.setdefault(day, {"revenue": 0.0, "orders": 0})
            bucket["revenue"] += order.total
            bucket["orders"] += 1

            fulfillment_key = order.fulfillment_type or "sin_especificar"
            by_fulfillment[fulfillment_key]["revenue"] += order.total
            by_fulfillment[fulfillment_key]["orders"] += 1

            payment_key = order.payment_method or "sin_especificar"
            by_payment[payment_key]["revenue"] += order.total
            by_payment[payment_key]["orders"] += 1

        return {
            "range": range_key,
            "orders_count": orders_count,
            "revenue_total": round(revenue_total, 2),
            "average_ticket": round(average_ticket, 2),
            "cancelled_count": cancelled_count,
            "cancelled_rate": round(cancelled_rate, 4),
            "revenue_by_day": [
                {"date": day.isoformat(), "revenue": round(v["revenue"], 2), "orders": v["orders"]}
                for day, v in sorted(by_day.items())
            ],
            "revenue_by_fulfillment": [
                {"key": k, "revenue": round(v["revenue"], 2), "orders": v["orders"]}
                for k, v in sorted(by_fulfillment.items(), key=lambda kv: -kv[1]["revenue"])
            ],
            "revenue_by_payment_method": [
                {"key": k, "revenue": round(v["revenue"], 2), "orders": v["orders"]}
                for k, v in sorted(by_payment.items(), key=lambda kv: -kv[1]["revenue"])
            ],
        }

    # ------------------------------------------------------------------
    # Platos: mas pedidos por cantidad, por ingreso, y por categoria.
    # ------------------------------------------------------------------
    async def top_products(self, range_key: str, limit: int) -> dict:
        orders = await self._load_orders(range_key)

        products: dict[int, dict] = {}
        by_category: dict[str, dict] = defaultdict(lambda: {"revenue": 0.0, "quantity": 0})
        orders_with_items = 0

        for order in orders:
            if order.items:
                orders_with_items += 1
            for item in order.items:
                revenue = item.quantity * item.unit_price
                name = item.product.name if item.product else f"Producto #{item.product_id} (eliminado)"
                category = item.product.category if item.product else "sin_categoria"
                entry = products.setdefault(
                    item.product_id,
                    {"product_id": item.product_id, "name": name, "category": category, "quantity": 0, "revenue": 0.0, "orders": set()},
                )
                entry["quantity"] += item.quantity
                entry["revenue"] += revenue
                entry["orders"].add(order.id)

                by_category[category]["revenue"] += revenue
                by_category[category]["quantity"] += item.quantity

        rows = [
            {
                "product_id": p["product_id"],
                "name": p["name"],
                "category": p["category"],
                "quantity": p["quantity"],
                "revenue": round(p["revenue"], 2),
                "orders_count": len(p["orders"]),
            }
            for p in products.values()
        ]

        return {
            "range": range_key,
            "orders_with_items": orders_with_items,
            "by_quantity": sorted(rows, key=lambda r: -r["quantity"])[:limit],
            "by_revenue": sorted(rows, key=lambda r: -r["revenue"])[:limit],
            "by_category": [
                {"category": k, "revenue": round(v["revenue"], 2), "quantity": v["quantity"]}
                for k, v in sorted(by_category.items(), key=lambda kv: -kv[1]["revenue"])
            ],
        }

    # ------------------------------------------------------------------
    # Clientes: quien gasta mas, quien pide mas seguido.
    # ------------------------------------------------------------------
    async def top_customers(self, range_key: str, limit: int) -> dict:
        orders = await self._load_orders(range_key)

        customers: dict[int, dict] = {}
        anonymous_revenue = 0.0
        anonymous_orders = 0

        for order in orders:
            if order.customer_id is None or order.customer is None:
                anonymous_revenue += order.total
                anonymous_orders += 1
                continue
            entry = customers.setdefault(
                order.customer_id,
                {
                    "customer_id": order.customer_id,
                    "name": order.customer.name,
                    "phone": order.customer.phone,
                    "revenue": 0.0,
                    "orders_count": 0,
                    "last_order_at": order.created_at,
                },
            )
            entry["revenue"] += order.total
            entry["orders_count"] += 1
            entry["last_order_at"] = max(entry["last_order_at"], order.created_at)

        rows = [
            {
                "customer_id": c["customer_id"],
                "name": c["name"],
                "phone": c["phone"],
                "revenue": round(c["revenue"], 2),
                "orders_count": c["orders_count"],
                "average_ticket": round(c["revenue"] / c["orders_count"], 2),
                "last_order_at": c["last_order_at"].isoformat(),
            }
            for c in customers.values()
        ]

        return {
            "range": range_key,
            "registered_customers": len(rows),
            "by_spend": sorted(rows, key=lambda r: -r["revenue"])[:limit],
            "by_frequency": sorted(rows, key=lambda r: -r["orders_count"])[:limit],
            "anonymous_orders": anonymous_orders,
            "anonymous_revenue": round(anonymous_revenue, 2),
        }

    # ------------------------------------------------------------------
    # Canales (telefono/web/whatsapp) y metodos de entrega/pago.
    # ------------------------------------------------------------------
    async def sales_by_channel(self, range_key: str) -> dict:
        orders = await self._load_orders(range_key)

        conversation_ids = {o.conversation_id for o in orders if o.conversation_id}
        channel_by_conversation: dict[str, str] = {}
        if conversation_ids:
            rows = (
                await self.session.execute(
                    select(Conversation.external_id, Conversation.channel).where(
                        Conversation.tenant_id == self.tenant_id,
                        Conversation.external_id.in_(conversation_ids),
                    )
                )
            ).all()
            channel_by_conversation = {external_id: channel for external_id, channel in rows}

        by_channel: dict[str, dict] = defaultdict(lambda: {"revenue": 0.0, "orders": 0})
        for order in orders:
            channel = channel_by_conversation.get(order.conversation_id, "manual") if order.conversation_id else "manual"
            by_channel[channel]["revenue"] += order.total
            by_channel[channel]["orders"] += 1

        return {
            "range": range_key,
            "by_channel": [
                {"key": k, "revenue": round(v["revenue"], 2), "orders": v["orders"]}
                for k, v in sorted(by_channel.items(), key=lambda kv: -kv[1]["revenue"])
            ],
        }

    # ------------------------------------------------------------------
    # Cuando vende mas el negocio: dia de la semana y hora del dia.
    # ------------------------------------------------------------------
    async def sales_by_time(self, range_key: str) -> dict:
        orders = await self._load_orders(range_key)

        by_weekday = [{"revenue": 0.0, "orders": 0} for _ in range(7)]
        by_hour = [{"revenue": 0.0, "orders": 0} for _ in range(24)]

        for order in orders:
            local = _to_lima(order.created_at)
            by_weekday[local.weekday()]["revenue"] += order.total
            by_weekday[local.weekday()]["orders"] += 1
            by_hour[local.hour]["revenue"] += order.total
            by_hour[local.hour]["orders"] += 1

        weekday_rows = [
            {"weekday": i, "label": _WEEKDAY_NAMES_ES[i], "revenue": round(v["revenue"], 2), "orders": v["orders"]}
            for i, v in enumerate(by_weekday)
        ]
        hour_rows = [
            {"hour": h, "label": f"{h:02d}:00", "revenue": round(v["revenue"], 2), "orders": v["orders"]}
            for h, v in enumerate(by_hour)
        ]

        peak_weekday = max(weekday_rows, key=lambda r: r["revenue"]) if orders else None
        peak_hour = max(hour_rows, key=lambda r: r["revenue"]) if orders else None

        return {
            "range": range_key,
            "by_weekday": weekday_rows,
            "by_hour": hour_rows,
            "peak_weekday": peak_weekday,
            "peak_hour": peak_hour,
        }

    # ------------------------------------------------------------------
    # Comprobantes SUNAT: boletas/facturas emitidas e IGV recaudado.
    # ------------------------------------------------------------------
    async def invoices_summary(self, range_key: str, list_limit: int = 200) -> dict:
        query = select(Invoice).where(Invoice.tenant_id == self.tenant_id).order_by(Invoice.id.desc())
        start = _range_start_utc(range_key)
        if start is not None:
            query = query.where(Invoice.fecha_emision >= start.date())
        invoices = list((await self.session.execute(query)).scalars().all())

        by_status: dict[str, dict] = defaultdict(lambda: {"count": 0, "total": 0.0})
        by_type: dict[str, dict] = defaultdict(lambda: {"count": 0, "total": 0.0})
        total_facturado = 0.0
        total_igv = 0.0

        for inv in invoices:
            by_status[inv.sunat_status]["count"] += 1
            by_status[inv.sunat_status]["total"] += inv.total
            if inv.sunat_status == "accepted":
                by_type[inv.document_type]["count"] += 1
                by_type[inv.document_type]["total"] += inv.total
                total_facturado += inv.total
                total_igv += inv.total_igv or 0.0

        return {
            "range": range_key,
            "invoices_count": len(invoices),
            "total_facturado_aceptado": round(total_facturado, 2),
            "total_igv_aceptado": round(total_igv, 2),
            "by_status": [
                {"status": k, "count": v["count"], "total": round(v["total"], 2)}
                for k, v in sorted(by_status.items(), key=lambda kv: -kv[1]["total"])
            ],
            "by_document_type": [
                {"document_type": k, "count": v["count"], "total": round(v["total"], 2)}
                for k, v in sorted(by_type.items(), key=lambda kv: -kv[1]["total"])
            ],
            # Detalle uno-a-uno con serie-numero y el link real al PDF que
            # devuelve apisunat.pe (ver invoicing_services.py) -- para poder
            # abrir el comprobante desde el panel sin tener que ir a buscarlo
            # a otro lado. Capado a `list_limit` (mas reciente primero); los
            # totales de arriba SI consideran todos los comprobantes del
            # rango, no solo los de esta lista.
            "recent_invoices": [
                {
                    "id": inv.id,
                    "order_id": inv.order_id,
                    "document_type": inv.document_type,
                    "serie_numero": f"{inv.serie}-{inv.numero:08d}",
                    "fecha_emision": inv.fecha_emision.isoformat(),
                    "cliente_tipo_doc": inv.cliente_tipo_doc,
                    "cliente_numero_doc": inv.cliente_numero_doc,
                    "cliente_denominacion": inv.cliente_denominacion,
                    "total": round(inv.total, 2),
                    "total_igv": round(inv.total_igv, 2) if inv.total_igv is not None else None,
                    "sunat_status": inv.sunat_status,
                    "sunat_message": inv.sunat_message,
                    "pdf_a4_url": inv.sunat_pdf_a4_url,
                    "pdf_ticket_url": inv.sunat_pdf_ticket_url,
                }
                for inv in invoices[:list_limit]
            ],
        }
