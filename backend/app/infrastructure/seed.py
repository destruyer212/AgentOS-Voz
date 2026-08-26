"""Seed de datos demo para poder probar el caso restaurante sin configurar nada.

Idempotente: si el tenant demo ya tiene productos, no vuelve a insertar.
"""

from sqlalchemy import select

from app.domain.models import Customer, InventoryItem, Product, Tenant
from app.infrastructure.config import settings
from app.infrastructure.db.session import AsyncSessionLocal

# sku, nombre, descripcion, precio, stock inicial
DEMO_PRODUCTS = [
    ("HB-CLA", "Hamburguesa Clasica", "Carne, queso, lechuga y tomate", 12.90, 50),
    ("HB-DOB", "Hamburguesa Doble", "Doble carne, doble queso", 18.90, 40),
    ("HB-BBQ", "Hamburguesa BBQ", "Carne, cebolla caramelizada y salsa BBQ", 19.90, 30),
    ("BEB-INCA", "Inca Kola 500ml", "Gaseosa Inca Kola personal", 5.50, 100),
    ("BEB-COCA", "Coca-Cola 500ml", "Gaseosa Coca-Cola personal", 5.50, 100),
    ("PAP-CLA", "Papas Fritas Clasicas", "Porcion clasica de papas fritas", 8.90, 60),
    ("POS-VOL", "Volcan de Chocolate", "Postre de chocolate con centro fundente", 9.90, 25),
]


async def seed_demo_data() -> None:
    async with AsyncSessionLocal() as session:
        tenant = await session.get(Tenant, settings.default_tenant_id)
        if tenant is None:
            tenant = Tenant(id=settings.default_tenant_id, name="Restaurante Demo", industry="restaurant")
            session.add(tenant)
            await session.flush()

        existing = (
            await session.execute(select(Product).where(Product.tenant_id == tenant.id))
        ).scalars().first()

        if existing is None:
            for sku, name, description, price, stock in DEMO_PRODUCTS:
                product = Product(
                    tenant_id=tenant.id,
                    sku=sku,
                    name=name,
                    description=description,
                    price=price,
                )
                session.add(product)
                await session.flush()
                session.add(
                    InventoryItem(tenant_id=tenant.id, product_id=product.id, quantity=stock, reserved=0)
                )

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
