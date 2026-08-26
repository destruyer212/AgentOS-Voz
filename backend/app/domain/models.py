from sqlalchemy import Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infrastructure.db.base import Base, TenantScopedMixin, TimestampMixin


class Tenant(Base, TimestampMixin):
    __tablename__ = "tenants"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    industry: Mapped[str] = mapped_column(String(80), default="restaurant")


class Customer(Base, TenantScopedMixin, TimestampMixin):
    __tablename__ = "customers"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(160))
    phone: Mapped[str | None] = mapped_column(String(40), index=True)
    address: Mapped[str | None] = mapped_column(String(240))
    notes: Mapped[str | None] = mapped_column(Text)


class Product(Base, TenantScopedMixin, TimestampMixin):
    __tablename__ = "products"
    __table_args__ = (UniqueConstraint("tenant_id", "sku"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    sku: Mapped[str] = mapped_column(String(80))
    name: Mapped[str] = mapped_column(String(160), index=True)
    description: Mapped[str | None] = mapped_column(Text)
    price: Mapped[float] = mapped_column(Float)
    active: Mapped[bool] = mapped_column(default=True)


class InventoryItem(Base, TenantScopedMixin, TimestampMixin):
    __tablename__ = "inventory"
    __table_args__ = (UniqueConstraint("tenant_id", "product_id"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    quantity: Mapped[int] = mapped_column(Integer, default=0)
    reserved: Mapped[int] = mapped_column(Integer, default=0)

    product: Mapped[Product] = relationship()


class Order(Base, TenantScopedMixin, TimestampMixin):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("customers.id"))
    status: Mapped[str] = mapped_column(String(40), default="draft")
    requested_time: Mapped[str | None] = mapped_column(String(40))
    total: Mapped[float] = mapped_column(Float, default=0)
    source: Mapped[str] = mapped_column(String(40), default="agent")

    customer: Mapped[Customer | None] = relationship()
    items: Mapped[list["OrderItem"]] = relationship(cascade="all, delete-orphan")


class OrderItem(Base, TenantScopedMixin, TimestampMixin):
    __tablename__ = "order_items"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"))
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    quantity: Mapped[int] = mapped_column(Integer)
    unit_price: Mapped[float] = mapped_column(Float)
    notes: Mapped[str | None] = mapped_column(Text)

    product: Mapped[Product] = relationship()


class Conversation(Base, TenantScopedMixin, TimestampMixin):
    __tablename__ = "conversations"
    __table_args__ = (UniqueConstraint("tenant_id", "external_id"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    external_id: Mapped[str] = mapped_column(String(64), index=True)
    agent_id: Mapped[str] = mapped_column(String(80), default="sofia_demo")
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("customers.id"))
    channel: Mapped[str] = mapped_column(String(40), default="web")
    status: Mapped[str] = mapped_column(String(40), default="active")
    transcript: Mapped[str] = mapped_column(Text, default="")
    outcome: Mapped[str | None] = mapped_column(String(80))


class WorkflowRun(Base, TenantScopedMixin, TimestampMixin):
    __tablename__ = "workflow_runs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    workflow_key: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(40))
    context_snapshot: Mapped[str] = mapped_column(Text, default="{}")
    trace: Mapped[str] = mapped_column(Text, default="[]")


class AuditLog(Base, TenantScopedMixin, TimestampMixin):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    actor: Mapped[str] = mapped_column(String(80))
    action: Mapped[str] = mapped_column(String(120))
    entity_type: Mapped[str] = mapped_column(String(80))
    entity_id: Mapped[str] = mapped_column(String(80))
    detail: Mapped[str] = mapped_column(Text, default="")
