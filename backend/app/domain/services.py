from datetime import UTC, datetime, timedelta

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.domain.models import (
    AuditLog,
    Conversation,
    Customer,
    InventoryItem,
    Order,
    OrderItem,
    Product,
)
from app.domain.schemas import (
    CustomerCreate,
    CustomerUpdate,
    OrderCreate,
    OrderItemOut,
    OrderOut,
    ProductOut,
)
from app.domain.text_utils import (
    normalize_spoken_fractions,
    normalize_text,
    tokenize,
    tokens_partial_match,
)

_PRODUCT_QUERY_ALIASES = {
    "inca cola": "inca kola",
    "inka cola": "inca kola",
    "inka kola": "inca kola",
    "indo cola": "inca kola",
    "indo kola": "inca kola",
    "indocola": "inca kola",
    "indokola": "inca kola",
    # Bug real, visto en vivo: el cliente dijo "Mostro Olivar" (chaufa del
    # menu) y el ASR lo transcribio como "monstruo olivar" -- "mostro" no
    # es una palabra comun, asi que el modelo de lenguaje del STT se va
    # hacia "monstruo" (mucho mas frecuente en español). "monstruo" no
    # matcheaba "mostro" ni por prefijo ni por sufijo (son substrings
    # distintos), y "olivar" solo calzaba con OTROS 4 productos de otras
    # categorias -- nunca encontraba el chaufa real que se acababa de
    # nombrar en el turno anterior.
    "monstruo olivar": "mostro olivar",
    "monstruo": "mostro",
}


class DomainError(Exception):
    pass


_VALID_ORDER_STATUSES = {
    "draft", "pending_confirmation", "confirmed", "preparing", "ready",
    "dispatched", "scheduled", "delivered", "cancelled", "failed",
}

# Flujo de cocina->motorizado->entregado (ver panel de Pedidos): que
# transicion es valida desde cada estado, para que el encargado no pueda
# saltarse pasos por error (ej. pasar de "confirmed" directo a "delivered"
# sin que nadie en cocina ni el motorizado hayan hecho nada). Un estado sin
# entrada en este dict, o mapeado a un set vacio, es terminal -- no admite
# mas cambios via update_status.
_ORDER_STATUS_TRANSITIONS: dict[str, set[str]] = {
    "draft": {"pending_confirmation", "confirmed", "cancelled", "failed"},
    "pending_confirmation": {"confirmed", "cancelled", "failed"},
    "confirmed": {"preparing", "cancelled"},
    "scheduled": {"preparing", "cancelled"},
    # "dispatched" es el paso del motorizado (solo tiene sentido para
    # delivery -- dispara el aviso de WhatsApp "ya salio"). "ready" es para
    # recojo en el local: el cliente se lleva su pedido directo, sin
    # motorizado de por medio, asi que pasa derecho a "delivered".
    "preparing": {"ready", "dispatched", "cancelled"},
    "ready": {"delivered", "cancelled"},
    "dispatched": {"delivered"},
    "delivered": set(),
    "cancelled": set(),
    "failed": set(),
}


def _canonical_product_query(query: str) -> str:
    query = normalize_spoken_fractions(query)
    normalized = " ".join(tokenize(query))
    if normalized in _PRODUCT_QUERY_ALIASES:
        return _PRODUCT_QUERY_ALIASES[normalized]
    return query


