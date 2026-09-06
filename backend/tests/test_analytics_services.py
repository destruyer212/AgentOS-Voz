"""Contabilidad del panel (/contabilidad, ver app/domain/analytics_services.py).

Cubre lo que de verdad puede salir mal en un reporte de plata: contar un
pedido cancelado como venta, agrupar "por dia" con el dia UTC en vez del
dia de Peru (America/Lima, UTC-5 -- un pedido de las 7pm hora Lima cae en
el dia UTC siguiente si no se convierte), o inflar el total facturado con
comprobantes rechazados/anulados por SUNAT.
"""

from datetime import UTC, date, datetime

import pytest
from sqlalchemy import delete, select, update

from app.domain.analytics_services import AnalyticsError, AnalyticsService
from app.domain.invoicing_models import Invoice, InvoiceItem
from app.domain.models import Conversation, InventoryItem, Order, OrderItem, Product
from app.domain.schemas import CustomerCreate, OrderCreate, OrderItemIn
from app.domain.services import CustomerService, OrderService
from app.infrastructure.config import settings
from app.infrastructure.db.session import AsyncSessionLocal, init_db
from app.infrastructure.seed import seed_demo_data


@pytest.fixture(autouse=True)
async def demo_db():
    await init_db()
    await seed_demo_data()
    yield


async def _wipe_transactional_data() -> None:
    async with AsyncSessionLocal() as session:
        for model in (OrderItem, Order, InvoiceItem, Invoice, Conversation):
            await session.execute(delete(model).where(model.tenant_id == settings.default_tenant_id))
        # Bug real de la suite (ver conftest.py): el stock del seed es
        # compartido por TODO el archivo de test y nunca se repone solo --
        # este archivo crea muchos pedidos confirmados (cada uno descuenta
        # stock de verdad), asi que sin esto puede dejar productos como
        # "Hamburguesa Clasica" en 0 unidades para los tests de otros
        # archivos que corran despues. Reponer stock generoso antes de cada
        # test es mas simple y confiable que rastrear cuanto se gasto.
        await session.execute(
            update(InventoryItem)
            .where(InventoryItem.tenant_id == settings.default_tenant_id)
            .values(quantity=9999, reserved=0)
        )
        await session.commit()


@pytest.fixture(autouse=True)
async def _isolated_order_data(demo_db):
    """Los tests de este archivo agregan sobre TODOS los pedidos del tenant
    (`range="all"`) -- sin este borrado, pedidos/comprobantes que dejaron
    otros archivos de test en el mismo sqlite compartido (ver conftest.py)
    inflan los conteos y los tests se vuelven no deterministas segun el
    orden en que corra la suite completa. Se corre DESPUES de `demo_db` (se
    lo pide como parametro) para no borrar el seed de productos/tenant, y
    TAMBIEN al terminar cada test -- si no, los comprobantes B001/numero=1
    que estos tests crean a mano chocan (UNIQUE constraint) con el
    correlativo real que arma InvoicingService en test_invoicing.py cuando
    corre despues en la misma suite."""
    await _wipe_transactional_data()
    yield
    await _wipe_transactional_data()


async def _first_two_products(session) -> list[Product]:
    rows = (await session.execute(select(Product).order_by(Product.id).limit(2))).scalars().all()
    assert len(rows) >= 2, "el seed demo necesita al menos 2 productos para estos tests"
    return list(rows)


async def _set_created_at(session, order_id: int, when_utc: datetime) -> None:
    """`when_utc` debe ser tz-aware (UTC) -- se guarda naive porque asi
    vive `created_at` en la columna real (ver TimestampMixin), pero forzar
    tzinfo explicito al construirlo en el test evita que sea ambiguo de
    donde sale ese naive (mismo motivo que el resto del repo usa
    `datetime.now(UTC).replace(tzinfo=None)` en vez de un naive suelto)."""
    order = await session.get(Order, order_id)
    order.created_at = when_utc.replace(tzinfo=None)
    await session.commit()


@pytest.mark.asyncio
async def test_summary_excludes_cancelled_and_draft_orders_from_revenue():
    async with AsyncSessionLocal() as session:
        order_svc = OrderService(session, settings.default_tenant_id)
        product, _ = await _first_two_products(session)

        kept = await order_svc.create_confirmed_order(
            OrderCreate(items=[OrderItemIn(product_id=product.id, quantity=1)])
        )
        cancelled = await order_svc.create_confirmed_order(
            OrderCreate(items=[OrderItemIn(product_id=product.id, quantity=1)])
        )
        await order_svc.update_status(cancelled.id, "cancelled")

        summary = await AnalyticsService(session, settings.default_tenant_id).summary("all")
        assert summary["orders_count"] == 1
        assert summary["revenue_total"] == round(kept.total, 2)
        assert summary["cancelled_count"] == 1
        assert summary["cancelled_rate"] == 0.5


