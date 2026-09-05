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
async def test_order_status_follows_kitchen_to_delivery_pipeline():
    # Flujo real del panel de Pedidos: cocina acepta (preparing), sale con
    # el motorizado (dispatched), el encargado marca entregado (delivered).
    # Cada paso tiene que quedar disponible en orden -- ver
    # _ORDER_STATUS_TRANSITIONS en services.py.
    async with AsyncSessionLocal() as session:
        order_svc = OrderService(session, settings.default_tenant_id)
        products = await session.execute(select(Product).limit(1))
        product = products.scalars().first()
        order = await order_svc.create_confirmed_order(
            OrderCreate(items=[OrderItemIn(product_id=product.id, quantity=1)])
        )
        assert order.status == "confirmed"

        order = await order_svc.update_status(order.id, "preparing")
        assert order.status == "preparing"

        order = await order_svc.update_status(order.id, "dispatched")
        assert order.status == "dispatched"

        order = await order_svc.update_status(order.id, "delivered")
        assert order.status == "delivered"


@pytest.mark.asyncio
async def test_order_status_rejects_skipping_steps():
    # No se puede pasar de "confirmed" directo a "delivered" ni "dispatched"
    # -- tiene que pasar por cocina primero. Bug real que se queria evitar:
    # hoy el desplegable del frontend deja saltar a cualquier estado sin
    # ningun control.
    async with AsyncSessionLocal() as session:
        order_svc = OrderService(session, settings.default_tenant_id)
        products = await session.execute(select(Product).limit(1))
        product = products.scalars().first()
        order = await order_svc.create_confirmed_order(
            OrderCreate(items=[OrderItemIn(product_id=product.id, quantity=1)])
        )

        with pytest.raises(DomainError):
            await order_svc.update_status(order.id, "delivered")
        with pytest.raises(DomainError):
            await order_svc.update_status(order.id, "dispatched")

        # Un estado terminal (delivered/cancelled/failed) tampoco admite mas
        # cambios -- ni siquiera volver para atras.
        order = await order_svc.update_status(order.id, "preparing")
        order = await order_svc.update_status(order.id, "dispatched")
        order = await order_svc.update_status(order.id, "delivered")
        with pytest.raises(DomainError):
            await order_svc.update_status(order.id, "preparing")


@pytest.mark.asyncio
async def test_get_customer_phone_returns_none_without_customer():
    async with AsyncSessionLocal() as session:
        order_svc = OrderService(session, settings.default_tenant_id)
        products = await session.execute(select(Product).limit(1))
        product = products.scalars().first()
        order = await order_svc.create_confirmed_order(
            OrderCreate(items=[OrderItemIn(product_id=product.id, quantity=1)])
        )
        assert await order_svc.get_customer_phone(order.id) is None

        customer_svc = CustomerService(session, settings.default_tenant_id)
        customer = await customer_svc.get_or_create(
            CustomerCreate(name="Con telefono", phone="+51900000099")
        )
        await session.commit()
        order2 = await order_svc.create_confirmed_order(
            OrderCreate(customer_id=customer.id, items=[OrderItemIn(product_id=product.id, quantity=1)])
        )
        assert await order_svc.get_customer_phone(order2.id) == "+51900000099"


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


@pytest.mark.asyncio
async def test_record_whatsapp_status_persists_status_and_timestamp():
    # Ver AgentRuntime._issue_invoice_and_notify / _notify_only: el panel de
    # Llamadas necesita saber de verdad si el aviso llego, no solo que se
    # disparo.
    async with AsyncSessionLocal() as session:
        order_svc = OrderService(session, settings.default_tenant_id)
        products = await session.execute(select(Product).limit(1))
        product = products.scalars().first()
        order = await order_svc.create_confirmed_order(
            OrderCreate(items=[OrderItemIn(product_id=product.id, quantity=1)])
        )
        assert order.whatsapp_status is None
        assert order.whatsapp_sent_at is None

        await order_svc.record_whatsapp_status(order.id, "sent")

        updated = await order_svc.get(order.id)
        assert updated.whatsapp_status == "sent"
        assert updated.whatsapp_sent_at is not None
