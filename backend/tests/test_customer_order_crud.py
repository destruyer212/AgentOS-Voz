"""CRUD de administracion agregado para el panel: editar/eliminar clientes,
cambiar el estado de un pedido. No pasa por el agente conversacional."""

import pytest
from sqlalchemy import select

from app.domain.models import Product
from app.domain.schemas import CustomerCreate, CustomerUpdate, OrderCreate, OrderItemIn
from app.domain.services import CustomerService, DomainError, OrderService
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