@pytest.mark.asyncio
async def test_average_ticket_is_revenue_over_order_count():
    async with AsyncSessionLocal() as session:
        order_svc = OrderService(session, settings.default_tenant_id)
        product, _ = await _first_two_products(session)

        o1 = await order_svc.create_confirmed_order(OrderCreate(items=[OrderItemIn(product_id=product.id, quantity=1)]))
        o2 = await order_svc.create_confirmed_order(OrderCreate(items=[OrderItemIn(product_id=product.id, quantity=3)]))

        summary = await AnalyticsService(session, settings.default_tenant_id).summary("all")
        expected_avg = round((o1.total + o2.total) / 2, 2)
        assert summary["average_ticket"] == expected_avg


@pytest.mark.asyncio
async def test_revenue_by_day_buckets_by_lima_calendar_day_not_utc():
    # 03:00 UTC == 22:00 del dia anterior en Lima (UTC-5) -- si el bucketing
    # no convierte a hora local, este pedido cae en el dia equivocado.
    async with AsyncSessionLocal() as session:
        order_svc = OrderService(session, settings.default_tenant_id)
        product, _ = await _first_two_products(session)
        order = await order_svc.create_confirmed_order(
            OrderCreate(items=[OrderItemIn(product_id=product.id, quantity=1)])
        )
        utc_early_morning = datetime(2026, 3, 11, 3, 0, 0, tzinfo=UTC)  # 2026-03-10 22:00 hora Lima
        await _set_created_at(session, order.id, utc_early_morning)

        summary = await AnalyticsService(session, settings.default_tenant_id).summary("all")
        assert len(summary["revenue_by_day"]) == 1
        assert summary["revenue_by_day"][0]["date"] == date(2026, 3, 10).isoformat()


@pytest.mark.asyncio
async def test_summary_range_today_excludes_orders_from_previous_days():
    async with AsyncSessionLocal() as session:
        order_svc = OrderService(session, settings.default_tenant_id)
        product, _ = await _first_two_products(session)
        old_order = await order_svc.create_confirmed_order(
            OrderCreate(items=[OrderItemIn(product_id=product.id, quantity=1)])
        )
        await _set_created_at(session, old_order.id, datetime(2020, 1, 1, 12, 0, 0, tzinfo=UTC))

        summary = await AnalyticsService(session, settings.default_tenant_id).summary("today")
        assert summary["orders_count"] == 0
        assert summary["revenue_total"] == 0.0


@pytest.mark.asyncio
async def test_invalid_range_raises_analytics_error():
    async with AsyncSessionLocal() as session:
        with pytest.raises(AnalyticsError):
            await AnalyticsService(session, settings.default_tenant_id).summary("nunca-jamas")


@pytest.mark.asyncio
async def test_top_products_aggregates_quantity_and_revenue_across_orders():
    async with AsyncSessionLocal() as session:
        order_svc = OrderService(session, settings.default_tenant_id)
        product_a, product_b = await _first_two_products(session)

        await order_svc.create_confirmed_order(
            OrderCreate(items=[OrderItemIn(product_id=product_a.id, quantity=2)])
        )
        await order_svc.create_confirmed_order(
            OrderCreate(
                items=[
                    OrderItemIn(product_id=product_a.id, quantity=1),
                    OrderItemIn(product_id=product_b.id, quantity=5),
                ]
            )
        )

        report = await AnalyticsService(session, settings.default_tenant_id).top_products("all", limit=10)
        by_id = {row["product_id"]: row for row in report["by_quantity"]}
        assert by_id[product_a.id]["quantity"] == 3
        assert by_id[product_a.id]["orders_count"] == 2
        assert by_id[product_b.id]["quantity"] == 5
        # Ordenado por cantidad desc: product_b (5) antes que product_a (3).
        assert report["by_quantity"][0]["product_id"] == product_b.id


@pytest.mark.asyncio
async def test_top_customers_separates_registered_from_anonymous():
    async with AsyncSessionLocal() as session:
        order_svc = OrderService(session, settings.default_tenant_id)
        customer_svc = CustomerService(session, settings.default_tenant_id)
        product, _ = await _first_two_products(session)

        customer = await customer_svc.get_or_create(CustomerCreate(name="Cliente Fiel", phone="+51911111111"))
        await session.commit()

        await order_svc.create_confirmed_order(
            OrderCreate(customer_id=customer.id, items=[OrderItemIn(product_id=product.id, quantity=1)])
        )
        await order_svc.create_confirmed_order(
            OrderCreate(customer_id=customer.id, items=[OrderItemIn(product_id=product.id, quantity=2)])
        )
        anon_order = await order_svc.create_confirmed_order(
            OrderCreate(items=[OrderItemIn(product_id=product.id, quantity=1)])
        )

        report = await AnalyticsService(session, settings.default_tenant_id).top_customers("all", limit=10)
        assert report["by_spend"][0]["customer_id"] == customer.id
        assert report["by_spend"][0]["orders_count"] == 2
        assert report["anonymous_orders"] == 1
        assert report["anonymous_revenue"] == round(anon_order.total, 2)


