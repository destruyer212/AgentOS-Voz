from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.domain.models import AuditLog, Customer, InventoryItem, Order, OrderItem, Product
from app.domain.schemas import CustomerCreate, OrderCreate, OrderItemOut, OrderOut, ProductOut
from app.domain.text_utils import tokenize


class DomainError(Exception):
    pass


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
            stock_available=max(inventory.quantity - inventory.reserved, 0),
        )

    async def search(self, query: str, limit: int = 5) -> list[ProductOut]:
        """Matching difuso en Python (no SQL LIKE): tolera plurales y orden
        de palabras distinto ("hamburguesas dobles" -> "Hamburguesa Doble"),
        clave para que el NLU basado en reglas encuentre productos reales."""
        query_tokens = tokenize(query)
        if not query_tokens:
            return []

        scored: list[tuple[float, Product, InventoryItem]] = []
        for product, inventory in await self._active_with_inventory():
            name_tokens = tokenize(product.name)
            token_score = 0.0
            for qt in query_tokens:
                if qt in name_tokens:
                    token_score += 1.0  # match exacto de palabra completa
                elif any(qt in nt or nt in qt for nt in name_tokens):
                    token_score += 0.6  # match parcial (substring)
            if token_score == 0:
                continue
            score = token_score / len(query_tokens)
            scored.append((score, product, inventory))

        scored.sort(key=lambda row: (-row[0], row[1].name))
        return [self._to_out(product, inventory) for _, product, inventory in scored[:limit]]

    async def list_all(self) -> list[ProductOut]:
        rows = sorted(await self._active_with_inventory(), key=lambda row: row[0].name)
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

        total = 0.0
        for item in data.items:
            product = product_by_id.get(item.product_id)
            inventory = inventory_by_product.get(item.product_id)
            if not product or not inventory:
                raise DomainError(f"Producto no disponible: {item.product_id}")
            available = inventory.quantity - inventory.reserved
            if available < item.quantity:
                raise DomainError(f"Stock insuficiente para {product.name}. Disponible: {available}")
            total += product.price * item.quantity

        order = Order(
            tenant_id=self.tenant_id,
            customer_id=data.customer_id,
            status="confirmed",
            requested_time=data.requested_time,
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

    @staticmethod
    def _to_out(order: Order) -> OrderOut:
        return OrderOut(
            id=order.id,
            customer_id=order.customer_id,
            customer_name=order.customer.name if order.customer else None,
            status=order.status,
            requested_time=order.requested_time,
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
