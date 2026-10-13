"""Registro de tools autorizadas. Esta es la unica puerta por la que el
agente (o el workflow engine) puede tocar el negocio: LLM -> Tool ->
Domain Service -> DB transaction. Nunca al reves."""

from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models import AuditLog
from app.domain.schemas import CustomerCreate, OrderCreate, OrderItemIn
from app.domain.services import CustomerService, OrderService, ProductService
from app.integrations.notifications import NotificationService

ToolHandler = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


class ToolRegistry:
    def __init__(self, session: AsyncSession, tenant_id: str):
        self.session = session
        self.tenant_id = tenant_id

    def _tools(self) -> dict[str, ToolHandler]:
        return {
            "products.search": self.search_products,
            "products.menu": self.menu_products,
            "customers.get": self.get_customer,
            "customers.get_or_create": self.get_or_create_customer,
            "orders.create_confirmed": self.create_confirmed_order,
            "orders.schedule_delivery": self.schedule_delivery,
            "notifications.send_confirmation": self.send_confirmation,
            "conversation.transfer_to_human": self.transfer_to_human,
        }

    async def call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        tools = self._tools()
        if name not in tools:
            raise ValueError(f"Tool no registrada: {name}")
        return await tools[name](arguments)

    async def search_products(self, arguments: dict[str, Any]) -> dict[str, Any]:
        scored = await ProductService(self.session, self.tenant_id).search_scored(arguments.get("query", ""))
        # "ambiguo": el termino calza igual de bien con 2+ productos distintos
        # (ej. "hamburguesa" solo, sin decir cual) -- quien llama debe
        # preguntar cual en vez de adivinar (antes se quedaba con el primero
        # del orden alfabetico, silenciosamente).
        ambiguous = len(scored) > 1 and scored[0][0] == scored[1][0]
        return {
            "products": [product.model_dump() for _, product in scored],
            "ambiguous": ambiguous,
        }

    async def menu_products(self, arguments: dict[str, Any]) -> dict[str, Any]:
        products = await ProductService(self.session, self.tenant_id).list_all(category=arguments.get("category"))
        return {"products": [product.model_dump() for product in products]}

    async def get_customer(self, arguments: dict[str, Any]) -> dict[str, Any]:
        phone = arguments.get("phone")
        customer = await CustomerService(self.session, self.tenant_id).find_by_phone(phone) if phone else None
        if not customer:
            return {"customer": None}
        return {
            "customer": {
                "id": customer.id,
                "name": customer.name,
                "phone": customer.phone,
                "address": customer.address,
            }
        }

    async def get_or_create_customer(self, arguments: dict[str, Any]) -> dict[str, Any]:
        customer = await CustomerService(self.session, self.tenant_id).get_or_create(
            CustomerCreate(**arguments)
        )
        await self.session.commit()
        return {
            "customer": {
                "id": customer.id,
                "name": customer.name,
                "phone": customer.phone,
                "address": customer.address,
            }
        }

    async def create_confirmed_order(self, arguments: dict[str, Any]) -> dict[str, Any]:
        data = OrderCreate(
            customer_id=arguments.get("customer_id"),
            conversation_id=arguments.get("conversation_id"),
            requested_time=arguments.get("requested_time"),
            fulfillment_type=arguments.get("fulfillment_type"),
            delivery_address=arguments.get("delivery_address"),
            payment_method=arguments.get("payment_method"),
            payment_reference=arguments.get("payment_reference"),
            items=[OrderItemIn(**item) for item in arguments.get("items", [])],
        )
        order = await OrderService(self.session, self.tenant_id).create_confirmed_order(data)
        return {"order": order.model_dump()}

    async def schedule_delivery(self, arguments: dict[str, Any]) -> dict[str, Any]:
        result = await OrderService(self.session, self.tenant_id).schedule_delivery(
            arguments.get("order_id"), arguments.get("requested_time")
        )
        return {"schedule": result}

    async def send_confirmation(self, arguments: dict[str, Any]) -> dict[str, Any]:
        result = await NotificationService(self.session, self.tenant_id).send_order_confirmation(
            arguments.get("order_id"), arguments.get("customer_id"), arguments.get("channel") or "whatsapp"
        )
        return {"notification": result}

    async def transfer_to_human(self, arguments: dict[str, Any]) -> dict[str, Any]:
        self.session.add(
            AuditLog(
                tenant_id=self.tenant_id,
                actor="agent",
                action="conversation.transfer_to_human",
                entity_type="Conversation",
                entity_id=str(arguments.get("conversation_id", "")),
                detail=arguments.get("reason") or "",
            )
        )
        await self.session.commit()
        return {"transferred": True}