@pytest.mark.asyncio
async def test_sales_by_channel_reads_channel_from_matching_conversation():
    async with AsyncSessionLocal() as session:
        order_svc = OrderService(session, settings.default_tenant_id)
        product, _ = await _first_two_products(session)

        session.add(
            Conversation(
                tenant_id=settings.default_tenant_id,
                external_id="conv-phone-1",
                channel="phone",
                status="closed",
            )
        )
        await session.commit()

        await order_svc.create_confirmed_order(
            OrderCreate(
                conversation_id="conv-phone-1",
                items=[OrderItemIn(product_id=product.id, quantity=1)],
            )
        )
        # Pedido sin conversation_id (ej. armado a mano desde el panel) --
        # debe caer en el balde "manual", nunca reventar por conversacion
        # faltante.
        await order_svc.create_confirmed_order(
            OrderCreate(items=[OrderItemIn(product_id=product.id, quantity=1)])
        )

        report = await AnalyticsService(session, settings.default_tenant_id).sales_by_channel("all")
        by_key = {row["key"]: row for row in report["by_channel"]}
        assert by_key["phone"]["orders"] == 1
        assert by_key["manual"]["orders"] == 1


@pytest.mark.asyncio
async def test_sales_by_time_buckets_by_lima_weekday_and_hour():
    async with AsyncSessionLocal() as session:
        order_svc = OrderService(session, settings.default_tenant_id)
        product, _ = await _first_two_products(session)
        order = await order_svc.create_confirmed_order(
            OrderCreate(items=[OrderItemIn(product_id=product.id, quantity=1)])
        )
        # 2026-03-11 (miercoles) 01:00 UTC == 2026-03-10 (martes) 20:00 Lima.
        await _set_created_at(session, order.id, datetime(2026, 3, 11, 1, 0, 0, tzinfo=UTC))

        report = await AnalyticsService(session, settings.default_tenant_id).sales_by_time("all")
        tuesday = report["by_weekday"][1]  # 0=lunes, 1=martes
        assert tuesday["label"] == "Martes"
        assert tuesday["orders"] == 1
        assert report["by_hour"][20]["orders"] == 1
        assert report["peak_hour"]["hour"] == 20


@pytest.mark.asyncio
async def test_invoices_summary_only_counts_accepted_toward_total_facturado():
    async with AsyncSessionLocal() as session:
        accepted = Invoice(
            tenant_id=settings.default_tenant_id,
            document_type="boleta",
            serie="B001",
            numero=1,
            fecha_emision=datetime.now(UTC).date(),
            cliente_tipo_doc="1",
            cliente_numero_doc="12345678",
            cliente_denominacion="Cliente Aceptado",
            total=118.0,
            total_igv=18.0,
            sunat_status="accepted",
            sunat_pdf_a4_url="https://apisunat.pe/pdf/a4/b001-1.pdf",
        )
        rejected = Invoice(
            tenant_id=settings.default_tenant_id,
            document_type="boleta",
            serie="B001",
            numero=2,
            fecha_emision=datetime.now(UTC).date(),
            cliente_tipo_doc="1",
            cliente_numero_doc="87654321",
            cliente_denominacion="Cliente Rechazado",
            total=59.0,
            total_igv=9.0,
            sunat_status="rejected",
        )
        session.add_all([accepted, rejected])
        await session.commit()

        report = await AnalyticsService(session, settings.default_tenant_id).invoices_summary("all")
        assert report["invoices_count"] == 2
        assert report["total_facturado_aceptado"] == 118.0
        assert report["total_igv_aceptado"] == 18.0
        statuses = {row["status"]: row["count"] for row in report["by_status"]}
        assert statuses == {"accepted": 1, "rejected": 1}

        # Detalle con serie-numero formateado y el link al PDF real --
        # ambos comprobantes aparecen aca (el filtro accepted-only es solo
        # para el total facturado, no para la lista).
        by_serie_numero = {row["serie_numero"]: row for row in report["recent_invoices"]}
        assert by_serie_numero["B001-00000001"]["pdf_a4_url"] == "https://apisunat.pe/pdf/a4/b001-1.pdf"
        assert by_serie_numero["B001-00000001"]["sunat_status"] == "accepted"
        assert by_serie_numero["B001-00000002"]["sunat_status"] == "rejected"