class ProductService:
    def __init__(self, session: AsyncSession, tenant_id: str):
        self.session = session
        self.tenant_id = tenant_id

    async def _active_with_inventory(self) -> list[tuple[Product, InventoryItem]]:
        stmt = (
            select(Product, InventoryItem)
            .join(InventoryItem, InventoryItem.product_id == Product.id)
            .where(Product.tenant_id == self.tenant_id)
            .where(Product.active.is_(True))
        )
        return list((await self.session.execute(stmt)).all())

    @staticmethod
    def _to_out(product: Product, inventory: InventoryItem) -> ProductOut:
        return ProductOut(
            id=product.id,
            sku=product.sku,
            name=product.name,
            description=product.description,
            price=product.price,
            category=product.category,
            stock_available=max(inventory.quantity - inventory.reserved, 0),
            unidad_medida=product.unidad_medida,
            igv_affectation_code=product.igv_affectation_code,
            igv_percentage=product.igv_percentage,
            igv_tribute_name=product.igv_tribute_name,
        )

    async def search_scored(self, query: str, limit: int = 5) -> list[tuple[float, ProductOut]]:
        """Matching difuso en Python (no SQL LIKE): tolera plurales y orden
        de palabras distinto ("hamburguesas dobles" -> "Hamburguesa Doble"),
        clave para que el NLU basado en reglas encuentre productos reales.
        Devuelve el score junto al producto para que quien llama pueda
        detectar empates (termino generico como "hamburguesa" que calza
        igual de bien con varias variantes) y pedir aclaracion en vez de
        adivinar cual quiso decir el cliente."""
        query_tokens = tokenize(_canonical_product_query(query))
        if not query_tokens:
            return []
        normalized_query = normalize_text(_canonical_product_query(query))

        scored: list[tuple[float, Product, InventoryItem]] = []
        for product, inventory in await self._active_with_inventory():
            normalized_name = normalize_text(product.name)
            name_tokens = tokenize(product.name)
            token_score = 0.0
            for qt in query_tokens:
                if qt in name_tokens:
                    token_score += 1.0  # match exacto de palabra completa
                elif any(tokens_partial_match(qt, nt) for nt in name_tokens):
                    # match parcial (prefijo/sufijo, no substring a mitad de
                    # palabra -- ver tokens_partial_match) -- el minimo de 3
                    # caracteres es a proposito: un fragmento de 1-2 letras
                    # (ej. "C" de una transcripcion cortada) es prefijo de
                    # CASI cualquier palabra y generaba coincidencias sin
                    # sentido. Visto en vivo en una llamada real: "C"
                    # matcheo contra 4 productos no relacionados entre si.
                    token_score += 0.6
            if token_score == 0:
                continue
            score = round(token_score / len(query_tokens), 4)
            if normalized_query == normalized_name:
                score += 2.0
            elif normalized_query in normalized_name:
                score += 0.25
            scored.append((score, product, inventory))

        scored.sort(key=lambda row: (-row[0], row[1].name))
        return [(score, self._to_out(product, inventory)) for score, product, inventory in scored[:limit]]

    async def search(self, query: str, limit: int = 5) -> list[ProductOut]:
        return [out for _, out in await self.search_scored(query, limit)]

    async def list_all(self, category: str | None = None) -> list[ProductOut]:
        rows = sorted(await self._active_with_inventory(), key=lambda row: row[0].name)
        if category:
            rows = [row for row in rows if row[0].category == category]
        return [self._to_out(product, inventory) for product, inventory in rows]


