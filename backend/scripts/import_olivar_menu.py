"""Importa el menu real de El Olivar Grill a products/inventory.

Uso:
    python scripts/import_olivar_menu.py

Respeta DATABASE_URL del entorno o de backend/.env. Es idempotente: actualiza
productos existentes por tenant_id + sku, crea los que faltan y deja stock.
"""

import asyncio

from sqlalchemy import select

from app.domain.models import InventoryItem, Product, Tenant
from app.infrastructure.config import settings
from app.infrastructure.db.session import AsyncSessionLocal
from app.infrastructure.olivar_menu import OLIVAR_INITIAL_STOCK, OLIVAR_PRODUCTS


async def import_olivar_menu() -> None:
    async with AsyncSessionLocal() as session:
        tenant = await session.get(Tenant, settings.default_tenant_id)
        if tenant is None:
            tenant = Tenant(id=settings.default_tenant_id, name="El Olivar Grill", industry="restaurant")
            session.add(tenant)
            await session.flush()
        else:
            tenant.name = "El Olivar Grill"
            tenant.industry = "restaurant"

        rows = (
            await session.execute(select(Product).where(Product.tenant_id == tenant.id))
        ).scalars().all()
        existing_by_sku = {product.sku: product for product in rows}
        olivar_skus = {sku for sku, *_ in OLIVAR_PRODUCTS}

        created = 0
        updated = 0
        for sku, name, description, price, category in OLIVAR_PRODUCTS:
            product = existing_by_sku.get(sku)
            if product is None:
                product = Product(
                    tenant_id=tenant.id,
                    sku=sku,
                    name=name,
                    description=description,
                    price=price,
                    category=category,
                    active=True,
                )
                session.add(product)
                await session.flush()
                created += 1
            else:
                product.name = name
                product.description = description
                product.price = price
                product.category = category
                product.active = True
                updated += 1

            inventory = await session.scalar(
                select(InventoryItem).where(
                    InventoryItem.tenant_id == tenant.id,
                    InventoryItem.product_id == product.id,
                )
            )
            if inventory is None:
                session.add(
                    InventoryItem(
                        tenant_id=tenant.id,
                        product_id=product.id,
                        quantity=OLIVAR_INITIAL_STOCK,
                        reserved=0,
                    )
                )
            elif inventory.quantity <= 0:
                inventory.quantity = OLIVAR_INITIAL_STOCK
                inventory.reserved = 0

        deactivated = 0
        for product in rows:
            if product.sku not in olivar_skus and product.active:
                product.active = False
                deactivated += 1

        await session.commit()
        print(
            f"Menu Olivar importado: {created} creados, {updated} actualizados, "
            f"{deactivated} productos antiguos desactivados."
        )


if __name__ == "__main__":
    asyncio.run(import_olivar_menu())
