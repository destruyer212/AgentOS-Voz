"""Seed de datos demo para poder probar el caso restaurante sin configurar nada.

Idempotente: inserta solo los SKUs demo que falten, sin duplicar catalogo.
"""

from sqlalchemy import select

from app.domain.invoicing_models import InvoiceSeries
from app.domain.models import Customer, InventoryItem, Product, Tenant
from app.infrastructure.config import settings
from app.infrastructure.db.session import AsyncSessionLocal

# sku, nombre, descripcion, precio, categoria, stock inicial
DEMO_PRODUCTS = [
    ("HB-CLA", "Hamburguesa Clasica", "Carne, queso, lechuga y tomate", 12.90, "hamburguesa", 50),
    ("HB-DOB", "Hamburguesa Doble", "Doble carne, doble queso", 18.90, "hamburguesa", 40),
    ("HB-BBQ", "Hamburguesa BBQ", "Carne, cebolla caramelizada y salsa BBQ", 19.90, "hamburguesa", 30),
    ("HB-VEG", "Hamburguesa Vegetariana", "Base de vegetales, palta y queso", 16.90, "hamburguesa", 25),
    ("BEB-INCA", "Inca Kola 500ml", "Gaseosa Inca Kola personal", 5.50, "bebida", 100),
    ("BEB-COCA", "Coca-Cola 500ml", "Gaseosa Coca-Cola personal", 5.50, "bebida", 100),
    ("BEB-CHI", "Chicha Morada 500ml", "Chicha morada casera", 6.50, "bebida", 60),
    ("BEB-LIM", "Limonada 500ml", "Limonada frozen", 6.50, "bebida", 60),
    ("BEB-AGU", "Agua Mineral 500ml", "Agua sin gas", 3.50, "bebida", 80),
    ("PAP-CLA", "Papas Fritas Clasicas", "Porcion clasica de papas fritas", 8.90, "acompanamiento", 60),
    ("PAP-QUE", "Papas Fritas con Queso", "Papas fritas bañadas en queso cheddar", 11.90, "acompanamiento", 40),
    ("ARO-CEB", "Aros de Cebolla", "Porcion de aros de cebolla crocantes", 9.90, "acompanamiento", 35),
    ("NUG-POL", "Nuggets de Pollo", "6 unidades con salsa a elegir", 10.90, "acompanamiento", 35),
    ("ENS-FRE", "Ensalada Fresca", "Lechuga, tomate y palta", 7.90, "acompanamiento", 30),
    ("POS-VOL", "Volcan de Chocolate", "Postre de chocolate con centro fundente", 9.90, "postre", 25),
    ("POS-ALF", "Alfajor", "Alfajor relleno de manjar blanco", 4.50, "postre", 40),
    ("POS-HEL", "Helado 2 Bolas", "Helado artesanal, sabores a elegir", 7.90, "postre", 30),
]


async def seed_demo_data() -> None:
    async with AsyncSessionLocal() as session:
        tenant = await session.get(Tenant, settings.default_tenant_id)
        if tenant is None:
            tenant = Tenant(id=settings.default_tenant_id, name="Restaurante Demo", industry="restaurant")
            session.add(tenant)
            await session.flush()

        existing_products = (
            await session.execute(select(Product).where(Product.tenant_id == tenant.id))
        ).scalars().all()
        existing_skus = {product.sku for product in existing_products}

        for sku, name, description, price, category, stock in DEMO_PRODUCTS:
            if sku not in existing_skus:
                product = Product(
                    tenant_id=tenant.id,
                    sku=sku,
                    name=name,
                    description=description,
                    price=price,
                    category=category,
                )
                session.add(product)
                await session.flush()
                session.add(
                    InventoryItem(tenant_id=tenant.id, product_id=product.id, quantity=stock, reserved=0)
                )

        # Producto real para el cobro del motorizado (ver
        # AgentRuntime._confirm_order): precio atado a settings.delivery_fee_soles,
        # no a un literal aparte -- si el cobro cambia, esto cambia solo.
        # Stock alto a proposito, es un cargo de servicio, no algo que se
        # pueda "agotar".
        if "DELIVERY-FEE" not in existing_skus:
            delivery_product = Product(
                tenant_id=tenant.id,
                sku="DELIVERY-FEE",
                name="Delivery",
                description="Cobro del motorizado, solo para pedidos por delivery.",
                price=settings.delivery_fee_soles,
                category="servicio",
                unidad_medida="ZZ",  # servicio, no un bien -- catalogo 03 SUNAT
            )
            session.add(delivery_product)
            await session.flush()
            session.add(
                InventoryItem(tenant_id=tenant.id, product_id=delivery_product.id, quantity=999999, reserved=0)
            )

        # Series de comprobantes electronicos (ver invoicing_services.py):
        # B001 para boletas, F001 para facturas -- las series estandar que
        # usa cualquier negocio chico con un solo punto de emision. Si el
        # negocio necesita mas series (varios locales, por ejemplo) se
        # agregan despues a mano, esto solo garantiza que las dos basicas
        # existan desde el arranque.
        existing_series = (
            await session.execute(select(InvoiceSeries).where(InvoiceSeries.tenant_id == tenant.id))
        ).scalars().all()
        existing_series_keys = {(s.document_type, s.serie) for s in existing_series}
        for document_type, serie in (("boleta", "B001"), ("factura", "F001")):
            if (document_type, serie) not in existing_series_keys:
                session.add(
                    InvoiceSeries(tenant_id=tenant.id, document_type=document_type, serie=serie, next_number=1)
                )

        existing_customer = await session.scalar(
            select(Customer).where(Customer.tenant_id == tenant.id, Customer.phone == "+51999999999")
        )
        if existing_customer is None:
            session.add(
                Customer(
                    tenant_id=tenant.id,
                    name="Cliente Demo",
                    phone="+51999999999",
                    address="Av. Siempre Viva 123",
                    notes="Cliente de prueba creado por el seed",
                )
            )

        await session.commit()