class CustomerService:
    def __init__(self, session: AsyncSession, tenant_id: str):
        self.session = session
        self.tenant_id = tenant_id

    async def get_or_create(self, data: CustomerCreate) -> Customer:
        if data.phone:
            existing = await self.session.scalar(
                select(Customer).where(
                    Customer.tenant_id == self.tenant_id,
                    Customer.phone == data.phone,
                )
            )
            if existing:
                return existing

        customer = Customer(tenant_id=self.tenant_id, **data.model_dump())
        self.session.add(customer)
        await self.session.flush()
        await self._audit("customer.created", "Customer", str(customer.id), customer.name)
        return customer

    async def find_by_phone(self, phone: str) -> Customer | None:
        return await self.session.scalar(
            select(Customer).where(Customer.tenant_id == self.tenant_id, Customer.phone == phone)
        )

    async def list_all(self, query: str | None = None, limit: int = 100) -> list[Customer]:
        stmt = select(Customer).where(Customer.tenant_id == self.tenant_id)
        if query:
            like = f"%{query}%"
            stmt = stmt.where(or_(Customer.name.ilike(like), Customer.phone.ilike(like)))
        stmt = stmt.order_by(Customer.id.desc()).limit(limit)
        return list((await self.session.execute(stmt)).scalars().all())

    async def update_name(self, customer_id: int, name: str) -> None:
        customer = await self.session.get(Customer, customer_id)
        if customer and customer.tenant_id == self.tenant_id:
            customer.name = name

    async def update_address(self, customer_id: int, address: str) -> None:
        customer = await self.session.get(Customer, customer_id)
        if customer and customer.tenant_id == self.tenant_id:
            customer.address = address

    async def update_tax_info(self, customer_id: int, doc_type: str, doc_number: str, legal_name: str) -> None:
        """Guarda el RUC/razon social que dio el cliente al pedir factura
        (ver AgentRuntime._apply_detail_answer, need_ruc) para no tener que
        volver a pedirlo la proxima vez que llame o escriba."""
        customer = await self.session.get(Customer, customer_id)
        if customer and customer.tenant_id == self.tenant_id:
            customer.doc_type = doc_type
            customer.doc_number = doc_number
            customer.legal_name = legal_name

    async def update(self, customer_id: int, data: "CustomerUpdate") -> Customer:
        customer = await self.session.get(Customer, customer_id)
        if not customer or customer.tenant_id != self.tenant_id:
            raise DomainError("Cliente no encontrado.")
        fields = data.model_dump(exclude_unset=True)
        if "name" in fields and not (fields["name"] or "").strip():
            raise DomainError("El nombre no puede quedar vacío.")
        for key, value in fields.items():
            setattr(customer, key, value)
        await self._audit("customer.updated", "Customer", str(customer.id), customer.name)
        await self.session.commit()
        return customer

    async def delete(self, customer_id: int) -> None:
        customer = await self.session.get(Customer, customer_id)
        if not customer or customer.tenant_id != self.tenant_id:
            raise DomainError("Cliente no encontrado.")

        # No lo dejamos ir si tiene pedidos o conversaciones reales
        # asociadas -- borrarlo ahi rompe la referencia (FK) y, peor,
        # destruye historial de negocio real sin avisar. Mejor decir por
        # que no se puede en vez de fallar con un error de base de datos
        # crudo, o silenciosamente dejar huerfanos.
        has_orders = await self.session.scalar(
            select(Order.id).where(Order.tenant_id == self.tenant_id, Order.customer_id == customer_id).limit(1)
        )
        if has_orders:
            raise DomainError(
                "No se puede eliminar: este cliente tiene pedidos asociados. "
                "Conserva el historial o contacta soporte para un borrado forzado."
            )
        has_conversations = await self.session.scalar(
            select(Conversation.id)
            .where(Conversation.tenant_id == self.tenant_id, Conversation.customer_id == customer_id)
            .limit(1)
        )
        if has_conversations:
            raise DomainError(
                "No se puede eliminar: este cliente tiene conversaciones registradas."
            )

        await self._audit("customer.deleted", "Customer", str(customer.id), customer.name)
        await self.session.delete(customer)
        await self.session.commit()

    async def _audit(self, action: str, entity_type: str, entity_id: str, detail: str) -> None:
        self.session.add(
            AuditLog(
                tenant_id=self.tenant_id,
                actor="system",
                action=action,
                entity_type=entity_type,
                entity_id=entity_id,
                detail=detail,
            )
        )


