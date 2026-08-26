"""Integracion de notificaciones. Para el laboratorio simula el envio
(deja rastro en audit_logs) en vez de llamar a la API real de WhatsApp/SMS;
el contrato ya queda listo para enchufar el proveedor real despues."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models import AuditLog


class NotificationService:
    def __init__(self, session: AsyncSession, tenant_id: str):
        self.session = session
        self.tenant_id = tenant_id

    async def send_order_confirmation(
        self, order_id: int, customer_id: int | None, channel: str = "whatsapp"
    ) -> dict:
        message = f"Tu pedido #{order_id} fue confirmado. Te avisaremos cuando este listo."
        self.session.add(
            AuditLog(
                tenant_id=self.tenant_id,
                actor="system",
                action="notification.sent",
                entity_type="Order",
                entity_id=str(order_id),
                detail=f"[{channel}] customer={customer_id} :: {message}",
            )
        )
        await self.session.commit()
        return {"channel": channel, "message": message, "delivered": True}
