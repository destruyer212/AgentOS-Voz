"""CRUD de administracion agregado para el panel: editar/eliminar clientes,
cambiar el estado de un pedido. No pasa por el agente conversacional."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.domain.models import Conversation, Product
from app.domain.schemas import CustomerCreate, CustomerUpdate, OrderCreate, OrderItemIn
from app.domain.services import (
    CustomerService,
    DomainError,
    OrderService,
    close_stale_web_conversations,
)
from app.infrastructure.config import settings
from app.infrastructure.db.session import AsyncSessionLocal, init_db
from app.infrastructure.seed import seed_demo_data


@pytest.fixture(autouse=True)
async def demo_db():
    await init_db()
    await seed_demo_data()
    yield


@pytest.mark.asyncio
async def test_update_customer_edits_only_provided_fields():
    async with AsyncSessionLocal() as session:
        svc = CustomerService(session, settings.default_tenant_id)
        customer = await svc.get_or_create(CustomerCreate(name="Original", phone="+51900000001"))
        await session.commit()

        updated = await svc.update(customer.id, CustomerUpdate(address="Av. Test 123"))
        assert updated.name == "Original"  # no se toco
        assert updated.address == "Av. Test 123"


@pytest.mark.asyncio
async def test_update_customer_rejects_blank_name():
    async with AsyncSessionLocal() as session:
        svc = CustomerService(session, settings.default_tenant_id)
        customer = await svc.get_or_create(CustomerCreate(name="Alguien", phone="+51900000002"))
        await session.commit()

        with pytest.raises(DomainError):
            await svc.update(customer.id, CustomerUpdate(name="   "))


@pytest.mark.asyncio
async def test_delete_customer_blocked_when_has_orders():
    async with AsyncSessionLocal() as session:
        customer_svc = CustomerService(session, settings.default_tenant_id)
        customer = await customer_svc.get_or_create(CustomerCreate(name="Con pedido", phone="+51900000003"))
        await session.commit()

        order_svc = OrderService(session, settings.default_tenant_id)
        products = await session.execute(select(Product).limit(1))
        product = products.scalars().first()
        await order_svc.create_confirmed_order(
            OrderCreate(customer_id=customer.id, items=[OrderItemIn(product_id=product.id, quantity=1)])
        )

        with pytest.raises(DomainError):
            await customer_svc.delete(customer.id)


@pytest.mark.asyncio
async def test_delete_customer_succeeds_without_history():
    async with AsyncSessionLocal() as session:
        svc = CustomerService(session, settings.default_tenant_id)
        customer = await svc.get_or_create(CustomerCreate(name="Sin historial", phone="+51900000004"))
        await session.commit()

        await svc.delete(customer.id)  # no debe tirar


@pytest.mark.asyncio
async def test_order_status_update_happy_path_and_rejects_invalid():
    async with AsyncSessionLocal() as session:
        order_svc = OrderService(session, settings.default_tenant_id)
        products = await session.execute(select(Product).limit(1))
        product = products.scalars().first()
        order = await order_svc.create_confirmed_order(
            OrderCreate(items=[OrderItemIn(product_id=product.id, quantity=1)])
        )

        updated = await order_svc.update_status(order.id, "preparing")
        assert updated.status == "preparing"

        with pytest.raises(DomainError):
            await order_svc.update_status(order.id, "no_existe")


@pytest.mark.asyncio
async def test_close_stale_web_conversations_only_touches_old_inactive_web():
    """Bug real: conversaciones web abandonadas (pestana cerrada, pruebas
    manuales) se quedaban en status="active" para siempre -- inflaban
    cualquier contador de "llamadas activas" del panel. El barrido debe
    cerrar solo canal web + vieja, nunca canal phone ni una reciente."""
    async with AsyncSessionLocal() as session:
        stale_web = Conversation(
            tenant_id=settings.default_tenant_id,
            external_id="stale-web-1",
            channel="web",
            status="active",
            updated_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=30),
        )
        recent_web = Conversation(
            tenant_id=settings.default_tenant_id,
            external_id="recent-web-1",
            channel="web",
            status="active",
            updated_at=datetime.now(UTC).replace(tzinfo=None),
        )
        stale_phone = Conversation(
            tenant_id=settings.default_tenant_id,
            external_id="stale-phone-1",
            channel="phone",
            status="active",
            updated_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=30),
        )
        session.add_all([stale_web, recent_web, stale_phone])
        await session.commit()

        closed = await close_stale_web_conversations(session, timeout_minutes=20)
        assert closed == ["stale-web-1"]

        await session.refresh(stale_web)
        await session.refresh(recent_web)
        await session.refresh(stale_phone)
        assert stale_web.status == "closed"
        assert stale_web.detail_status == "closed"
        assert stale_web.outcome == "session.timeout"
        assert recent_web.status == "active"  # muy reciente, no se toca
        assert stale_phone.status == "active"  # canal phone nunca se toca aca