class OrderService:
    def __init__(self, session: AsyncSession, tenant_id: str):
        self.session = session
        self.tenant_id = tenant_id

    async def create_confirmed_order(self, data: OrderCreate) -> OrderOut:
        if not data.items:
            raise DomainError("El pedido debe tener al menos un item.")

        product_ids = [item.product_id for item in data.items]
        products = (
            await self.session.execute(
                select(Product).where(Product.tenant_id == self.tenant_id, Product.id.in_(product_ids))
            )
        ).scalars().all()
        product_by_id = {product.id: product for product in products}

        inventory_rows = (
            await self.session.execute(
                select(InventoryItem).where(
                    InventoryItem.tenant_id == self.tenant_id,
                    InventoryItem.product_id.in_(product_ids),
                )
            )
        ).scalars().all()
        inventory_by_product = {item.product_id: item for item in inventory_rows}

        # Si el mismo producto aparece en mas de un item del pedido (ej. dos
        # lineas separadas de "Coca-Cola" en vez de una con quantity=2), hay
        # que sumar lo pedido de ESE producto antes de comparar contra stock:
        # chequear cada linea por separado contra el mismo `inventory.quantity`
        # sin descontar deja pasar la validacion de las dos aunque juntas
        # superen el disponible (el UPDATE atomico de abajo lo termina
        # bloqueando igual, pero con un mensaje enganoso de "se agoto justo
        # antes de confirmar" en vez de avisar stock insuficiente de una).
        requested_by_product: dict[int, int] = {}
        for item in data.items:
            requested_by_product[item.product_id] = requested_by_product.get(item.product_id, 0) + item.quantity

        total = 0.0
        for item in data.items:
            product = product_by_id.get(item.product_id)
            inventory = inventory_by_product.get(item.product_id)
            if not product or not inventory:
                raise DomainError(f"Producto no disponible: {item.product_id}")
            available = inventory.quantity - inventory.reserved
            if available < requested_by_product[item.product_id]:
                raise DomainError(f"Stock insuficiente para {product.name}. Disponible: {available}")
            total += product.price * item.quantity

        order = Order(
            tenant_id=self.tenant_id,
            customer_id=data.customer_id,
            conversation_id=data.conversation_id,
            status="confirmed",
            requested_time=data.requested_time,
            fulfillment_type=data.fulfillment_type,
            delivery_address=data.delivery_address,
            payment_method=data.payment_method,
            total=round(total, 2),
            source="agent",
        )
        self.session.add(order)
        await self.session.flush()

        for item in data.items:
            product = product_by_id[item.product_id]

            # UPDATE atomico guardado por condicion: el chequeo de arriba ya
            # dio un mensaje de error rapido en el caso comun, pero entre esa
            # lectura y este punto otra confirmacion concurrente pudo agotar
            # el stock (dos pedidos confirmandose al mismo tiempo). Un
            # read-then-write en Python no es seguro ahi; este UPDATE con
            # condicion WHERE si lo es, sin importar el motor de DB.
            result = await self.session.execute(
                update(InventoryItem)
                .where(
                    InventoryItem.tenant_id == self.tenant_id,
                    InventoryItem.product_id == item.product_id,
                    (InventoryItem.quantity - InventoryItem.reserved) >= item.quantity,
                )
                .values(quantity=InventoryItem.quantity - item.quantity)
            )
            if result.rowcount != 1:
                raise DomainError(
                    f"Stock insuficiente para {product.name} (se agoto justo antes de confirmar)."
                )

            self.session.add(
                OrderItem(
                    tenant_id=self.tenant_id,
                    order_id=order.id,
                    product_id=product.id,
                    quantity=item.quantity,
                    unit_price=product.price,
                    notes=item.notes,
                )
            )

        self.session.add(
            AuditLog(
                tenant_id=self.tenant_id,
                actor="agent",
                action="order.created",
                entity_type="Order",
                entity_id=str(order.id),
                detail=f"Pedido confirmado por S/ {order.total}",
            )
        )
        await self.session.commit()
        return await self.get(order.id)

    async def schedule_delivery(self, order_id: int, requested_time: str | None) -> dict:
        order = await self.session.scalar(
            select(Order).where(Order.tenant_id == self.tenant_id, Order.id == order_id)
        )
        if not order:
            raise DomainError("Pedido no encontrado para programar entrega.")

        order.requested_time = requested_time or order.requested_time
        order.status = "scheduled" if order.requested_time else "confirmed"
        self.session.add(
            AuditLog(
                tenant_id=self.tenant_id,
                actor="system",
                action="order.scheduled",
                entity_type="Order",
                entity_id=str(order.id),
                detail=f"status={order.status} requested_time={order.requested_time}",
            )
        )
        await self.session.commit()
        return {"order_id": order.id, "status": order.status, "requested_time": order.requested_time}

    async def update_status(self, order_id: int, status: str) -> OrderOut:
        if status not in _VALID_ORDER_STATUSES:
            raise DomainError(f"Estado de pedido invalido: {status}")
        order = await self.session.scalar(
            select(Order).where(Order.tenant_id == self.tenant_id, Order.id == order_id)
        )
        if not order:
            raise DomainError("Pedido no encontrado.")
        previous = order.status
        if status != previous:
            allowed = _ORDER_STATUS_TRANSITIONS.get(previous, set())
            if status not in allowed:
                raise DomainError(
                    f"No se puede pasar el pedido de '{previous}' a '{status}' directamente."
                )
        order.status = status
        self.session.add(
            AuditLog(
                tenant_id=self.tenant_id,
                actor="admin",
                action="order.status_changed",
                entity_type="Order",
                entity_id=str(order.id),
                detail=f"{previous} -> {status}",
            )
        )
        await self.session.commit()
        return await self.get(order.id)

    async def get_customer_phone(self, order_id: int) -> str | None:
        """Solo para el aviso de WhatsApp al despachar (ver
        app/api/v1/orders.py) -- OrderOut no expone el telefono a proposito
        (no hace falta mostrarlo en la tabla de Pedidos del frontend)."""
        order = await self.session.scalar(
            select(Order)
            .options(selectinload(Order.customer))
            .where(Order.tenant_id == self.tenant_id, Order.id == order_id)
        )
        if not order or not order.customer:
            return None
        return order.customer.phone

    async def get(self, order_id: int) -> OrderOut:
        order = await self.session.scalar(
            select(Order)
            .options(
                selectinload(Order.items).selectinload(OrderItem.product),
                selectinload(Order.customer),
            )
            .where(Order.tenant_id == self.tenant_id, Order.id == order_id)
        )
        if not order:
            raise DomainError("Pedido no encontrado.")
        return self._to_out(order)

    async def list_recent(self, limit: int = 50) -> list[OrderOut]:
        orders = (
            await self.session.execute(
                select(Order)
                .options(
                    selectinload(Order.items).selectinload(OrderItem.product),
                    selectinload(Order.customer),
                )
                .where(Order.tenant_id == self.tenant_id)
                .order_by(Order.id.desc())
                .limit(limit)
            )
        ).scalars().all()
        return [self._to_out(order) for order in orders]

    async def get_by_conversation(self, conversation_id: str) -> OrderOut | None:
        order = await self.session.scalar(
            select(Order)
            .options(
                selectinload(Order.items).selectinload(OrderItem.product),
                selectinload(Order.customer),
            )
            .where(Order.tenant_id == self.tenant_id, Order.conversation_id == conversation_id)
            .order_by(Order.id.desc())
        )
        return self._to_out(order) if order else None

    @staticmethod
    def _to_out(order: Order) -> OrderOut:
        return OrderOut(
            id=order.id,
            customer_id=order.customer_id,
            customer_name=order.customer.name if order.customer else None,
            conversation_id=order.conversation_id,
            status=order.status,
            requested_time=order.requested_time,
            fulfillment_type=order.fulfillment_type,
            delivery_address=order.delivery_address,
            payment_method=order.payment_method,
            total=order.total,
            items=[
                OrderItemOut(
                    product_id=item.product_id,
                    product_name=item.product.name,
                    quantity=item.quantity,
                    unit_price=item.unit_price,
                    notes=item.notes,
                )
                for item in order.items
            ],
        )


class ConversationService:
    def __init__(self, session: AsyncSession, tenant_id: str):
        self.session = session
        self.tenant_id = tenant_id

    async def list_recent(self, limit: int = 50) -> list[Conversation]:
        stmt = (
            select(Conversation)
            .options(selectinload(Conversation.customer))
            .where(Conversation.tenant_id == self.tenant_id)
            .order_by(Conversation.updated_at.desc())
            .limit(limit)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def get_by_external_id(self, external_id: str) -> Conversation | None:
        stmt = (
            select(Conversation)
            .options(selectinload(Conversation.customer))
            .where(Conversation.tenant_id == self.tenant_id, Conversation.external_id == external_id)
        )
        return await self.session.scalar(stmt)


async def close_stale_web_conversations(session: AsyncSession, *, timeout_minutes: int) -> list[str]:
    """Cierra conversaciones de canal "web" que quedaron abandonadas -- sin
    ningun turno nuevo en `timeout_minutes` -- y nunca llegaron a un cierre
    real del agente (order.confirm, cancelacion, handoff). El chat web no
    tiene equivalente al auto-hangup de la llamada telefonica, asi que sin
    esto se quedan en status="active" para siempre e inflan cualquier
    contador de "llamadas activas" del panel.

    Nunca toca canal "phone": esas ya se cierran solas via el bridge de
    Telnyx/Deepgram (voice_agent_bridge.py) y forzar un cierre aca podria
    cortar una llamada real en curso por una condicion de carrera.

    Devuelve los external_id cerrados, para poder loguearlo. Corre sin
    scope de tenant a proposito -- es un barrido de mantenimiento, no una
    operacion de un tenant en particular.
    """
    # naive UTC a proposito: la columna updated_at se guarda naive (ver
    # created_at/updated_at en TimestampMixin), no comparable con un
    # datetime con tzinfo.
    cutoff = datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=timeout_minutes)
    stmt = select(Conversation).where(
        Conversation.status == "active",
        Conversation.channel == "web",
        Conversation.updated_at < cutoff,
    )
    stale = list((await session.execute(stmt)).scalars().all())
    for convo in stale:
        convo.status = "closed"
        convo.detail_status = "closed"
        if not convo.outcome:
            convo.outcome = "session.timeout"
        session.add(
            AuditLog(
                tenant_id=convo.tenant_id,
                actor="system",
                action="conversation.auto_closed",
                entity_type="Conversation",
                entity_id=convo.external_id,
                detail=f"Sin actividad por mas de {timeout_minutes} min, canal={convo.channel}",
            )
        )
    if stale:
        await session.commit()
    return [c.external_id for c in stale]
